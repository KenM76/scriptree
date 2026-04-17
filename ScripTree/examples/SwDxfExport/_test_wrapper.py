"""Ad-hoc validation of run_dxf_export.substitute() against the real .csx.

Not part of the pytest suite — this lives next to the wrapper script and
is run manually after edits.
"""
from pathlib import Path

import run_dxf_export as r


def main() -> int:
    csx = Path(r.DEFAULT_CSX).read_text(encoding="utf-8")
    print(f"Template size: {len(csx)} chars")
    print(f"Has <<OUTPUT_DIR>>: {'<<OUTPUT_DIR>>' in csx}")
    print(f'"KIT" occurrences: {csx.count(chr(34) + "KIT" + chr(34))}')

    # 1. Normal substitution.
    out = r.substitute(csx, Path("D:/plates_out"), "KIT", no_pdf=False)
    assert "<<OUTPUT_DIR>>" not in out
    # On Windows, Path("D:/plates_out") -> "D:\\plates_out". The wrapper
    # doubles each \ for C# string literal safety, so the final text
    # contains "D:\\\\plates_out" (4 backslashes in source = 2 in string).
    assert "plates_out" in out
    # The line should now be a C# verbatim string with the escaped path.
    assert 'string outputDir = @"D:' in out
    print("OK: normal substitution")

    # 2. Different config name.
    out2 = r.substitute(csx, Path("D:/out"), "Default", no_pdf=False)
    assert '"Default"' in out2
    assert '"KIT"' not in out2
    print("OK: config substitution (KIT -> Default)")

    # 3. --no-pdf toggle.
    out3 = r.substitute(csx, Path("D:/out"), "KIT", no_pdf=True)
    assert "bool generatePdf = false;" in out3
    assert "bool generatePdf = true;" not in out3
    print("OK: --no-pdf toggles generatePdf flag")

    # 4. Missing placeholder must fail loud.
    try:
        r.substitute("no placeholders here", Path("D:/out"), "KIT", no_pdf=False)
    except SystemExit as e:
        assert "<<OUTPUT_DIR>>" in str(e)
        print("OK: missing <<OUTPUT_DIR>> fails loud")
    else:
        raise AssertionError("substitute should have raised")

    # 5. Double-KIT template must be rejected (uniqueness check).
    # Add a second "KIT" inside a comment so the template still has
    # <<OUTPUT_DIR>> and therefore reaches the KIT-count check.
    bad = csx + '\n// note: also has "KIT" here\n'
    try:
        r.substitute(bad, Path("D:/out"), "New", no_pdf=False)
    except SystemExit as e:
        assert "2 occurrences" in str(e)
        print("OK: duplicate KIT is rejected")
    else:
        raise AssertionError("substitute should have rejected duplicate KIT")

    print()
    print("ALL SUBSTITUTION CHECKS PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
