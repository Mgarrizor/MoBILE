"""The model chosen at the top of the Setup tab: how humans are represented, the disease, the vector species, and the
vector-ecology-only mode (mobile.sh -V and -e, the run script's vectorID and ecology)."""

# (label, mark): a choice with a mark is shown with it and cannot be chosen
HUMANS = {"agents": ("Agents", None), "bulk": ("Bulk", "in development")}
DISEASES = {1: ("Malaria", None), 2: ("Dengue", "to come"), 0: ("Cholera", "to come")}  # By disID
# vecID: (label, mark, disID of the disease it carries); a mark here is a warning, the species can be chosen
VECTORS = {
    0: ("An. gambiae", None, 1),
    1: ("An. funestus", "not evaluated", 1),
    2: ("An. sacharovi", None, 1),
    10: ("Ae. albopictus", None, 2),
    11: ("Ae. aegypti", None, 2),
}
VECTOR_GENERA = {"Anopheles": (0, 1, 2), "Aedes": (10, 11)}
DEFAULT_VECTOR = 0
VECTOR_BORNE = {spec[2] for spec in VECTORS.values()}  # The diseases a species is chosen for (not cholera)
ECOLOGY_DISEASE = 1  # mobile.sh -e 1 needs -v 1 -d 1
RUN_DEFAULTS = {"vecID": 0, "ecology": 0}  # Optional run keys: a setup without them is An. gambiae, coupled


def label(choices, key):
    """A choice's label with its mark, e.g. "An. funestus (not evaluated)"."""
    name, mark = choices[key][:2]
    return f"{name} ({mark})" if mark else name


def disabled(choices):
    """The keys of HUMANS or DISEASES that cannot be chosen: those marked in development or to come. (A vector's mark is
    a warning: every species can be chosen.)"""
    return {key for key, spec in choices.items() if spec[1]}


def vectors_for(disease, ecology):
    """The vecIDs offered: every species in the ecology-only mode, else those of the disease."""
    return [vec for vec, spec in VECTORS.items() if ecology or spec[2] == disease]


def model_said(run):
    """The model of a setup's run keys, e.g. "Malaria · An. gambiae" or "Vector ecology · Ae. albopictus"."""
    run = {**RUN_DEFAULTS, **run}
    vector = VECTORS.get(run["vecID"], (f"vecID {run['vecID']}",))[0]
    if run["ecology"]:
        return f"Vector ecology · {vector}"
    disease = DISEASES.get(run["disID"], (f"disID {run['disID']}",))[0]
    return f"{disease} · {vector}"


def species_problems(run):
    """What is wrong with the vector species and mode of a setup's run keys."""
    run = {**RUN_DEFAULTS, **run}
    vec, ecology = run["vecID"], run["ecology"]
    found = []
    if vec not in VECTORS:
        found.append(f"run: vecID {vec!r} is no vector species: choose {', '.join(str(v) for v in VECTORS)} "
                     f"({', '.join(f'{v} {s[0]}' for v, s in VECTORS.items())})")
    if ecology not in (0, 1):
        found.append(f"run: ecology is 0 (coupled) or 1 (vector ecology only), got {ecology!r}")
    elif ecology == 1 and run.get("disID") != ECOLOGY_DISEASE:
        found.append(f"run: vector ecology only (ecology: 1) runs with disID {ECOLOGY_DISEASE}, got {run.get('disID')!r}")
    elif ecology == 0 and vec in VECTORS:
        name, _, disease = VECTORS[vec]
        if DISEASES[disease][1]:
            found.append(f"run: {name} carries {DISEASES[disease][0].lower()}, whose model is not written yet: run it with "
                         "vector ecology only (ecology: 1)")
        elif run.get("disID") in VECTOR_BORNE and disease != run["disID"]:
            found.append(f"run: {name} does not carry {DISEASES[run['disID']][0].lower()}")
    return found
