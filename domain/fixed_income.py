"""Unified Fixed Income risk-metric contract (§6 of the FI TZ)."""

from dataclasses import dataclass, field
from typing import Any


@dataclass
class FixedIncomeResult:
    """Every FI pricer fills this; fields are None where not applicable."""

    npv: float | None = None
    clean_price: float | None = None
    dirty_price: float | None = None
    accrued_interest: float | None = None
    yield_: float | None = None                      # YTM / instrument yield

    # durations / convexity
    mac_duration: float | None = None
    mod_duration: float | None = None
    effective_duration: float | None = None
    convexity: float | None = None

    # rate sensitivities (pv01/bpv are aliases of dv01)
    dv01: float | None = None
    pv01: float | None = None
    bpv: float | None = None
    key_rate_durations: dict[float, float] = field(default_factory=dict)

    # yields-to-workout
    ytc: float | None = None
    ytp: float | None = None
    ytw: float | None = None

    # spread analytics
    g_spread: float | None = None
    i_spread: float | None = None
    z_spread: float | None = None
    asw: float | None = None
    discount_margin: float | None = None
    oas: float | None = None

    # instrument-specific extras (indexed principal, real yield, ctd, etc.)
    extra: dict[str, Any] = field(default_factory=dict)
    cashflows: list = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    def __post_init__(self):
        if self.dv01 is not None:
            if self.pv01 is None:
                self.pv01 = self.dv01
            if self.bpv is None:
                self.bpv = self.dv01

    def as_dict(self) -> dict:
        out = dict(self.__dict__)
        out["yield"] = out.pop("yield_")
        return out
