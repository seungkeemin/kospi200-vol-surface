"""Monte Carlo for Mirae Asset Securities ELS No. 38133 (KOSPI200, 3Y, knock-in 40%).

Terms from the prospectus (KR6MD0008YV6): five semi-annual autocall dates, barriers 85/85/85/80/75%,
4.6% per period; at maturity 12,760 won unless the index closed below 40% of the initial level on
any day after the initial fixing and ends below 70%, in which case 10,000 x S_T / S_ref.
Payment is 3 business days after each observation. Korean holidays are not modelled.
"""

import datetime as dt

import numpy as np

from .config import S0, VAL_DATE
from .curve import discount_factor
from .localvol import local_vol

FACE = 10000.0
AC_DATES = [dt.date(2027, 3, 30), dt.date(2027, 9, 28), dt.date(2028, 3, 28), dt.date(2028, 9, 26), dt.date(2029, 3, 28)]
AC_BARRIER = np.array([0.85, 0.85, 0.85, 0.80, 0.75])
AC_PAYOFF = FACE * (1 + 0.046 * np.arange(1, 6))              # 10,460 ... 12,300
FIX_DATE = dt.date(2026, 10, 2)                               # initial reference fixing (prospectus)
MAT_DATE, MAT_PAY_DATE = dt.date(2029, 9, 27), dt.date(2029, 10, 2)
MAT_BARRIER, KI_BARRIER, MAT_COUPON = 0.70, 0.40, 12760.0


def add_business_days(d, n):
    while n > 0:
        d += dt.timedelta(days=1)
        n -= d.weekday() < 5
    return d


def time_grid():
    """Weekdays plus observation dates. Returns t (ACT/365) and the indices of fixing, autocalls, maturity."""
    special = {FIX_DATE, MAT_DATE, *AC_DATES}
    days, d = [], VAL_DATE
    while d <= MAT_DATE:
        if d.weekday() < 5 or d in special:
            days.append(d)
        d += dt.timedelta(days=1)
    t = np.array([(x - VAL_DATE).days / 365.0 for x in days])
    return t, days.index(FIX_DATE), [days.index(a) for a in AC_DATES], days.index(MAT_DATE)


def payment_discount_factors():
    pays = [add_business_days(a, 3) for a in AC_DATES] + [MAT_PAY_DATE]
    return discount_factor(np.array([(p - VAL_DATE).days / 365.0 for p in pays]))


DF_PAY = payment_discount_factors()                           # 5 autocalls + maturity


def evolve(lnS, lnF0, lnF1, sigma, dt_, z):
    """One step of ln S under the forward measure: E[S_t] = F(t) for any sigma."""
    return lnS + (lnF1 - lnF0) - 0.5 * sigma * sigma * dt_ + sigma * np.sqrt(dt_) * z


def els_pv(ref, S_ac, S_T, min_S):
    """Present value per path. ref, S_T, min_S: (n,); S_ac: (5, n)."""
    pv = np.zeros(len(ref))
    alive = np.ones(len(ref), dtype=bool)
    for k in range(5):
        hit = alive & (S_ac[k] >= AC_BARRIER[k] * ref)
        pv[hit] = AC_PAYOFF[k] * DF_PAY[k]
        alive &= ~hit
    knocked = min_S < KI_BARRIER * ref
    r = S_T / ref
    redeem = np.where((r >= MAT_BARRIER) | ~knocked, MAT_COUPON, FACE * r)
    pv[alive] = redeem[alive] * DF_PAY[5]
    return pv


class FlatVol:
    def __init__(self, sigma):
        self.sigma = sigma

    def __call__(self, k, S):
        return self.sigma


class LocalVolTable:
    """Local vol precomputed at every simulation time on a K/S0 grid, interpolated at K = current S."""

    def __init__(self, surface, t, x=np.linspace(0.35, 1.30, 96)):
        self.x = x
        self.table = np.empty((len(t), len(x)))
        for k, tk in enumerate(t):
            self.table[k] = local_vol(surface, x * S0, np.full_like(x, max(tk, 1e-4)))

    def __call__(self, k, S):
        return np.interp(np.clip(S / S0, self.x[0], self.x[-1]), self.x, self.table[k])


def run_els(surface, sigma_fn, n_paths, seed, ref_mode="fix", snapshots=()):
    """Simulate the ELS with antithetic normals.

    ref_mode "fix": initial level is the simulated close on FIX_DATE (prospectus). "spot" uses S0
    and is the wrong reading: the fair value date (09-14) is 18 days before the fixing.
    Knock-in is watched from the day after the fixing.
    """
    if ref_mode not in ("fix", "spot"):
        raise ValueError('ref_mode must be "fix" or "spot"')
    t, i_fix, i_ac, _ = time_grid()
    rng = np.random.default_rng(seed)
    half = n_paths // 2
    lnF = np.log(surface.forward(t))
    lnS = np.full(2 * half, np.log(S0))
    ref = np.full(2 * half, S0) if ref_mode == "spot" else None
    min_S = np.full(2 * half, np.inf)
    S_ac, snaps = np.zeros((5, 2 * half)), {}
    for k in range(len(t) - 1):
        z = rng.standard_normal(half)
        z = np.r_[z, -z]
        lnS = evolve(lnS, lnF[k], lnF[k + 1], sigma_fn(k, np.exp(lnS)), t[k + 1] - t[k], z)
        j, S = k + 1, np.exp(lnS)
        if j in snapshots:
            snaps[j] = S.copy()
        if j == i_fix and ref is None:
            ref = S.copy()
        if j > i_fix:
            min_S = np.minimum(min_S, S)
            if j in i_ac:
                S_ac[i_ac.index(j)] = S
    S_T = np.exp(lnS)
    pv = els_pv(ref, S_ac, S_T, min_S)
    hit = S_ac >= AC_BARRIER[:, None] * ref
    red = np.where(hit.any(axis=0), hit.argmax(axis=0), 5)
    return dict(pv=pv, red=red, ki=min_S < KI_BARRIER * ref, r_T=S_T / ref, S_T=S_T, snaps=snaps, t=t)


def price_stats(res):
    pv = res["pv"]
    return pv.mean(), pv.std(ddof=1) / np.sqrt(len(pv))


def redemption_table(res):
    """Probability of each redemption event and its contribution to the price."""
    n = len(res["pv"])
    rows = []
    for a, label in enumerate(["autocall 1", "autocall 2", "autocall 3", "autocall 4", "autocall 5", "maturity"]):
        sel = res["red"] == a
        rows.append((label, sel.mean(), res["pv"][sel].sum() / n))
    loss = (res["red"] == 5) & res["ki"] & (res["r_T"] < MAT_BARRIER)
    rows.append(("maturity loss (knock-in, < 70%)", loss.mean(), res["pv"][loss].sum() / n))
    rows.append(("knock-in touched", res["ki"].mean(), np.nan))
    return rows
