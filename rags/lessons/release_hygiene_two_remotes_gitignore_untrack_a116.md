---
topic: release_hygiene_two_remotes_and_gitignore_does_not_untrack
date: 2026-07-01
status: gotcha
related: [portable_zip_bundles_solidworks_interop, combridge_bundle_workflow]
version: v0.8.0a116
---
# Releasing ScripTree to git: two remotes, `.gitignore` doesn't untrack, gate the push, UTF-8 commit messages

Captured from the a89→a116 release (Ken: "release to git"). Five things bit
(or nearly bit) us; each has a durable fix. This is the runbook for the next
`main` release.

## 0. The tree geography (don't commit from the wrong place)

The uncommitted release work lives in the **MAIN tree** `D:\Dev\ScripTree`
(checked out on `main`), NOT in the `.claude/worktrees/*` worktrees (those sit
on `claude/*` branches behind `main`). `git worktree list` shows all three.
Commit the release from the main tree: `git -C /d/Dev/ScripTree …`. A stale
memory once claimed HEAD was `a82`; it was actually `a88` — always re-derive
state with `git -C /d/Dev/ScripTree log --oneline -1`, never trust a remembered
version number.

## 1. TWO remotes — `main` pushes to BOTH

```
git remote -v
#   internal  github.com/KenM76/scriptree-internal.git   (PRIVATE mirror)
#   public    github.com/KenM76/scriptree.git            (PUBLIC source repo)
```

`main` is published to **both**. Confirm the current tip is on both before
pushing (so it's a clean fast-forward, no force):
`git branch -r --contains HEAD` → expect `internal/main` + `public/main`.
Push order: `git push internal main` then `git push public main`.
Because `public` is genuinely public, the never-commit list is load-bearing.

## 2. `.gitignore` does NOT untrack already-tracked files (the big one)

Adding `foo/` to `.gitignore` only stops NEW/untracked `foo/` files. Anything
already tracked stays tracked. Two never-commit-list items were tracked from
long before and would have shipped again on a blind `git add -A`:

- `scriptree.ini` — tracked since ~a1. Machine-SENSITIVE: window-geometry
  `@ByteArray` blobs + a `recent_tools`/`recent_trees` list with absolute
  `C:\Users\Ken\…\pytest-of-Ken\…` paths. **Untrack it.**
- `scriptree/resources/concepts/01-05` — tracked since the v0.1.15 V3 fork
  (`2a6d83b`). Non-sensitive design art, regenerated on demand by
  `scriptree/resources/make_icon.py` (no runtime code loads it). **Untrack it.**

Fix pattern (keeps the file on disk, removes it from the index/tip; does NOT
purge history — fine for non-sensitive art already public):
```
git rm --cached scriptree.ini
git rm --cached -r scriptree/resources/concepts/    # -r on the dir hits only
                                                    # TRACKED entries; untracked
                                                    # 06-10 are left alone
# then add both paths to .gitignore so they never re-enter
```
Gotcha within the gotcha: `git rm --cached scriptree/resources/concepts/*.png`
lets the SHELL glob expand to include UNTRACKED files too, and `git rm` aborts
fatally on the first non-tracked path (staging nothing). Use `git rm --cached -r
<dir>/` (index-scoped) or `--ignore-unmatch`, not a disk glob.

**You cannot find these by scanning the DELTA.** `git status` only shows changed
files, so pre-existing tracked violations are invisible. Sweep the WHOLE
published tree:
```
git ls-tree -r HEAD --name-only | grep -iE \
  'solidworkstools|sw_bridge|\.csx$|interop.*sldworks|/concepts/|\.configs\.json$|\.treeconfigs\.json$|^user_configs/|^scriptree\.ini$|\.bak$'
```
(In a116 this also surfaced benign pre-existing `icons/icon-solidworks.*`
glyphs, a `docs/screenshots/solidworks-toolkit-menu.png`, and the
`portable_zip_bundles_solidworks_interop.md` lesson — none are TOOLS, all
intentional. The rule targets proprietary tools: `.csx`, `sw_bridge`,
`SolidWorksTools/`, Interop DLLs — none of which are git-tracked.)

## 3. Verification must GATE the push, not just print

A `grep … && echo "DO NOT PUSH" || echo ok` sitting in the SAME command block
as `git push` does NOT stop the push — the echoes are cosmetic; the push runs
regardless. In a116 the first push (`a4b2ef9`) went out with `concepts/ 01-05`
still tracked because the "DO NOT PUSH" was only a print. Gate for real:
```
if git ls-tree -r HEAD --name-only | grep -q 'resources/concepts/'; then
  echo "ABORT: forbidden content in tree"; else
  git push internal main && git push public main; fi
```
(The sensitive file — scriptree.ini — WAS correctly removed from a4b2ef9; only
the non-sensitive concept art needed the `28211ec` follow-up. Don't force-push
`public` to fold a follow-up into the release commit: a4b2ef9 was already public,
so a non-destructive extra commit is correct, an amend+force is not.)

## 4. Windows commit-message UTF-8 double-encoding trap

`git log … | python -c "… json.load(sys.stdin) …"` decodes stdin as **cp1252**
on Windows. A UTF-8 em-dash `—` (`e2 80 94`) becomes three cp1252 chars, then
re-writing as UTF-8 yields `c3a2 e282ac …` = mojibake `â€"` in the commit
subject. The a116 subject shipped corrupt and had to be `git commit --amend`ed
(caught pre-push). FIXES:
- Read source files with `open(path, encoding='utf-8')`, never through
  `sys.stdin`.
- `export PYTHONIOENCODING=utf-8` before any Python that PRINTS non-ASCII
  (otherwise the debug print itself crashes on `→`).
- Verify stored bytes: `git log -1 --format=%B | python -c "import sys;
  b=sys.stdin.buffer.read(); print(b'\xc3\xa2\xe2\x82\xac' in b)"` must be False.

## 5. Source push ≠ release zip

`git push` publishes only the tracked SOURCE (no SolidWorks tools present). A
downloadable **release zip** built by `make_portable.py` is a separate artifact
that bundles `lib/combridge/` whole — including `plugins/SolidWorks/
SolidWorks.Interop.*.dll` (SolidWorks's own SDK, NOT redistributable). Those
must be stripped from the zip before `gh release create` — see
`portable_zip_bundles_solidworks_interop.md`. a116 was a source push only; no
zip was cut, so that step didn't apply here but WILL next time a zip ships.

## Pre-flight checklist for the next `main` release
1. `git -C /d/Dev/ScripTree` — confirm you're on the main tree, on `main`.
2. Full-tree never-commit sweep (§2) — untrack any pre-existing violations.
3. Update `.gitignore` for anything newly excluded.
4. Version in lockstep: `scriptree/__init__.py` (`__version__` +
   `__build_date__`) == `pyproject.toml` (a test enforces equality).
5. Write the commit message file as UTF-8 (§4); verify no mojibake.
6. Stage, then print `git diff --cached --name-status` and eyeball it.
7. GATE the push (§3), then `git push internal main && git push public main`.
8. If a downloadable zip is part of the release, strip SW interop DLLs (§5).
