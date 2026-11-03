import numpy as np

from volsurface import sabr_vol

F, T, ALPHA, RHO, NU = 1050.0, 0.5, 0.40, -0.3, 1.0


def test_atm_has_no_nan_and_matches_hagan_2_18():
    atm_218 = ALPHA * (1 + (RHO * NU * ALPHA / 4 + (2 - 3 * RHO**2) * NU**2 / 24) * T)
    K = F * np.array([1 - 1e-9, 1.0, 1 + 1e-9])
    vol = sabr_vol(F, K, T, ALPHA, RHO, NU)
    assert np.all(np.isfinite(vol))
    np.testing.assert_allclose(vol, atm_218, atol=1e-6)


def test_wings_match_hagan_2_17_reference_values():
    # Reference values checked in the assignment against a direct evaluation of (2.17).
    vol = sabr_vol(F, F * np.array([0.5, 1.3]), T, ALPHA, RHO, NU)
    np.testing.assert_allclose(vol, [0.594123, 0.397184], atol=1e-5)


def test_array_in_array_out():
    K = F * np.linspace(0.35, 1.30, 50)
    assert sabr_vol(F, K, T, ALPHA, RHO, NU).shape == K.shape
