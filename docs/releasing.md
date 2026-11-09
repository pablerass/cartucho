# Releasing

Versions follow `MAJOR.MINOR.PATCH` and every release is a `vMAJOR.MINOR.PATCH`
git tag. Pushing a tag makes the CI workflow publish that version to PyPI and
create its GitHub release. That release is marked as a pre-release only when
the tag has a PEP 440 pre-release suffix (`a`, `b` or `rc`, as in `v0.1.0a1`).

Each `MAJOR.MINOR` lives on a `release/MAJOR.MINOR` branch, which only receives
fixes. New features go to `main`, and the next minor or major release is cut
from it.

```text
main ──●──●──[v0.1.0]──●──●──[v0.2.0]──●──▶
                 │                │
                 │                └─ release/0.2
                 └─ release/0.1 ──●──[v0.1.1]──●──[v0.1.2]
```

## Commands

| Command | Run it on | Result |
|---|---|---|
| `make release-minor` | `main` | `X.Y+1.0`: version commit on `main`, tag, new `release/X.Y+1` branch |
| `make release-major` | `main` | `X+1.0.0`: version commit on `main`, tag, new `release/X+1.0` branch |
| `make release-patch` | `release/X.Y` | `X.Y.Z+1`: version commit and tag on that branch |

All of them run `scripts/release.sh`, which:

1. Checks that the working tree is clean, the branch is the right one and it
   isn't behind its remote, and that the tag and branch don't exist yet.
2. Sets the new version with bumpver (in `pyproject.toml` and
   `cartucho/__init__.py`) and updates `uv.lock`, which records the project
   version and must match for `uv sync --locked` in CI.
3. Commits `Bump version vOLD -> vNEW`, adds an annotated `vNEW` tag and, for
   minor and major releases, creates the `release/X.Y` branch on that commit.

Nothing is pushed unless you ask for it, so you can review the result first.

| Variable | Effect |
|---|---|
| `DRY_RUN=1` | Only print the version, branch and push command that would be used |
| `PUSH=1` | Push the branches and the tag at the end, which **publishes the release** |
| `REMOTE` | Remote to check and push to (default `origin`) |
| `MAIN` | Name of the main branch (default `main`) |

## Cutting a minor (or major) release

```bash
git switch main && git pull
make release-minor DRY_RUN=1   # check the version it will use
make release-minor
git push --atomic origin main release/0.2 v0.2.0   # the command it prints
```

The version commit is made on `main` and the release branch starts there, so
`main` always holds the latest released `MAJOR.MINOR` and the next
`release-minor` bumps from it.

While `main` holds a pre-release such as `0.1.0a1`, the next release is its
final version (`0.1.0`), not the one after it.

## Releasing a fix (patch)

Fix the bug on `main` first, then bring the fix to each release branch that
needs it and release it there:

```bash
git switch release/0.1 && git pull
git cherry-pick <fix commit>
make release-patch
git push --atomic origin release/0.1 v0.1.1
```

Patch versions are only committed to their release branch; `main` keeps its
own version.

## When something goes wrong

If bumpver or `uv lock` fails, the script reverts the files it changed. Before
pushing, a release can be undone locally with:

```bash
git tag -d v0.2.0
git branch -D release/0.2    # minor and major releases only
git reset --hard HEAD~1      # drops the version commit
```

Once a tag is pushed the version is on PyPI and can't be reused: release a new
patch instead.
