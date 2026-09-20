"""Rothermel surface fire spread, as an independent voice in the MAGI ensemble.

Why this exists. MAGI's three magi are three parameterizations of *one* kernel:
MELCHIOR-1 at defaults, BALTHASAR-2 with wind and R0 gains, CASPER-3 with the
fuel and slope terms dropped. They share the spread law, the seed, the wind and
the grid, so they agree for structural reasons rather than physical ones --
which is why `FINDINGS.md` records the ensemble never beating its best member.
An error bar drawn from correlated members is not an error bar.

BALTHASAR-2 is the one with nothing of its own to say. Its gains only ever
*increase* rate, so its arrival times are pointwise below MELCHIOR-1's: a
monotone speed-up carrying no shape information. `MAGI.md` records the
consequence -- it can never set CONFIRMED, which is "exactly Melchior n Casper"
-- and records that an attempt to give it real dissent (a 20 degree wind veer)
was tried and deleted. This module is the intended replacement. **It is not
wired into `magi.py` yet**: doing so needs a per-cell rate path, because
Rothermel gives a rate per fuel code where `spread.py` takes one global R0.

What this is. The Rothermel (1972) surface fire spread model in Albini's (1976)
reformulation: the equations underneath BehavePlus, FARSITE, FlamMap, ELMFIRE
and GridFire. It is genuinely independent of `spread.py` -- rate comes from fuel
particle physics rather than a fitted R0, so when it agrees with Ignis the
agreement carries information.

The one thing it buys the ensemble that no knob could: **there is no R0 here.**
`palisades.py` measured Ignis's single fitted R0 failing to transfer across a
wind regime -- fitted on a 29 km/h night, it predicted 55 km2 against 87 km2
observed on the 36 km/h night after. Rothermel derives spread rate from fuel
load, surface-area-to-volume ratio, bed depth, moisture and wind, so there is
no per-incident knob left to fail to transfer.

Fuel moisture is a real input here and Ignis has never had one. It is passed in
rather than fetched: the model has to run for the Palisades replay offline, and
the live RAWS path is separate plumbing. See `Moisture`.

Units are Rothermel's throughout -- imperial, because every published
coefficient is. Only `spread_rate_m_per_min` crosses back into metric.

Parameters are the Scott & Burgan 40 fuel models, from Scott & Burgan 2005,
RMRS-GTR-153. That is a US Government publication and the values are public
domain; they were cross-checked against the encoding in the Pyregence
`pyretechnics` project, which is EPL-2.0 and is *not* vendored here.

Validation, in full in FINDINGS.md: every load, SAV, depth and extinction
moisture checked against GTR-153 table 7, and characteristic SAV and packing
ratio against the published per-model pages. Those still hold.

The spread-rate comparison does NOT. It claimed all 40 models agreeing with
the BehavePlus core to a constant 1.029, and that number was measured while
this module omitted mineral damping on the stated grounds that BehavePlus
omits it too -- which the reference source disproves (see
`MINERAL_DAMPING_APPLIED`). The coefficient is applied now, no rate table or
runnable comparison against BehavePlus is checked in here, and the ratio has
been withdrawn rather than adjusted. Do not quote an agreement figure for
this module until one can be re-measured and committed alongside it.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

# Rothermel's fuel particle constants. Not knobs.
RHO_P = 32.0             # oven-dry particle density, lb/ft^3
S_T = 0.0555             # total mineral content, fraction
S_E = 0.01               # effective (silica-free) mineral content, fraction

# Mineral damping, eta_s = 0.174 * S_E^-0.19, capped at 1.0. At S_E = 0.01
# that is 0.4174 -- a factor of 2.4 on reaction intensity, so whether it is
# applied is not a detail.
#
# It IS applied, and it used to not be. The reason given for omitting it was
# that the BehavePlus core did not appear to apply it either. That reason is
# false. The Forest Service implementation computes it in `calculateEtaS()`
#
#     etaS_[i] = 0.174 / pow(weightedSilica[i], 0.19);
#     if (etaS_[i] > 1.0) { etaS_[i] = 1.0; }
#
# and multiplies it into reaction intensity per life state
#
#     reactionIntensityForLifeState_[i] =
#         gamma * weightedFuelLoad[i] * weightedHeat[i] * etaM_[i] * etaS_[i];
#
# -- surfaceFireReactionIntensity.cpp, firelab/behave. It also builds
# `weightedFuelLoad` from NET load, `wnDead[i] = loadDead_[i] * (1.0 -
# totalSilicaContent_)`, in surfaceFuelbedIntermediates.cpp. So the reference
# applies BOTH corrections: the (1 - S_T) net load this module already had,
# and eta_s on top of it. Rothermel (1972) and Albini (1976) say the same.
#
# ponytail: what this does NOT do is explain the TL8 arithmetic that the old
# comment rested on -- that reproducing "its" reaction intensity with eta_s in
# place needs a net load of 0.578 lb/ft^2 against TL8's total of 0.381. Two
# published sources agreeing outrank one internal reconciliation whose
# comparison setup is no longer on disk, which is why the coefficient is in;
# but the reconciliation is unfinished, not resolved. Finishing it means
# checking in a reference rate table and a runnable comparison, and until
# that exists no agreement ratio with BehavePlus should be quoted from this
# module. The old 1.029 figure has been withdrawn from FINDINGS.md for
# exactly that reason.
MINERAL_DAMPING_APPLIED = True
HEAT_CONTENT = 8000.0    # low heat content, Btu/lb
# ...for 39 of the 40 models. GR6 is 9000, alone in the set. Verified against
# Scott & Burgan 2005 RMRS-GTR-153 table 7, which is also where every load,
# SAV, depth and extinction moisture in FUEL_MODELS was checked, value by
# value. An 11th column carrying 8000.0 forty times would hide this.
HEAT_CONTENT_BY_MODEL = {106: 9000.0}


def heat_content(code: int) -> float:
    return HEAT_CONTENT_BY_MODEL.get(code, HEAT_CONTENT)

# Six size classes: four dead, two live, in this fixed order --
#   0 dead 1-hr, 1 dead 10-hr, 2 dead 100-hr, 3 dead herbaceous (cured),
#   4 live herbaceous, 5 live woody
# Class 3 is live herbaceous load transferred across by curing: the dynamic
# fuel model step, which the GR and GS families live or die by.
DEAD = range(0, 4)
LIVE = range(4, 6)
SIGMA_DEAD_10HR = 109.0    # fixed by the fuel model standard
SIGMA_DEAD_100HR = 30.0

KMH_TO_FT_PER_MIN = 54.6806649
FT_TO_M = 0.3048

# code: (delta, M_x_dead, w_1hr, w_10hr, w_100hr, w_herb, w_woody,
#        sigma_1hr, sigma_herb, sigma_woody)
# delta is bed depth (ft), M_x_dead dead moisture of extinction (%),
# w_* oven-dry loads (lb/ft^2), sigma_* surface-area-to-volume ratios (1/ft).
FUEL_MODELS = {
    91: ( 0.00,   0.0, 0.0000, 0.0000, 0.0000, 0.0000, 0.0000,    0.0,    0.0,    0.0),  # NB1
    92: ( 0.00,   0.0, 0.0000, 0.0000, 0.0000, 0.0000, 0.0000,    0.0,    0.0,    0.0),  # NB2
    93: ( 0.00,   0.0, 0.0000, 0.0000, 0.0000, 0.0000, 0.0000,    0.0,    0.0,    0.0),  # NB3
    98: ( 0.00,   0.0, 0.0000, 0.0000, 0.0000, 0.0000, 0.0000,    0.0,    0.0,    0.0),  # NB4
    99: ( 0.00,   0.0, 0.0000, 0.0000, 0.0000, 0.0000, 0.0000,    0.0,    0.0,    0.0),  # NB5
    101: ( 0.40,  15.0, 0.0046, 0.0000, 0.0000, 0.0138, 0.0000, 2200.0, 2000.0,    0.0),  # GR1
    102: ( 1.00,  15.0, 0.0046, 0.0000, 0.0000, 0.0459, 0.0000, 2000.0, 1800.0,    0.0),  # GR2
    103: ( 2.00,  30.0, 0.0046, 0.0184, 0.0000, 0.0689, 0.0000, 1500.0, 1300.0,    0.0),  # GR3
    104: ( 2.00,  15.0, 0.0115, 0.0000, 0.0000, 0.0872, 0.0000, 2000.0, 1800.0,    0.0),  # GR4
    105: ( 1.50,  40.0, 0.0184, 0.0000, 0.0000, 0.1148, 0.0000, 1800.0, 1600.0,    0.0),  # GR5
    106: ( 1.50,  40.0, 0.0046, 0.0000, 0.0000, 0.1561, 0.0000, 2200.0, 2000.0,    0.0),  # GR6
    107: ( 3.00,  15.0, 0.0459, 0.0000, 0.0000, 0.2479, 0.0000, 2000.0, 1800.0,    0.0),  # GR7
    108: ( 4.00,  30.0, 0.0230, 0.0459, 0.0000, 0.3352, 0.0000, 1500.0, 1300.0,    0.0),  # GR8
    109: ( 5.00,  40.0, 0.0459, 0.0459, 0.0000, 0.4132, 0.0000, 1800.0, 1600.0,    0.0),  # GR9
    121: ( 0.90,  15.0, 0.0092, 0.0000, 0.0000, 0.0230, 0.0298, 2000.0, 1800.0, 1800.0),  # GS1
    122: ( 1.50,  15.0, 0.0230, 0.0230, 0.0000, 0.0275, 0.0459, 2000.0, 1800.0, 1800.0),  # GS2
    123: ( 1.80,  40.0, 0.0138, 0.0115, 0.0000, 0.0666, 0.0574, 1800.0, 1600.0, 1600.0),  # GS3
    124: ( 2.10,  40.0, 0.0872, 0.0138, 0.0046, 0.1561, 0.3260, 1800.0, 1600.0, 1600.0),  # GS4
    141: ( 1.00,  15.0, 0.0115, 0.0115, 0.0000, 0.0069, 0.0597, 2000.0, 1800.0, 1600.0),  # SH1
    142: ( 1.00,  15.0, 0.0620, 0.1102, 0.0344, 0.0000, 0.1768, 2000.0,    0.0, 1600.0),  # SH2
    143: ( 2.40,  40.0, 0.0207, 0.1377, 0.0000, 0.0000, 0.2847, 1600.0,    0.0, 1400.0),  # SH3
    144: ( 3.00,  30.0, 0.0390, 0.0528, 0.0092, 0.0000, 0.1171, 2000.0, 1800.0, 1600.0),  # SH4
    145: ( 6.00,  15.0, 0.1653, 0.0964, 0.0000, 0.0000, 0.1331,  750.0,    0.0, 1600.0),  # SH5
    146: ( 2.00,  30.0, 0.1331, 0.0666, 0.0000, 0.0000, 0.0643,  750.0,    0.0, 1600.0),  # SH6
    147: ( 6.00,  15.0, 0.1607, 0.2433, 0.1010, 0.0000, 0.1561,  750.0,    0.0, 1600.0),  # SH7
    148: ( 3.00,  40.0, 0.0941, 0.1561, 0.0390, 0.0000, 0.1997,  750.0,    0.0, 1600.0),  # SH8
    149: ( 4.40,  40.0, 0.2066, 0.1125, 0.0000, 0.0712, 0.3214,  750.0, 1800.0, 1500.0),  # SH9
    161: ( 0.60,  20.0, 0.0092, 0.0413, 0.0689, 0.0092, 0.0413, 2000.0, 1800.0, 1600.0),  # TU1
    162: ( 1.00,  30.0, 0.0436, 0.0826, 0.0574, 0.0000, 0.0092, 2000.0,    0.0, 1600.0),  # TU2
    163: ( 1.30,  30.0, 0.0505, 0.0069, 0.0115, 0.0298, 0.0505, 1800.0, 1600.0, 1400.0),  # TU3
    164: ( 0.50,  12.0, 0.2066, 0.0000, 0.0000, 0.0000, 0.0918, 2300.0,    0.0, 2000.0),  # TU4
    165: ( 1.00,  25.0, 0.1837, 0.1837, 0.1377, 0.0000, 0.1377, 1500.0,    0.0,  750.0),  # TU5
    181: ( 0.20,  30.0, 0.0459, 0.1010, 0.1653, 0.0000, 0.0000, 2000.0,    0.0,    0.0),  # TL1
    182: ( 0.20,  25.0, 0.0643, 0.1056, 0.1010, 0.0000, 0.0000, 2000.0,    0.0,    0.0),  # TL2
    183: ( 0.30,  20.0, 0.0230, 0.1010, 0.1286, 0.0000, 0.0000, 2000.0,    0.0,    0.0),  # TL3
    184: ( 0.40,  25.0, 0.0230, 0.0689, 0.1928, 0.0000, 0.0000, 2000.0,    0.0,    0.0),  # TL4
    185: ( 0.60,  25.0, 0.0528, 0.1148, 0.2020, 0.0000, 0.0000, 2000.0,    0.0, 1600.0),  # TL5
    186: ( 0.30,  25.0, 0.1102, 0.0551, 0.0551, 0.0000, 0.0000, 2000.0,    0.0,    0.0),  # TL6
    187: ( 0.40,  25.0, 0.0138, 0.0643, 0.3719, 0.0000, 0.0000, 2000.0,    0.0,    0.0),  # TL7
    188: ( 0.30,  35.0, 0.2663, 0.0643, 0.0505, 0.0000, 0.0000, 1800.0,    0.0,    0.0),  # TL8
    189: ( 0.60,  35.0, 0.3053, 0.1515, 0.1905, 0.0000, 0.0000, 1800.0,    0.0, 1600.0),  # TL9
    201: ( 1.00,  25.0, 0.0689, 0.1377, 0.5051, 0.0000, 0.0000, 2000.0,    0.0,    0.0),  # SB1
    202: ( 1.00,  25.0, 0.2066, 0.1951, 0.1837, 0.0000, 0.0000, 2000.0,    0.0,    0.0),  # SB2
    203: ( 1.20,  25.0, 0.2525, 0.1263, 0.1377, 0.0000, 0.0000, 2000.0,    0.0,    0.0),  # SB3
    204: ( 2.70,  25.0, 0.2410, 0.1607, 0.2410, 0.0000, 0.0000, 2000.0,    0.0,    0.0),  # SB4
}

# Anything outside the table -- including LANDFIRE's nodata -- does not burn.
NONBURNABLE = frozenset(code for code, row in FUEL_MODELS.items() if row[0] <= 0.0)


@dataclass(frozen=True)
class Moisture:
    """Fuel moisture as a fraction, not a percentage.

    Defaults are Southern California Santa Ana conditions, the regime both
    validation fires ran under. They are deliberately a *stated assumption*
    rather than a silent constant: dead fuel moisture drives spread rate about
    as hard as wind does, and a model that hides it is lying about its inputs.
    Feed real RAWS observations in preference to any of them.
    """
    dead_1hr: float = 0.06
    dead_10hr: float = 0.07
    dead_100hr: float = 0.08
    live_herbaceous: float = 0.60
    live_woody: float = 0.75

    @property
    def curing(self) -> float:
        """Fraction of live herbaceous load transferred to the dead pool.

        Derived from live herbaceous moisture rather than set: fully green at
        120% and above, fully cured at 30% and below, linear between. That is
        the transfer the BehavePlus core uses, and making it a free parameter
        (it was one) let the grass models run up to 60% fast against that
        reference, because 100% cured moves every blade of grass into the dead
        pool at 6% moisture.
        """
        return min(max((1.20 - self.live_herbaceous) / 0.90, 0.0), 1.0)


def _fuel_bed(code: int, moisture: Moisture):
    """Loads, SAVs and moistures per size class, after curing."""
    (delta, m_x_dead, w_1, w_10, w_100, w_herb, w_woody,
     s_1, s_herb, s_woody) = FUEL_MODELS[code]

    # Curing moves part of the live herbaceous load into the dead pool at the
    # live herb SAV. Skip it and every grass model comes out far too slow.
    cured = w_herb * moisture.curing
    w_o = [w_1, w_10, w_100, cured, w_herb - cured, w_woody]
    sigma = [s_1, SIGMA_DEAD_10HR, SIGMA_DEAD_100HR, s_herb, s_herb, s_woody]
    m_f = [moisture.dead_1hr, moisture.dead_10hr, moisture.dead_100hr,
           moisture.dead_1hr, moisture.live_herbaceous, moisture.live_woody]
    return delta, m_x_dead / 100.0, w_o, sigma, m_f


# Albini's size-class boundaries for net fuel loading, in 1/ft. Six bins, and
# the count matters: collapsing 10-hr and 100-hr into one bin makes them share
# a weight, which over-weights coarse fuels. Against the BehavePlus core that
# error ran to +73% on the litter models with the heaviest 100-hr loads (TL4,
# TL7, SB1) while leaving the 1-hr-dominated ones alone. Six bins drops the
# spread of the disagreement from 0.39-0.72 to 0.39-0.49.
SAV_BIN_EDGES = (1200.0, 192.0, 96.0, 48.0, 16.0)


def _sav_bin(sigma: float) -> int:
    """Which size class a surface-area-to-volume ratio falls in."""
    for index, edge in enumerate(SAV_BIN_EDGES):
        if sigma >= edge:
            return index
    return len(SAV_BIN_EDGES) if sigma > 0.0 else len(SAV_BIN_EDGES) + 1


def _weightings(w_o, sigma):
    """Albini's f_ij (within category), f_i (between) and g_ij (net loading).

    f_ij weights by mean total surface area, which is what the reaction
    intensity and the heat sink want. g_ij is a different thing and easy to
    conflate with it: net fuel loading bins classes by SAV and weights by the
    *bin*, so a 10-hour class is not diluted by the 1-hour class beside it.
    Using f_ij for both is the classic way to get a plausible wrong answer.
    """
    a_ij = [s * w / RHO_P for s, w in zip(sigma, w_o)]
    a_dead = sum(a_ij[j] for j in DEAD)
    a_live = sum(a_ij[j] for j in LIVE)

    f_ij = [0.0] * 6
    for j in range(6):
        total = a_dead if j in DEAD else a_live
        f_ij[j] = a_ij[j] / total if total > 0 else 0.0

    a_total = a_dead + a_live
    f_i = (a_dead / a_total, a_live / a_total) if a_total > 0 else (0.0, 0.0)

    g_ij = [0.0] * 6
    for category in (DEAD, LIVE):
        totals: dict[int, float] = {}
        for j in category:
            totals[_sav_bin(sigma[j])] = (totals.get(_sav_bin(sigma[j]), 0.0)
                                          + f_ij[j])
        for j in category:
            g_ij[j] = totals.get(_sav_bin(sigma[j]), 0.0) if w_o[j] > 0 else 0.0
    return f_ij, f_i, g_ij


def _characteristic_sav(f_ij, f_i, sigma) -> float:
    return sum(f_i[c] * sum(f_ij[j] * sigma[j] for j in category)
               for c, category in enumerate((DEAD, LIVE)))


def _live_extinction_moisture(w_o, sigma, m_f, m_x_dead) -> float:
    """Live fuels' M_x is not tabulated -- it rises as the dead fuel dries out.

    Without this every live-bearing model burns at the tabulated dead value and
    the shrub families come out far too flammable.
    """
    fine_dead = sum(w_o[j] * math.exp(-138.0 / sigma[j])
                    for j in DEAD if sigma[j] > 0)
    fine_live = sum(w_o[j] * math.exp(-500.0 / sigma[j])
                    for j in LIVE if sigma[j] > 0)
    if fine_live <= 0 or m_x_dead <= 0:
        return m_x_dead
    dead_moisture = (sum(m_f[j] * w_o[j] * math.exp(-138.0 / sigma[j])
                         for j in DEAD if sigma[j] > 0) / fine_dead
                     if fine_dead > 0 else 0.0)
    m_x_live = (2.9 * (fine_dead / fine_live) * (1.0 - dead_moisture / m_x_dead)
                - 0.226)
    return max(m_x_live, m_x_dead)


def _moisture_damping(m_f: float, m_x: float) -> float:
    """1 at bone dry, 0 at the moisture of extinction."""
    if m_x <= 0:
        return 0.0
    r = min(m_f / m_x, 1.0)
    return max(0.0, 1.0 - 2.59 * r + 5.11 * r * r - 3.52 * r ** 3)


def _packing(w_o, delta, sigma_prime):
    beta = sum(w_o) / RHO_P / delta
    return beta, 3.348 * sigma_prime ** -0.8189


def no_wind_no_slope_rate(code: int, moisture: Moisture = Moisture()) -> float:
    """Rothermel's R0 in ft/min: the fuel bed's own spread rate.

    Confusingly named against `spread.R0_M_PER_MIN`, which is a fitted knob.
    This one is derived, and that is the whole point of the module.
    """
    if code not in FUEL_MODELS or code in NONBURNABLE:
        return 0.0
    delta, m_x_dead, w_o, sigma, m_f = _fuel_bed(code, moisture)
    if delta <= 0 or sum(w_o) <= 0:
        return 0.0

    f_ij, f_i, g_ij = _weightings(w_o, sigma)
    sigma_prime = _characteristic_sav(f_ij, f_i, sigma)
    if sigma_prime <= 0:
        return 0.0
    beta, beta_op = _packing(w_o, delta, sigma_prime)
    m_x_live = _live_extinction_moisture(w_o, sigma, m_f, m_x_dead)

    # Reaction intensity: optimum reaction velocity times the damped net load.
    exponent = 133.0 * sigma_prime ** -0.7913
    gamma_max = sigma_prime ** 1.5 / (495.0 + 0.0594 * sigma_prime ** 1.5)
    ratio = beta / beta_op if beta_op > 0 else 0.0
    gamma = gamma_max * ratio ** exponent * math.exp(exponent * (1.0 - ratio))

    eta_s = mineral_damping()
    reaction = 0.0
    for category, m_x in ((DEAD, m_x_dead), (LIVE, m_x_live)):
        w_n = sum(g_ij[j] * w_o[j] * (1.0 - S_T) for j in category)
        m_f_i = sum(f_ij[j] * m_f[j] for j in category)
        reaction += (w_n * heat_content(code)
                     * _moisture_damping(m_f_i, m_x) * eta_s)
    i_r = gamma * reaction

    # Propagating flux ratio, then the heat sink it has to overcome.
    xi = (math.exp((0.792 + 0.681 * math.sqrt(sigma_prime)) * (beta + 0.1))
          / (192.0 + 0.2595 * sigma_prime))
    rho_b = sum(w_o) / delta
    heat_sink = rho_b * sum(
        f_i[c] * sum(f_ij[j] * math.exp(-138.0 / sigma[j])
                     * (250.0 + 1116.0 * m_f[j])
                     for j in category if sigma[j] > 0)
        for c, category in enumerate((DEAD, LIVE)))
    return i_r * xi / heat_sink if heat_sink > 0 else 0.0


def mineral_damping(s_e: float = S_E) -> float:
    """eta_s. Capped at 1.0 the way the reference caps it: the expression runs
    above 1 for very clean fuel, and a damping coefficient that amplifies is
    not damping."""
    if not MINERAL_DAMPING_APPLIED:
        return 1.0
    return min(0.174 * s_e ** -0.19, 1.0)


def wind_slope_factors(code: int, wind_ft_per_min: float, slope_tan: float,
                       moisture: Moisture = Moisture()) -> tuple[float, float]:
    """(phi_wind, phi_slope), the multipliers on the no-wind no-slope rate."""
    if code not in FUEL_MODELS or code in NONBURNABLE:
        return 0.0, 0.0
    delta, _, w_o, sigma, _ = _fuel_bed(code, moisture)
    if delta <= 0 or sum(w_o) <= 0:
        return 0.0, 0.0

    f_ij, f_i, _ = _weightings(w_o, sigma)
    sigma_prime = _characteristic_sav(f_ij, f_i, sigma)
    if sigma_prime <= 0:
        return 0.0, 0.0
    beta, beta_op = _packing(w_o, delta, sigma_prime)
    if beta <= 0 or beta_op <= 0:
        return 0.0, 0.0

    c = 7.47 * math.exp(-0.133 * sigma_prime ** 0.55)
    b = 0.02526 * sigma_prime ** 0.54
    e = 0.715 * math.exp(-3.59e-4 * sigma_prime)
    phi_wind = (c * wind_ft_per_min ** b * (beta / beta_op) ** -e
                if wind_ft_per_min > 0 else 0.0)
    phi_slope = 5.275 * beta ** -0.3 * slope_tan * slope_tan
    return phi_wind, phi_slope


def spread_rate_m_per_min(code: int, wind_kmh: float, slope_tan: float = 0.0,
                          moisture: Moisture = Moisture(),
                          midflame_factor: float = 0.4) -> float:
    """Head fire spread rate in metres per minute. The only metric-facing call.

    `wind_kmh` is the 10 m open wind every weather feed reports; Rothermel
    wants midflame, so the same 0.4 adjustment `elliptical.py` documents
    applies here too. `slope_tan` is rise over run, not degrees.
    """
    wind_ft_per_min = max(wind_kmh, 0.0) * midflame_factor * KMH_TO_FT_PER_MIN
    phi_wind, phi_slope = wind_slope_factors(code, wind_ft_per_min, slope_tan,
                                             moisture)
    return (no_wind_no_slope_rate(code, moisture)
            * (1.0 + phi_wind + phi_slope) * FT_TO_M)


if __name__ == "__main__":
    families = {101: "GR", 121: "GS", 141: "SH", 161: "TU", 181: "TL", 201: "SB"}
    print(f"{'code':>5} {'calm':>8} {'20 km/h':>8} {'50 km/h':>8}   (m/min)")
    for code in sorted(c for c in FUEL_MODELS if c not in NONBURNABLE):
        label = max((lo for lo in families if lo <= code), default=None)
        name = f"{families[label]}{code - label + 1}" if label else str(code)
        print(f"{name:>5} {spread_rate_m_per_min(code, 0):>8.2f} "
              f"{spread_rate_m_per_min(code, 20):>8.2f} "
              f"{spread_rate_m_per_min(code, 50):>8.2f}")
