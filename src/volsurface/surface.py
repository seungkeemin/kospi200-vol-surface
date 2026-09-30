"""Continuous vol surface: observed SABR slices, total-variance interpolation, long-end assumption."""

import numpy as np
from scipy.optimize import brentq

from .config import ANCHOR_T, ELS_FAIR_VOL, EXTRAP_BASE_EXPIRY, S0, VARSWAP_M_RANGE
from .curve import zero_rate
from .sabr import black_price, sabr_vol


class VolSurface:
    """sigma(K, T) on m = K / F(T) with w(m, T) = sigma^2 T.

    slices: DataFrame(expiry, T, F, alpha, rho, nu) for observed expiries
    anchor: dict(T, alpha, rho, nu), the 3Y assumption slice
    q_long: dividend yield assumed after the last observed expiry
    calendar_floor: apply w_i(m) >= w_{i-1}(m) on observed slices (see slice_total_variance)
    """

    def __init__(self, slices, anchor, q_long, calendar_floor=True):
        self.slices = slices.sort_values("T").reset_index(drop=True)
        self.anchor = anchor
        self.q_long = q_long
        self.calendar_floor = calendar_floor
        self.T_obs = self.slices["T"].to_numpy()
        self.T_last = self.T_obs[-1]
        self._lnf_T = np.r_[0.0, self.T_obs]
        self._lnf = np.r_[0.0, np.log(self.slices["F"].to_numpy() / S0)]
        self._div_last = zero_rate(self.T_last) * self.T_last - self._lnf[-1]

    def forward(self, T):
        """ln F linear up to the last observed expiry, then ln F/S0 = r(T) T - [D_last + q_long (T - T_last)]."""
        T = np.asarray(T, dtype=float)
        inside = np.interp(T, self._lnf_T, self._lnf)
        outside = zero_rate(T) * T - (self._div_last + self.q_long * (T - self.T_last))
        return S0 * np.exp(np.where(T <= self.T_last, inside, outside))

    def sabr_total_variance(self, i, m):
        s = self.slices.iloc[i]
        return sabr_vol(1.0, m, s["T"], s["alpha"], s["rho"], s["nu"]) ** 2 * s["T"]

    def slice_total_variance(self, i, m):
        """Total variance the surface uses on observed expiry i.

        With the calendar floor, w_i(m) = max over j <= i of the SABR w_j(m). It only binds in
        wings without market data, where one slice's SABR extrapolation can fall below the
        previous one; where data exists the SABR fit is left unchanged.
        """
        if not self.calendar_floor:
            return self.sabr_total_variance(i, m)
        w = self.sabr_total_variance(0, m)
        for j in range(1, i + 1):
            w = np.maximum(w, self.sabr_total_variance(j, m))
        return w

    def anchor_total_variance(self, m, T):
        a = self.anchor
        return sabr_vol(1.0, m, a["T"], a["alpha"], a["rho"], a["nu"]) ** 2 * T

    def long_total_variance(self, m, T):
        """T > T_last: w linear between the last observed slice and the 3Y slice, flat sigma after 3Y."""
        T = np.asarray(T, dtype=float)
        T_a = self.anchor["T"]
        w_last = self.slice_total_variance(len(self.slices) - 1, m)
        w_anchor = self.anchor_total_variance(m, T_a)
        lam = np.clip((T - self.T_last) / (T_a - self.T_last), 0.0, 1.0)
        return np.where(T <= T_a, w_last + lam * (w_anchor - w_last), self.anchor_total_variance(m, T))

    def total_variance(self, K, T):
        K, T = np.broadcast_arrays(np.asarray(K, dtype=float), np.asarray(T, dtype=float))
        m = K / self.forward(T)
        out = np.empty(K.shape)
        out[...] = self.slice_total_variance(0, m) / self.T_obs[0] * T   # before the first expiry: flat sigma

        for i in range(len(self.T_obs) - 1):                             # between observed expiries: linear w
            T1, T2 = self.T_obs[i], self.T_obs[i + 1]
            sel = (T > T1) & (T <= T2)
            if sel.any():
                w1 = self.slice_total_variance(i, m[sel])
                w2 = self.slice_total_variance(i + 1, m[sel])
                out[sel] = w1 + (T[sel] - T1) / (T2 - T1) * (w2 - w1)

        sel = T > self.T_last                                            # long end: assumption
        if sel.any():
            out[sel] = self.long_total_variance(m[sel], T[sel])
        return out

    def implied_vol(self, K, T):
        T = np.maximum(np.asarray(T, dtype=float), 1e-8)
        return np.sqrt(self.total_variance(K, T) / T)


def varswap_vol_from_smile(vol_fn, T, m_range=VARSWAP_M_RANGE, n=4001):
    """VIX-style variance-swap vol: sigma^2 = (2/T) * integral of OTM(m) / m^2 dm (F = 1, undiscounted)."""
    m = np.linspace(*m_range, n)
    sig = vol_fn(m)
    otm = np.where(m < 1.0, black_price(1.0, m, T, sig, "P"), black_price(1.0, m, T, sig, "C"))
    return np.sqrt(2.0 / T * np.trapezoid(otm / m ** 2, m))


def varswap_vol(surface, T):
    F = surface.forward(T)
    return varswap_vol_from_smile(lambda m: surface.implied_vol(m * F, T), T)


def build_surface(params, anchor_type="varswap", anchor_vol=ELS_FAIR_VOL, anchor_T=ANCHOR_T,
                  base_expiry=EXTRAP_BASE_EXPIRY, q_long=None, calendar_floor=True):
    """Observed slices plus the long-end assumption.

    rho_L = rho(base), nu_L = nu(base) * sqrt(T_base / 3).
    alpha_L makes the 3Y ATM vol ("atm") or the 3Y variance-swap vol ("varswap") equal anchor_vol.
    q_long defaults to the cumulative dividend up to the last observed expiry, treated as one year's worth.
    """
    if anchor_type not in ("atm", "varswap"):
        raise ValueError('anchor_type must be "atm" or "varswap"')
    params = params.sort_values("T").reset_index(drop=True)
    base = params.set_index("expiry").loc[base_expiry]
    rho_l, nu_l = base["rho"], base["nu"] * np.sqrt(base["T"] / anchor_T)

    def smile(a):
        return lambda m: sabr_vol(1.0, m, anchor_T, a, rho_l, nu_l)

    if anchor_type == "atm":
        f = lambda a: smile(a)(1.0) - anchor_vol                                     # noqa: E731
    else:
        f = lambda a: varswap_vol_from_smile(smile(a), anchor_T) - anchor_vol        # noqa: E731
    anchor = dict(T=anchor_T, alpha=brentq(f, 0.01, 1.5), rho=rho_l, nu=nu_l)
    if q_long is None:
        last = params.iloc[-1]
        q_long = zero_rate(last["T"]) * last["T"] - np.log(last["F"] / S0)
    cols = ["expiry", "T", "F", "alpha", "rho", "nu"]
    return VolSurface(params[cols], anchor, float(q_long), calendar_floor=calendar_floor)
