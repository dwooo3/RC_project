"""
Portfolio manager: positions, aggregated risk, P&L attribution.
"""

import numpy as np
from dataclasses import dataclass, field
from typing import Optional


@dataclass
class Position:
    """Single portfolio position."""
    id:         str
    instrument: str          # "option","bond","swap","cds","future","fx_fwd","equity"
    description: str
    quantity:   float        # number of contracts / face amount
    params:     dict         # all pricing parameters

    # Computed at runtime
    price:      float = 0.0
    market_value: float = 0.0
    delta:      float = 0.0
    gamma:      float = 0.0
    vega:       float = 0.0
    theta:      float = 0.0
    rho:        float = 0.0
    dv01:       float = 0.0
    cs01:       float = 0.0  # credit sensitivity
    fx_delta:   float = 0.0
    pnl_1d:     float = 0.0

    currency:   str   = "RUB"
    book:       str   = "Trading"
    trader:     str   = ""
    ccy_pair:   str   = ""


class Portfolio:
    """Portfolio of positions with aggregated Greeks and risk."""

    def __init__(self, name: str = "Main Portfolio"):
        self.name: str = name
        self.positions: list[Position] = []

    def add(self, pos: Position):
        self.positions.append(pos)

    def remove(self, position_id: str):
        self.positions = [p for p in self.positions if p.id != position_id]

    def price_all(self):
        """Reprice all positions using their params."""
        for pos in self.positions:
            try:
                self._price_position(pos)
            except Exception as e:
                pos.price = float("nan")

    def _price_position(self, pos: Position):
        p  = pos.params
        qt = pos.quantity
        inst = pos.instrument

        if inst in ("call", "put", "option"):
            from models.black_scholes import bsm
            g = bsm(p["S"], p["K"], p["T"], p["r"], p["sigma"],
                    p.get("q",0), p.get("opt", inst))
            pos.price         = g.price
            pos.market_value  = g.price * qt
            pos.delta         = g.delta * qt
            pos.gamma         = g.gamma * qt
            pos.vega          = g.vega  * qt
            pos.theta         = g.theta * qt
            pos.rho           = g.rho   * qt

        elif inst == "bond":
            from instruments.fixed_income import fixed_bond, YieldCurve
            curve = p.get("curve") or YieldCurve.flat(p["r"])
            res   = fixed_bond(p["face"], p["coupon"], p["T"], p.get("freq",2), curve)
            pos.price        = res["price"]
            pos.market_value = res["price"] * qt / p["face"]
            pos.dv01         = res["dv01"] * qt / p["face"]
            pos.delta        = res["mod_duration"] * pos.market_value / 100

        elif inst == "cds":
            from instruments.credit import cds, cds_implied_hazard
            hazard = cds_implied_hazard(p["spread"], p["T"], p.get("freq",4),
                                        p["r"], p.get("recovery",0.4))
            res    = cds(p["notional"], p["spread"], p["T"], p.get("freq",4),
                         hazard, p["r"], p.get("recovery",0.4), p.get("buy",True))
            pos.price        = res["npv"]
            pos.market_value = res["npv"] * qt
            pos.cs01         = res["dv01"] * qt

        elif inst in ("irs", "swap"):
            from instruments.fixed_income import irs, YieldCurve
            curve  = p.get("curve") or YieldCurve.flat(p["r"])
            res    = irs(p["notional"], p["fixed_rate"], p["T"], p.get("freq",4),
                         curve, p.get("pay_fixed",True))
            pos.price        = res["npv"]
            pos.market_value = res["npv"] * qt
            pos.dv01         = res["dv01"] * qt

        elif inst == "equity":
            S = p["S"]
            pos.price        = S
            pos.market_value = S * qt
            pos.delta        = qt  # delta = quantity

        elif inst == "fx_forward":
            from instruments.fx import fx_forward
            res = fx_forward(p["S"], p["r_d"], p["r_f"], p["T"])
            pos.price        = res["forward"]
            pos.market_value = (res["forward"] - p.get("K", res["forward"])) * qt
            pos.fx_delta     = qt

        elif inst == "future":
            F = p.get("F", p.get("S",0))
            pos.price        = F
            pos.market_value = F * qt * p.get("multiplier",1)
            pos.delta        = qt * p.get("multiplier",1)

    # ── Aggregated risk ──────────────────────────────────────

    def aggregate(self) -> dict:
        self.price_all()
        total_mv    = sum(p.market_value for p in self.positions)
        total_delta = sum(p.delta for p in self.positions)
        total_gamma = sum(p.gamma for p in self.positions)
        total_vega  = sum(p.vega  for p in self.positions)
        total_theta = sum(p.theta for p in self.positions)
        total_rho   = sum(p.rho   for p in self.positions)
        total_dv01  = sum(p.dv01  for p in self.positions)
        total_cs01  = sum(p.cs01  for p in self.positions)

        return dict(
            n_positions  = len(self.positions),
            market_value = total_mv,
            delta        = total_delta,
            gamma        = total_gamma,
            vega         = total_vega,
            theta        = total_theta,
            rho          = total_rho,
            dv01         = total_dv01,
            cs01         = total_cs01,
        )

    def positions_table(self) -> list[dict]:
        self.price_all()
        return [dict(
            id=p.id, instrument=p.instrument, description=p.description,
            quantity=p.quantity, price=round(p.price,4),
            market_value=round(p.market_value,2),
            delta=round(p.delta,4), gamma=round(p.gamma,6),
            vega=round(p.vega,4), theta=round(p.theta,4),
            dv01=round(p.dv01,2), cs01=round(p.cs01,2),
            currency=p.currency, book=p.book,
        ) for p in self.positions]

    def scenario_pnl(self, dS: float = 0, dVol: float = 0,
                     dr: float = 0, dSpread: float = 0) -> dict:
        """First-order scenario P&L for the whole portfolio."""
        agg = self.aggregate()
        pnl = (agg["delta"]  * dS
             + agg["gamma"]  * dS**2 / 2
             + agg["vega"]   * dVol * 100
             + agg["theta"]  * 1
             + agg["rho"]    * dr * 100
             - agg["dv01"]   * dr * 10000
             - agg["cs01"]   * dSpread * 10000)
        return dict(pnl=pnl, dS=dS, dVol=dVol, dr=dr, dSpread=dSpread,
                    components=dict(delta=agg["delta"]*dS,
                                    gamma=agg["gamma"]*dS**2/2,
                                    vega=agg["vega"]*dVol*100,
                                    theta=agg["theta"],
                                    ir_01=agg["dv01"]*dr*10000,
                                    cs_01=agg["cs01"]*dSpread*10000))

    def __len__(self): return len(self.positions)
    def __repr__(self): return f"Portfolio('{self.name}', {len(self)} positions)"
