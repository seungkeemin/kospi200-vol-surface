"""Dupire local vol on the calibrated surface, the zero-local-vol wedge, and the ELS price.

Runs from the calibrated SABR parameters in tests/fixtures (no KRX data needed):

    python scripts/run_els.py            # about 30 seconds, writes figures/local_vol_*.png, figures/els_*.png
"""

import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from volsurface import black_iv, build_surface, check_butterfly, check_calendar, sabr_vol, standard_grids, varswap_vol  # noqa: E402
from volsurface.config import ELS_FAIR_PRICE, ELS_FAIR_VOL, MIN_FWD_VAR, SMOOTH_EPS, S0  # noqa: E402
from volsurface.els import FlatVol, LocalVolTable, price_stats, redemption_table, run_els, time_grid  # noqa: E402
from volsurface.localvol import diagnostic_grid, local_vol, lv_on_grid  # noqa: E402

N_PATHS, SEED = 2 ** 17, 11
PARAMS = pd.read_csv(ROOT / "tests" / "fixtures" / "sabr_params.csv", dtype={"expiry": str})


def fit_change_bp(surf, m=np.linspace(0.59, 1.30, 72)):
    """Largest change from the calibrated SABR smile on the strikes with market data (K/F 0.59..1.30)."""
    return max(np.abs(surf.implied_vol(m * surf.forward(p["T"]), p["T"]) - sabr_vol(1.0, m, p["T"], p.alpha, p.rho, p.nu)).max()
               for _, p in PARAMS.iterrows()) * 1e4


def main():
    XX, TT = diagnostic_grid()
    plain = build_surface(PARAMS)
    lv1 = lv_on_grid(plain, XX, TT)
    bad = lv1 < 0.01
    print(f"plain calendar floor: local vol < 1% on {bad.sum()} of {lv1.size} grid points, "
          f"T {TT[bad].min():.2f}~{TT[bad].max():.2f}, K/F {XX[bad].min():.2f}~{XX[bad].max():.2f}")

    print("\nfloor size sweep (smooth max eps = %.0e)" % SMOOTH_EPS)
    print(f"{'v':>7} {'fwd vol':>8} {'fit chg bp':>11} {'min LV':>7}")
    for v in [0.0, 0.01, 0.02, 0.0225, 0.025, 0.03, 0.035, 0.04]:
        s = build_surface(PARAMS, min_fwd_var=v, smooth_eps=SMOOTH_EPS)
        print(f"{v:7.4f} {np.sqrt(v):8.1%} {fit_change_bp(s):11.3f} {lv_on_grid(s, XX, TT).min():7.3f}")

    surf = build_surface(PARAMS, min_fwd_var=MIN_FWD_VAR, smooth_eps=SMOOTH_EPS)
    k, T = standard_grids()
    lv2 = lv_on_grid(surf, XX, TT)
    print(f"\nfloor with minimum forward variance (v = {MIN_FWD_VAR}, eps = {SMOOTH_EPS}): fit change {fit_change_bp(surf):.3f}bp, "
          f"calendar {len(check_calendar(surf, k, T))}, butterfly {len(check_butterfly(surf, k, T))}, "
          f"3Y variance-swap vol {varswap_vol(surf, 3.0):.2%}, min local vol {lv2.min():.3f}")

    t, _, i_ac, i_mat = time_grid()
    res_flat = run_els(surf, FlatVol(ELS_FAIR_VOL), N_PATHS, SEED)
    table = LocalVolTable(surf, t)
    snaps = [i_ac[0], i_ac[2], i_mat]
    res_lv = run_els(surf, table, N_PATHS, SEED, snapshots=set(snaps))
    F_t = surf.forward(t)
    ts_sig = np.array([np.interp(F_t[j] / S0, table.x, table.table[j]) for j in range(len(t))])
    res_ts = run_els(surf, lambda j, S: ts_sig[j], N_PATHS, SEED)
    res_spot = run_els(surf, FlatVol(ELS_FAIR_VOL), N_PATHS, SEED, ref_mode="spot")

    p_flat, se_flat = price_stats(res_flat)
    p_ts, se_ts = price_stats(res_ts)
    p_lv, se_lv = price_stats(res_lv)
    p_spot, se_spot = price_stats(res_spot)
    print(f"\nELS ({N_PATHS:,} antithetic paths, seed {SEED}, 794 daily steps)")
    print(f"  disclosed fair value        {ELS_FAIR_PRICE:9,.2f}")
    print(f"  flat 35.47%, ref = fixing   {p_flat:9,.2f} ± {se_flat:.2f}   ({p_flat - ELS_FAIR_PRICE:+.2f})")
    print(f"  flat 35.47%, ref = spot     {p_spot:9,.2f} ± {se_spot:.2f}   ({p_spot - ELS_FAIR_PRICE:+.2f})  <- wrong initial level")
    print(f"  ATM local vol term structure{p_ts:9,.2f} ± {se_ts:.2f}   (term structure {p_ts - p_flat:+.1f})")
    print(f"  local vol                   {p_lv:9,.2f} ± {se_lv:.2f}   (skew {p_lv - p_ts:+.1f}, total {p_lv - p_flat:+.1f})")

    print("\nmartingale E[S_T]/F(T):", round(res_lv["S_T"].mean() / float(F_t[-1]), 4))
    print("vanilla repricing on the local vol paths (MC implied vol - surface implied vol, bp):")
    for j in snaps:
        F = float(surf.forward(t[j]))
        diffs = []
        for m in [0.7, 0.85, 1.0, 1.1]:
            K, cp = m * F, ("P" if m < 1 else "C")
            S = res_lv["snaps"][j]
            mc = (np.maximum(K - S, 0) if cp == "P" else np.maximum(S - K, 0)).mean()
            diffs.append((black_iv(mc, F, K, t[j], cp) - float(surf.implied_vol(K, t[j]))) * 1e4)
        print(f"  T={t[j]:.2f}: " + "  ".join(f"{d:+.1f}" for d in diffs))

    print(f"\n{'event':<32}{'flat P':>8}{'LV P':>8}{'flat contrib':>14}{'LV contrib':>12}")
    for (lab, pf, cf), (_, pl, cl) in zip(redemption_table(res_flat), redemption_table(res_lv)):
        cf_s = f"{cf:14,.1f}" if np.isfinite(cf) else " " * 14
        cl_s = f"{cl:12,.1f}" if np.isfinite(cl) else " " * 12
        print(f"{lab:<32}{pf:8.1%}{pl:8.1%}{cf_s}{cl_s}")

    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
    except ImportError:
        print("\nmatplotlib not installed: figures skipped")
        return
    fig = plt.figure(figsize=(13, 5))
    sel_x, sel_t = XX[0] <= 1.0, TT[:, 0] <= 1.5
    for n, (name, Z) in enumerate([("Plain calendar floor: local vol", lv1), ("With minimum forward variance: local vol", lv2)]):
        ax = fig.add_subplot(1, 2, n + 1, projection="3d")
        ax.plot_surface(XX[np.ix_(sel_t, sel_x)], TT[np.ix_(sel_t, sel_x)], np.minimum(Z[np.ix_(sel_t, sel_x)], 0.9),
                        cmap="viridis", vmin=0, vmax=0.9, linewidth=0, antialiased=True)
        ax.set_xlabel("K/F"); ax.set_ylabel("T (years)"); ax.set_zlabel("local vol"); ax.set_zlim(0, 0.9)
        ax.set_title(name); ax.view_init(elev=25, azim=-60)
    plt.tight_layout(); fig.savefig(ROOT / "figures" / "local_vol_wedge.png", dpi=130); plt.close(fig)

    fig, ax = plt.subplots(figsize=(7, 3.6))
    labels = ["disclosed\n(flat 35.47%)", "flat 35.47%\nMC", "ATM local vol\n(term structure)", "local vol\n(with skew)"]
    vals, ses = [ELS_FAIR_PRICE, p_flat, p_ts, p_lv], [0, se_flat, se_ts, se_lv]
    ax.bar(range(4), vals, color=["#9aa3ad", "#2F5FB3", "#8E6BB5", "#E07B39"], width=0.55)
    for n, (v, se) in enumerate(zip(vals, ses)):
        ax.text(n, v + 12, f"{v:,.0f}", ha="center", fontsize=9)
        if se:
            ax.errorbar(n, v, yerr=se, color="k", capsize=3, lw=1)
    ax.set_xticks(range(4)); ax.set_xticklabels(labels); ax.set_ylim(9400, 9950); ax.set_ylabel("ELS price (KRW per 10,000)")
    plt.tight_layout(); fig.savefig(ROOT / "figures" / "els_decomposition.png", dpi=130); plt.close(fig)
    print("\nfigures written")


if __name__ == "__main__":
    main()
