# 3. Storage format of cache entries

Date: 2026-11-09

## Status

Accepted: entries stay in pickle for now. The replacement format is open and
will be decided in a later ADR, using the requirements below.

## Context

Every place where cartucho serializes entries uses pickle:

- `MemoryBackend.save()` / `load()` write and read one file with every scope.
- `RedisBackend` stores each entry as a pickle (behind a small header).
- [ADR 2](0002-results-bound-to-the-caller.md) (proposed) binds cached results to
  the current caller with `Pickler.persistent_id` / `Unpickler.persistent_load`.

Pickle stores any Python value with no per-type code: pydantic models (such as
the `BGGGame` cached by carton), dataclasses, named tuples and nested containers
all just work. Keeping the exact types matters, because callers get back the
same kind of object a call returned.

The price is that a pickle only makes sense to the program that wrote it:

- **Reading it needs the code that wrote it.** A pickled `BGGGame` is a
  reference to `carton.models.boardgame.BGGGame` plus instructions to rebuild
  it. A tool without carton installed can't even list the entries, and a renamed
  or moved class makes old entries unreadable.
- **Reading it runs code.** Unpickling a file or a Redis value someone else
  could write is arbitrary code execution, so both must be trusted (documented in
  `MemoryBackend.load` and `RedisBackend`).
- **`save()` / `load()` work on the whole file.** One entry can't be read or
  written alone, so a program has to load everything at start and rewrite
  everything at exit, and a crash in between loses every new entry.

We want a command line tool that queries saved content: list scopes, find the
entries of a function for some arguments, show fields of a result, or clean up
entries not used for a while (`last_retrieved`). Pickle makes that tool either
depend on the application's code or impossible.

A previous implementation stored one pandas `DataFrame` per scope, pickled to a
file named after the scope. Splitting files by scope is convenient, but the
files were still pickles, with the same problems, plus a pandas dependency.

## Decision

**Pickle remains the only serialization format for now**, in `MemoryBackend`'s
files and in `RedisBackend`. No other format is added until the requirements
below are met by a concrete design, which will get its own ADR.

Reasons for not changing it yet:

- No candidate stores arbitrary results without per-type code, so every option
  narrows what can be cached or keeps pickle as a fallback.
- ADR 2's binding of results to the caller depends on `persistent_id`; any
  replacement needs an equivalent way to leave placeholders in a stored value.
- The command line tool, the only consumer that needs another format, doesn't
  exist yet; its queries should shape the format, not the other way around.

### Requirements for a future format

1. **Readable without the application's code.** The tool must list and show
   entries, at least as plain data, without importing the classes of results,
   and reading must never run code from the file.
2. **Types are kept for the application.** The program that owns the cache
   gets back the same types it cached (pydantic models, dataclasses, tuples
   versus lists, sets, `1` versus `True`, see the type-aware keys of `Params`).
   Rebuilding classes must be limited to types the application allows.
3. **Arguments can be queried**, e.g. "the entry of `boardgame_by_id` with
   `id=13`", not only through a digest.
4. **Single entries can be read and written** without loading or rewriting the
   whole store, safely if the process stops halfway and, ideally, with several
   processes using it.
5. **Placeholders for caller context** (ADR 2), or an explicit rule that bound
   results fall back to pickle.
6. **A clear fallback** for values the format can't represent: either refuse to
   cache them or store them as pickle, marked so the tool shows them as opaque.
7. **Few dependencies.** Cartucho has none today; heavy ones must be optional
   extras.

### Options to evaluate

- **SQLite with JSON columns.** One row per entry (scope, key digest, params as
  JSON, encoded result, encoding, timestamps). It's in the standard library,
  updates single entries, handles concurrent processes, and can be queried with
  SQL (`json_extract`) even before the tool exists. Results need a JSON encoding
  that tags tuples, sets, non-string keys and registered classes, with pickle as
  the per-entry fallback. Leading candidate for a persistent backend.
- **Parquet, one file per scope.** It continues the previous per-scope idea in an
  open, typed, compressed, columnar format that DuckDB, pandas and polars query
  directly, so arguments can be columns and analytical queries over results (all
  games with some rating) are cheap. But it needs `pyarrow` (a large optional
  dependency), files are immutable (adding an entry means rewriting the scope's
  file or adding small files to compact later, and concurrent writers are not
  supported), every result of a scope must fit one schema, and objects that
  Arrow can't represent end up as pickled bytes again. It fits better as an
  **export or snapshot format** for analysis than as the live store.
- **A single JSON (or JSON Lines) file.** No dependency and readable by any
  tool, but it keeps the whole-file load and rewrite of today's `save()` and
  has no indexed queries.
- **msgpack or CBOR.** Compact and typed with extensions, but they add a
  dependency and are binary, so generic tools can't inspect them.

These can be combined, e.g. SQLite as the persistent backend and a Parquet
export command in the tool.

## Consequences

- Nothing changes for users: results must be picklable to be saved or used with
  Redis, the classes of results must be importable wherever entries are read,
  and saved files and Redis must only be writable by trusted parties.
- Renaming or moving a cached class makes existing entries unreadable. Programs
  loading a saved cache should treat a failing `load()` as an empty cache, as
  carton does.
- Until a new format exists, a query tool can still work on today's files if
  it runs **in the application's environment** (where its classes import), at
  the cost of loading the whole file and trusting it. That is a reasonable
  first version of the tool, not the final design.
- When the format changes, files written by `MemoryBackend.save()` will need a
  migration path (a one-off conversion command) or will be dropped, which is
  acceptable for a cache.
