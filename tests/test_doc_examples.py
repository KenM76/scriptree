"""Doc-example regression guard.

Premise (a real bug we shipped): an LLM session followed a stale
``schema_version: 2`` example in ``help/LLM/scriptreetree_format.md``
after the loader had rolled to v3.  The runtime hard-rejected the
file because the doc number was below the build's
``SCHEMA_VERSION``.  Worse, a *higher* number would also break
because ``core/io.py`` is a forward-compat tripwire.

This test enumerates every fenced ``json`` block in the LLM
help directory and:

  * JSON-parses it; if the block is a *shape sketch* (placeholder
    string values like ``"string, required"`` or a non-int
    ``schema_version``) it can't be JSON-loaded — those are
    skipped explicitly so the test stays signal not noise.
  * for blocks that DO parse cleanly AND look like a real
    ``ToolDef`` / ``TreeDef`` (``schema_version`` is an int,
    plus the format-defining required fields), runs the dict
    through the production ``tool_from_dict`` /
    ``tree_from_dict`` loader.  Any loader failure (including a
    schema-version mismatch) becomes a CI failure here, so a
    stale example can't survive a PR.

Why fenced ``json`` and not all ``code`` blocks: shape sketches
in this repo's docs are tagged ``json`` too, but they are
explicitly NOT meant to be JSON-loadable (they carry annotation
strings as values).  The "is this a real example?" gate is
``isinstance(d.get('schema_version'), int)`` — real examples
carry an int.  That happens to be exactly the bug class we're
guarding against.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

from scriptree.core.io import (
    tool_from_dict, tree_from_dict,
)


_LLM_DIR = Path(__file__).resolve().parents[1] / "docs" / "LLM"


def _iter_json_blocks() -> list[tuple[Path, int, str]]:
    """Yield (path, line_no, raw_json_str) for every ```json fenced
    block in docs/LLM/*.md.  Recurses into subdirectories so
    parser-specific doc pages are covered too.
    """
    blocks: list[tuple[Path, int, str]] = []
    fence_re = re.compile(
        r"^```json\s*$\n(.*?)^```\s*$",
        re.MULTILINE | re.DOTALL,
    )
    for md in sorted(_LLM_DIR.rglob("*.md")):
        text = md.read_text(encoding="utf-8")
        for m in fence_re.finditer(text):
            # Compute the 1-based line of the opening fence.
            line_no = text.count("\n", 0, m.start()) + 1
            blocks.append((md, line_no, m.group(1)))
    return blocks


_BLOCKS = _iter_json_blocks()


def test_at_least_one_block_was_discovered() -> None:
    """Sanity: if the regex stops finding blocks, the test is
    silently passing on nothing.  Lock the lower bound."""
    assert len(_BLOCKS) >= 10, (
        f"expected the doc set to carry at least 10 ```json blocks, "
        f"found {len(_BLOCKS)} — the fenced-block regex may be broken."
    )


@pytest.mark.parametrize(
    "md_path,line_no,raw",
    _BLOCKS,
    ids=[f"{p.name}:L{ln}" for p, ln, _ in _BLOCKS],
)
def test_json_block_is_real_or_shape_sketch(
    md_path: Path, line_no: int, raw: str,
) -> None:
    """Every fenced JSON block must be EITHER a shape sketch
    (well-formed-on-purpose placeholder values, can't JSON-parse)
    OR a real example that JSON-parses AND loads through the
    production loader if it has a real ``schema_version`` integer.

    The dual mode is intentional: forcing every shape sketch to
    be JSON-loadable would make them less informative (you can't
    write ``"string, required"`` as a placeholder value if the
    test demands a real string at parse time).  Real examples
    DO have to round-trip — that's the bug class we caught.
    """
    try:
        parsed = json.loads(raw)
    except (json.JSONDecodeError, ValueError):
        # A shape sketch with placeholder strings can't parse —
        # that's expected.  We don't fail; sketches stay readable.
        return

    if not isinstance(parsed, dict):
        # Top-level array / scalar examples are out of scope for
        # the tool/tree loader gates.
        return

    sv = parsed.get("schema_version")
    if not isinstance(sv, int):
        # Either no schema_version (partial sub-object example like
        # a ``cell`` block on its own) or a placeholder string.
        # Skip — not a complete tool/tree.
        return

    # Real example.  Route to the right loader by the shape's
    # format-defining required field(s).
    is_tool = (
        "executable" in parsed and "argument_template" in parsed
    )
    is_tree = (
        "nodes" in parsed and "executable" not in parsed
    )

    if is_tool:
        try:
            tool_from_dict(parsed)
        except Exception as exc:  # noqa: BLE001
            pytest.fail(
                f"{md_path.name}:L{line_no}: real ToolDef example "
                f"failed to load via tool_from_dict: {exc!r}.  "
                f"Most likely a stale schema_version — read the "
                f"current value from "
                f"scriptree/core/model.py:SCHEMA_VERSION."
            )
    elif is_tree:
        try:
            tree_from_dict(parsed)
        except Exception as exc:  # noqa: BLE001
            pytest.fail(
                f"{md_path.name}:L{line_no}: real TreeDef example "
                f"failed to load via tree_from_dict: {exc!r}.  "
                f"Most likely a stale schema_version — read the "
                f"current value from "
                f"scriptree/core/model.py:SCHEMA_VERSION."
            )
    # Else: it parses + has an int schema_version but isn't a
    # tool or tree — could be the sidecar, a ring file, a config
    # dict, etc.  Those have their own format-specific loaders;
    # extending coverage to them is left for later.
