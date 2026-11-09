# Agent instructions

Instructions for any coding agent working on this repository.

## Keep the documentation updated in the same change

The Sphinx site (`make docs`) is built from three sources. Every change to
behaviour or public API must update the ones it affects before it is
considered done:

- **Docstrings** (Google style): they are the API reference (`docs/api.rst`
  uses `automodule`). Document new parameters, return values, raised
  exceptions and behaviour changes. Reference objects as `` `Name` ``; the
  docs resolve short names.
- **`README.md`**: it is also the home page of the docs (`docs/index.md`
  includes it). Update usage examples and the "Good to know" notes when user
  visible behaviour changes. Links are relative to the repository root
  (`docs/adr/...`).
- **ADRs in `docs/adr/`**: record design decisions (new options, changed
  semantics, rejected alternatives) as `NNNN-short-title.md`, following the
  structure of the existing ones (Status, Context, Decision, Alternatives
  considered, Consequences). They are picked up by the toctree automatically.
  - Before choosing a number, list `docs/adr/` again: other sessions may have
    added one meanwhile. Never reuse a number.
  - Update an existing ADR's status or consequences when a change affects it,
    instead of contradicting it silently.

New pages outside `docs/adr/` must be added to the toctree in
`docs/index.md`.

## Checks before finishing

Run all of them and fix every failure, including warnings in the docs build:

```bash
uv run pytest           # tests
uv run ruff check       # lint
uv run ty check         # types
make docs               # nitpicky, fails on any warning or broken reference
```

New behaviour needs tests, and backend behaviour common to every backend goes
in `tests/test_backends.py`, which runs against all of them.
