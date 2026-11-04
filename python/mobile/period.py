"""The period to simulate: a first and a last day, within the dates of the driving files.

The model starts at the first day of the driving fields, so a run that starts later is a run on copies of
the time-varying files cut to the period (see region.py).
"""

import datetime

import numpy as np

PERIOD_KEYS = ("start", "end")


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
