"""CLI subcommands for ScripTree (v0.5.0+).

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
"""
