"""The steps of a calibration as boxes joined by arrows, in a column at the right of the Calibration tab that stays in
view while the page scrolls: each box grey while its step is to do, amber while it is going on or needs attention,
green once it is done, with a word saying which (so that the colour is never the only sign) and a short note. A box is
a link to the card of its step (Setup: to tab 1). The column collapses to the right into a rail of numbered squares in
the same colours (the title and state on hover), remembered in the browser."""

from shiny import reactive, render, ui

# (key, title, where its link goes: the id of an element of the tab, or None for tab 1)
STEPS = (
    ("setup", "Setup applied", None),
    ("data", "Data loaded", "cal-step-data"),
    ("model", "Model chosen", "cal-step-model"),
    ("compared", "Model and data compared", "cal-step-compared"),
    ("objectives", "Objectives added", "cal-step-objectives"),
    ("what", "What to calibrate", "cal-step-what"),
    ("created", "Calibration created", "cal-step-calibrations"),
    ("run", "Run", "cal-step-calibrations"),
    ("results", "Results", "cal-step-results"),
)
TODO, DOING, DONE = "todo", "doing", "done"
CHOSEN, NEW = "chosen", "new"  # The steps follow the calibration chosen under Calibrations, or a new one in the form
WORDS = {TODO: "to do", DOING: "in progress", DONE: "done"}

STYLE = """
/* The tab and, at its right, the steps; below 992 px wide the steps are left out */
.cal-layout { display: grid; grid-template-columns: minmax(0, 1fr) 12rem; gap: 1rem; align-items: start; }
.cal-progress { position: sticky; top: calc(var(--header-height, 0px) + 0.75rem);
  max-height: calc(100vh - var(--header-height, 0px) - 1.5rem); overflow-y: auto; }  /* Scrolls itself on short screens */
@media (max-width: 991.98px) { .cal-layout { grid-template-columns: minmax(0, 1fr); } .cal-progress { display: none; } }
.cal-step-anchor { scroll-margin-top: calc(var(--header-height, 0px) + 1rem); }
.cal-steps { display: flex; flex-direction: column; align-items: stretch; }
.cal-step { display: block; border: 1px solid; border-radius: 0.5rem; padding: 0.35rem 0.6rem; text-decoration: none;
  font-size: 0.8rem; line-height: 1.25; }
.cal-step:hover { filter: brightness(0.97); text-decoration: none; }
.cal-step .cal-step-title { font-weight: 600; }
.cal-step .cal-step-state { float: right; font-size: 0.7rem; font-weight: 600; }
.cal-step .cal-step-note { display: block; font-size: 0.72rem; margin-top: 0.1rem; }
/* Each state its colours, in the light and the dark theme (data-bs-theme, set by the Light / System / Dark switch) */
.cal-step { --step-bg: #f4f4f2; --step-border: #c9c8c3; --step-word: #6c6b66; --step-ink: #1f1e1c; --step-note: #5f5e5a;
  background: var(--step-bg); border-color: var(--step-border); color: var(--step-ink); }
.cal-step.doing { --step-bg: #fff4d6; --step-border: #e0a526; --step-word: #8a5a00; }
.cal-step.done { --step-bg: #ddf1e4; --step-border: #2e9e6b; --step-word: #1d6b47; }
[data-bs-theme="dark"] .cal-step { --step-bg: #2a2a28; --step-border: #5c5b57; --step-word: #b9b7b0; --step-ink: #ecebe6; --step-note: #b0aea7; }
[data-bs-theme="dark"] .cal-step.doing { --step-bg: #3a2f12; --step-border: #c98f1b; --step-word: #f2c45a; }
[data-bs-theme="dark"] .cal-step.done { --step-bg: #173326; --step-border: #3fae7c; --step-word: #7fd6a9; }
.cal-step:hover { color: var(--step-ink); }
.cal-step .cal-step-state { color: var(--step-word); }
.cal-step .cal-step-note { color: var(--step-note); }
.cal-step-arrow { text-align: center; color: #9a9893; line-height: 1; font-size: 0.85rem; margin: 0.1rem 0; }
/* The main area of the page has overflow: auto (bslib) without scrolling, which would hold the steps in place: while
   the Calibration tab is shown, it clips instead, which keeps them in view as the page scrolls */
.main:has(> .tab-content > .tab-pane.active .cal-layout) { overflow-x: clip; overflow-y: visible; }
/* A step still to do has a dashed border: its state is told by shape too, not only by colour */
.cal-step.todo { border-style: dashed; }
.cal-steps-head { display: flex; align-items: center; justify-content: space-between; margin-bottom: 0.25rem; }
.cal-steps-toggle { border: 1px solid var(--bs-border-color); background: transparent; color: var(--bs-secondary-color);
  border-radius: 0.35rem; font-size: 0.8rem; line-height: 1; padding: 0.2rem 0.45rem; }
.cal-steps-toggle:hover { color: var(--bs-body-color); background: var(--bs-tertiary-bg); }
.cal-step-number { display: none; font-size: 0.72rem; font-weight: 700; color: var(--step-word); }
/* Collapsed to the right: a narrow rail of numbered squares, each in the colour of its state, in the same order */
.cal-layout.steps-collapsed { grid-template-columns: minmax(0, 1fr) 2.25rem; }
.steps-collapsed .cal-steps-head { justify-content: center; }
.steps-collapsed .cal-steps-label, .steps-collapsed .cal-step-title, .steps-collapsed .cal-step-state,
.steps-collapsed .cal-step-note { display: none; }
.steps-collapsed .cal-step { width: 1.7rem; height: 1.7rem; padding: 0; margin: 0 auto; border-radius: 0.4rem;
  display: flex; align-items: center; justify-content: center; }
.steps-collapsed .cal-step-number { display: inline; }
.steps-collapsed .cal-step-arrow { font-size: 0.7rem; }
/* Which calibration the steps follow: a choice when open, a letter (C: this calibration, N: a new one) when collapsed */
.cal-steps-follow { font-size: 0.78rem; line-height: 1.3; }
.cal-steps-follow .form-check, .cal-steps-follow .radio { margin-bottom: 0.1rem; }
.cal-steps-follow .shiny-input-container { margin-bottom: 0.4rem; }
.cal-steps-mark { display: none; text-align: center; font-size: 0.72rem; font-weight: 700; color: var(--bs-secondary-color);
  border: 1px solid var(--bs-border-color); border-radius: 0.35rem; width: 1.7rem; margin: 0 auto 0.3rem; }
.steps-collapsed .cal-steps-follow { display: none; }
.steps-collapsed .cal-steps-mark { display: block; }
"""
# Collapses or opens the steps, and remembers it in this browser (a convenience: without storage, they start open)
TOGGLE = """
function calStepsCollapse(collapsed) {
  document.querySelectorAll('.cal-layout').forEach(layout => layout.classList.toggle('steps-collapsed', collapsed));
  document.querySelectorAll('.cal-steps-toggle').forEach(button => {
    button.setAttribute('aria-expanded', String(!collapsed));
    button.textContent = collapsed ? '\u00ab' : '\u00bb';
    button.title = collapsed ? 'Show the steps' : 'Collapse the steps to the right';
  });
  try { localStorage.setItem('mobile-cal-steps-collapsed', collapsed ? '1' : '0'); } catch (error) {}
}
document.addEventListener('DOMContentLoaded', () => {
  let collapsed = false;
  try { collapsed = localStorage.getItem('mobile-cal-steps-collapsed') === '1'; } catch (error) {}
  calStepsCollapse(collapsed);
});
"""
# Tab 1 is opened by clicking its tab, as a link within this tab would scroll instead
TO_SETUP = "document.querySelector('.navbar a[data-value=\"setup\"]').click(); return false;"


def progress_column():
    """The column of the steps, filled by progress_server."""
    toggle = ui.tags.button("\u00bb", type="button", class_="cal-steps-toggle", title="Collapse the steps to the right",
                            onclick="calStepsCollapse(!this.closest('.cal-layout').classList.contains('steps-collapsed'))",
                            **{"aria-expanded": "true", "aria-label": "Collapse or show the steps"})
    head = ui.div(ui.span("Steps", class_="cal-steps-label small text-muted fw-semibold"), toggle, class_="cal-steps-head")
    follow = ui.div(ui.input_radio_buttons("cal_steps_follow", None, {CHOSEN: "This calibration", NEW: "A new one"}, selected=CHOSEN),
                    ui.div(ui.output_text("cal_steps_name", inline=True), class_="text-muted text-truncate mb-1",
                           style="font-size: 0.72rem;"),
                    class_="cal-steps-follow")
    return ui.div(ui.tags.style(STYLE), ui.tags.script(ui.HTML(TOGGLE)), head, follow, ui.output_ui("cal_progress"),
                  class_="cal-progress")


def anchor(key):
    """An empty mark where the link of a step goes, at the top of its card or section."""
    target = dict((k, t) for k, _, t in STEPS)[key]
    return ui.span(id=target, class_="cal-step-anchor")


def step_box(key, title, target, state, note=None, number=None):
    """The box of a step; collapsed, only its number shows (number), in the colour of its state."""
    link = {"href": "#", "onclick": TO_SETUP} if target is None else {"href": f"#{target}"}
    said = f"{number}. " if number else ""
    return ui.tags.a(ui.span(WORDS[state], class_="cal-step-state"), ui.span(title, class_="cal-step-title"),
                     ui.span(note, class_="cal-step-note") if note else None,
                     ui.span(str(number), class_="cal-step-number", **{"aria-hidden": "true"}) if number else None,
                     class_=f"cal-step {state}", title=f"{said}{title}: {WORDS[state]}" + (f" ({note})" if note else ""), **link)


def progress_server(input, prepared, what, stored, activity, chosen_input):
    """The steps, following the calibration chosen under Calibrations (all it was made from is stored in it) or a new one
    being prepared in the form. prepared(): {step: (state, note)} of the form up to the objectives; what(): that of
    What to calibrate in the form; stored(): (name, {step: (state, note)}) of the calibration chosen or running, or
    (None, None); activity(): changes as a new one is prepared (data, model run, objectives); chosen_input(): the
    calibration chosen under Calibrations. Choosing one makes the steps follow it; preparing makes them follow a new one;
    the switch at their top changes it by hand."""

    @reactive.effect
    @reactive.event(chosen_input)
    def follow_chosen():
        if chosen_input():
            ui.update_radio_buttons("cal_steps_follow", selected=CHOSEN)

    seen = {"activity": None}

    @reactive.effect
    def follow_new():
        """A new one is being prepared when the data set shown, the run of the Model box or the objectives change; not when
        the app fills the menu of runs at the start (no run before)."""
        now = activity()
        before, seen["activity"] = seen["activity"], now
        if before is None or now == before:
            return
        (data_before, run_before, objectives_before), (data_now, run_now, objectives_now) = before, now
        if data_before == data_now and objectives_before == objectives_now and not run_before:
            return
        ui.update_radio_buttons("cal_steps_follow", selected=NEW)

    @render.text
    def cal_steps_name():
        """The name of the calibration "This calibration" is (said apart from the switch: updating its choices would also
        set it, and could undo a change on its way)."""
        name, _ = stored()
        return f"This calibration: {name}" if name else "No calibration chosen"

    @render.ui
    def cal_progress():
        name, kept = stored()
        following = input.cal_steps_follow() if "cal_steps_follow" in input else CHOSEN
        if following == CHOSEN and kept is not None:
            states, mark = kept, ui.div("C", class_="cal-steps-mark", title=f"The steps of the calibration {name}")
        else:
            states = {**prepared(), **what(), "created": (TODO, "Create only, or Run"), "run": (TODO, None), "results": (TODO, None)}
            mark = ui.div("N", class_="cal-steps-mark", title="The steps of a new calibration, from the form")
        items = [mark]
        for k, (key, title, target) in enumerate(STEPS):
            if k:
                items.append(ui.div("↓", class_="cal-step-arrow", **{"aria-hidden": "true"}))
            state, note = states.get(key, (TODO, None))
            items.append(step_box(key, title, target, state, note, number=k + 1))
        return ui.div(*items, class_="cal-steps", role="list")
