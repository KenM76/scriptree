---
topic: v3-architecture
date: 2026-05-07
status: bugfix
related: [runner, env, tree_view, main_window]
---
# Tree-level `path_prepend` finally reaches the child's PATH (v0.3.2)

## What happened / rule

The audit that landed in v0.3.1 (commit `44af445`) added
``TestTreePathPrependDeadCodeGap`` — four tests pinning the broken
state of ``TreeDef.path_prepend`` at run time.  v0.3.2 closes the
gap by threading a ``tree_path_prepend`` kwarg through the runner
stack.

Before v0.3.2:

* ``TreeDef.path_prepend`` round-tripped through ``save_tree`` /
  ``load_tree`` ✓
* The missing-executable recovery dialog appended to it via
  ``add_to_scriptreetree_path_prepend`` ✓
* But nothing ever read it at run time — the entries were silently
  dropped on every launch.

After v0.3.2: when a user opens a tool through a loaded
`.scriptreetree`, the tree's ``path_prepend`` entries are
prepended to the spawned child's PATH at the documented priority
(between local tool/config entries and the global Settings list).

## Wiring map

| Layer | File | Change |
|---|---|---|
| Pure-logic core | ``core/runner.py::build_env`` | New kwarg ``tree_path_prepend: list[str] \| None = None``; included in the empty-check; slotted into the prepend assembly between ``tool_and_cfg`` and ``global_resolved``.  The override-flag flips behave identically — both modes preserve "tree comes after local entries". |
| Wrapper | ``core/runner.py::build_full_argv`` | Same kwarg; forwarded straight to ``build_env``. |
| Launcher API | ``ui/tree_view.py::TreeLauncherView.tree_path_prepend()`` | Returns the loaded tree's ``path_prepend`` list (empty when no tree is loaded). |
| Runner setter | ``ui/tool_runner.py::ToolRunnerView.set_tree_path_prepend(list)`` | Public setter so the same runner can be re-used across tree-load events; reads back via ``tree_path_prepend()``. |
| Runner consumer | ``ui/tool_runner.py::ToolRunnerView._start_run`` | Passes ``tree_path_prepend=self._tree_path_prepend or None`` to ``build_full_argv``. |
| Main window glue | ``ui/main_window.py::MainWindow._show_runner`` | Calls ``view.set_tree_path_prepend(self._launcher.tree_path_prepend())`` every time a runner surfaces, so cached runners stay in sync. |

## Layer order

Default (highest priority first):

```
[tool.path_prepend, config.path_prepend, tree.path_prepend,
 global.path_prepend, original PATH]
```

When ``global_path_overrides=True``:

```
[global.path_prepend, tool.path_prepend, config.path_prepend,
 tree.path_prepend, original PATH]
```

Tree always sits after local (tool + config) but before global —
matches the documented intent on ``TreeDef.path_prepend``:
"tree-wide overrides win over global but lose to per-tool".

## Asymmetry warning

PATH search uses **prepend order** (earlier = higher priority).
Env-var merging uses **dict.update order** (later = higher
priority).  This means:

* For env vars: ``config_env`` overrides ``tool_env``.
* For PATH: ``tool.path_prepend`` is searched before
  ``config.path_prepend``.

Documented in the "Layering rules" section of
``help/environment.md`` and pinned by tests in
``tests/test_global_env_layering.py``.  The asymmetry matches the
pre-v0.3.2 behaviour; v0.3.2 only added the tree slot, did not
re-litigate the asymmetry.

## Runner caching gotcha (and why we need a setter)

``MainWindow`` caches a ``ToolRunnerView`` per opened-file path in
``self._runners[key]``.  A user can:

1. Load tree A (with ``path_prepend = ["/A"]``).
2. Open tool ``foo.scriptree`` from tree A → runner cached.
3. Load tree B (with ``path_prepend = ["/B"]``) without closing
   the runner.
4. Re-open ``foo.scriptree`` from tree B (same path) → existing
   runner surfaces.

The runner is the same instance, but the parent tree changed.  A
constructor-only kwarg would freeze the v0.1.11-style wrong path
forever in step 4.  The ``set_tree_path_prepend(list)`` setter
called on every ``_show_runner`` keeps the runner in sync.

Tests:
- ``test_show_runner_sets_tree_path_on_runner`` — happy path.
- ``test_show_runner_clears_tree_path_when_no_tree`` — opening a
  bare tool without a tree produces an empty list (so a previously
  cached runner with stale tree state gets reset).

## How future-me detects it

* If a tool's child process doesn't see PATH entries that the
  user added via the recovery dialog's "tree path_prepend" scope,
  check that ``MainWindow._show_runner`` is calling
  ``set_tree_path_prepend`` and that the launcher's
  ``tree_path_prepend()`` returns the expected list.
* If you add a new env layer (e.g. workspace-level), follow the
  same five-step pattern: kwarg in ``build_env`` →
  ``build_full_argv`` forward → launcher API → runner setter →
  main-window glue.

## Tests

12 tests pinning v0.3.2's contract:

- ``TestTreePathPrependWiring`` (8): build_env / build_full_argv
  signatures + behaviour, default vs override-mode priority,
  trigger-non-None empty-check fix.
- ``TestTreeLauncherViewExposesPathPrepend`` (2): launcher API
  empty-when-no-tree + populated-after-load.
- ``TestMainWindowForwardsTreePathPrepend`` (2): runner setter
  called on show, cleared when no tree.

The four ``TestTreePathPrependDeadCodeGap`` tests from v0.3.1 are
gone — the dead-code state is no more.

Suite at v0.3.2: 991/991 (was 983 at v0.3.1).
