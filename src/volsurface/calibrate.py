"""Per-expiry SABR calibration."""

import numpy as np
import pandas as pd
from scipy.optimize import least_squares

from .sabr import sabr_vol


def calibrate_slice(F, T, K, market_iv):
    """Fit (alpha, rho, nu) to one expiry's market IVs with equal weights.

    Start: alpha = market IV interpolated at F, rho = -0.3, nu = 1.0.
    Bounds keep |rho| < 1 so that x(z) stays defined.
    """
    K = np.asarray(K, dtype=float)
    market_iv = np.asarray(market_iv, dtype=float)
    order = np.argsort(K)
    alpha0 = np.interp(F, K[order], market_iv[order])

    def resid(p):
        return sabr_vol(F, K, T, *p) - market_iv

    res = least_squares(resid, x0=[alpha0, -0.3, 1.0],
                        bounds=([1e-4, -0.999, 1e-4], [5.0, 0.999, 5.0]))
    return tuple(res.x)


def fit_all(market: pd.DataFrame, forwards: pd.Series) -> pd.DataFrame:
    """Calibrate every expiry in market (columns expiry, T, K, iv); returns one row per expiry with RMSE in bp."""
    rows = []
    for exp, g in market.groupby("expiry"):
        F, T = float(forwards[exp]), float(g["T"].iloc[0])
        K, iv = g["K"].to_numpy(), g["iv"].to_numpy()
        a, r, n = calibrate_slice(F, T, K, iv)
        rmse = np.sqrt(np.mean((sabr_vol(F, K, T, a, r, n) - iv) ** 2)) * 1e4
        rows.append(dict(expiry=exp, T=T, F=F, alpha=a, rho=r, nu=n, n_points=len(g), rmse_bp=rmse))
    return pd.DataFrame(rows).sort_values("T").reset_index(drop=True)
