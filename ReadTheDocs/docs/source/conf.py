# Configuration file for the Sphinx documentation builder.
#
# For the full list of built-in configuration values, see the documentation:
# https://www.sphinx-doc.org/en/master/usage/configuration.html

# -- Project information -----------------------------------------------------
# https://www.sphinx-doc.org/en/master/usage/configuration.html#project-information

import datetime
import os
import subprocess


def _release():
    """The version being documented: a tag on Read the Docs, 'latest' for its main branch, git describe otherwise."""
    if os.environ.get('READTHEDOCS'):
        return os.environ.get('READTHEDOCS_VERSION_NAME', 'latest')
    try:
        return subprocess.run(['git', 'describe', '--tags', '--always'], capture_output=True, text=True,
                              check=True, cwd=os.path.dirname(__file__)).stdout.strip()
    except (OSError, subprocess.CalledProcessError):
        return 'development'


project = 'MoBILE'
copyright = f'2025-{datetime.date.today().year}, Miguel Garrido Zornoza'
author = 'Miguel Garrido Zornoza'
release = _release()

# -- General configuration ---------------------------------------------------
# https://www.sphinx-doc.org/en/master/usage/configuration.html#general-configuration

extensions = []

templates_path = ['_templates']
exclude_patterns = []



# -- Options for HTML output -------------------------------------------------
# https://www.sphinx-doc.org/en/master/usage/configuration.html#options-for-html-output

#html_theme = 'alabaster'
html_theme = 'sphinx_rtd_theme'
#html_theme = 'furo'
