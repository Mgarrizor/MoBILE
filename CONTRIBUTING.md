# Contributing

## Branches

| Branch | Purpose | Rules (GitHub rulesets) |
|---|---|---|
| `main` | Released code | Changes only through a pull request with 1 approval. No force pushes or deletion. |
| `gui` | Shared development of the Python package and GUI (`python/`) | Changes only through a pull request; the tests must pass and review comments must be resolved. No force pushes or deletion. No one can bypass these rules. |
| your own branch | One task at a time, branched from `gui` | None: push freely. |

Release tags (`v*`) cannot be moved or deleted.

## Working on the GUI

```bash
git switch gui && git pull            # start from the latest gui
git switch -c gui-<short-task-name>   # one branch per task
# ... commit, and push the branch whenever you like ...
git push -u origin gui-<short-task-name>
```

Then open a pull request into `gui`. It can be merged once the tests pass and any review comments
are resolved. Keep branches small and merge them within days. When `gui` is stable, it is merged
into `main` through a pull request.

Never use `git push --force` on `gui` or `main`: it would delete the other person's commits.

## Tests

`.github/workflows/python-tests.yml` runs the tests in `python/tests` on every pull request into
`gui` or `main`, and on every push to `gui`, with Python 3.11 and 3.13. The checks `test (3.11)` and
`test (3.13)` must pass before a pull request into `gui` can be merged. If the Python versions in the
workflow change, update the required checks in the `gui` ruleset as well.

Run them locally before opening a pull request, from the root of the repository:

```bash
pip install -e python
MOBILE=$PWD python -m unittest discover python/tests
```

They need no compiler and run no simulation. They check the package against the Fortran source
and the example data, so some fail on purpose when the model changes:

- a model default of a slider parameter changed: update `python/mobile/default_params.txt`;
- a slider added or removed in `python/mobile/sliders.yaml`: add its default to `default_params.txt`
  and update the count in the test;
- an `&OUTPUT` flag added or removed: update the Outputs table in `python/mobile/layout.py` and the
  count in the test.

They do not test the GUI in a browser, nor run the model: check those by hand.

## Documentation

`.github/workflows/docs.yml` builds the FORD documentation of the source code (published on
GitHub Pages) and checks the Sphinx user documentation, which fails on any warning. Read the Docs
publishes the user documentation: https://mobile-ictp.readthedocs.io
