"""The pieces of the page that do not depend on a run: sliders, output switches, header, logos, docs."""

import math
from pathlib import Path

from shiny import ui

from .config import SLIDER_GROUPS


MODEL_NAMES = {0: "Cholera", 1: "VECTRI-ABM"}  # By disID
# Tabs for each type of analysis, under the Analysis menu, to be filled
ANALYSIS_TABS = (
    ("Time series", "Time series analysis, such as spectrograms: to come."),
    ("Demography", "Age-related analysis: to come."),
    ("Mobility", "Mobility analysis: to come. Mobility is not yet functional in MoBILE."),
    ("Sensitivity analysis", "Sensitivity analysis of the model parameters with SALib: to come."),
)
ASSETS = Path(__file__).parent / "assets"
LOGO_SUFFIXES = (".png", ".svg", ".jpg", ".jpeg")
FUNDER_PLACEHOLDERS = 3
CODE_DOCS_URL = "https://mgarrizor.github.io/MoBILE/"  # FORD, built from the source code
USER_DOCS_URL = "https://mobile-ictp.readthedocs.io/en/latest/"  # Sphinx, on Read the Docs
GUI_OUTPUT = ("out_EIR", "out_vect")  # What a run writes unless changed in the Outputs tab


# The flags of &OUTPUT: (flag, label, compiled-in default), by the group of the output file they write to
OUTPUT_FLAGS = {
    "Human": [
        ("out_pop", "Population density", True),
        ("out_age", "Age structure (not a map)", True),
        ("out_N", "Agents per cell", True),
        ("out_HA", "Humans per agent", True),
        ("out_S", "Susceptible", False),
        ("out_E", "Exposed", False),
        ("out_I", "Symptomatic", True),
        ("out_I_new", "New symptomatic cases", True),
        ("out_A", "Asymptomatic", False),
        ("out_R", "Recovered", False),
        ("out_EIR", "Entomological inoculation rate", True),
        ("out_P1", "Probability of an infective bite", True),
        ("out_hbr", "Human biting rate", False),
        ("out_imm", "Immunity", True),
    ],
    "Human, by age (one field per age band, large output)": [
        ("out_Ia", "Symptomatic", False),
        ("out_Ia_new", "New symptomatic cases", False),
        ("out_Aa", "Asymptomatic", False),
        ("out_imm_a", "Immunity", False),
        ("out_N_a", "Agents", False),
    ],
    "Vector": [
        ("out_vect", "Vector density", True),
        ("out_vecinfc", "Infective vector density", True),
        ("out_larv", "Larval density", False),
    ],
    "Hydro": [
        ("out_wpond", "Pond fraction", True),
        ("out_wperm", "Permanent water fraction", True),
        ("out_wurbn", "Urban water fraction", False),
    ],
}


def with_tip(label, text):
    """A label followed by an (i) that explains the control on hover or focus."""
    icon = ui.tags.span("ⓘ", class_="text-muted ms-1", tabindex="0", role="img", **{"aria-label": "More information"})
    return ui.TagList(label, ui.tooltip(icon, text, placement="right"))


def quick_start():
    """The steps from a setup to its results, as the tabs are numbered."""
    strong = ui.tags.strong
    return ui.tags.ol(
        ui.tags.li(strong("Setup"), ": choose the model, the days to simulate and the driving files, then press ", strong("Apply setup"), "."),
        ui.tags.li(strong("Parameters"), ": move the sliders to change, and choose the outputs. Sliders you do not move keep their value."),
        ui.tags.li("In the sidebar, set the number of agents and the seed, and press ", strong("Run"),
                   ". The model is compiled, then simulated: the example takes minutes."),
        ui.tags.li(strong("Results"), ": choose a variable and a day, and click a cell on the map for its time series."),
        class_="mb-2",
    )


def no_run_yet():
    """Shown in the Results tab until there are results."""
    strong = ui.tags.strong
    return ui.card(
        ui.card_header("No results yet"),
        ui.p("Press ", strong("Run"), " in the sidebar to simulate with the current setup and parameters, or choose an earlier "
             "run under ", strong("Earlier runs"), " and press ", strong("Load run"), ". The results then show here.", class_="mb-0"),
        class_="border-info mb-3",
    )


def slider_grid(spec):
    """(min, max, step, decimals) of a slider: 3 decimals, more if the range would have under 100 steps."""
    decimals = max(3, math.ceil(-math.log10((spec["max"] - spec["min"]) / 100)))
    step = 10.0**-decimals
    return (
        round(math.floor(spec["min"] / step) * step, decimals),
        round(math.ceil(spec["max"] / step) * step, decimals),
        step,
        decimals,
    )


def _slider(name, spec, value, source="const"):
    low, high, step, _ = slider_grid(spec)
    label = spec.get("label", name) + (" (default)" if source == "default" else "")
    return ui.input_slider(f"param_{name}", label, min=low, max=high, value=value, step=step)


def logo_files(folder, stem=None):
    """Images in a folder by name; with stem, only those with that name."""
    if not folder.is_dir():
        return []
    return sorted(
        path for path in folder.iterdir()
        if path.suffix.lower() in LOGO_SUFFIXES and (stem is None or path.stem.lower() == stem)
    )


def _logo_placeholder(text, **style):
    return ui.div(
        text,
        style="display: flex; align-items: center; justify-content: center; border: 1px dashed var(--bs-border-color); "
        "color: var(--bs-secondary-color); font-size: 0.75rem; text-align: center; width: 140px; height: 56px;",
        class_="logo-placeholder",
        **style,
    )


def _logo(path, folder, height):
    return ui.img(src=f"/assets/{folder}{path.name}", alt=path.stem, class_="logo",
                  style=f"height: {height}px; max-width: 220px; object-fit: contain;")


def page_header(config):
    """The name of the model and the project, which follow the applied setup."""
    disease = config.run["disID"]
    return ui.div(
        ui.div("MoBILE", style="font-size: 1.4rem; font-weight: 600; line-height: 1.2;"),
        ui.div(f"Model: {MODEL_NAMES.get(disease, f'disID {disease}')} · Project: {config.project or 'not set'}",
               style="font-size: 0.95rem; font-weight: 400;"),
    )


# (value, symbol, label); scripts.THEME applies the choice and keeps it in the browser
THEME_CHOICES = (("light", "☀\ufe0e", "Light"), ("system", "◐\ufe0e", "System"), ("dark", "☾\ufe0e", "Dark"))


def theme_switch():
    buttons = [
        ui.tags.button(f"{symbol} {label}", type="button", class_="btn btn-outline-secondary", title=f"{label} colours",
                       **{"data-theme-choice": value, "aria-pressed": "false"})
        for value, symbol, label in THEME_CHOICES
    ]
    return ui.div(*buttons, class_="btn-group btn-group-sm", role="group", **{"aria-label": "Colour theme"})


def page_title(header):
    """The header, then the theme switch and the ICTP logo at the right."""
    ictp = logo_files(ASSETS, "ictp")
    return ui.div(
        header,
        ui.div(
            theme_switch(),
            _logo(ictp[0], "", 56) if ictp else _logo_placeholder("ICTP logo", id="ictp_logo"),
            style="display: flex; align-items: center; gap: 1rem;",
        ),
        style="display: flex; align-items: center; justify-content: space-between; flex-wrap: wrap; gap: 0.5rem; width: 100%;",
    )


def funders():
    logos = logo_files(ASSETS / "funders")
    items = [_logo(path, "funders/", 48) for path in logos] or [
        _logo_placeholder(f"Funder logo {number}") for number in range(1, FUNDER_PLACEHOLDERS + 1)
    ]
    return ui.div(
        ui.div("Funded by", class_="small mb-2"),
        ui.div(*items, style="display: flex; flex-wrap: wrap; gap: 1rem; align-items: center;"),
        id="funders",
        class_="mt-3 pt-3 border-top",
    )


def player_controls(prefix="player"):
    def button(name, symbol, title):
        return ui.tags.button(symbol, id=f"{prefix}_{name}", type="button", title=title, class_="btn btn-sm btn-outline-secondary")

    return ui.div(
        button("first", "⏮\ufe0e", "Back to day 1"),
        button("much_slower", "«", "Much slower"),
        button("slower", "‹", "Slower"),
        button("play", "▶", "Play"),
        button("faster", "›", "Faster"),
        button("much_faster", "»", "Much faster"),
        ui.tags.span(id=f"{prefix}_rate", class_="small ms-2"),
        style="display: flex; align-items: center; gap: 0.25rem;",
    )


def help_tab():
    return ui.div(
        ui.card(ui.card_header("Getting started"), quick_start(),
                ui.p("An earlier run, with its setup and parameters, is reloaded from ", ui.tags.strong("Earlier runs"),
                     " in the sidebar. Hover over ⓘ for an explanation of a setting.", class_="small text-muted mb-0")),
        docs(),
        class_="mt-3",
    )


def docs():
    """The documentation built with the package, readable offline; a placeholder until there is one."""
    code_docs = ui.p("Documentation of the source code: ", ui.a(CODE_DOCS_URL, href=CODE_DOCS_URL, target="_blank"), class_="small")
    online = ui.p("User documentation online: ", ui.a(USER_DOCS_URL, href=USER_DOCS_URL, target="_blank"), class_="small")
    if not (ASSETS / "docs" / "index.html").is_file():
        return ui.div(ui.p("The user documentation is not included in this installation.", class_="text-muted mt-3"), online, code_docs)
    return ui.div(
        ui.p(ui.a("Open in a new window", href="/assets/docs/index.html", target="_blank"), class_="small mt-3 mb-2"),
        ui.tags.iframe(src="/assets/docs/index.html", title="Documentation", style="width: 100%; height: 80vh; border: 1px solid var(--bs-border-color);"),
        online,
        code_docs,
    )


def output_switch_id(flag):
    return f"output_{flag}"


def output_groups(selected):
    """A heading per group of the output file, with a switch per flag."""
    return [
        ui.div(
            ui.h6(group, class_="mt-2"),
            ui.layout_column_wrap(
                *[ui.input_switch(output_switch_id(flag), label, value=flag in selected) for flag, label, _ in flags],
                width="200px", gap="0 1rem",
            ),
        )
        for group, flags in OUTPUT_FLAGS.items()
    ]


PARAMETER_SOURCES = {
    "const": ("#007bc2", "from {const}"),  # The colour of the sliders of the theme
    "default": ("#8a8984", "model default"),
}


def parameter_legend(const):
    """What the two colours of the sliders mean; the labels also say it, so not by colour alone."""
    items = [
        ui.span(ui.span(class_="param-swatch", style=f"background: {colour};"), text.format(const=const), class_="me-3")
        for colour, text in PARAMETER_SOURCES.values()
    ]
    return ui.div(*items, class_="small mb-2")


def slider_groups(sliders, values, sources):
    """A heading per group that has sliders, with the sliders side by side."""
    groups = []
    for group in SLIDER_GROUPS:
        group_sliders = [
            ui.div(_slider(name, spec, values[name], sources[name]), class_=f"param-{sources[name]}")
            for name, spec in sliders.items() if spec["group"] == group
        ]
        if group_sliders:
            groups.append(ui.div(ui.h6(group, class_="mt-2"), ui.layout_column_wrap(*group_sliders, width="240px", gap="0 1.5rem")))
    return groups
