"""Dupire local vol and the floor that keeps it positive."""

from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from volsurface import build_surface, check_butterfly, check_calendar, sabr_vol, standard_grids, varswap_vol
from volsurface.config import ELS_FAIR_VOL, MIN_FWD_VAR, S0, SMOOTH_EPS
from volsurface.localvol import diagnostic_grid, local_vol, lv_on_grid
from volsurface.surface import smooth_max

ROOT = Path(__file__).resolve().parents[1]
PARAMS = pd.read_csv(ROOT / "tests" / "fixtures" / "sabr_params.csv", dtype={"expiry": str})


class FlatSurface:
    """sigma constant, F growing at 3%: Dupire must return sigma everywhere."""

    def __init__(self, sigma, r=0.03):
        self.sigma, self.r = sigma, r

    def forward(self, T):
        return S0 * np.exp(self.r * np.asarray(T, dtype=float))

    def total_variance(self, K, T):
        return self.sigma ** 2 * np.broadcast_arrays(np.asarray(K, dtype=float), np.asarray(T, dtype=float))[1]


class SkewSurface(FlatSurface):
    """sigma depends only on y = ln(K/F): w = (a + b y)^2 T. At fixed y, dw/dT = (a + b y)^2."""

    def __init__(self, a=0.30, b=-0.20, r=0.03):
        super().__init__(a, r)
        self.a, self.b = a, b

    def total_variance(self, K, T):
        K, T = np.broadcast_arrays(np.asarray(K, dtype=float), np.asarray(T, dtype=float))
        y = np.log(K / self.forward(T))
        return (self.a + self.b * y) ** 2 * T


@pytest.fixture(scope="module")
def plain():
    return build_surface(PARAMS)


@pytest.fixture(scope="module")
def floored():
    return build_surface(PARAMS, min_fwd_var=MIN_FWD_VAR, smooth_eps=SMOOTH_EPS)


def test_flat_surface_gives_flat_local_vol():
    K = np.linspace(0.5, 1.5, 11)[:, None] * S0
    T = np.array([0.25, 1.0, 3.0])[None, :]
    np.testing.assert_allclose(local_vol(FlatSurface(0.25), K, T), 0.25, atol=1e-6)


def test_time_derivative_is_taken_at_fixed_forward_moneyness():
    # With F moving in T, differentiating at fixed K instead of fixed y gives a different (wrong) answer.
    s = SkewSurface()
    T = np.array([0.5, 1.0, 2.0])[None, :]
    y = np.linspace(-0.4, 0.2, 7)[:, None]
    K = s.forward(T) * np.exp(y)
    sig, ds = s.a + s.b * y, s.b
    w, w_T, w_y, w_yy = sig ** 2 * T, sig ** 2, 2 * sig * ds * T, 2 * ds ** 2 * T
    g = 1 - y / w * w_y + 0.25 * (-0.25 - 1 / w + y ** 2 / w ** 2) * w_y ** 2 + 0.5 * w_yy
    np.testing.assert_allclose(local_vol(s, K, T), np.sqrt(w_T / g), rtol=1e-4)


def test_plain_floor_leaves_a_zero_local_vol_wedge(plain):
    # The hard calendar floor makes dw/dT = 0 where it binds, so Dupire's numerator vanishes.
    XX, TT = diagnostic_grid()
    bad = lv_on_grid(plain, XX, TT) < 0.01
    assert bad.sum() == 63
    assert 0.35 <= TT[bad].min() and TT[bad].max() <= 0.45 and XX[bad].max() <= 0.55


def test_min_forward_variance_removes_the_wedge_and_keeps_everything_else(floored):
    assert lv_on_grid(floored).min() > 0.08
    k, T = standard_grids()
    assert len(check_calendar(floored, k, T)) == 0 and len(check_butterfly(floored, k, T)) == 0
    assert abs(varswap_vol(floored, 3.0) - ELS_FAIR_VOL) < 1e-4
    for _, p in PARAMS.iterrows():                       # where there is market data the fit barely moves
        m = np.linspace(0.59, 1.30, 72)
        got = floored.implied_vol(m * floored.forward(p["T"]), p["T"])
        assert np.abs(got - sabr_vol(1.0, m, p["T"], p.alpha, p.rho, p.nu)).max() < 1e-4   # 1bp


def test_smooth_floor_is_within_eps_ln2_of_the_hard_floor(floored):
    m = np.linspace(0.35, 1.30, 50)
    for i in range(1, len(floored.T_obs)):
        w_i, w_prev = floored.slice_total_variance(i, m), floored.slice_total_variance(i - 1, m)
        hard = np.maximum(floored.sabr_total_variance(i, m), w_prev + MIN_FWD_VAR * (floored.T_obs[i] - floored.T_obs[i - 1]))
        assert np.all(w_i >= hard - 1e-12) and np.all(w_i <= hard + SMOOTH_EPS * np.log(2) + 1e-12)
    assert smooth_max(1.0, 0.0, 1e-3) == pytest.approx(1.0)
