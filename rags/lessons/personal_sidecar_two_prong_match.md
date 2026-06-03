---
topic: v3-architecture
date: 2026-06-03
status: recipe
related: [uninstall_keep_remove_flags_with_backup]
---
# Personal-sidecar match needs BOTH source-filename and source-location prongs

## What happened

While building the per-app uninstall feature, the question came up:
"given an app folder I'm uninstalling, which personal sidecar
configs in the user-config directory belong to *this* app and only
this app?"

Naively matching on `source_filename` alone (i.e., "anything whose
recorded source filename matches a `.scriptree` in this app folder")
sweeps the wrong files: two different installs of the same-named
tool (e.g. two separate copies of `robocopy.scriptree` under
different app trees) would each claim the OTHER install's personal
configs and orphan them on uninstall.

## Root cause

A personal sidecar JSON records two pieces of identity:

- `source_filename` — the bare filename of the catalog it came from
  (e.g. `robocopy.scriptree`).
- `source_locations` — a list of directories where that catalog
  has been seen.

A sidecar genuinely "belongs to" a specific app folder only when
BOTH pieces match: the filename appears inside the app folder
*and* at least one recorded source-location resolves to a path
under the app-folder tree. Either prong alone is a false-positive
trap.

The same predicate is already enforced at *load* time by
`load_personal_configs_for` — the uninstall walk just has to mirror
it.

## Fix / recipe

New helper in `D:\Dev\ScripTree\scriptree\core\configs.py`:

```python
def find_personal_configs_for_app(
    app_dir: str | Path,
    *,
    personal_dir: str | Path | None = None,
) -> list[Path]:
    """Return personal sidecars belonging to scripts inside app_dir.

    Both prongs must match:
      1) sidecar.source_filename is the basename of a .scriptree or
         .scriptreetree found anywhere (recursive) under app_dir.
      2) at least one entry in sidecar.source_locations resolves to
         a directory under app_dir.

    Stdlib-only — `os`, `json`, `pathlib`. Stays Qt-free so the
    helper is headlessly testable.
    """
    app_dir = Path(app_dir).resolve()
    # Walk the app tree to collect catalog basenames in this app.
    catalog_basenames: set[str] = set()
    for root, _, files in os.walk(app_dir):
        for f in files:
            if f.endswith((".scriptree", ".scriptreetree")):
                catalog_basenames.add(f)

    matches: list[Path] = []
    for sidecar in _iter_personal_sidecars(personal_dir):
        data = json.loads(sidecar.read_text(encoding="utf-8"))
        if data.get("source_filename") not in catalog_basenames:
            continue
        locations = data.get("source_locations") or []
        if any(
            _path_is_under(Path(loc).resolve(), app_dir)
            for loc in locations
        ):
            matches.append(sidecar)
    return matches
```

Pinned by `D:\Dev\ScripTree\tests\test_app_uninstall.py::TestFindPersonalConfigsForApp`
(4 cases — both prongs match, only filename matches, only location
matches, neither matches).

## How future-me detects it

* Symptom: uninstalling one copy of a same-named tool causes the
  OTHER install to lose its saved user configs. That's a missing
  location-prong.
* Conversely: if a tool's saved configs disappear after the user
  renames the app folder (so locations no longer match) — that's
  the right behaviour by this rule, but worth noting to the user.
* Any new helper that asks "do these personal sidecars belong to
  this app folder?" must use both prongs, never just filename. The
  load-time predicate `load_personal_configs_for` is the reference.
