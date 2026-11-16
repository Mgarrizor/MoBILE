"""Population growth for the growth mode of the model (mobile.sh -G, `demog_growth`): the annual growth factor g, typed
or fitted to a population series (e.g. the N column of case data), the growth over the period simulated, and the
headroom the agent slots need for it (`growth_ratio_ceiling`). The model holds the age structure while the population
grows by g a year, from the end of the spin-up (which does not grow)."""

import numpy as np
import pandas as pd

POPULATION_NAMES = ("n", "pop", "population", "people", "persons", "inhabitants")  # Column names taken as population
DATE_NAMES = ("date", "time", "day", "month")
GROWTH_RANGE = (0.9, 1.1)  # Annual factors accepted: -10% to +10% a year
# growth_ratio_ceiling at least this times the growth over the period: the spare slots are placed per cell at the start
# and never move, so a cell can run out before the total does. Senegal (LaCie, AGEING): 1.7% of the births unclaimed in
# the last year at 1.4 for x1.31 (1.07 times); a 24-year test run (16 Nov): none at 2.0 for x1.65 (1.21 times).
HEADROOM = 1.15
SEPARATORS = (",", "\t", ";", r"\s+")


class GrowthError(ValueError):
    """The population series cannot give a growth: says why."""


def _dates(column):
    return pd.to_datetime(column, errors="coerce", format="mixed")


def read_population(path):
    """The population by date, from a text table (comma, tab, semicolon or spaces between columns) with a date column
    and a population column named e.g. N or population, as a Series sorted by date; a date given more than once keeps
    its first value. Raises GrowthError saying what is missing."""
    tables = []
    for separator in SEPARATORS:
        try:
            table = pd.read_csv(path, sep=separator, engine="python")
        except (OSError, UnicodeDecodeError) as error:
            raise GrowthError(f"cannot read {path}: {error}") from None
        except (ValueError, pd.errors.ParserError):
            continue
        if table.shape[1] >= 2:
            tables.append(table)
    for table in tables:
        names = {str(column).strip().strip("\"'").lower(): column for column in table.columns}
        population = next((names[name] for name in POPULATION_NAMES if name in names), None)
        date = next((names[name] for name in DATE_NAMES if name in names), None)
        if date is None:  # The first column that reads as dates
            date = next((column for column in table.columns if column != population and not pd.api.types.is_numeric_dtype(table[column])
                         and _dates(table[column]).notna().mean() > 0.9), None)
        if population is None or date is None:
            continue
        days = _dates(table[date])
        values = pd.to_numeric(table[population], errors="coerce")
        keep = days.notna() & values.notna() & (values > 0)
        if keep.sum() < 2:
            raise GrowthError(f"{path}: fewer than two dates with a population above 0")
        series = pd.Series(values[keep].to_numpy(), index=pd.DatetimeIndex(days[keep]))
        return series[~series.index.duplicated(keep="first")].sort_index()
    columns = ", ".join(str(column) for column in (tables[0].columns if tables else []))
    raise GrowthError(f"{path}: needs a date column and a population column named one of {', '.join(POPULATION_NAMES)} "
                      f"(case does not matter){f'; it has {columns}' if columns else ''}")


def fit_growth(series, first, last):
    """{g, first, last, start, end, departure, covers} of a population series within the period [first, last]: the
    annual growth factor of a straight line through the log of the population (least squares), the dates and values
    it was fitted from, the largest departure of the values from the line (a share), and whether the series covers the
    period (to a month at each end). Raises GrowthError if less than a year of it lies within the period."""
    first, last = pd.Timestamp(first), pd.Timestamp(last)
    inside = series[(series.index >= first) & (series.index <= last)]
    if len(inside) < 2 or (inside.index[-1] - inside.index[0]).days < 365:
        raise GrowthError(f"the population series has less than a year within the period {first.date()} to {last.date()}")
    years = (inside.index - inside.index[0]).days.to_numpy() / 365.25
    slope, intercept = np.polyfit(years, np.log(inside.to_numpy(dtype=float)), 1)
    line = np.exp(intercept + slope * years)
    month = pd.Timedelta(days=31)
    return {"g": float(np.exp(slope)), "first": inside.index[0], "last": inside.index[-1], "start": float(inside.iloc[0]),
            "end": float(inside.iloc[-1]), "departure": float(np.max(np.abs(inside.to_numpy() / line - 1))),
            "covers": inside.index[0] <= first + month and inside.index[-1] >= last - month}


def growth_over(g, first, last):
    """The factor by which the population grows over a period [first, last] at g a year."""
    return float(g ** (((pd.Timestamp(last) - pd.Timestamp(first)).days + 1) / 365.25))


def ceiling_needed(g, first, last):
    """The least growth_ratio_ceiling for g over a period: the growth over it with HEADROOM, rounded up to 0.1; 1 for
    no growth or a decline (no spare slots needed)."""
    over = growth_over(g, first, last)
    return 1.0 if over <= 1 else float(np.ceil(over * HEADROOM * 10 - 1e-9) / 10)


def percent(g):
    """e.g. '2.13% a year' for g = 1.0213."""
    return f"{100 * (g - 1):.2f}% a year"
