from __future__ import annotations

from collections import deque
import numpy as np

from .events import BarEvent
from .strategy import Signal, Strategy


class EMATrendBenchmark(Strategy):
    name = "ema_trend"

    def __init__(self, fast: int = 20, slow: int = 50, stop_pct: float = 0.01):
        if fast >= slow:
            raise ValueError("fast EMA must be shorter than slow EMA")
        self.fast = fast
        self.slow = slow
        self.stop_pct = stop_pct
        self.reset()

    def reset(self):
        self.ema_fast = None
        self.ema_slow = None
        self.prev_fast = None
        self.prev_slow = None
        self.n = 0

    @staticmethod
    def _ema(prev, x, span):
        if prev is None:
            return x
        a = 2.0 / (span + 1.0)
        return a * x + (1.0 - a) * prev

    def on_bar(self, bar: BarEvent):
        self.prev_fast, self.prev_slow = self.ema_fast, self.ema_slow
        self.ema_fast = self._ema(self.ema_fast, bar.close, self.fast)
        self.ema_slow = self._ema(self.ema_slow, bar.close, self.slow)
        self.n += 1
        if self.n < self.slow or self.prev_fast is None or self.prev_slow is None:
            return None
        crossed = self.prev_fast <= self.prev_slow and self.ema_fast > self.ema_slow
        if not crossed:
            return None
        strength = max(0.0, self.ema_fast / self.ema_slow - 1.0)
        return Signal(bar.symbol, bar.event_time, strength=strength, stop_pct=self.stop_pct, metadata={"family": self.name})


class DonchianBreakoutBenchmark(Strategy):
    name = "donchian_breakout"

    def __init__(self, lookback: int = 36, volume_lookback: int = 20, volume_mult: float = 1.5, stop_pct: float = 0.012):
        self.lookback = lookback
        self.volume_lookback = volume_lookback
        self.volume_mult = volume_mult
        self.stop_pct = stop_pct
        self.reset()

    def reset(self):
        self.highs = deque(maxlen=self.lookback)
        self.volumes = deque(maxlen=self.volume_lookback)

    def on_bar(self, bar: BarEvent):
        prior_high = max(self.highs) if len(self.highs) == self.lookback else None
        vol_med = float(np.median(self.volumes)) if len(self.volumes) == self.volume_lookback else None
        self.highs.append(bar.high)
        self.volumes.append(bar.volume)
        if prior_high is None or vol_med is None or vol_med <= 0:
            return None
        if bar.close <= prior_high or bar.volume < self.volume_mult * vol_med:
            return None
        strength = (bar.close / prior_high - 1.0) + max(0.0, bar.volume / vol_med - self.volume_mult)
        return Signal(bar.symbol, bar.event_time, strength=strength, stop_pct=self.stop_pct, metadata={"family": self.name})


class VWAPMeanReversionBenchmark(Strategy):
    name = "vwap_mean_reversion"

    def __init__(self, deviation_pct: float = 0.012, stop_pct: float = 0.01):
        self.deviation_pct = deviation_pct
        self.stop_pct = stop_pct
        self.reset()

    def reset(self):
        self.day = None
        self.cum_pv = 0.0
        self.cum_v = 0.0
        self.armed = False

    def on_bar(self, bar: BarEvent):
        day = bar.event_time.floor("D")
        if self.day is None or day != self.day:
            self.day = day
            self.cum_pv = 0.0
            self.cum_v = 0.0
            self.armed = False
        typical = (bar.high + bar.low + bar.close) / 3.0
        self.cum_pv += typical * bar.volume
        self.cum_v += bar.volume
        if self.cum_v <= 0:
            return None
        vwap = self.cum_pv / self.cum_v
        deviation = bar.close / vwap - 1.0
        if deviation <= -self.deviation_pct:
            self.armed = True
            return None
        if self.armed and bar.close >= vwap:
            self.armed = False
            return Signal(bar.symbol, bar.event_time, strength=abs(deviation), stop_pct=self.stop_pct, tp1_r=1.0, tp2_r=2.0, metadata={"family": self.name, "vwap": vwap})
        return None


BENCHMARK_FACTORIES = {
    "ema_trend": lambda: EMATrendBenchmark(),
    "donchian_breakout": lambda: DonchianBreakoutBenchmark(),
    "vwap_mean_reversion": lambda: VWAPMeanReversionBenchmark(),
}
