"""The Setup tab: choosing the driving files and previewing them."""

import calendar
from dataclasses import replace

from shiny import ui

from .checks import driving_days
from .driving import LAT_NAMES, LON_NAMES, POP_NAMES, RAIN_NAMES, TEMP_NAMES, TIME_NAMES
from .grid import pop_coordinates
from .layout import player_controls, with_tip
from .plots import COLOUR_MAPS
from .setup import OPTIONAL_FILES, REGION_MODES, REQUIRED_FILES, region_mode
from .worldpop import COUNTRIES, PRODUCTS, product_countries, year_label


SUFFIX_NAMES = {"netcdf": ("netCDF (.nc)",), "text": ("text (.txt, .csv)",), "data": ("netCDF (.nc)", "tables (.csv, .txt)"), "folder": ()}


FILE_LABELS = {key: label for key, label, _ in (*REQUIRED_FILES, *OPTIONAL_FILES)}
MODEL_CHOICES = {"1": "VECTRI-ABM (malaria)", "0": "Cholera model (to come)"}
MODELS_TO_COME = {0}  # disID listed in the menu, greyed out: not tested yet
AVAILABLE_MODEL = 1
MODEL_TO_COME_NOTE = "Cholera model is not available yet; VECTRI-ABM is selected."


def available_model(config):
    """(config, note): a setup with a model still to come runs VECTRI-ABM instead, with a note saying so.
    Only in the GUI: `mobile run` still runs any model."""
    if config.run["disID"] not in MODELS_TO_COME:
        return config, None
    return replace(config, run={**config.run, "disID": AVAILABLE_MODEL}), MODEL_TO_COME_NOTE


def _model_select(selected):
    """The model menu, with the models still to come shown but not selectable."""
    menu = ui.input_select("setup_disID", "Model", MODEL_CHOICES, selected=selected)
    pending = [menu]
    while pending:
        tag = pending.pop()
        if getattr(tag, "name", None) == "option" and int(tag.attrs["value"]) in MODELS_TO_COME:
            tag.attrs["disabled"] = ""
        pending.extend(getattr(tag, "children", []))
    return menu


def _path_input(id, label, value, kind):
    """A box for a path, typed or chosen with the file browser of the GUI."""
    return ui.div(
        ui.input_text(id, label, value=value, width="100%"),
        ui.input_action_button(f"browse_{id}", "Browse", class_="btn-sm mb-3"),
        **{"data-kind": kind},
    )


def setup_value(config, key):
    value = config.inputs.get(key, "")
    return "" if value == "NONE" else str(value)


def period_values(config):
    """(first, last, start, end), as ISO dates, of the days in the rainfall file of a setup and its period,
    all of them by default; None if the file has no days that can be read."""
    days = driving_days(config.inputs.get("rain_file", ""))
    if days is None or not len(days):
        return None
    first, last = str(days[0]), str(days[-1])
    period = config.period or {"start": first, "end": last}
    return first, last, str(period["start"]), str(period["end"])


def setup_tab(config):
    """Everything a run needs that is not a parameter or an output: how to run, and where the data and
    results are. Applied, and checked, with its button."""
    run = config.run
    first, last, start, end = period_values(config) or (None, None, None, None)
    run_box = ui.card(
        ui.card_header("Run parameters"),
        ui.input_text("setup_project", "Project", value=config.project, width="100%"),
        _model_select(str(run["disID"])),
        ui.div(
            ui.tags.label("Period to simulate (default: all the driving data)", class_="form-label mb-0"),
            ui.input_action_button("setup_period_reset", "Reset", class_="btn-sm btn-outline-primary ms-2",
                                   title="Back to the default: all the days of the rainfall file"),
            class_="d-flex align-items-center mb-1",
        ),
        ui.layout_columns(
            ui.input_date("setup_start", "Start", value=start, min=first, max=last, format="yyyy-mm-dd"),
            ui.input_date("setup_end", "End", value=end, min=first, max=last, format="yyyy-mm-dd"),
            col_widths=(6, 6), fill=False,
        ),
        ui.output_ui("period_summary"),
        ui.input_switch("setup_spin_up", with_tip("Spin-up to equilibrium", "Let the model settle to equilibrium before the simulated period starts."), value=run["spin_up"] == 1),
        ui.input_numeric("setup_threads", with_tip("Threads", "CPU threads used by the model. Results depend on the number: keep it fixed to compare runs."), value=run["threads"], min=1, step=1),
        _path_input("setup_runs_dir", "Results folder", str(config.runs_dir), "folder"),
        ui.p("The number of agents and the seed are set in the sidebar, as they often change between runs.", class_="small text-muted"),
    )
    files_box = ui.card(
        ui.card_header("Driving files"),
        ui.output_ui("example_note"),
        *[_path_input(f"setup_{key}", label, setup_value(config, key), kind) for key, label, kind in REQUIRED_FILES],
        _age_inputs(config),
        ui.accordion(
            ui.accordion_panel(
                ui.TagList("Optional files ", ui.tags.span("(Beta release - do not use)", class_="text-danger ms-1")),
                *[_path_input(f"setup_{key}", label, setup_value(config, key), kind) for key, label, kind in OPTIONAL_FILES],
                ui.input_switch("setup_counterfactual", "Counterfactual demography", value=config.inputs.get("counterfactual") == 1),
                value="optional_files",
            ),
            open=False,
        ),
    )
    return ui.div(
        ui.p("Choose the model, the period to simulate, the driving data and, if not the whole grid, the region to simulate, then press ",
             ui.tags.strong("Apply setup"), ". Next, set the parameters in the Parameters & SA tab and press Run in the sidebar.",
             class_="text-muted"),
        driving_files_help(),
        ui.layout_columns(run_box, files_box, col_widths=(5, 7)),
        ui.div(
            ui.input_action_button("apply_setup", "Apply setup", class_="btn-primary btn-lg"),
            ui.output_ui("setup_status"),
            class_="apply-bar",
        ),
        _region_card(config),
        _preview_box(),
        _age_card(),
        class_="mt-3",
    )


AUTO = "auto"  # The menu entry for the product, or the year, chosen from the start of the period
AUTO_YEAR = AUTO
AUTO_PRODUCT_LABEL = "From the start of the period"  # 2000–2020 before 2015, R2025A from 2015: the status line names it


def age_values(config):
    """(product, country, year) entries of the age structure menus for a setup."""
    choice = config.age_structure or {"country": "SEN"}
    product, year = choice.get("product"), choice.get("year")
    return product or AUTO, choice["country"], AUTO if year is None else str(year)


def product_choices():
    return {AUTO: AUTO_PRODUCT_LABEL, **{key: spec["label"] for key, spec in PRODUCTS.items()}}


def country_choices(product):
    """{ISO3: name} by name: of the product, or of all products when it is chosen from the period."""
    countries = product_countries(product) if product in PRODUCTS else COUNTRIES
    return dict(sorted(countries.items(), key=lambda item: item[1]))


def year_choices(product):
    """The year menu: the default, then the estimates and the projections of the product in groups of their own. With
    the product chosen from the period, the year is too."""
    if product not in PRODUCTS:
        return {AUTO: "Closest to the start of the period"}
    first, last = PRODUCTS[product]["years"]
    projected_from = PRODUCTS[product].get("projected_from", last + 1)
    estimates = {str(year): str(year) for year in range(first, min(projected_from, last + 1))}
    projections = {str(year): year_label(year, product) for year in range(max(projected_from, first), last + 1)}
    if not projections:
        return {AUTO_YEAR: "Closest to the start of the period", **estimates}
    return {AUTO_YEAR: "Closest to the start of the period", "Estimates": estimates, "Projections": projections}


def _age_inputs(config):
    """The age structure of the agents: a WorldPop product, a country and a year, instead of a file."""
    product, country, year = age_values(config)
    return ui.div(
        ui.tags.label("Age structure (WorldPop)", class_="form-label fw-semibold mb-1"),
        ui.input_select("setup_age_product", "Product", product_choices(), selected=product, width="100%"),
        ui.p("⚠ The model does not use the sex structure yet: the female and male shares are averaged into one age structure.",
             class_="small mb-1", style=AMBER_TEXT),
        ui.output_ui("age_source"),
        ui.layout_columns(
            ui.input_select("setup_age_country", "Country", country_choices(product), selected=country, width="100%"),
            ui.input_select("setup_age_year", "Year", year_choices(product), selected=year, width="100%"),
            col_widths=(7, 5), fill=False,
        ),
        ui.output_ui("age_status"),
        class_="border-top pt-2 mb-3",
    )


AGE_FIGURES = {"age_fit": "Age structure and fitted mortality", "age_cumulative": "Cumulative weights",
               "age_sexes": "Sex structure", "age_heterogeneity": "Spatial heterogeneity"}


def age_method():
    """How the age structure is made from WorldPop, for the curious, as in utils/fetch_age.sh."""
    item = ui.tags.li
    return ui.accordion(
        ui.accordion_panel(
            "How the age structure is computed",
            ui.tags.ol(
                item("WorldPop gives, for each 1 km cell of the country, the number of people of each sex in 18 age groups: under 1, "
                     "1 to 4, then groups of 5 years up to 75 to 79, and 80 and over. The 36 rasters are downloaded once."),
                item("In each cell, the share of each age group in the people of that sex is computed. The histograms of these "
                     "shares over the cells (Spatial heterogeneity) show how far the age structure varies across the country: "
                     "the model takes the same structure in every cell."),
                item("The shares are averaged over the cells, each cell counting the same, and then over the two sexes, with "
                     "equal weight (Sex structure): the model does not use the sex structure yet. The products differ in the "
                     "cells they have people in: R2025A (constrained) only in the cells with buildings, the 2000–2020 "
                     "product (unconstrained) in every land cell, many with few people."),
                item("The cumulative sum of the mean shares, each age group at its last year of age (0, 4, 9, ..., 79), is "
                     "interpolated to every year of age from 0 to 79 with a monotone cubic (PCHIP), so that the weight of a "
                     "year of age never rises with age. The 80 and over group is left out, so the weights end just below 1. "
                     "These 80 weights are the age file the model reads (Cumulative weights)."),
                item("The weight of each year of age, the difference of consecutive cumulative weights, is fitted by "
                     "A·exp(−γ·age) (least squares). With births equal to deaths, as by default in the model, a population "
                     "with mortality γ has this age structure: γ is the fitted mortality, which can be used for the "
                     "mortality mu in the Parameters & SA tab."),
            ),
            ui.p("The same steps as utils/fetch_age.sh in the MoBILE repository, which does this for a run outside the GUI.",
                 class_="small text-muted mb-0"),
        ),
        open=False,
        class_="mt-2",
    )


def _age_card():
    """The age structure of the applied setup, from WorldPop, as the model gets it."""
    return ui.card(
        ui.card_header("Age structure"),
        ui.output_ui("age_card_summary"),
        ui.input_radio_buttons("age_figure", None, AGE_FIGURES, inline=True),
        ui.panel_conditional("input.age_figure !== 'age_heterogeneity'", ui.div(id="age_plot", style="height: 520px;")),
        ui.panel_conditional("input.age_figure === 'age_heterogeneity'", ui.div(id="age_heterogeneity_plot", style="height: 900px;")),
        age_method(),
        class_="mt-3",
    )


AMBER_TEXT = "color: #d97706;"  # As the markers of moved sliders and the note on the sex structure


def _names(names):
    """e.g. `rain`, `rainfall` as code."""
    return ui.TagList(*[ui.TagList(", " if i else "", ui.tags.code(name)) for i, name in enumerate(names)])


# (file, variable names, units, time axis, putting it on the model grid with CDO): as the table of the README of MoBILE
DRIVING_TABLE = (
    ("Rainfall", RAIN_NAMES, ("mm/day",), ("daily; ", ui.tags.code(TIME_NAMES[0]), " or ", ui.tags.code(TIME_NAMES[1])),
     ("conservative, the mean over the part covered: ", ui.tags.code("CDO_REMAP_NORM=fracarea cdo remapcon"))),
    ("Temperature", TEMP_NAMES, ("°C (ERA5 is in K: ", ui.tags.code("cdo subc,273.15"), ")"), ("daily mean, the same days as rainfall",),
     ("as rainfall (", ui.tags.code("remapcon"), " with ", ui.tags.code("fracarea"), "); none if the model grid is the temperature grid")),
    ("Population density", POP_NAMES, ("persons/m² (WorldPop density is per km²: ", ui.tags.code("cdo mulc,1e-6"), ")"), ("none (static)",),
     ("conservative, keeping the people: ", ui.tags.code("CDO_REMAP_NORM=destarea cdo remapcon"))),
)


def driving_files_help():
    """What the driving files must be, folded: the table of the README of MoBILE for the files of the GUI, why, and what
    the GUI does itself."""
    header = ui.tags.thead(ui.tags.tr(*[ui.tags.th(text) for text in (
        "File", "Variable names accepted", "Units", "Time axis", "Putting it on the model grid with CDO")]))
    rows = ui.tags.tbody(*[
        ui.tags.tr(ui.tags.td(ui.tags.strong(name)), ui.tags.td(_names(names)), ui.tags.td(*units), ui.tags.td(*time), ui.tags.td(*cdo))
        for name, names, units, time, cdo in DRIVING_TABLE
    ])
    item = ui.tags.li
    why = ui.accordion(
        ui.accordion_panel(
            "Why these choices",
            ui.tags.ul(
                item(ui.tags.strong("Why remapcon, not bilinear. "), "Population must add up, so the regridding must keep its total; "
                     "rainfall and temperature are averages, so each model cell must get the mean of what falls in it. Conservative "
                     "remapping does both, giving each model cell the area-weighted mean of the source cells it overlaps. Bilinear "
                     "interpolation, a common default, does neither in general."),
                item(ui.tags.strong("fracarea or destarea. "), "They differ only where a model cell is partly covered by the source, "
                     "typically on the coast, where the source has no values over the sea. A model cell gets (sum of source value × "
                     "overlap area) / A: with ", ui.tags.code("fracarea"), " A is the covered area, with ", ui.tags.code("destarea"),
                     " the whole cell. For a coastal cell half land: rain of 10 mm/day on the land half gives 10 mm/day with fracarea, "
                     "5 with destarea; the sea half is unmeasured, not dry, so use fracarea. 1,000 people on the land half give twice "
                     "the density with fracarea, and the model, which makes people from density × cell area, would put 2,000 in the "
                     "cell; the sea really is empty, so use destarea, which keeps the total of the source."),
                item(ui.tags.strong("Count products. "), "A population count (persons per pixel, as WorldPop's count products) must "
                     "first be divided by the area of the pixel: ", ui.tags.code("cdo div pop.nc -gridarea pop.nc"), ". WorldPop's "
                     "density products (persons per km²) only need ", ui.tags.code("cdo mulc,1e-6"), "."),
            ),
        ),
        open=False,
        class_="mt-2",
    )
    return ui.accordion(
        ui.accordion_panel(
            "What the driving files must be",
            ui.p("Three netCDF files on one grid, the model grid. ", ui.tags.strong("The model applies no unit conversion"),
                 ": the units below are requirements. Cells with no data in the population, rainfall or temperature are not simulated.",
                 class_="small mb-2"),
            ui.div(ui.tags.table(header, rows, class_="table table-sm small align-top mb-2 driving-table"), class_="table-responsive"),
            ui.p("Coordinates: latitude ", _names(LAT_NAMES), ", longitude ", _names(LON_NAMES), ". The grid of the population file is "
                 "the model grid: rainfall and temperature must be on it.", class_="small mb-2"),
            ui.p("Not needed in the GUI: a parameter file (the parameters are in the Parameters & SA tab), a cell area file (the "
                 "model computes the areas from the grid of the population file) or an age file (the age structure comes from "
                 "WorldPop, in the Age structure menus of Driving files).", class_="small mb-2"),
            ui.p("⚠ A region chosen in the GUI keeps the size of its cells by itself. Only a file you make with a single latitude or "
                 "longitude needs the cell bounds of its coordinates (a CF bounds attribute, e.g. ", ui.tags.code("lat_bnds"), ", ",
                 ui.tags.code("lon_bnds"), "): one centre gives no cell size.", class_="small mb-2", style=AMBER_TEXT),
            ui.p("Apply setup compares the files (grid, days) and checks the units of rainfall and temperature, and warns before "
                 "applying a setup whose files may not work together.", class_="small mb-0"),
            why,
        ),
        open=False,
        class_="mb-3",
    )


def region_values(config):
    """(mode, {box: value}) of the region boxes for a setup. Without a region, the boxes hold the
    edges and the middle of the grid, as a start."""
    region = config.region
    values = {}
    try:
        lon, lat = (sorted(axis) for axis in pop_coordinates(config.inputs["pop_file"]))
        values = {"north": lat[-1], "west": lon[0], "south": lat[0], "east": lon[-1],
                  "point_lat": lat[len(lat) // 2], "point_lon": lon[len(lon) // 2]}
    except (OSError, ValueError, KeyError, StopIteration, RuntimeError):
        pass
    if region is not None and region_mode(region) == "box":
        values.update(region)
    elif region is not None:
        values.update(point_lat=region["north"], point_lon=region["west"])
    return region_mode(region), {key: round(float(value), 3) for key, value in values.items()}


REGION_LAYERS = {"pop_file": "Population density", "rain_file": "Rainfall", "temp_file": "Temperature"}
SEASONS = {"DJF": (12, 1, 2), "MAM": (3, 4, 5), "JJA": (6, 7, 8), "SON": (9, 10, 11)}
# What the mean of the region map is over: {choice: (name, calendar months or None for all of them)}
REGION_MONTHS = {
    "all": ("all year", None),
    **{season: (f"{season} ({calendar.month_name[months[0]]} to {calendar.month_name[months[-1]]})", months)
       for season, months in SEASONS.items()},
    **{str(month): (calendar.month_name[month], (month,)) for month in range(1, 13)},
}
REGION_MONTH_MENU = {
    "all": "All year",
    "Seasons": {season: REGION_MONTHS[season][0] for season in SEASONS},
    "Months": {str(month): calendar.month_name[month] for month in range(1, 13)},
}


REGION_BOXES = (("north", "North [°N]"), ("west", "West [°E]"), ("east", "East [°E]"), ("south", "South [°N]"))


REGION_HINTS = {
    "all": "The whole grid is simulated. To simulate part of it, choose Subregion or Single point.",
    "box": "Type the edges, or drag a rectangle on the map. A new rectangle replaces the one before.",
    "point": "Type the coordinates, or click a cell on the map.",
}


def _region_card(config):
    """The region to simulate, with a map of its own: the whole grid, a box as in the Copernicus data store,
    or a point. The map shows the population, or the mean rainfall or temperature, and is used for the region only."""
    mode, values = region_values(config)
    boxes = [
        ui.div(ui.input_numeric(f"setup_{key}", label, value=values.get(key), step=0.05), class_=f"region-{key}")
        for key, label in REGION_BOXES
    ]
    hints = [
        ui.panel_conditional(f"input.setup_region === '{key}'", ui.p(text, class_="small text-muted mb-2"))
        for key, text in REGION_HINTS.items()
    ]
    return ui.card(
        ui.card_header("Region to simulate (optional)"),
        ui.p("The model runs on the whole grid of the driving files, or on part of it. A run on part of the grid uses "
             "copies of the driving files cut to it; the files themselves are not changed.", class_="small text-muted mb-2"),
        ui.layout_columns(
            ui.div(
                ui.input_radio_buttons("setup_region", None, REGION_MODES, selected=mode),
                *hints,
                ui.panel_conditional("input.setup_region === 'box'", ui.div(*boxes, class_="region-grid")),
                ui.panel_conditional(
                    "input.setup_region === 'point'",
                    ui.input_numeric("setup_point_lat", "Latitude [°N]", value=values.get("point_lat"), step=0.05),
                    ui.input_numeric("setup_point_lon", "Longitude [°E]", value=values.get("point_lon"), step=0.05),
                ),
                ui.output_ui("region_summary"),
            ),
            ui.div(
                ui.div(
                    ui.input_radio_buttons(
                        "region_layer",
                        with_tip("Map", "Rainfall and temperature are their mean over the period in Run parameters, from the "
                                        "files in Driving files: to help choose the region."),
                        REGION_LAYERS, inline=True,
                    ),
                    ui.panel_conditional("input.region_layer !== 'pop_file'",
                                         ui.input_select("region_month", "Mean over", REGION_MONTH_MENU, width="15rem")),
                    class_="d-flex flex-wrap align-items-end gap-4",
                ),
                ui.div(id="region_map", style="height: 480px;"),
            ),
            col_widths=(4, 8),
        ),
        class_="mt-3",
    )


PREVIEW_FILES = {"rain_file": "Rainfall", "temp_file": "Temperature", "pop_file": "Population density"}
DAILY_FILES = ("rain_file", "temp_file")
# Colour map and scale each map starts with
PREVIEW_STYLE = {"rain_file": ("Blues", "linear"), "temp_file": ("Coolwarm", "linear"), "pop_file": ("Reds", "log")}


def _preview_box():
    """A look at the driving files in the boxes above, before they are applied."""
    daily = " || ".join(f"input.preview_file === '{key}'" for key in DAILY_FILES)
    maps = " || ".join(f"input.preview_file === '{key}'" for key in PREVIEW_STYLE)
    return ui.card(
        ui.card_header("Preview driving files"),
        ui.p(
            "The files in the boxes above, as they are now, also before Apply. Each map is drawn on the grid of its "
            "file: a file whose grid differs from that of the population shows so.",
            class_="small text-muted mb-1",
        ),
        ui.layout_columns(
            ui.input_select("preview_file", "File", PREVIEW_FILES),
            ui.panel_conditional(
                daily,
                ui.input_slider("preview_day", ui.TagList("Day ", ui.tags.span(id="preview_day_date", class_="ms-1")), min=1, max=2, value=1, step=1, width="100%"),
                player_controls("preview_player"),
            ),
            col_widths=(3, 9),
        ),
        ui.panel_conditional(
            maps,
            ui.layout_columns(
                ui.input_select("preview_colour_map", "Colour map", list(COLOUR_MAPS), selected=PREVIEW_STYLE["rain_file"][0]),
                ui.input_radio_buttons("preview_scale", "Scale", {"linear": "Linear", "log": "Log"}, inline=True),
                ui.input_numeric("preview_vmin", "Minimum", value=None, step="any"),
                ui.input_numeric("preview_vmax", "Maximum", value=None, step="any"),
                ui.div(ui.input_action_button("preview_auto_range", "Automatic range", class_="btn-sm"), class_="pt-4"),
                col_widths=(2, 2, 2, 2, 3),
            ),
        ),
        ui.panel_conditional(
            maps,
            ui.div(
                ui.div(ui.tags.strong("Dots on the map"), ui.input_action_button("preview_add", "Add dot", class_="btn-sm btn-outline-primary ms-3"),
                       class_="d-flex align-items-center mb-2"),
                ui.output_ui("preview_dots"),
                class_="dots",
            ),
        ),
        ui.div(id="preview_map", style="height: 600px;"),
        ui.panel_conditional(daily, ui.div(id="preview_cell_plot", style="height: 300px;")),
        class_="mt-3",
    )


EXAMPLE_FOLDER = ("utils", "test_run")  # In the MoBILE repository


def example_note_box():
    """Said while the boxes hold the example files bundled with MoBILE."""
    return ui.div(
        ui.tags.strong("Example data for Senegal. "),
        "These files come with MoBILE, in utils/test_run of its GitHub repository: Senegal from 2012 to 2014 on a "
        "0.05° grid, with rainfall from CHIRPS, temperature from CHIRTS and population from WorldPop (2020). Its age "
        "structure is that of Senegal from WorldPop. "
        "Choose your own files for another region or period.",
        class_="alert alert-info small py-2 mb-3",
    )


def setup_problems(error):
    """The problems of a setup, from a ConfigError, with the labels of the Setup panel."""
    lines = []
    for line in str(error).splitlines():
        for key, label in FILE_LABELS.items():
            line = line.replace(f"inputs: {key} ", f"{label}: ")
        lines.append(line.replace("inputs: ", "").replace("run: ", ""))
    return lines
