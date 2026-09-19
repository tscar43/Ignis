"""Offline tests for the Rothermel surface spread model. No network.

These pin behaviour and the published intermediates. The comparison against
the BehavePlus computational core lives outside the suite -- it needs
`pyrothermel`, which is not a dependency of this repo -- so what is pinned
here is every conclusion that comparison reached: six size-class bins rather
than three, curing derived rather than set, mineral damping deliberately
absent. Each of those was a real bug, and each would return plausible metres
per minute if it came back. FINDINGS.md has the numbers.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from backend.fire import rothermel  # noqa: E402

GR2, SH5, TL1, NB1 = 102, 145, 181, 91


def test_every_fbfm40_model_is_present_and_only_the_nb_family_is_inert():
    assert len(rothermel.FUEL_MODELS) == 45          # 40 burnable + 5 NB
    assert rothermel.NONBURNABLE == frozenset({91, 92, 93, 98, 99})


def test_non_burnable_never_spreads_however_hard_the_wind_blows():
    assert rothermel.spread_rate_m_per_min(NB1, 100.0) == 0.0
    assert rothermel.no_wind_no_slope_rate(NB1) == 0.0


def test_an_unknown_code_is_treated_as_non_burnable_not_an_exception():
    """LANDFIRE nodata reaches this function; it must not raise mid-raster."""
    assert rothermel.spread_rate_m_per_min(0, 30.0) == 0.0
    assert rothermel.spread_rate_m_per_min(255, 30.0) == 0.0


def test_spread_rate_rises_monotonically_with_wind():
    rates = [rothermel.spread_rate_m_per_min(GR2, w) for w in (0, 5, 10, 20, 50)]
    assert rates == sorted(rates)
    assert rates[0] > 0


def test_grass_outruns_timber_litter_at_every_wind_speed():
    for wind in (0, 10, 40):
        assert (rothermel.spread_rate_m_per_min(GR2, wind)
                > rothermel.spread_rate_m_per_min(TL1, wind))


def test_wet_dead_fuel_above_the_extinction_moisture_stops_the_fire():
    """GR2's dead M_x is 15%. Past it the damping coefficient floors at zero."""
    soaked = rothermel.Moisture(dead_1hr=0.40, dead_10hr=0.40, dead_100hr=0.40)
    # The damping polynomial is exactly zero at r = 1 only in exact arithmetic;
    # in floats it lands around 1e-14 m/min, which is 4e-12 m over the 6 h
    # horizon. Physically stopped, so the tolerance goes here rather than a
    # clamp going into the model.
    assert rothermel.spread_rate_m_per_min(GR2, 30.0, moisture=soaked) == (
        pytest.approx(0.0, abs=1e-9))


def test_drier_dead_fuel_always_spreads_faster():
    rates = [rothermel.spread_rate_m_per_min(
                 SH5, 20.0, moisture=rothermel.Moisture(dead_1hr=m))
             for m in (0.03, 0.06, 0.10, 0.14)]
    assert rates == sorted(rates, reverse=True)


def test_curing_is_derived_from_live_herbaceous_moisture():
    """Fully green at 120%, fully cured at 30%, linear between.

    It used to be a free parameter defaulting to 1.0, which ran the grass
    models up to 60% fast against the BehavePlus core: full curing moves every
    blade into the dead pool at 6% moisture.
    """
    assert rothermel.Moisture(live_herbaceous=1.50).curing == 0.0
    assert rothermel.Moisture(live_herbaceous=1.20).curing == 0.0
    assert rothermel.Moisture(live_herbaceous=0.30).curing == pytest.approx(1.0)
    assert rothermel.Moisture(live_herbaceous=0.10).curing == 1.0
    assert rothermel.Moisture(live_herbaceous=0.75).curing == pytest.approx(0.5)


def test_curing_is_what_makes_a_grass_model_burn():
    """Green grass barely spreads; cured grass runs.

    Dropping the curing step is a silent failure: the model still returns a
    number, just a far too small one, and only the grass families show it.
    """
    cured = rothermel.Moisture(live_herbaceous=0.30)
    green = rothermel.Moisture(live_herbaceous=1.20)
    assert (rothermel.spread_rate_m_per_min(GR2, 20.0, moisture=cured)
            > 5 * rothermel.spread_rate_m_per_min(GR2, 20.0, moisture=green))


def test_six_size_class_bins_not_three():
    """Collapsing 10-hr and 100-hr into one bin over-weights coarse fuels.

    It cost up to +73% on the litter models with the heaviest 100-hr loads
    (TL4, TL7, SB1) against the BehavePlus core, while leaving the
    1-hr-dominated ones untouched -- which is exactly how it stayed hidden.
    """
    assert len(rothermel.SAV_BIN_EDGES) == 5        # five edges, six bins
    assert rothermel._sav_bin(2000.0) == 0          # 1-hr
    assert rothermel._sav_bin(109.0) == 2           # 10-hr
    assert rothermel._sav_bin(30.0) == 4            # 100-hr
    assert rothermel._sav_bin(109.0) != rothermel._sav_bin(30.0)


def test_mineral_damping_is_deliberately_not_applied():
    """Guard against someone reinstating it from the published equation.

    Rothermel gives eta_s = 0.174 S_E^-0.19 = 0.4174 at S_E = 0.01. Applying
    it puts this model a factor of 2.4 under the BehavePlus core, and the
    arithmetic says BehavePlus is right: matching its reaction intensity for
    TL8 with the coefficient in place needs a net fuel load of 0.578 lb/ft2
    when TL8's entire oven-dry load is 0.381.
    """
    assert rothermel.MINERAL_DAMPING_APPLIED is False
    source = Path(rothermel.__file__).read_text(encoding="utf-8")
    body = source.split("def no_wind_no_slope_rate")[1]
    assert "S_E ** -0.19" not in body


def test_live_extinction_moisture_exceeds_the_tabulated_dead_value():
    """It is derived, not tabulated, and rises as the dead fuel dries out."""
    delta, m_x_dead, w_o, sigma, m_f = rothermel._fuel_bed(
        SH5, rothermel.Moisture())
    live = rothermel._live_extinction_moisture(w_o, sigma, m_f, m_x_dead)
    assert live > m_x_dead

    wetter = rothermel._fuel_bed(SH5, rothermel.Moisture(dead_1hr=0.13))[4]
    assert rothermel._live_extinction_moisture(w_o, sigma, wetter, m_x_dead) < live


def test_the_two_weightings_are_not_the_same_array():
    """f_ij weights by surface area, g_ij by SAV bin. Conflating them is the
    classic Rothermel bug: plausible output, wrong reaction intensity."""
    _, _, w_o, sigma, _ = rothermel._fuel_bed(161, rothermel.Moisture())  # TU1
    f_ij, _, g_ij = rothermel._weightings(w_o, sigma)
    assert f_ij != g_ij
    assert sum(f_ij[j] for j in rothermel.DEAD) == pytest.approx(1.0)


def test_slope_only_ever_speeds_fire_up_and_scales_with_the_square():
    flat = rothermel.spread_rate_m_per_min(SH5, 10.0, slope_tan=0.0)
    gentle = rothermel.spread_rate_m_per_min(SH5, 10.0, slope_tan=0.2)
    steep = rothermel.spread_rate_m_per_min(SH5, 10.0, slope_tan=0.4)
    assert flat < gentle < steep
    # phi_slope goes as tan^2, so quadrupling the excess over flat.
    assert (steep - flat) == pytest.approx(4 * (gentle - flat), rel=0.01)


def test_calm_air_carries_no_wind_factor():
    phi_wind, phi_slope = rothermel.wind_slope_factors(GR2, 0.0, 0.0)
    assert phi_wind == 0.0 and phi_slope == 0.0
    assert (rothermel.spread_rate_m_per_min(GR2, 0.0)
            == pytest.approx(rothermel.no_wind_no_slope_rate(GR2)
                             * rothermel.FT_TO_M))


def test_there_is_no_fitted_rate_constant_to_calibrate():
    """The reason this model is in the ensemble at all.

    `spread.py` carries R0_M_PER_MIN, fitted per incident and measured in
    palisades.py failing to transfer across a wind regime. Nothing here plays
    that role, so a guard against one quietly appearing.
    """
    assert not hasattr(rothermel, "R0_M_PER_MIN")
    assert not any(name.startswith("R0") for name in vars(rothermel))


# Characteristic SAV (1/ft) and packing ratio, as published on each fuel model's
# page in Scott & Burgan 2005 RMRS-GTR-153. These are two of the model's own
# intermediates, so they check the weighting logic and the curing transfer
# against the primary source rather than against another implementation.
# All 40 models were compared when this was written; 39 agree to 0.1%. The
# spread across families is what is kept here.
PUBLISHED = {
    101: ("GR1", 2054, 0.00143),
    102: ("GR2", 1820, 0.00158),
    109: ("GR9", 1612, 0.00316),
    145: ("SH5", 1252, 0.00206),
    164: ("TU4", 2216, 0.01865),
    181: ("TL1", 1716, 0.04878),
    204: ("SB4", 1907, 0.00744),
}


@pytest.mark.parametrize("code", sorted(PUBLISHED))
def test_characteristic_sav_matches_the_published_value(code):
    name, sav_published, _ = PUBLISHED[code]
    _, _, w_o, sigma, _ = rothermel._fuel_bed(code, rothermel.Moisture())
    f_ij, f_i, _ = rothermel._weightings(w_o, sigma)
    assert rothermel._characteristic_sav(f_ij, f_i, sigma) == pytest.approx(
        sav_published, rel=0.001), name


@pytest.mark.parametrize("code", sorted(PUBLISHED))
def test_packing_ratio_matches_the_published_value(code):
    name, _, beta_published = PUBLISHED[code]
    delta, _, w_o, _, _ = rothermel._fuel_bed(code, rothermel.Moisture())
    beta = sum(w_o) / rothermel.RHO_P / delta
    # Published to five decimals, so the smallest models round hard.
    assert beta == pytest.approx(beta_published, rel=0.006), name


def test_gr6_is_the_one_model_that_is_not_8000_btu_per_pound():
    """Caught by the table verification, not by inspection.

    The module hardcoded 8000 for all 40 with a comment claiming they were all
    the same. GR6 is 9000, and nothing else is.
    """
    assert rothermel.heat_content(106) == 9000.0
    assert rothermel.HEAT_CONTENT_BY_MODEL == {106: 9000.0}
    for code in rothermel.FUEL_MODELS:
        if code != 106:
            assert rothermel.heat_content(code) == 8000.0


def test_gs4_is_the_known_disagreement_with_the_published_intermediates():
    """GS4 computes to 1631, its GTR-153 page says 1674 -- a 2.6% gap.

    Characteristic SAV telescopes to sum(sigma^2 w) / sum(sigma w), which is
    invariant to how load is split between the dead and live categories, so
    curing cannot explain it. The packing ratio and fine fuel load on the same
    page both agree with our loads, which rules the loads out too. Left as a
    pinned known difference rather than tuned away: bending one model's inputs
    to hit one published number is exactly the kind of fit this repo refuses
    elsewhere.
    """
    _, _, w_o, sigma, _ = rothermel._fuel_bed(124, rothermel.Moisture())
    f_ij, f_i, _ = rothermel._weightings(w_o, sigma)
    assert rothermel._characteristic_sav(f_ij, f_i, sigma) == pytest.approx(1631, rel=0.002)
