"""Linear equity products (Этап 5, EQD trade-capture линейка).

Closed-form, no volatility input — эти продукты чувствительны к carry
(ставка/дивиденды), а не к вол. Конвенции: непрерывные r и q, ACT/365,
дивиденды как непрерывная доходность q (дискретные дивиденды —
следующий шаг, требует dividend-графика по имени).
"""

from __future__ import annotations

import numpy as np
from models.black_scholes import bsm


def equity_forward(S: float, K: float, T: float, r: float, q: float = 0.0,
                   notional: float = 1.0, position: str = "long") -> dict:
    """Equity forward/future с поставочной ценой K.

    Fair forward F = S·e^{(r−q)T}; стоимость длинного контракта на единицу =
    (F − K)·e^{−rT} = S·e^{−qT} − K·e^{−rT}. Delta = e^{−qT} (в единицах спота).
    """
    fair_forward = S * np.exp((r - q) * T)
    unit_value = S * np.exp(-q * T) - K * np.exp(-r * T)
    sign = 1.0 if position == "long" else -1.0
    npv = sign * notional * unit_value
    return dict(
        npv=npv, value=npv, fair_forward=fair_forward,
        forward_points=fair_forward - S,
        delta=sign * notional * np.exp(-q * T),
        rho=sign * notional * K * T * np.exp(-r * T),
        carry=fair_forward - S, basis=fair_forward - K,
        S=S, K=K, T=T,
    )


def equity_swap(S: float, notional: float, T: float, r: float, q: float = 0.0,
                spread: float = 0.0, freq: int = 4,
                receive_equity: bool = True) -> dict:
    """Equity total-return swap: одна нога — полный доход акции (цена +
    дивиденды), другая — плавающая ставка + спред на ноционал.

    При непрерывном ресете ноги carry/дивидендов сокращаются точно (форвард
    акции), и стоимость свопа сводится к −(спред-аннуитет) для получателя
    equity-ноги: fair spread = 0 при паритете. Возвращаем разложение по ногам.
    """
    dt = 1.0 / freq
    times = [i * dt for i in range(1, int(round(T * freq)) + 1)]
    annuity = sum(dt * np.exp(-r * t) for t in times)     # плавающий аннуитет

    # equity-нога (получить полный доход, расчёт в T): PV = N·(1 − e^{−rT})
    equity_leg = notional * (1.0 - np.exp(-r * T))
    # плавающая нога (заплатить r): та же PV по построению
    floating_leg = notional * (1.0 - np.exp(-r * T))
    spread_leg = notional * spread * annuity

    sign = 1.0 if receive_equity else -1.0
    # получатель equity платит floating+spread
    npv = sign * (equity_leg - floating_leg - spread_leg)
    return dict(
        npv=npv, value=npv,
        equity_leg_pv=equity_leg, floating_leg_pv=floating_leg,
        spread_leg_pv=spread_leg, annuity=annuity,
        fair_spread=0.0,                       # ноги паритетны без спреда
        breakeven_spread=(equity_leg - floating_leg) / (notional * annuity)
        if annuity > 0 else 0.0,
        # In this par-start continuous-reset approximation both legs are
        # expressed on the same fixed notional and cancel before the spread
        # leg. NPV is therefore spot-independent; reporting a forward-like
        # delta was inconsistent with the implemented value function.
        delta=0.0,
        notional=notional, T=T,
    )


def dividend_swap(S: float, T: float, r: float, q: float,
                  div_strike: float | None = None,
                  notional: float = 1.0, position: str = "long") -> dict:
    """Dividend swap: одна нога — реализованные дивиденды за [0,T], другая —
    фиксированный страйк div_strike (в тех же ден. единицах на единицу).

    Ожидаемая PV дивидендов при непрерывной доходности q = S·(1 − e^{−qT}).
    Fair strike (недисконтированная сумма к уплате в T) = S(1−e^{−qT})·e^{rT}.
    """
    expected_div_pv = S * (1.0 - np.exp(-q * T))
    fair_strike = expected_div_pv * np.exp(r * T)
    if div_strike is None:
        div_strike = fair_strike
    sign = 1.0 if position == "long" else -1.0
    unit_value = expected_div_pv - div_strike * np.exp(-r * T)
    npv = sign * notional * unit_value
    return dict(
        npv=npv, value=npv,
        expected_dividends_pv=expected_div_pv,
        fair_strike=fair_strike, div_strike=div_strike,
        delta=sign * notional * (1.0 - np.exp(-q * T)),   # dPV/dS
        S=S, T=T, q=q,
    )


def equity_future(S: float, K: float, T: float, r: float, q: float = 0.0,
                  notional: float = 1.0, position: str = "long") -> dict:
    """Equity future: справедливая фьючерсная цена F=S·e^{(r−q)T}.

    В отличие от форварда, вариационная маржа платится ежедневно, поэтому
    mark-to-market стоимость позиции по локированной цене K = (F − K)·notional
    БЕЗ дисконтирования (в форварде — со множителем e^{−rT}). Delta к споту =
    e^{(r−q)T} (futures delta), тоже больше форвардной.
    """
    fair_future = S * np.exp((r - q) * T)
    sign = 1.0 if position == "long" else -1.0
    npv = sign * notional * (fair_future - K)          # без дисконта (daily MtM)
    return dict(
        npv=npv, value=npv, fair_future=fair_future,
        basis=fair_future - S, contango=fair_future - S,
        delta=sign * notional * np.exp((r - q) * T),
        S=S, K=K, T=T,
    )


def warrant(S: float, K: float, T: float, r: float, sigma: float,
            q: float = 0.0, n_shares: float = 100.0, n_warrants: float = 10.0,
            opt: str = "call", notional: float = 1.0) -> dict:
    """Warrant с поправкой на разводнение (dilution).

    При исполнении M варрантов на N акций выпускаются новые акции, размывая
    капитал: стоимость варранта = (N/(N+M))·C_BSM. Это стандартная
    dilution-factor аппроксимация (точная — неявная, C зависит от размытой
    цены); для листингованных варрантов на малой доле M/N расхождение мало.
    """
    g = bsm(S, K, T, r, sigma, q, opt)
    dilution = n_shares / (n_shares + n_warrants)
    price = dilution * g.price
    return dict(
        price=price, value=notional * price, undiluted_price=g.price,
        dilution_factor=dilution,
        delta=notional * dilution * g.delta,
        gamma=notional * dilution * g.gamma,
        vega=notional * dilution * g.vega,
        n_shares=n_shares, n_warrants=n_warrants,
    )
