"""ScripTree runtime shim — wraps spawned Python tools.

## For humans

This file is **executed as a script**, not imported.  When ScripTree's
runner spawns a Python tool, it injects this shim between the
interpreter and the tool::

    Before:  python.exe                          tool.py [args...]
    After:   python.exe scriptree/core/_runtime_shim.py tool.py [args...]

The shim then sets up ``sys.path`` so sibling imports (``import _foo``
from a sibling file in the tool's folder) work reliably **regardless**
of:

  * the bundled embeddable Python's ``python<ver>._pth`` file (which
    disables PYTHONPATH and the script-dir auto-prepend),
  * Python 3.11+ ``-P`` / ``PYTHONSAFEPATH`` mode,
  * whether the user replaced ``lib/python/`` with a fresh download
    from python.org (which strips out our ``Lib/site-packages/
    sitecustomize.py``),
  * whatever Python the user happens to be running.

Why a shim and not (just) a sitecustomize?
``sitecustomize.py`` lives **inside** the swappable ``lib/python/``
tree — a manual upgrade by the user blows it away.  This shim lives
in ``scriptree/core/`` (next to the runner that invokes it), which
ScripTree owns and the user is unlikely to disturb.  v0.3.13+ uses
both: this shim is the durable architectural fix; the sitecustomize
is belt-and-suspenders for callers who run the bundled
``python.exe`` directly without going through ScripTree's runner.

What the shim does (in order):

1. Pop its own path off ``sys.argv[0]`` so the tool sees the same
   argv it would have if invoked directly: ``[tool.py, ...args]``.
2. Read ``SCRIPTREE_TOOL_DIR`` from the environment.  This is the
   directory of the ``.scriptree`` file being launched, set by
   ``runner.inject_tool_dir_env``.  Prepend it to ``sys.path`` if
   the directory exists.
3. Prepend the directory containing the real tool script
   (``sys.argv[0]`` after step 1) to ``sys.path``, mimicking
   Python's normal script-dir behaviour.
4. Execute the tool via ``runpy.run_path(..., run_name="__main__")``
   so ``__name__ == "__main__"`` checks fire as the author intended.

Failures inside the shim must NEVER prevent the tool from running —
fall through to a direct ``runpy`` call and let the user's tool
handle ``ImportError`` itself.  A broken shim that crashes every
tool is unacceptable; degraded sibling imports are acceptable.

Robustness invariants:

* The shim has no third-party dependencies — only stdlib.  This
  means it can run under ANY Python 3.x the user might point us at,
  including a stripped-down embeddable.
* It must not import anything from ``scriptree.*`` (that would
  bring in PySide6 etc., which a CLI tool spawned by ScripTree
  has no business pulling in).
* It must propagate the tool's exit code.  ``runpy.run_path`` lets
  ``SystemExit`` bubble up; we let Python's default exit-code
  handling do the rest.

## For maintainers / LLMs

* This runs in the SPAWNED CHILD process, not in ScripTree. It is a
  contract with ``runner._inject_runtime_shim``: that function
  produces exactly ``[python, <this file>, tool.py, ...args]``.
  Change the argv shape on one side ⇒ change the other, or every
  Python tool breaks.
* STDLIB-ONLY, and specifically NO ``scriptree.*`` import — that
  would drag PySide6 into a plain CLI tool's process. The ``core``
  Qt-purity test does not cover this file directly, but the rule is
  stricter here: not even sibling-core imports.
* sys.path order is the whole point: SCRIPTREE_TOOL_DIR is prepended
  FIRST (step 2), then the tool's own script dir (step 3) — so the
  script dir ends at ``sys.path[0]`` and WINS, matching Python's
  native ``python tool.py`` behaviour. Don't reorder; a sibling
  module next to the entry script must shadow a same-named module
  elsewhere.
* ``_prepend_sys_path`` is idempotent via case-folded absolute-path
  comparison (so ``C:\\Foo`` and ``c:/foo`` aren't double-added on
  Windows) and is exception-safe per entry.
* Failure policy is asymmetric: sys.path SETUP failure → print one
  stderr line, CONTINUE (degraded imports beat an opaque crash);
  ``FileNotFoundError`` for the tool itself → clean message, exit 1;
  ``SystemExit`` from the tool → RE-RAISE so the tool's exit code
  propagates (do NOT swallow it — exit-code fidelity is required).
* ``sys.argv`` is rewritten to ``[tool_script, *argv[2:]]`` BEFORE
  running so the tool's ``argparse``/``sys.argv`` sees what it would
  if launched directly. ``runpy`` does not strip argv[0] for us.
* ``run_name="__main__"`` is required so the tool's
  ``if __name__ == "__main__":`` guard fires.
* The bottom guard uses ``raise SystemExit(main())`` so a normal
  ``return 0/1/2`` from ``main`` becomes the process exit code while
  a tool's own ``SystemExit`` still passes through unmodified.
"""
import os
import runpy
import sys


def _prepend_sys_path(directory: str) -> None:
    """Prepend ``directory`` to ``sys.path`` if it isn't already there.

    Idempotent — calling twice with the same path leaves a single
    entry at ``sys.path[0]``.  Compares with case-folded absolute
    paths so ``C:\\Foo`` and ``c:/foo`` aren't treated as distinct
    on Windows.
    """
    if not directory:
        return
    try:
        absdir = os.path.abspath(directory)
    except (OSError, ValueError):
        return
    key = os.path.normcase(absdir)
    for existing in sys.path:
        try:
            if os.path.normcase(os.path.abspath(existing or ".")) == key:
                return
        except (OSError, ValueError):
            continue
    sys.path.insert(0, absdir)


def _remove_shim_dir_from_path() -> None:
    """Drop THIS shim's own directory (``scriptree/core``) from ``sys.path``.

    When ScripTree spawns a tool it runs ``python <this-file> tool.py``,
    so the interpreter auto-inserts the shim's directory —
    ``scriptree/core`` — at ``sys.path[0]`` (Python's normal
    "directory of the script being run" behaviour).

    That directory is a PACKAGE dir full of modules whose top-level
    names collide with the stdlib: ``platform.py`` (i.e.
    ``scriptree.core.platform``), ``io.py``, and friends.  Leaving it on
    ``sys.path`` means a tool — or, more insidiously, a *library the
    tool imports* — that does a bare ``import platform`` / ``import io``
    resolves it to ScripTree's package module instead of the stdlib.
    The real-world symptom was ezdxf's font manager doing
    ``platform.system()`` and dying with
    ``AttributeError: module 'platform' has no attribute 'system'``.

    The shim has finished importing everything it needs by the time it
    hands control to the tool, so removing its own dir is safe — and it
    is exactly the mess the shim exists to prevent for the tool's OWN
    siblings.  Idempotent; case-folded absolute-path comparison so
    ``C:\\Foo`` and ``c:/foo`` match on Windows; exception-safe per entry.
    """
    try:
        shim_dir = os.path.dirname(os.path.abspath(__file__))
    except (OSError, ValueError, NameError):
        return
    key = os.path.normcase(shim_dir)
    kept = []
    for entry in sys.path:
        try:
            if os.path.normcase(os.path.abspath(entry or ".")) == key:
                continue  # this is the shim's own dir — drop it
        except (OSError, ValueError):
            pass
        kept.append(entry)
    sys.path[:] = kept


def _setup_sys_path_for_tool(tool_script: str) -> None:
    """Apply the two ``sys.path`` prepends documented at the top of
    this file, then drop the shim's own directory.  Order matters: the
    tool's own folder lands at ``sys.path[0]`` so ``import _sibling``
    resolves to the file next to the tool, not to a same-named module
    elsewhere on PYTHONPATH or in the stdlib.
    """
    # 1. SCRIPTREE_TOOL_DIR — the .scriptree's parent directory.
    #    Set by ``runner.inject_tool_dir_env`` for ScripTree-launched
    #    tools.  May be unset when the shim is used by a third-party
    #    caller — that's fine; step 2 still runs.
    tool_dir = os.environ.get("SCRIPTREE_TOOL_DIR", "").strip()
    if tool_dir and os.path.isdir(tool_dir):
        _prepend_sys_path(tool_dir)

    # 2. The tool script's own directory (Python's normal behaviour
    #    when invoked as ``python tool.py`` outside of restricted-
    #    sys.path mode).  This wins over SCRIPTREE_TOOL_DIR — same
    #    rule Python uses, and the right one when the tool author
    #    explicitly bundled siblings next to the entry script.
    try:
        script_abs = os.path.abspath(tool_script)
    except (OSError, ValueError):
        return
    script_dir = os.path.dirname(script_abs)
    if script_dir and os.path.isdir(script_dir):
        _prepend_sys_path(script_dir)

    # 3. Finally, evict the shim's OWN directory (scriptree/core) that
    #    Python auto-added at sys.path[0]. It holds stdlib-shadowing
    #    package modules (platform.py, io.py, ...) that must never be
    #    visible to a spawned tool or the libraries it imports.
    _remove_shim_dir_from_path()


def main() -> int:
    # argv[0] = this shim's path
    # argv[1] = the real tool script
    # argv[2:] = the tool's actual args
    if len(sys.argv) < 2:
        sys.stderr.write(
            "scriptree shim: missing tool script in argv.\n"
            "usage: python _runtime_shim.py <tool_script> [args...]\n"
        )
        return 2

    tool_script = sys.argv[1]

    # Fix sys.argv to look like the user invoked the tool directly.
    # ``runpy.run_path`` doesn't strip argv[0] for us; if we don't
    # do this, the tool sees its own path at argv[0] (which is what
    # Python normally provides — good) but with the shim's path
    # ahead of it (bad — every argparse / sys.argv access misreads).
    sys.argv = [tool_script, *sys.argv[2:]]

    try:
        _setup_sys_path_for_tool(tool_script)
    except Exception as exc:  # noqa: BLE001
        # NEVER let a setup failure block the tool from running.
        # Print a one-line diagnostic to stderr and continue with
        # whatever sys.path we have.  The tool may still fail on
        # ``import _sibling`` — but at least the user gets the
        # original ImportError, not an opaque shim crash.
        sys.stderr.write(
            f"scriptree shim: sys.path setup failed: {exc!r}; "
            f"continuing with the unfixed path\n"
        )

    # Run the tool.  ``run_name="__main__"`` so guards fire correctly.
    # ``run_path`` propagates SystemExit naturally, which is how
    # CLI tools signal their exit code.
    try:
        runpy.run_path(tool_script, run_name="__main__")
    except SystemExit:
        # Re-raise so Python's default exit-code handling honours
        # whatever code the tool requested.
        raise
    except FileNotFoundError as exc:
        # Tool script missing — surface a clear error rather than
        # a stack trace from inside runpy.
        sys.stderr.write(
            f"scriptree shim: tool script not found: {tool_script}\n"
            f"  ({exc})\n"
        )
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
