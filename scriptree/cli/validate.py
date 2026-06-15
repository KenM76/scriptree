"""``scriptree validate <path>`` — verify a ``.scriptree`` file
loads cleanly via the real ``io.load_tool`` path, and that every
param's widget is valid for its type per ``VALID_WIDGETS``.

## For humans

This is the command automated test harnesses (and LLM hooks)
should run before declaring a ``.scriptree`` file done.  It
catches the failure modes that JSON-shape validation misses —
notably the v0.5.0 vocabulary slip where an LLM writes ``int``
or ``spinbox`` instead of the canonical ``integer`` / ``number``.

Usage::

    python -m scriptree.cli.validate path/to/tool.scriptree
    python -m scriptree.cli.validate path/to/tree/            # recurse

Exit codes:
  * 0 — every file passed
  * 1 — at least one file failed
  * 2 — input path doesn't exist

Output (success)::

    ✓ Valid: path/to/tool.scriptree (34 params)

Output (failure) shows the offending field, the value, the
nearest valid alternative (via difflib), and the full list of
valid values — same format ``io.py``'s loader produces.

## For maintainers / LLMs

- Validation goes through the REAL loader (``io.load_tool`` /
  ``io.load_tree``), so it inherits the loader's fail-loud
  structural checks for free. Do NOT reimplement schema parsing
  here; if the loader's checks change, this command's behaviour
  changes with it (by design).
- The widget-vs-type cross-check is the ONLY thing this command
  adds on top of the loader: ``io.load_tool`` is deliberately
  permissive about widget/type mismatch (so legacy/hand-edited
  files still open in the editor); ``validate`` is where that
  mismatch becomes a hard failure before run time.
- ``.scriptreetree`` dispatches to ``load_tree`` (reports node
  count, no widget check — trees have no params);
  ``.scriptree`` dispatches to ``load_tool``. Suffix match is
  case-insensitive.
- Only ``OSError``/``ValueError`` from the loader are turned into
  a clean FAIL line; other exception types propagate (treated as
  bugs, not invalid files) — keep this contract if you touch the
  try/except.
- Output uses ASCII ``[OK  ]``/``[FAIL]`` markers on purpose:
  Windows cp1252 consoles can't encode ✓/✗. Don't reintroduce
  Unicode markers in the per-file lines.
- Exit-code contract mirrors ``migrate``: 0 all-valid, 1 any
  failure, 2 missing path OR zero files found.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path


# --- Lint thresholds (v0.8.0a25+) -----------------------------------------
#
# These constants encode the "form should be sectioned" guidance from
# ``docs/LLM/scriptree_format.md``.  Keep them in lockstep with that
# doc -- if you bump them here, update the doc, and vice versa.
#
#   * ``LINT_SECTION_THRESHOLD`` -- a form with strictly MORE params
#     than this and NO ``sections`` declared triggers a warning
#     ("group these into 2-4 named sections").
#   * ``LINT_TAB_THRESHOLD`` -- a form with AT LEAST this many params
#     and no tab-mode section triggers a stronger hint
#     ("prefer tab-mode for 10+ params").
#
# Warnings DO NOT change the exit code by default; the caller has to
# pass ``--strict`` to promote them.  Sectioning is a recommendation,
# not a correctness requirement, and breaking legacy catalogs over
# style is never the right call.
LINT_SECTION_THRESHOLD = 4
LINT_TAB_THRESHOLD = 10


def _lint_tool(tool) -> list[str]:  # noqa: ANN001 -- ToolDef, avoid circular import
    """Return non-blocking advisory warnings about the tool's form
    organisation.  Empty list when the form follows the recommended
    structure.

    Two checks today:

      1. Too many params with no sections -> recommend grouping.
      2. Many params (>=10) without a tab-mode section -> recommend
         tab mode specifically.

    Both are pure "form ergonomics" advice -- the tool still runs
    fine without sections; the user just has a worse experience.
    """
    warnings: list[str] = []
    n_params = len(tool.params)

    if n_params > LINT_SECTION_THRESHOLD and not tool.sections:
        if n_params >= LINT_TAB_THRESHOLD:
            warnings.append(
                f"{n_params} params but no sections.  The format "
                f"guide recommends grouping >{LINT_SECTION_THRESHOLD} "
                f"params into 2-4 named sections; for "
                f">={LINT_TAB_THRESHOLD} params, prefer tab-mode "
                f"sections (layout: \"tab\").  "
                f"See docs/LLM/scriptree_format.md."
            )
        else:
            warnings.append(
                f"{n_params} params but no sections.  The format "
                f"guide recommends grouping >{LINT_SECTION_THRESHOLD} "
                f"params into 2-4 named sections.  "
                f"See docs/LLM/scriptree_format.md."
            )
    elif tool.sections and n_params >= LINT_TAB_THRESHOLD:
        # Sectioned but not tab-mode for a 10+ param form -- softer
        # nudge: tab-mode is the preferred layout at this scale.
        has_tab = any(
            getattr(s, "layout", "collapse") == "tab"
            for s in tool.sections
        )
        if not has_tab:
            warnings.append(
                f"{n_params} params with collapse-mode sections only.  "
                f"For >={LINT_TAB_THRESHOLD} params, the format guide "
                f"recommends tab-mode sections (layout: \"tab\")."
            )

    return warnings


def validate_one(path: Path) -> tuple[bool, str]:
    """Validate a single ``.scriptree`` or ``.scriptreetree`` file.

    Returns ``(ok, message)``.  ``ok=True`` ⇒ valid, ``message``
    is a one-line summary.  ``ok=False`` ⇒ invalid, ``message``
    is the loader's error text (already formatted with hints).

    Dispatches by suffix: ``.scriptree`` → ``load_tool``,
    ``.scriptreetree`` → ``load_tree``.
    """
    from scriptree.core.io import load_tool, load_tree
    from scriptree.core.model import VALID_WIDGETS

    suffix = path.suffix.lower()
    try:
        if suffix == ".scriptreetree":
            tree = load_tree(path)
            return True, (
                f"Valid: {path} ({len(tree.nodes)} top-level "
                f"node(s))"
            )
        tool = load_tool(path)
    except (OSError, ValueError) as exc:
        return False, str(exc)

    # Cross-check widget validity against the param's type.
    # ``io.load_tool`` doesn't enforce this (the loader is
    # permissive so legacy / hand-edited files don't hard-fail
    # on a widget mismatch that the editor would tolerate); we
    # do it here so ``validate`` catches it before run time.
    issues: list[str] = []
    for p in tool.params:
        valid_widgets = VALID_WIDGETS.get(p.type, ())
        if p.widget not in valid_widgets:
            allowed = ", ".join(w.value for w in valid_widgets) or "(none)"
            issues.append(
                f"  param {p.id!r}: widget {p.widget.value!r} "
                f"is not valid for type {p.type.value!r}.\n"
                f"    Valid widgets for {p.type.value!r}: {allowed}."
            )
    if issues:
        return False, "Widget / type mismatch:\n" + "\n".join(issues)

    types = sorted({p.type.value for p in tool.params})
    widgets = sorted({p.widget.value for p in tool.params})
    return True, (
        f"Valid: {path} ({len(tool.params)} params; "
        f"types: {', '.join(types)}; widgets: {', '.join(widgets)})"
    )


_VALIDATABLE_SUFFIXES = (".scriptree", ".scriptreetree")


def validate_tree(root: Path) -> tuple[int, int, int]:
    """Walk ``root`` and validate every ``.scriptree`` and
    ``.scriptreetree`` underneath.

    Returns ``(scanned_count, failed_count, warned_count)``.
    ``warned_count`` is the number of files that produced at least
    one ``[WARN]`` line.  ``main()`` uses it to gate ``--strict``.
    """
    if root.is_file():
        targets = [root]
    else:
        targets = sorted(
            list(root.rglob("*.scriptree"))
            + list(root.rglob("*.scriptreetree"))
        )
    scanned = 0
    failed = 0
    warned = 0
    # ASCII markers — Windows consoles often run cp1252 which
    # can't encode ✓/✗.  Stick to OK / FAIL / WARN so output
    # renders cleanly everywhere.
    for p in targets:
        if not p.is_file():
            continue
        if p.suffix.lower() not in _VALIDATABLE_SUFFIXES:
            continue
        scanned += 1
        ok, msg = validate_one(p)
        marker = "OK  " if ok else "FAIL"
        print(f"[{marker}] {msg}")
        if not ok:
            failed += 1
            continue

        # Lint pass (v0.8.0a25+) -- non-blocking advisory warnings.
        # Only run on .scriptree files; trees have a different shape
        # and the section-count guidance doesn't apply.  Loading the
        # tool a second time is cheap (JSON parse for a few KB) and
        # keeps ``validate_one``'s public 2-tuple contract intact.
        if p.suffix.lower() == ".scriptree":
            try:
                from scriptree.core.io import load_tool, param_load_warnings
                tool = load_tool(p)
                lints = _lint_tool(tool)
                # v0.8.0a50+ -- per-param load warnings (e.g.
                # MISSING_EXPLICIT_DEFAULT on checkbox_list /
                # dropdown-multi params).  Re-parse the file JSON
                # to pair each raw param dict with its resolved
                # ParamDef -- ``load_tool``'s public API doesn't
                # expose raw provenance, so the lint pass uses the
                # raw JSON for the per-param check.
                try:
                    import json
                    with p.open("r", encoding="utf-8") as f:
                        raw = json.load(f)
                    raw_params = raw.get("params") or []
                    by_id = {
                        (rp.get("id") or ""): rp for rp in raw_params
                        if isinstance(rp, dict)
                    }
                    for resolved in tool.params:
                        rp = by_id.get(resolved.id)
                        if rp is None:
                            continue
                        lints.extend(param_load_warnings(rp, resolved))
                except Exception:  # noqa: BLE001 -- lint never fatal
                    pass
            except Exception:  # noqa: BLE001
                lints = []
            for w in lints:
                print(f"[WARN] {p}: {w}")
            if lints:
                warned += 1
    return scanned, failed, warned


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="scriptree validate",
        description=(
            "Verify .scriptree files load cleanly via the real "
            "loader and that every widget matches its param's "
            "type."
        ),
    )
    parser.add_argument(
        "path",
        type=Path,
        help=(
            "Path to a .scriptree file OR a directory to recurse "
            "through (every .scriptree found is validated)."
        ),
    )
    parser.add_argument(
        "--strict", action="store_true",
        help=(
            "Promote lint warnings to a non-zero exit.  Useful "
            "for CI checks that want to enforce form-organisation "
            "guidance (sectioning of large forms, tab mode for "
            "10+ params)."
        ),
    )
    args = parser.parse_args(argv)

    if not args.path.exists():
        print(f"scriptree validate: not found: {args.path}", file=sys.stderr)
        return 2

    scanned, failed, warned = validate_tree(args.path)
    if scanned == 0:
        print(
            f"scriptree validate: no .scriptree files found under "
            f"{args.path}", file=sys.stderr,
        )
        return 2
    if failed:
        print(
            f"\nscriptree validate: {failed}/{scanned} failed, "
            f"{warned} warned."
        )
        return 1
    if warned:
        if args.strict:
            print(
                f"\nscriptree validate: {scanned}/{scanned} valid "
                f"but {warned} produced lint warnings (--strict)."
            )
            return 1
        print(
            f"\nscriptree validate: {scanned}/{scanned} valid "
            f"({warned} with lint warnings; use --strict to fail "
            f"on them)."
        )
        return 0
    print(f"\nscriptree validate: {scanned}/{scanned} valid.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
