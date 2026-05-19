"""CLI subcommands for ScripTree (v0.5.0+).

## For humans

Public submodules:

  * ``validate`` — ``scriptree validate <path>`` — load a tool
    through the real ``io.load_tool`` path and report any issues
    with clear, actionable error messages.

  * ``migrate``  — ``scriptree migrate <path>`` — upgrade v2
    ``.scriptree`` files to v3 vocabulary (JSON-Schema-aligned
    type names + HTML5-aligned widget names).  Idempotent; safe
    to re-run.

Both modules are runnable standalone (``python -m scriptree.cli.validate
<path>``) AND exposed through ``main.py``'s subcommand dispatcher so
``scriptree validate`` / ``scriptree migrate`` work via the
installed entry point.

## For maintainers / LLMs

- Two delivery paths per submodule: standalone ``python -m
  scriptree.cli.<x>`` and ``main.py``'s dispatcher. Adding a
  subcommand => wire BOTH the ``__init__`` doc here and the
  ``main.py`` dispatcher, and keep the module's ``main(argv)``
  signature stable (the dispatcher passes ``argv``).
- ``validate`` deliberately routes through the real loader so it
  inherits the loader's fail-loud structural checks; it must not
  reimplement parsing.
- ``migrate`` is contractually idempotent and walks both
  ``.scriptree`` and ``.scriptreetree``; ``.scriptreering`` /
  ``.scriptreeforest`` are intentionally out of scope (separate
  version keys).
- Exit-code contract is shared convention: 0 = all ok, 1 = at
  least one failure, 2 = bad/empty input path. Keep new
  subcommands consistent.
"""
