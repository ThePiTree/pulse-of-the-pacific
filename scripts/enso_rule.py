#!/usr/bin/env python3
"""
enso_rule.py - the ONE place the El Nino / La Nina episode rule is written down.

Everything that labels a season (the JSON the site serves, the CSV archive, the
tests) imports it from here, so the rule cannot drift between files. The same rule
is implemented once more, in JavaScript, in public/assets/app.js (tenths / phaseOf /
classifySeq); tests/test_frontend.mjs checks the two against the same NOAA table.

THE RULE (NOAA Climate Prediction Center, historical episodes)
    A season belongs to an El Nino (La Nina) episode when the index is at or above
    +0.5 C (at or below -0.5 C) for at least 5 consecutive overlapping 3-month
    seasons.

THE DETAIL THAT MATTERS
    NOAA's data files carry two decimals (0.47); NOAA's published tables show one
    (0.5), and the episode colouring in those tables follows the ONE-decimal value.
    So 0.47, 0.50, 0.64, 0.62, 0.47 (SON 1979 - JFM 1980) is a five-season El Nino
    in NOAA's table, although only three of the five two-decimal values reach 0.50.
    Applying the threshold to the raw two-decimal values - which this project did
    until November 2026 - mislabelled about 5 % of all seasons (42 of 921 ONI
    seasons, 48 of 921 Relative ONI seasons) and missed whole episodes that NOAA's
    tables show: the 1969-70 and 1979-80 El Ninos in both indices, among others.

    The tabulated value is the file value rounded to one decimal with an exact half
    rounded UP (toward the warmer value): 0.45 -> 0.5, -0.45 -> -0.4. That is what
    NOAA's tables show in 167 of the 177 exact halves published to date; the other
    ten go the other way for reasons that cannot be recovered from a two-decimal
    file. With this convention the rule below reproduces NOAA's ONI table colouring
    for all 920 seasons published there (1950 - JAS 2026) and NOAA's Relative ONI
    table for 917 of 921 (the exception: FMA-MJJ 1984, see tests/fixtures/README.md).

Standard library only. No I/O.
"""

THRESHOLD_TENTHS = 5     # +/-0.5 C, counted in tenths of a degree
MIN_SEASONS = 5          # consecutive overlapping 3-month seasons


def tenths(v):
    """v as NOAA's tables print it - one decimal, an exact half rounded up - returned
    as a whole number of tenths so that no floating-point comparison is involved.

        0.44 -> 4    0.45 -> 5    0.95 -> 10    -0.45 -> -4    -0.46 -> -5
    """
    return (int(round(v * 100)) + 5) // 10


def one_decimal(v):
    """The tabulated value as a float: one_decimal(0.47) == 0.5."""
    return tenths(v) / 10


def side(v):
    """+1 when the tabulated value meets the El Nino threshold, -1 for La Nina, else 0."""
    t = tenths(v)
    return 1 if t >= THRESHOLD_TENTHS else -1 if t <= -THRESHOLD_TENTHS else 0


def episode_codes(values):
    """One code per season, oldest first: 'E' (El Nino episode), 'L' (La Nina
    episode) or 'N' (neither). A run counts only once it is MIN_SEASONS long, so the
    newest seasons of a developing event stay 'N' until the fifth one arrives - see
    pending_run() for labelling those honestly."""
    sides = [side(v) for v in values]
    n = len(sides)
    out = ["N"] * n
    i = 0
    while i < n:
        if sides[i] == 0:
            i += 1
            continue
        j = i
        while j < n and sides[j] == sides[i]:
            j += 1
        if j - i >= MIN_SEASONS:
            out[i:j] = ["E" if sides[i] > 0 else "L"] * (j - i)
        i = j
    return out


def pending_run(values):
    """(start_index, side) of a run that reaches the END of the record, meets the
    threshold, and is still shorter than MIN_SEASONS - an event that may be forming.
    Returns (None, 0) when there is none (including when the trailing run already
    qualifies as an episode)."""
    n = len(values)
    if not n:
        return None, 0
    s = side(values[-1])
    if s == 0:
        return None, 0
    i = n - 1
    while i >= 0 and side(values[i]) == s:
        i -= 1
    start = i + 1
    return (start, s) if n - start < MIN_SEASONS else (None, 0)
