"""Expiry forwards from put-call parity."""

import numpy as np
import pandas as pd


def parity_forwards(pairs: pd.DataFrame) -> pd.Series:
    """F per expiry from C - P = DF (F - K): F_K = K + (C - P) / DF, median over strikes.

    pairs: columns expiry, DF, K, call, put (near-the-money strikes).
    The median removes single-strike noise from stale settlement prices.
    """
    f_k = pairs["K"] + (pairs["call"] - pairs["put"]) / pairs["DF"]
    return f_k.groupby(pairs["expiry"]).median()


def forward_futures_gap_bp(forwards: pd.Series, futures: pd.Series) -> pd.Series:
    """(F_parity / futures - 1) in bp, for expiries that have a futures price."""
    common = forwards.index.intersection(futures.dropna().index)
    return (forwards[common] / futures[common] - 1.0) * 1e4
