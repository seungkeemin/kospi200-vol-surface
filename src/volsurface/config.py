"""Valuation date, spot, KRW rate quotes and ELS inputs shared by week 1 and week 2."""

import datetime as dt

VAL_DATE = dt.date(2026, 9, 14)
S0 = 1050.83                       # KOSPI200 close

# KRW rate quotes on 2026-09-14
CD91_RATE = 0.03160                # CD 91D, simple, ACT/365
KTB_YIELDS = {                     # KTB final quotes: par yields of semi-annual coupon bonds
    1.0: 0.03573,
    2.0: 0.03932,
    3.0: 0.04025,
    5.0: 0.04279,
}
CD_DAYS = 91
COUPON_FREQ = 2

# ELS (Mirae Asset Securities No. 38133) valuation inputs
ELS_FAIR_VOL = 0.3547              # disclosed valuation vol (prospectus)
SURFACE_T_MAX = 3.1
SURFACE_K_RANGE = (0.35, 1.30)

# Surface construction
EXTRAP_BASE_EXPIRY = "202612"      # expiry whose rho, nu anchor the long end
ANCHOR_T = 3.0                     # 3Y assumption slice
VARSWAP_M_RANGE = (0.20, 2.50)     # variance-swap integration range in K/F
