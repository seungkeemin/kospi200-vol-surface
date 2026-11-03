"""Static arbitrage checks on a vol surface."""

import numpy as np
import pandas as pd

from .config import S0
from .sabr import black_price


def check_calendar(surface, m_grid, T_grid, tol=1e-10):
    """Total variance must not fall with T at fixed K/F. Returns the violating grid points."""
    M, TT = np.meshgrid(m_grid, T_grid)
    dw = np.diff(surface.total_variance(M * surface.forward(TT), TT), axis=0)
    i, j = np.where(dw < -tol)
    return pd.DataFrame(dict(T_from=T_grid[i], T_to=T_grid[i + 1], K_over_F=m_grid[j], dw=dw[i, j]))


def check_butterfly(surface, k_grid, T_grid, tol=1e-10):
    """Call prices must be convex in K (k_grid = K/S0). Returns the violating grid points."""
    rows = []
    for T in T_grid:
        K = k_grid * S0
        C = black_price(float(surface.forward(T)), K, T, surface.implied_vol(K, T), "C") / S0
        d2 = C[:-2] - 2 * C[1:-1] + C[2:]
        rows += [dict(T=T, K_over_S0=k_grid[j + 1], d2C=d2[j]) for j in np.where(d2 < -tol)[0]]
    return pd.DataFrame(rows, columns=["T", "K_over_S0", "d2C"])


def standard_grids():
    """K/F (or K/S0) 0.35..1.30 step 0.01 and T 0.02..3.10 step 0.02, as in the assignment."""
    k_grid = np.round(np.arange(0.35, 1.3001, 0.01), 2)
    T_grid = np.round(np.arange(0.02, 3.1001, 0.02), 2)
    return k_grid, T_grid
