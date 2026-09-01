from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Mapping

from .events import BarEvent, MarketEvent


@dataclass(frozen=True)
class Signal:
    symbol: str
    signal_time: object
    side: str = "long"
    strength: float = 1.0
    stop_pct: float = 0.01
    tp1_r: float = 1.25
    tp2_r: float = 2.5
    metadata: Mapping[str, object] = field(default_factory=dict)

    def __post_init__(self):
        if self.side not in ("long", "flat"):
            raise ValueError("v0.7 benchmark engine supports long/flat only")
        if self.side == "long" and not (0 < self.stop_pct < 1):
            raise ValueError("stop_pct must be between 0 and 1")
        if self.strength < 0:
            raise ValueError("strength cannot be negative")


class Strategy(ABC):
    """Small Jesse-inspired strategy interface, independent from any exchange SDK."""

    name: str = "strategy"

    def on_event(self, event: MarketEvent) -> Signal | None:
        if isinstance(event, BarEvent):
            return self.on_bar(event)
        return None

    @abstractmethod
    def on_bar(self, bar: BarEvent) -> Signal | None:
        raise NotImplementedError

    def reset(self) -> None:
        """Clear internal state before a new fold/replay."""
        return None
