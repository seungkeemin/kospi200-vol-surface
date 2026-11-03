"""ELS payoff, the Monte Carlo engine, and the disclosed fair value as a benchmark."""

from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from volsurface import build_surface
from volsurface.config import ELS_FAIR_PRICE, ELS_FAIR_VOL, MIN_FWD_VAR, SMOOTH_EPS
from volsurface.els import (AC_PAYOFF, DF_PAY, MAT_COUPON, FlatVol, LocalVolTable, els_pv, evolve, price_stats,
                            run_els, time_grid)

ROOT = Path(__file__).resolve().parents[1]
PARAMS = pd.read_csv(ROOT / "tests" / "fixtures" / "sabr_params.csv", dtype={"expiry": str})
N_FAST = 2 ** 14          # the README numbers use 2^17 (scripts/run_els.py)


@pytest.fixture(scope="module")
def surf():
    return build_surface(PARAMS, min_fwd_var=MIN_FWD_VAR, smooth_eps=SMOOTH_EPS)


def test_payoff_on_hand_made_paths():
    ref = np.full(5, 100.0)
    S_ac = np.full((5, 5), 50.0)
    S_ac[0, 0] = 85.0                      # path 0: first autocall exactly at the barrier
    S_ac[3, 1] = 80.0                      # path 1: fourth autocall (barrier 80%)
    S_T = np.array([0, 0, 69.0, 69.0, 30.0])
    min_S = np.array([50, 50, 45.0, 39.0, 30.0])
    pv = els_pv(ref, S_ac, S_T, min_S)
    np.testing.assert_allclose(pv[:2], [AC_PAYOFF[0] * DF_PAY[0], AC_PAYOFF[3] * DF_PAY[3]])
    assert pv[2] == pytest.approx(MAT_COUPON * DF_PAY[5])              # below 70% but never knocked in
    assert pv[3] == pytest.approx(10000 * 0.69 * DF_PAY[5])            # knocked in and below 70%
    assert pv[4] == pytest.approx(10000 * 0.30 * DF_PAY[5])


def test_evolve_keeps_the_forward():
    z = np.random.default_rng(0).standard_normal(400_000)
    S1 = np.exp(evolve(np.log(100.0), np.log(100.0), np.log(101.0), 0.4, 0.5, z))
    assert S1.mean() == pytest.approx(101.0, rel=3e-3)


def test_time_grid_matches_the_prospectus_dates():
    t, i_fix, i_ac, i_mat = time_grid()
    assert len(t) == 794 and t[-1] == pytest.approx(1109 / 365)
    assert i_fix < i_ac[0] < i_mat == len(t) - 1


def test_flat_vol_reproduces_the_disclosed_fair_value(surf):
    p, se = price_stats(run_els(surf, FlatVol(ELS_FAIR_VOL), N_FAST, seed=7))
    assert abs(p - ELS_FAIR_PRICE) < 3 * se + 5


def test_spot_as_initial_level_is_biased_low(surf):
    # Same random numbers, so the difference is far less noisy than either price.
    fix = price_stats(run_els(surf, FlatVol(ELS_FAIR_VOL), N_FAST, seed=7))[0]
    spot = price_stats(run_els(surf, FlatVol(ELS_FAIR_VOL), N_FAST, seed=7, ref_mode="spot"))[0]
    assert fix - spot > 20


def test_local_vol_price_is_below_flat(surf):
    t, _, _, _ = time_grid()
    p, se = price_stats(run_els(surf, LocalVolTable(surf, t), N_FAST, seed=7))
    assert 9550 < p < 9700 and p < ELS_FAIR_PRICE - 4 * se
