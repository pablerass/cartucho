"""Sphinx configuration. Build with ``make docs``."""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import cartucho  # noqa: E402

project = "cartucho"
author = "Pablo Muñoz"
copyright = "2025, Pablo Muñoz"
release = cartucho.__version__
version = release

extensions = [
    "sphinx.ext.autodoc",
    "sphinx.ext.napoleon",  # Google-style docstrings
    "sphinx.ext.intersphinx",  # links to the Python docs
    "sphinx.ext.viewcode",  # "[source]" links
    "myst_parser",  # Markdown pages (README, ADRs)
]

source_suffix = {".rst": "restructuredtext", ".md": "markdown"}
exclude_patterns = ["_build"]

# `Name` in docstrings links to the object it names.
default_role = "py:obj"

autodoc_member_order = "bysource"
autodoc_typehints = "description"
autodoc_default_options = {"members": True, "show-inheritance": True}

napoleon_google_docstring = True
napoleon_numpy_docstring = False

intersphinx_mapping = {"python": ("https://docs.python.org/3", None)}

# Markdown "#anchor" links between headings.
myst_heading_anchors = 3

html_theme = "furo"
html_title = f"cartucho {release}"

# `Redis` is only imported for type checking, so Sphinx can't find it.
nitpick_ignore = [("py:class", "Redis")]


def _resolve_short_names(app, env, node, contnode):
    """Link `Name` to the one documented object called ``Name``.

    Sphinx only resolves unqualified names inside the current module; this
    lets docstrings write `ReturnCache` instead of
    `cartucho.return_cache.ReturnCache` anywhere in the package.
    """
    from sphinx.util.nodes import make_refnode

    if node.get("refdomain") != "py":
        return None
    target = node["reftarget"]
    objects = env.get_domain("py").objects
    matches = [name for name in objects if name.endswith("." + target)]
    if len(matches) > 1:
        # e.g. `params` is both a module and the function inside it.
        matches = [name for name in matches if objects[name].objtype != "module"]
    if len(matches) != 1:
        return None
    obj = objects[matches[0]]
    return make_refnode(app.builder, node["refdoc"], obj.docname, obj.node_id, contnode, matches[0])


def setup(app):
    app.connect("missing-reference", _resolve_short_names)
