"""Directed regressions for BRW age-weighted historical simulation."""

import numpy as np
import pytest

from risk.historical_var import hs_age_weighted


def test_recent_extreme_loss_has_more_weight_than_old_extreme_loss():
    """The same loss multiset must be riskier when its extreme is most recent."""
    extreme_when_old = np.array([-100.0] + [-10.0] * 99)
    extreme_when_recent = extreme_when_old[::-1]

    old_result = hs_age_weighted(
        extreme_when_old, confidence=0.95, decay=0.90)
    recent_result = hs_age_weighted(
        extreme_when_recent, confidence=0.95, decay=0.90)

    assert old_result["VaR"] == pytest.approx(10.0)
    assert recent_result["VaR"] == pytest.approx(100.0)
    assert recent_result["VaR"] > old_result["VaR"]


def test_recent_benign_regime_outweighs_old_loss_cluster():
    """Old tail events must not dominate a long, more recent benign regime."""
    old_losses = np.array([-100.0] * 5 + [-10.0] * 95)
    recent_losses = old_losses[::-1]

    old_cluster = hs_age_weighted(
        old_losses, confidence=0.95, decay=0.90)
    recent_cluster = hs_age_weighted(
        recent_losses, confidence=0.95, decay=0.90)

    assert old_cluster["VaR"] == pytest.approx(10.0)
    assert recent_cluster["VaR"] == pytest.approx(100.0)
    assert recent_cluster["VaR"] > old_cluster["VaR"]
