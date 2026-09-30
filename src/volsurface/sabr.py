"""Black pricing and the Hagan et al. (2002) SABR approximation with beta = 1."""

import numpy as np
from scipy.optimize import brentq
from scipy.stats import norm


def black_price(F, K, T, sigma, cp="C", df=1.0):
    sd = np.maximum(sigma * np.sqrt(T), 1e-12)
    d1 = np.log(F / K) / sd + 0.5 * sd
    d2 = d1 - sd
    if cp == "C":
        return df * (F * norm.cdf(d1) - K * norm.cdf(d2))
    return df * (K * norm.cdf(-d2) - F * norm.cdf(-d1))


def black_iv(price, F, K, T, cp="C", df=1.0):
    """Black implied vol; nan if the price is outside no-arbitrage bounds."""
    intrinsic = df * max(F - K, 0.0) if cp == "C" else df * max(K - F, 0.0)
    if price <= intrinsic + 1e-10:
        return np.nan
    try:
        return brentq(lambda s: black_price(F, K, T, s, cp, df) - price, 1e-4, 5.0, xtol=1e-10)
    except ValueError:
        return np.nan


def sabr_vol(F, K, T, alpha, rho, nu):
    """Hagan (2.17) with beta = 1. K may be an array; at K = F it reduces to (2.18) without nan."""
    K = np.asarray(K, dtype=float)
    z = nu / alpha * np.log(F / K)
    x = np.log((np.sqrt(1 - 2 * rho * z + z * z) + z - rho) / (1 - rho))
    small = np.abs(z) < 1e-8
    z_over_x = np.where(small, 1.0, z / np.where(small, 1.0, x))
    correction = 1 + (rho * nu * alpha / 4 + (2 - 3 * rho * rho) * nu * nu / 24) * T
    return alpha * z_over_x * correction
