"""Dupire local vol from the implied total-variance surface."""

import numpy as np


def local_vol(surface, K, T, hy=1e-3, hT=1e-3):
    """Dupire local vol sigma_loc(K, T) by central differences on w(y, T), y = ln(K / F(T)).

    The time derivative is taken at fixed forward moneyness y, not at fixed K: with rates and
    dividends F moves with T, and Dupire in w(y, T) has no drift terms only in that form.
    Negative local variance is floored at 0 so that the diagnostics can find it.
    """
    K, T = np.broadcast_arrays(np.asarray(K, dtype=float), np.asarray(T, dtype=float))
    y = np.log(K / surface.forward(T))

    def w_of(yy, TT):
        return surface.total_variance(surface.forward(TT) * np.exp(yy), TT)

    w = w_of(y, T)
    wp, wm = w_of(y + hy, T), w_of(y - hy, T)
    w_y = (wp - wm) / (2 * hy)
    w_yy = (wp - 2 * w + wm) / hy ** 2
    T_lo = np.maximum(T - hT, 1e-6)
    w_T = (w_of(y, T + hT) - w_of(y, T_lo)) / (T + hT - T_lo)
    g = 1 - y / w * w_y + 0.25 * (-0.25 - 1 / w + y ** 2 / w ** 2) * w_y ** 2 + 0.5 * w_yy
    return np.sqrt(np.maximum(w_T / g, 0.0))


def diagnostic_grid():
    """K/F 0.35..1.30 (96 points) x T 0.05..3.10 step 0.05, the grid used in the assignment."""
    x = np.linspace(0.35, 1.30, 96)
    t = np.round(np.arange(0.05, 3.1001, 0.05), 2)
    return np.meshgrid(x, t)


def lv_on_grid(surface, XX=None, TT=None):
    """Local vol on the diagnostic grid (K = x * F(T))."""
    if XX is None:
        XX, TT = diagnostic_grid()
    return local_vol(surface, XX * surface.forward(TT), TT)
