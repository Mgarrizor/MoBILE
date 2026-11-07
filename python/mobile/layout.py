"""The pieces of the page that do not depend on a run: sliders, output switches, header, logos, docs."""

import html
import math
import re
from pathlib import Path

import yaml
from shiny import ui

from .parameters import PARAMETER_GROUPS


MODEL_NAMES = {0: "Cholera", 1: "VECTRI-ABM"}  # By disID
# Tabs for each type of analysis, under the Analysis menu, to be filled
ANALYSIS_TABS = (
    ("Time series", "Time series analysis, such as spectrograms: to come."),
    ("Demography", "Age-related analysis: to come."),
    ("Mobility", "Mobility analysis: to come. Mobility is not yet functional in MoBILE."),
)
ASSETS = Path(__file__).parent / "assets"
LOGO_SUFFIXES = (".png", ".svg", ".jpg", ".jpeg")
FUNDER_PLACEHOLDERS = 3
CODE_DOCS_URL = "https://mgarrizor.github.io/MoBILE/"  # FORD, built from the source code
USER_DOCS_URL = "https://mobile-ictp.readthedocs.io/en/latest/"  # Sphinx, on Read the Docs
SALIB_URL = "https://salib.readthedocs.io/"
VECTRI_DOCS_URL = "https://users.ictp.it/~tompkins/vectri/documentation/"  # The VECTRI model, which VECTRI-ABM builds on
OPTUNA_URL = "https://optuna.org/"
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


# More agents than people: the model stops at once ("More agents than people! --> STOP")
HA_BELOW_ONE = "HA is below 1: more agents than people, and the model stops at once. Use HA = 1 or more."

def with_tip(label, text):
    """A label followed by an (i) that explains the control on hover or focus."""
    icon = ui.tags.span("ⓘ", class_="text-muted ms-1", tabindex="0", role="img", **{"aria-label": "More information"})
    return ui.TagList(label, ui.tooltip(icon, text, placement="right"))


def quick_start():
    """The steps from a setup to its results, as the tabs are numbered."""
    strong = ui.tags.strong
    return ui.tags.ol(
        ui.tags.li(strong("Setup"), ": choose the model, the period to simulate and the driving files, then press ", strong("Apply setup"), "."),
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
        class_="border-info mb-3 no-run-yet",
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


def parameter_label(text, spec):
    """The label of a slider, which explains its parameter on hover or focus, from `info` and `source` in parameters.yaml."""
    if "info" not in spec:
        return text
    source = ui.div(f"Source: {spec['source']}", class_="param-source") if "source" in spec else None
    explanation = ui.div(ui.tags.strong(spec.get("label", "")), ui.div(spec["info"]), source, class_="param-info")
    trigger = ui.span(text, ui.span("ⓘ", class_="text-muted ms-1", **{"aria-hidden": "true"}), tabindex="0", class_="param-label")
    return ui.tooltip(trigger, explanation, placement="right")


UNIT_LABELS = {"per_year": " [per year]", "log10": " [log10]"}


def _slider(name, spec, value):
    low, high, step, decimals = slider_grid(spec)
    label = parameter_label(spec.get("label", name) + UNIT_LABELS.get(spec.get("display"), ""), spec)
    # The browser marks the slider, its section and its tab when the value leaves its start
    return ui.div(ui.input_slider(f"param_{name}", label, min=low, max=high, value=value, step=step),
                  class_="param-slider", data_start=f"{round(value, decimals)}", data_step=f"{step}")


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
        "color: var(--bs-secondary-color); font-size: 0.75rem; text-align: center; width: 100px; height: 40px;",
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
        ui.span("MoBILE", style="font-size: 1.4rem; font-weight: 600;"),
        ui.span(f"Model: {MODEL_NAMES.get(disease, f'disID {disease}')} · Project: {config.project or 'not set'}",
                style="font-size: 0.95rem; font-weight: 400; opacity: 0.8;"),
        style="display: flex; align-items: baseline; flex-wrap: wrap; column-gap: 1rem; line-height: 1.2;",
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
            _logo(ictp[0], "", 40) if ictp else _logo_placeholder("ICTP logo", id="ictp_logo"),
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


def publications(entries=None):
    """The publications of publications.yaml, or those given: the pinned ones first, in their order, then the others by
    year, oldest first."""
    if entries is None:
        entries = yaml.safe_load((Path(__file__).parent / "publications.yaml").read_text())["publications"]
    return sorted(entries, key=lambda entry: (entry.get("pinned") is None, entry.get("pinned") or 0, entry["year"]))


def _italics(text):
    """Text with *words* in italics, such as the name of a species."""
    return ui.HTML(re.sub(r"\*(.+?)\*", r"<em>\1</em>", html.escape(text)))


def publications_card():
    rows = []
    for entry in publications():
        link = f"https://doi.org/{entry['doi']}"
        rows.append(ui.tags.tr(
            ui.tags.td(str(entry["year"]) + (" 📌" if entry.get("pinned") else ""), class_="text-nowrap"),
            ui.tags.td(entry["authors"].rstrip("."), ". ", ui.tags.em(entry["title"]), ". ", entry["venue"], ". ",
                       ui.a(f"doi:{entry['doi']}", href=link, target="_blank")),
            ui.tags.td(entry["region"]),
            ui.tags.td(entry["domain"]),
            ui.tags.td(entry["side"]),
            ui.tags.td(_italics(entry["introduced"])),
        ))
    head = ui.tags.thead(ui.tags.tr(*[ui.tags.th(name) for name in ("Year", "Publication", "Region", "Domain", "Side", "What it introduced or studied")]))
    return ui.card(
        ui.card_header("Publications"),
        ui.p("On VECTRI and VECTRI-ABM. 📌 The two models; the others by year. Region: where the model was evaluated or "
             "applied. Domain: on a grid of cells (Spatial) or at one site (Point). Side: where the model was developed, on the vector, the human or both, or Application for a study "
             "that uses it.", class_="small text-muted mb-2"),
        ui.tags.table(head, ui.tags.tbody(*rows), class_="table table-sm small mb-0"),
    )


def help_tab():
    return ui.div(
        ui.card(ui.card_header("Getting started"), quick_start(),
                ui.p("An earlier run, with its setup and parameters, is reloaded from ", ui.tags.strong("Earlier runs"),
                     " in the sidebar. Hover over ⓘ for an explanation of a setting.", class_="small text-muted mb-0")),
        docs(),
        publications_card(),
        class_="mt-3",
    )


def docs():
    """The documentation built with the package, readable offline; a placeholder until there is one."""
    vectri = ui.p("VECTRI documentation: ", ui.a(VECTRI_DOCS_URL, href=VECTRI_DOCS_URL, target="_blank"), class_="small")
    code_docs = ui.p("Documentation of the source code (under construction): ", ui.a(CODE_DOCS_URL, href=CODE_DOCS_URL, target="_blank"), class_="small")
    online = ui.p("User documentation online (under construction): ", ui.a(USER_DOCS_URL, href=USER_DOCS_URL, target="_blank"), class_="small")
    if not (ASSETS / "docs" / "index.html").is_file():
        return ui.div(ui.p("The user documentation is not included in this installation.", class_="text-muted mt-3"), vectri, online, code_docs)
    return ui.div(
        ui.p(ui.a("Open in a new window", href="/assets/docs/index.html", target="_blank"), class_="small mt-3 mb-2"),
        ui.tags.iframe(src="/assets/docs/index.html", title="Documentation", style="width: 100%; height: 80vh; border: 1px solid var(--bs-border-color);"),
        vectri,
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


def sections(parameters):
    """{group: {section: [names]}} of parameters, in the order of the tabs and of the file."""
    grouped = {group: {} for group in PARAMETER_GROUPS}
    for name, spec in parameters.items():
        grouped[spec["group"]].setdefault(spec["section"], []).append(name)
    return {group: found for group, found in grouped.items() if found}


def slider_tabs(sliders, values):
    """A tab per group, with a folded section per theme holding its sliders. A dot marks a tab and a section
    with a slider moved from its start."""
    tabs = []
    for group, found in sections(sliders).items():
        panels = [
            ui.accordion_panel(
                section,
                ui.layout_column_wrap(*[_slider(name, sliders[name], values[name]) for name in names], width="240px", gap="0 1.5rem"),
                value=section,
            )
            for section, names in found.items()
        ]
        tabs.append(ui.nav_panel(group, ui.accordion(*panels, open=False, multiple=True, class_="mt-2 param-sections"), value=group))
    return ui.navset_underline(*tabs, id="param_tab")
