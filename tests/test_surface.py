"""Surface built from the calibrated SABR parameters (model output; KRX data is not in the repo)."""

from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from volsurface import (build_surface, check_butterfly, check_calendar, fit_all, parity_forwards,
                        sabr_vol, standard_grids, varswap_vol)
from volsurface.config import ELS_FAIR_VOL

ROOT = Path(__file__).resolve().parents[1]
PARAMS = pd.read_csv(ROOT / "tests" / "fixtures" / "sabr_params.csv", dtype={"expiry": str})


@pytest.fixture(scope="module")
def surf():
    return build_surface(PARAMS, "varswap")


def test_calibrated_surface_has_no_static_arbitrage(surf):
    k, T = standard_grids()
    assert len(check_calendar(surf, k, T)) == 0
    assert len(check_butterfly(surf, k, T)) == 0


def test_without_calendar_floor_the_long_wing_breaks():
    # The SABR wings of 2027-01 and 2027-03 cross where neither has data.
    k, T = standard_grids()
    cal = check_calendar(build_surface(PARAMS, "varswap", calendar_floor=False), k, T)
    assert len(cal) == 154
    assert cal["K_over_F"].max() < 0.59          # all below the lowest strike with market data


def test_surface_keeps_the_fit_where_there_is_data(surf):
    for _, p in PARAMS.iterrows():
        m = np.linspace(0.59, 1.30, 30)
        got = surf.implied_vol(m * surf.forward(p["T"]), p["T"])
        np.testing.assert_allclose(got, sabr_vol(1.0, m, p["T"], p.alpha, p.rho, p.nu), atol=1e-8)


def test_three_year_slice_matches_disclosed_varswap_vol(surf):
    assert abs(varswap_vol(surf, 3.0) - ELS_FAIR_VOL) < 1e-4


DATA = ROOT / "data"


@pytest.mark.skipif(not (DATA / "market_iv.csv").exists(), reason="processed KRX data not present")
def test_pipeline_reproduces_fixture_parameters():
    market = pd.read_csv(DATA / "market_iv.csv", dtype={"expiry": str})
    pairs = pd.read_csv(DATA / "atm_pairs.csv", dtype={"expiry": str})
    params = fit_all(market, parity_forwards(pairs))
    np.testing.assert_allclose(params[["F", "alpha", "rho", "nu"]].to_numpy(),
                               PARAMS[["F", "alpha", "rho", "nu"]].to_numpy(), rtol=1e-6)
