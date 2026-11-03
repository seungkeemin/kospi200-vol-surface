"""KRX raw files -> data/market_iv.csv, expiries.csv, atm_pairs.csv, discount_curve.csv, forwards.csv.

Download the KOSPI200 options and futures daily prices for 2026-09-14 (day session) from
KRX data.krx.co.kr and save them as data/raw/kospi200_options.csv and
data/raw/kospi200_futures.csv (cp949, as exported). Then run:

    python scripts/preprocess.py
"""

import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from volsurface.config import CD91_RATE, KTB_YIELDS, S0, VAL_DATE  # noqa: E402
from volsurface.curve import (CURVE_LNDF, CURVE_T, discount_factor, expiry_date,  # noqa: E402
                              year_frac, zero_rate)
from volsurface.sabr import black_iv  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
RAW = ROOT / "data" / "raw"
OUT = ROOT / "data"

USE_EXPIRIES = ["202611", "202612", "202701", "202703"]
EXCLUDE_REASON = {
    "202610": "만기 < 1개월: 만기 직전 스마일 왜곡, 장기 surface에 기여 없음",
    "202702": "비분기 원월물, 사용 만기 목록 밖 (2701·2703 사이)",
}
LONG_REASON = "거래 거의 없음(이론 정산가), 옵션 가격과 선물 가격이 크게 어긋남"

MIN_PRICE = 0.05
KF_RANGE = (0.35, 1.30)
ATM_BAND = 0.05          # |K/F - 1| band used for the parity forward


def _num(s):
    return pd.to_numeric(s.astype(str).str.replace(",", "").str.strip(), errors="coerce")


def load_options():
    df = pd.read_csv(RAW / "kospi200_options.csv", encoding="cp949", dtype=str)
    parts = df["종목명"].str.extract(r"코스피200 ([CP]) (\d{6})\s+([\d,\.]+) \((주간|야간)\)")
    df["cp"], df["expiry"], df["K"], df["session"] = parts[0], parts[1], _num(parts[2]), parts[3]
    df = df[df["session"] == "주간"].copy()
    close, settle = _num(df["종가"]), _num(df["익일정산가"])
    df["price"] = close.where(close > 0, settle)
    df["price_src"] = np.where(close > 0, "종가", "정산가")
    df["oi"] = _num(df["미결제약정"]).fillna(0)
    df["volume"] = _num(df["거래량"]).fillna(0)
    return df[["expiry", "cp", "K", "price", "price_src", "oi", "volume"]].reset_index(drop=True)


def load_futures():
    df = pd.read_csv(RAW / "kospi200_futures.csv", encoding="cp949", dtype=str)
    parts = df["종목명"].str.extract(r"코스피200 F (\d{6}) \((주간|야간)\)")
    df["expiry"], df["session"] = parts[0], parts[1]
    df = df[(df["session"] == "주간") & df["expiry"].notna()].copy()
    close, settle = _num(df["종가"]), _num(df["정산가"])
    df["fut"] = close.where(close > 0, settle)
    df["fut_src"] = np.where(close > 0, "종가", "이론정산가")
    df["fut_volume"] = _num(df["거래량"]).fillna(0)
    return df.set_index("expiry")[["fut", "fut_src", "fut_volume"]]


def parity_forward(opt, T, ref):
    """Median of F_K = K + (C - P)/DF over strikes within ATM_BAND of F (two passes to recentre)."""
    df = float(discount_factor(T))
    piv = opt.pivot_table(index="K", columns="cp", values="price").dropna()
    piv = piv[(piv["C"] > 0) & (piv["P"] > 0)]
    F = ref
    for _ in range(2):
        near = piv[np.abs(piv.index / F - 1) <= ATM_BAND]
        if near.empty:
            return np.nan, 0
        F = float(np.median(near.index + (near["C"] - near["P"]) / df))
    return F, len(near)


def main():
    opt, fut = load_options(), load_futures()
    fwd_rows, iv_rows, pair_rows = [], [], []
    for exp, g in opt.groupby("expiry"):
        T = year_frac(expiry_date(exp))
        df, r = float(discount_factor(T)), float(zero_rate(T))
        fut_px = fut["fut"].get(exp, np.nan)
        ref = fut_px if np.isfinite(fut_px) else S0 * np.exp(r * T)
        F, n_par = parity_forward(g, T, ref)

        otm = g[((g["cp"] == "P") & (g["K"] < F)) | ((g["cp"] == "C") & (g["K"] >= F))].copy()
        otm = otm[(otm["price"] > MIN_PRICE) & (otm["oi"] > 0) & otm["K"].div(F).between(*KF_RANGE)]
        otm["iv"] = [black_iv(p, F, k, T, c, df) for p, k, c in zip(otm["price"], otm["K"], otm["cp"])]
        otm = otm.dropna(subset=["iv"]).sort_values("K")

        used = exp in USE_EXPIRIES
        reason = "" if used else EXCLUDE_REASON.get(exp, LONG_REASON)
        fwd_rows.append(dict(expiry=exp, expiry_date=expiry_date(exp), T=T, r=r, DF=df, F_parity=F,
                             n_parity=n_par, futures=fut_px, fut_src=fut["fut_src"].get(exp, "-"),
                             fut_volume=fut["fut_volume"].get(exp, np.nan),
                             diff_bp=(F / fut_px - 1) * 1e4 if np.isfinite(fut_px) else np.nan,
                             opt_volume=g["volume"].sum(), n_otm=len(otm), used=used, reason=reason))
        if used:
            iv_rows.append(otm.assign(expiry=exp, T=T, DF=df))
            piv = g.pivot_table(index="K", columns="cp", values="price").dropna()
            piv = piv[(piv["C"] > 0) & (piv["P"] > 0) & (np.abs(piv.index / S0 - 1) <= ATM_BAND)]
            pair_rows.append(pd.DataFrame({"expiry": exp, "T": T, "DF": df, "K": piv.index,
                                           "call": piv["C"].values, "put": piv["P"].values}))

    fwd = pd.DataFrame(fwd_rows)
    fwd.to_csv(OUT / "forwards.csv", index=False, encoding="utf-8-sig")
    pd.concat(iv_rows)[["expiry", "T", "DF", "K", "cp", "price", "price_src", "oi", "iv"]].to_csv(
        OUT / "market_iv.csv", index=False, encoding="utf-8-sig")
    fwd[["expiry", "expiry_date", "T", "r", "DF", "futures", "fut_src", "fut_volume", "opt_volume",
         "used", "reason"]].to_csv(OUT / "expiries.csv", index=False, encoding="utf-8-sig")
    pd.concat(pair_rows).to_csv(OUT / "atm_pairs.csv", index=False, encoding="utf-8-sig")

    quotes = [("CD91", CD91_RATE, "단리 ACT/365")]
    quotes += [(f"국고채 {int(n)}Y", y, "반기 이표 par yield") for n, y in sorted(KTB_YIELDS.items())]
    pd.DataFrame({"instrument": [q[0] for q in quotes], "quote": [q[1] for q in quotes],
                  "convention": [q[2] for q in quotes], "T": CURVE_T, "DF": np.exp(CURVE_LNDF),
                  "zero_cc": -CURVE_LNDF / CURVE_T}).to_csv(OUT / "discount_curve.csv", index=False,
                                                             encoding="utf-8-sig")
    pd.set_option("display.width", 200)
    print(f"valuation date {VAL_DATE}, S0 = {S0}")
    print(fwd[["expiry", "T", "F_parity", "futures", "fut_src", "fut_volume", "diff_bp", "opt_volume",
               "used"]].round(4).to_string(index=False))


if __name__ == "__main__":
    main()
