# CommonRegex

- **Version:** 1.5.4
- **Source:** PyPI (https://pypi.org/project/CommonRegex/)
- **Upstream:** https://github.com/madisonmay/CommonRegex (MIT license)
- **Installed:** 2026-06-07
- **Installed by:** `pip install --target lib/pypi --no-deps CommonRegex==1.5.4`
  (bypassed `update_lib.py --upgrade` because that wipes the whole
  `lib/pypi/` first and another Python process held `bin/` locked at
  install time; manual targeted install is safe because CommonRegex
  has zero transitive deps).

## Notes

This package ships a single ~6 KB Python file (`commonregex.py`)
plus its dist-info metadata.  Used by the v0.8.0a48+ regex helper
dialog's "Library" tab to populate the built-in patterns list (email,
phone, link, date, ipv4, ipv6, time, money, btc-address, credit-card,
hex-color, street-address).  Each attribute on the module is a
pre-compiled `re.Pattern`; we read `.pattern` to get the raw regex
string for display + insertion into the user's pattern field.

The package is dormant upstream (last release 2018) but the patterns
themselves remain valid -- they're general-purpose, not tied to any
moving spec.  If a pattern proves wrong in the field, fork-and-patch
locally rather than chasing upstream maintenance.

For security audits, run `python lib/update_lib.py --audit`.
