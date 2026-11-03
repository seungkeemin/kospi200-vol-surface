import numpy as np

from volsurface import bootstrap_curve, discount_factor, par_yield
from volsurface.config import CD91_RATE, CD_DAYS, KTB_YIELDS


def test_bootstrap_reproduces_the_five_input_quotes():
    t, lndf = bootstrap_curve()
    t_cd = CD_DAYS / 365.0
    np.testing.assert_allclose(discount_factor(t_cd), 1.0 / (1.0 + CD91_RATE * t_cd), rtol=1e-12)
    for n, y in KTB_YIELDS.items():
        np.testing.assert_allclose(par_yield(n, t, lndf), y, atol=1e-10)


def test_discount_factors_decrease():
    T = np.linspace(0.01, 5.0, 200)
    assert np.all(np.diff(discount_factor(T)) < 0)
