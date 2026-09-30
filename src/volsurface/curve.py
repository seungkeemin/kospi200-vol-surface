"""KRW discount curve bootstrapped from CD 91D and KTB par yields."""

import datetime as dt

import numpy as np
from scipy.optimize import brentq

from .config import CD91_RATE, CD_DAYS, COUPON_FREQ, KTB_YIELDS, VAL_DATE


def year_frac(d, ref=VAL_DATE):
    """ACT/365."""
    return (d - ref).days / 365.0


def expiry_date(yyyymm):
    """KOSPI200 option expiry: second Thursday of the month."""
    y, m = int(str(yyyymm)[:4]), int(str(yyyymm)[4:6])
    first = dt.date(y, m, 1)
    offset = (3 - first.weekday()) % 7          # Thursday = 3
    return first + dt.timedelta(days=offset + 7)


def _lndf(T, t_nodes, lndf_nodes):
    """ln DF linear between (0, 0) and the nodes (piecewise flat forward), flat zero rate after the last node."""
    T = np.asarray(T, dtype=float)
    t = np.r_[0.0, t_nodes]
    y = np.r_[0.0, lndf_nodes]
    return np.where(T <= t[-1], np.interp(T, t, y), y[-1] / t[-1] * T)


def bootstrap_curve(cd_rate=CD91_RATE, ktb_yields=KTB_YIELDS):
    """Bootstrap (T, ln DF) nodes.

    CD91: DF(91/365) = 1 / (1 + r * 91/365).
    KTB n years: a par bond with semi-annual coupon c = y, 1 = sum (c/2) DF(t_k) + DF(n),
    t_k = 0.5, 1.0, ..., n (coupon dates approximated at half-year steps, accrued interest ignored).
    Coupon-date DFs between nodes use ln DF interpolation, so each new node is solved with brentq.
    """
    t_cd = CD_DAYS / 365.0
    t_nodes = [t_cd]
    lndf_nodes = [-np.log(1.0 + cd_rate * t_cd)]
    for n, y in sorted(ktb_yields.items()):
        coupon_times = np.arange(1, int(round(n * COUPON_FREQ)) + 1) / COUPON_FREQ
        c = y / COUPON_FREQ

        def par_gap(lndf_n):
            lndf = _lndf(coupon_times, np.r_[t_nodes, n], np.r_[lndf_nodes, lndf_n])
            return c * np.exp(lndf).sum() + np.exp(lndf[-1]) - 1.0

        lndf_n = brentq(par_gap, -1.0, 0.0)
        t_nodes.append(n)
        lndf_nodes.append(lndf_n)
    return np.array(t_nodes), np.array(lndf_nodes)


def par_yield(n, t_nodes, lndf_nodes):
    """Par yield of an n-year semi-annual bond priced off the curve (used to check the bootstrap)."""
    coupon_times = np.arange(1, int(round(n * COUPON_FREQ)) + 1) / COUPON_FREQ
    df = np.exp(_lndf(coupon_times, t_nodes, lndf_nodes))
    return COUPON_FREQ * (1.0 - df[-1]) / df.sum()


CURVE_T, CURVE_LNDF = bootstrap_curve()


def discount_factor(T):
    return np.exp(_lndf(T, CURVE_T, CURVE_LNDF))


def zero_rate(T):
    """Continuously compounded zero rate r(T) = -ln DF(T) / T."""
    T = np.maximum(np.asarray(T, dtype=float), 1e-8)
    return -np.log(discount_factor(T)) / T
