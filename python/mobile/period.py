"""The period to simulate: a first and a last day, within the dates of the driving files.

The model starts at the first day of the driving fields, so a run that starts later is a run on copies of
the time-varying files cut to the period (see region.py).
"""

import datetime

import numpy as np

PERIOD_KEYS = ("start", "end")
# ndays_year in mo_spinup.f90: the spin-up climatology is built from whole years of the simulated days
SPIN_UP_DAYS = 365
SPIN_UP_TOO_SHORT = (f"with spin-up, the model needs at least {SPIN_UP_DAYS} days to build its spin-up climatology: choose a "
                     "period of at least a year, or turn spin-up off.")


def parse_day(value):
    """A date from an ISO string or a date; None if it is neither."""
    if isinstance(value, datetime.datetime):
        return value.date()
    if isinstance(value, datetime.date):
        return value
    try:
        return datetime.date.fromisoformat(str(value))
    except ValueError:
        return None


def period_problems(period):
    """What is wrong with a period, as a list; a period is None (all the driving data) or {start, end}."""
    if period is None:
        return []
    if not isinstance(period, dict) or set(period) != set(PERIOD_KEYS):
        return [f"period: needs {', '.join(PERIOD_KEYS)} and nothing else"]
    start, end = (parse_day(period[key]) for key in PERIOD_KEYS)
    if start is None or end is None:
        return ["period: start and end must be dates, as YYYY-MM-DD"]
    if end < start:
        return ["period: the end must not be before the start"]
    return []


def spin_up_problem(spin_up, days):
    """Why a run of so many days cannot spin up, or None; days 0 or None, the days of the driving data, are not known here."""
    return SPIN_UP_TOO_SHORT if spin_up == 1 and days and days < SPIN_UP_DAYS else None


def period_days(period):
    """Number of days of a period, first and last day included."""
    start, end = (parse_day(period[key]) for key in PERIOD_KEYS)
    return (end - start).days + 1


def length_text(days):
    """The length of a simulation, as the Setup panel prints it."""
    text = f"{days:,} day{'' if days == 1 else 's'}"
    return f"{text} ({days / 365.25:.2f} years)" if days >= 365 else text


def as_days(dates):
    """Dates as an array of datetime64[D]; None if they cannot be read as dates (a calendar without dates
    on the usual calendar, no units)."""
    try:
        values = np.asarray(dates)
        if values.dtype.kind != "M":
            values = np.array([np.datetime64(value.isoformat()) for value in values.ravel()])
        return values.astype("datetime64[D]")
    except (AttributeError, TypeError, ValueError):
        return None


def day_range(days, period):
    """(first, last) index of a period in the dates of a file; ValueError if the file does not cover it."""
    start, end = (np.datetime64(parse_day(period[key])) for key in PERIOD_KEYS)
    if days is None or not len(days):
        raise ValueError("the dates of the driving files cannot be read")
    if start < days[0] or end > days[-1]:
        raise ValueError(f"the period is not within the driving data, {days[0]} to {days[-1]}")
    return int(np.searchsorted(days, start, "left")), int(np.searchsorted(days, end, "right")) - 1
