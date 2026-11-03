"""The variables of an output file, as the Variable and Age group menus offer them."""

import re


PREFERRED_VARIABLES = ("EIR", "V")
# A variable by age has a group of its own in the output file, of fields <name>_<age>
AGE_FIELD = re.compile(r"^.+_(bulk|\d+-\d+|\d+\+)$")
ALL_AGES = "bulk"
AGE_KEY = "age:"  # In the Variable menu: one entry for all the fields of a group


GROUP_ORDER = ("Human", "Vector", "Hydro", "Climate")
BY_AGE_HEADING = "By age"


def age_groups(variables):
    """{group: {age: variable}} of the groups of the output file that hold a variable by age."""
    groups = {}
    for name, info in variables.items():
        groups.setdefault(info["group"], {})[name] = AGE_FIELD.match(name)
    return {
        group: {match.group(1): name for name, match in fields.items()}
        for group, fields in groups.items()
        if all(fields.values()) and len(fields) > 1
    }


def age_label(age):
    return "All ages" if age == ALL_AGES else f"Age {age}"


def age_choices(ages):
    return {age: age_label(age) for age in sorted(ages, key=lambda age: age != ALL_AGES)}


def variable_choices(variables):
    """Choices of the Variable menu, by the group of the output file; a variable by age is one entry."""
    def order(group):
        return GROUP_ORDER.index(group) if group in GROUP_ORDER else len(GROUP_ORDER)

    by_age = age_groups(variables)
    choices = {}
    for name, info in variables.items():
        if info["group"] not in by_age:
            choices.setdefault(info["group"], {})[name] = info["long_name"]
    choices = {group: choices[group] for group in sorted(choices, key=order)}
    if by_age:
        choices[BY_AGE_HEADING] = {
            AGE_KEY + group: variables[next(name for age, name in ages.items() if age != ALL_AGES)]["long_name"]
            for group, ages in by_age.items()
        }
    return choices


def preferred_variable(variables, current=None):
    """The menu entry to show: the one on show if the output has it."""
    entries = [entry for group in variable_choices(variables).values() for entry in group]
    for entry in (current, *PREFERRED_VARIABLES):
        if entry in entries:
            return entry
    return entries[0]


def resolve_variable(variables, entry, age=None):
    """The field for a menu entry and an age group; All ages if that one is not available."""
    if not entry.startswith(AGE_KEY):
        return entry
    ages = age_groups(variables)[entry[len(AGE_KEY):]]
    return ages.get(age) or ages.get(ALL_AGES) or next(iter(ages.values()))
