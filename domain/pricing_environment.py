"""Pricing Environment (A1 отчёта валидации, Calypso §3.1).

Явный контракт «контура оценки»: какой снапшот маркет даты, какие кривые на
какие роли, какие поверхности, какие движки по умолчанию и какие численные
параметры использует данный контур (FO / Risk / EOD / VaR / Stress). До этого
всё это жило неявно: активный снапшот + дефолты каталога + параметры запроса.

Ограничение v1 (честно): curve_map задаёт ДЕФОЛТЫ выбора кривых в каталоге и
адаптерах воркстейшена (роль -> curve_id), а не полный remapping каждого
внутреннего вызова PricingService.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field

PURPOSES = ("fo", "risk", "eod", "var", "stress")

# Роли кривых, которые понимают каталог/адаптеры.
CURVE_ROLES = ("discount", "projection", "real", "credit")


@dataclass
class PricingEnvironment:
    env_id: str                                   # "FO", "RISK", ...
    name: str
    purpose: str = "fo"                           # one of PURPOSES
    snapshot_id: str | None = None                # None = активный снапшот
    curve_map: dict = field(default_factory=dict)      # role -> curve_id
    surface_map: dict = field(default_factory=dict)    # underlying -> surface_id
    pricer_overrides: dict = field(default_factory=dict)   # product_id -> engine_id
    default_params: dict = field(default_factory=dict)     # key -> value (request wins)
    measures: list = field(default_factory=lambda: ["value", "greeks"])
    metadata: dict = field(default_factory=dict)

    def __post_init__(self):
        if self.purpose not in PURPOSES:
            raise ValueError(f"purpose must be one of {PURPOSES}, got {self.purpose!r}")

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "PricingEnvironment":
        known = {f for f in cls.__dataclass_fields__}      # noqa: C401
        return cls(**{k: v for k, v in d.items() if k in known})


def default_environments() -> list[PricingEnvironment]:
    """Сид-набор контуров: FO — живой снапшот; Risk/EOD/VaR — пока = FO
    (различия появятся, когда появятся разные источники/снапшоты); Stress —
    тот же снапшот, помечен назначением."""
    # projection-роль в сид-набор НЕ входит: дефолтная проекция == дисконту
    # (single-curve, как вело себя всё до появления контуров); dual-curve
    # включается явным заданием curve_map["projection"] в своём контуре.
    base_curves = {"discount": "GCURVE_RUB",
                   "real": "REALCURVE_OFZIN", "credit": "CORP_T1"}
    return [
        PricingEnvironment("FO", "Front Office", "fo", None, dict(base_curves)),
        PricingEnvironment("RISK", "Desk Risk", "risk", None, dict(base_curves)),
        PricingEnvironment("EOD", "End of Day", "eod", None, dict(base_curves)),
        PricingEnvironment("VAR", "Market Risk / VaR", "var", None, dict(base_curves)),
        PricingEnvironment("STRESS", "Stress", "stress", None, dict(base_curves),
                           metadata={"note": "стрессовые окна задаются в Market Risk"}),
    ]
