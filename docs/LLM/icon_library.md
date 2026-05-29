# Icon library — picking, reusing, and extending

This doc is the LLM-facing reference for ScripTree's bundled
trademark-safe line-icon set, the runtime keyword heuristic that
maps a tool's name to one of those icons, and the rules for adding
a new icon when none of the existing ones fit.

If you are about to author or refresh a `.scriptree` / `.scriptreetree`
catalog: read **§1** (decision tree) and **§2** (the full bundled set
grouped by category), then either embed the chosen icon
(workflow in **§5**) or — only when no archetype fits — generate
a new SVG strictly to [`../host-software-icon-style.md`](../host-software-icon-style.md)
and follow **§6**.

The canonical style guide is [`../host-software-icon-style.md`](../host-software-icon-style.md);
the schema for the `cell.icon_data` field lives in
[`scriptree_format.md`](scriptree_format.md) under "`cell` sub-object".
This doc is the **menu of available glyphs + the decision rules** that
sit between those two.

> **v0.6.26+ — folder/leaf icon overrides.**  A `.scriptreetree`
> node (folder OR leaf) can carry its own `icon` / `icon_data` /
> `icon_format` triplet, which OVERRIDES the default glyph for
> that node's submenu marker / row in the single-click popup
> menu.  Use this when the tree-author wants a folder to show a
> category glyph instead of the generic OS folder icon, or when
> the same `.scriptree` is referenced from multiple trees that
> want different glyphs for it.  See
> [`scriptreetree_format.md`](scriptreetree_format.md) for the
> field-level contract; the picking rules in this doc apply
> unchanged.

---

## 1. Decision tree — which icon does this tool get?

For every catalog you touch:

```
1. Does a human-set icon already live on disk for this catalog?
   ├─ YES → leave it alone (do NOT clobber a deliberate user choice).
   └─ NO  → continue.

2. Does the catalog's *file stem* or *display name* contain a
   keyword that classify_icon would match?
   (see §3 — keyword → icon table)
   ├─ YES → embed `icon-<that_name>.png`.
   └─ NO  → continue.

3. Does any §2 category archetype fit the tool's functional purpose?
   ├─ YES → embed that icon.
   └─ NO  → continue.

4. Do you genuinely need a new archetype?
   (rare — usually §2 covers it.  If unsure, pick the closest §2
   match rather than creating noise.)
   ├─ YES → §6 "Adding a new icon".
   └─ NO  → use `icon-tool.png` (the universal "some utility" glyph).
```

> **Hard rules**
> * Never embed a vendor's real logo or brand mark (legal gate; see
>   [`../host-software-icon-style.md`](../host-software-icon-style.md) §5).
> * Never use multiple distinct icons for the same conceptual
>   operation across a single suite — pick one and stay consistent.
> * Folder/tree parents (`.scriptreetree`) get the category
>   archetype; leaves get the operation archetype.  Example:
>   `Outlook migration` tree → `email`; its `backup_data` leaf →
>   `archive`; its `restore_data` leaf → `download`.
> * A suite that shares a vendor identity (SolidWorks toolkit,
>   ffmpeg, etc.) keeps the *parent* glyph identifying the vendor
>   /category, while the *leaves* differ by operation.  That's how
>   the menu reads at a glance: one column shows "what suite",
>   the icons inside show "what operation".

---

## 2. The bundled set (54 icons, all 48-grid `currentColor` line glyphs)

Each entry: `icon-<name>` — what it is — when to pick it.  Names
without the `icon-` prefix are what you pass to `embed_icon` /
`bundled_icon_b64` / the `_OVERRIDES` table in
`scripts/refresh_app_icons.py`.

### 2.1 Host software (vendor-neutral category archetypes)

These six are the canonical examples from the style guide §4.  They
identify the **category** of host software, never a vendor's logo.

| Icon | Metaphor | Use for |
|---|---|---|
| `solidworks` | Gear with 8 spokes | Mechanical CAD: SolidWorks, FreeCAD, Creo, CATIA, Inventor — anything that builds 3D parts/assemblies. |
| `autocad` | Drafting triangle + crossbar | 2D drafting / DWG / DXF / drafting tools (the *editor* sense; for the *cut* sense use `scissors`). |
| `inventor` | Isometric box with edges | 3D solid modeling, assemblies, mechanical layout that isn't covered by `solidworks`. |
| `revit` | Building with roof + windows | BIM, architecture, IFC, plant layout. |
| `msoffice` | 2×2 grid of tiles | Office *suite* as a whole (Word + Excel + Outlook + PowerPoint together).  For individual apps see `document`, `spreadsheet`, `email`, `presentation`. |
| `cli` | Terminal window + `>` prompt + line | Command-line tools, shell scripts, console utilities. |

### 2.2 Domain-document types

| Icon | Use for |
|---|---|
| `document` | Generic document, text, note, README, manual, report. |
| `spreadsheet` | Excel, CSV, XLSX, any tabular calc workbook. |
| `presentation` | PowerPoint, slides, PPTX, Keynote, any deck. |
| `pdf` | PDF files / Acrobat / "convert X to PDF". |
| `email` | Mail, SMTP, IMAP, inbox, Outlook (the application). |

### 2.3 File system / containers

| Icon | Use for |
|---|---|
| `folder` | Directory, explorer, tree view, filesystem ops. |
| `archive` | ZIP / TAR / 7z / compression, backups (as in "produce a compressed bundle"). |
| `package` | Parcel/box: installers, distribution packages (MSI, wheel, npm, pip), "fully resolved" / "all components included". |
| `container` | Docker / Podman / Kubernetes / Compose / generic grouped-cells hub. |
| `forest` | Stepped conifer + trunk — the **ScripTree forest hub** (workspace root, owns rings + trees + tools).  Used as the default hub icon by `ForestController` when no bound catalog. |
| `ring` | Concentric circles (hub + orbit) — the **ScripTree ring hub** (a master cell that owns several cell members).  Used as the bare-hub default by `ring_io.load_ring`. |

### 2.4 Data / databases / metrics

| Icon | Use for |
|---|---|
| `database` | SQL, Postgres, MySQL, SQLite, Mongo, Redis. |
| `chart` | Analytics, metrics, reports, plots, dashboards. |
| `calendar` | Schedule, cron, timer, reminder, dated events. |
| `clock` | Time-stretch, stopwatch, duration, uptime, "pause"/wait. |

### 2.5 Network / cloud / servers

| Icon | Use for |
|---|---|
| `network` | Node graph: ping, TCP, sockets, DNS, SSH, FTP, VPN, LAN, subnets. |
| `server` | Daemons, services, web server (Apache, nginx, IIS), rack. |
| `cloud` | AWS, Azure, GCP, S3, Lambda, generic cloud. |
| `web` | HTTP, browser, HTML, REST, web APIs, websites. |

### 2.6 Operations on data (verbs)

| Icon | Use for |
|---|---|
| `convert` | Two cyclic arrows — transcode (ffmpeg), transform, encode/decode, export, import, rebuild, sync. |
| `filter` | Funnel — sed, awk, "hide all but selected", query, where-clause. |
| `search` | Magnifier — find, locate, grep / ripgrep, lookup, probe (inspect), "show all" / list-existing. |
| `download` | Tray + down arrow — fetch, wget, curl, restore-from-backup. |
| `upload` | Tray + up arrow — publish, push, sync-up, transfer-out. |
| `link` | Chain link — concatenate, alias, shortcut, symlink, merge two things. |
| `scissors` | Cut/trim, plasma/laser cut, nest, kerf, remove pages. |

### 2.7 Code / build / quality

| Icon | Use for |
|---|---|
| `code` | Generic source code, IDE, SDK, function. |
| `script` | Document with prompt — Python (.py), Node, Ruby, Lua, batch (.bat), macros, automation. |
| `build` | Stacked blocks — compile, make, gradle, maven, cmake, msbuild. |
| `test` | Flask — pytest, unittest, lint, spec, verify, QA. |
| `bug` | Beetle — debug, trace, profiler, diagnostics, "fix broken X". |
| `versioncontrol` | Branch — git, svn, mercurial, commit. |

### 2.8 Security

| Icon | Use for |
|---|---|
| `lock` | Padlock — encrypt/decrypt, cipher, SSL/TLS, "disable / lock down". |
| `key` | Key with bow — tokens, credentials, license, keygen, "stored data tied to identity" (autocomplete entries, addressbook). |
| `shield` | Shield with check — firewall, antivirus, "make X safe". |

### 2.9 Hardware / OS

| Icon | Use for |
|---|---|
| `chip` | CPU/SoC — processor, firmware, embedded, Arduino, Raspberry Pi, graphics compatibility. |
| `printer` | Printer + paper tray — print jobs, plotters, CUPS, "unshade for print". |
| `window` | App window — generic GUI app, desktop tool. |
| `settings` | Three sliders — preferences, configuration, profile, tuning. |
| `power` | Power symbol — PowerShell, power-management. |

### 2.10 Media

| Icon | Use for |
|---|---|
| `media` | Player — playlists, generic media. |
| `video` | Filmstrip + play — movies, mp4, streams, recordings. |
| `audio` | Speaker + waves — sound, mp3/wav, music, voice. |
| `image` | Picture frame — photos, raster (png/jpg), thumbnails, watermarks, raster output. |

### 2.11 Measurement / location / annotation

| Icon | Use for |
|---|---|
| `ruler` | Measure, dimension, caliper, gauge, "explicit size". |
| `pin` | Map pin — location, GPS, coordinate, checkpoint/bookmark. |
| `edit` | Pencil — rename, modify, patch, "set draft". |

### 2.12 The universal default

| Icon | Use for |
|---|---|
| `tool` | Wrench — the generic "some utility" glyph.  Used when no other archetype applies.  Avoid when you can — variety reads better than a wall of wrenches. |

---

## 3. The classify_icon keyword heuristic

When a catalog has **no** embedded icon, the runtime falls back to
`scriptree.shell.icon_assets.classify_icon(name, filename,
executable)`.  It builds a lowercased haystack from the inputs and
runs it through a first-match-wins rule table.  Knowing the
ordering matters because some keywords overlap (e.g. "dxf"
matches `autocad`, but "plasma" matches `scissors` higher up).

**Rule order (first match wins):**

1. Ring (ScripTree primitive — wins first so substring
   matches like "rest" → web don't misroute a ring-named
   tool): `" ring "`, `" rings "`, `scriptreering`,
   `tree ring`, `ring hub` → `ring`.
2. Forest (ScripTree primitive — same reason): `forest`,
   `scriptreeforest`, `workspace root` → `forest`.
3. CAD: `solidworks`, `sldworks`, `sw_bridge`, `catia`, `creo`,
   `mechanical`, `cad `, `freecad` → `solidworks`
4. Fabrication-cut: `scissors`, `cut`, `plasma`, `laser`, `nest`,
   `trim`, `kerf` → `scissors`  *(beats `autocad` so "DXF plasma cut"
   doesn't get the drafting triangle)*
5. 2D drafting: `autocad`, `dwg`, `dxf`, `draft` → `autocad`
6. 3D modeling: `inventor`, `fusion360`, `3d model`, `assembly`
   → `inventor`
7. BIM: `revit`, `bim`, `ifc`, `archicad` → `revit`
8. Measure: `ruler`, `measure`, `dimension`, `caliper`, `gauge`
   → `ruler`
9. VCS: `git`, `svn`, `mercurial`, `version control`, `commit`,
   `branch`, `vcs` → `versioncontrol`
10. PowerShell: `powershell`, `pwsh`, `.ps1`, `power shell` → `power`
11. Shell/CLI: `terminal`, `shell`, `bash`, `cmd`, `console`, `cli`,
   `command line`, `zsh`, `sh ` → `cli`
12. Script: `python`, `.py`, `node`, `ruby`, `perl`, `lua`, `script`,
    `macro`, `automation`, `batch`, `.bat` → `script`
13. Build: `compile`, `build`, `make`, `gradle`, `maven`, `cmake`,
    `msbuild`, `ninja`, `bundler` → `build`
14. Test: `test`, `pytest`, `unittest`, `lint`, `spec`, `verify`,
    `assert`, `qa` → `test`
15. Debug: `debug`, `bug`, `trace`, `profiler`, `diagnos` → `bug`
16. Archive: `zip`, `archive`, `tar`, `7z`, `compress`, `unzip`,
    `extract`, `gzip`, `rar` → `archive`
17. Package: `package`, `installer`, `setup`, `deploy`, `msi`,
    `wheel`, `npm`, `pip ` → `package`
18. Download: `download`, `fetch`, `pull`, `wget`, `curl`, `get `
    → `download`
19. Upload: `upload`, `publish`, `push`, `sync up`, `deploy to`
    → `upload`
20. Convert: `convert`, `transcode`, `ffmpeg`, `transform`, `encode`,
    `decode`, `export`, `import` → `convert`
21. Search: `search`, `find`, `locate`, `index`, `lookup`, `grep`,
    `ripgrep` → `search`  *(grep moved here from filter so "search
    files (ripgrep)" reads as search, not filter)*
22. Filter: `filter`, `sed`, `awk`, `query`, `select `, `where `
    → `filter`
23. Database: `database`, `sql`, `postgres`, `mysql`, `sqlite`,
    `mongo`, `redis`, `db ` → `database`
24. Network: `network`, `ping`, `tcp`, `socket`, `port`, `dns`,
    `ssh`, `ftp`, `vpn`, `lan`, `subnet` → `network`
25. Server: `server`, `daemon`, `service`, `apache`, `nginx`,
    `iis`, `hostname`, `webserver` → `server`  *(no bare `host`
    keyword — `ping host` was getting `server` instead of `network`)*
26. Cloud: `cloud`, `aws`, `azure`, `gcp`, `s3 `, `lambda` → `cloud`
27. Container: `docker`, `container`, `podman`, `kubernetes`, `k8s`,
    `compose` → `container`
28. Link: `link`, `url`, `shortcut`, `alias`, `symlink` → `link`
29. Lock: `lock`, `encrypt`, `decrypt`, `cipher`, `ssl`, `tls`,
    `credential`, `password`, `secret` → `lock`
30. Key: `key`, `token`, `auth`, `license`, `keygen` → `key`
31. Shield: `shield`, `secure`, `security`, `firewall`, `antivirus`,
    `protect`, `defender` → `shield`
32. Calendar: `schedule`, `calendar`, `cron`, `timer`, `reminder`
    → `calendar`
33. Clock: `clock`, `time`, `stopwatch`, `duration`, `uptime`
    → `clock`
34. Chart: `chart`, `graph`, `analytic`, `metric`, `stat`, `report`,
    `plot`, `dashboard` → `chart`
35. Spreadsheet: `spreadsheet`, `excel`, `csv`, `xlsx`, ` calc`
    → `spreadsheet`
36. Presentation: `presentation`, `powerpoint`, `slide`, `pptx`,
    `keynote` → `presentation`
37. MS Office: `office`, `word`, `docx`, `outlook` → `msoffice`
38. PDF: `pdf`, `acrobat` → `pdf`
39. Email: `email`, `mail`, `smtp`, `imap`, `inbox` → `email`
40. Print: `printer`, `print`, `plot `, `cups` → `printer`
41. Audio: `audio`, `sound`, `mp3`, `wav`, `music`, `voice` → `audio`
42. Video: `video`, `movie`, `film`, `mp4`, `stream`, `record`
    → `video`
43. Image: `image`, `photo`, `picture`, `png`, `jpg`, `jpeg`, `svg`,
    `raster`, `thumbnail` → `image`
44. Media: `media`, `player`, `playlist` → `media`
45. Chip: `chip`, `cpu`, `processor`, `firmware`, `embedded`,
    `arduino`, `raspberry` → `chip`
46. Disk/storage: `disk`, `drive`, `storage`, `backup`, `volume`,
    `partition`, `mount` → `server`
47. Pin: `location`, `map`, `pin`, `geo`, `gps`, `coordinate`
    → `pin`
48. Edit: `edit`, `editor`, `rename`, `modify`, `patch`, `pencil`
    → `edit`
49. Settings: `settings`, `config`, `preference`, `options`, `tune`,
    `profile` → `settings`
50. Web: `web`, `http`, `browser`, `html`, `rest`, `api`, `site`
    → `web`
51. Window: `window`, `gui`, `desktop`, `app ` → `window`
52. Code: `code`, `develop`, `ide`, `compiler`, `sdk`, `function`
    → `code`
53. Document: `document`, `doc `, `text`, `note`, `readme`,
    `manual`, `report ` → `document`
54. Ring (ScripTree primitive): `" ring "`, `" rings "`,
    `scriptreering`, `tree ring`, `ring hub` → `ring`
    *(word-boundary spaces are intentional; bare "ring" would
    misroute "string"/"monitoring"/"engineering")*
55. Forest (ScripTree primitive): `forest`, `scriptreeforest`,
    `workspace root` → `forest`
56. Folder: `folder`, `directory`, `explorer`, `tree`, `files`,
    `filesystem` → `folder`

Default when nothing matches: **`tool`**.

> The source of truth is `_ICON_RULES` in `scriptree/shell/icon_assets.py`.
> If you change the rule order there, regenerate this listing.

---

## 4. Reusing the centralised mapping in scripts/refresh_app_icons.py

When you're populating icons for a whole suite (or refreshing a
suite whose tools currently share one icon — the
ffmpeg/outlook/SolidWorks pattern), prefer adding a section to
`scripts/refresh_app_icons.py::_OVERRIDES` rather than embedding
ad-hoc in your own script.  Benefits:

* One canonical place to look up "what icon did we pick for tool X".
* The next refresh (e.g. when a new bundled icon is added) re-runs
  trivially with the same mappings.
* The mapping itself becomes a documentation artefact — future
  authors see the convention applied to similar tools.

The override key is the catalog's **file stem** (case-insensitive,
no extension; `Path.stem` lowercased).  The value is a bundled
icon name from §2.  Run `python scripts/refresh_app_icons.py` to
re-embed across the default target list, or pass explicit
directories: `python scripts/refresh_app_icons.py DIR [DIR ...]`.

---

## 5. Embed workflow (PNG, not SVG)

The portable/vendored PySide6 has no qsvg image-format plugin, so
`QPixmap.loadFromData(svg_bytes, "SVG")` returns False there.  **The
runtime artifact must be PNG.**  The shipped `icons/` set carries
both `icon-<name>.svg` (the design source) and `icon-<name>.png`
(the runtime artifact).

For one catalog, use the production helper:

```python
from scriptree.core.cell_metadata import embed_icon
from scriptree.shell.icon_assets import bundled_icon_png_path

png = bundled_icon_png_path("scissors")     # → Path / None
embed_icon("path/to/tool.scriptree", str(png))
```

`embed_icon` reads the PNG bytes, base64-encodes them, sets
`cell.icon_data` + `cell.icon_format="png"`, clears any prior
`cell.icon` path, and writes the catalog file back atomically.

For a whole tree, use `scripts/refresh_app_icons.py` (see §4).

> **Don't write `cell.icon` to point at a path you control.**
> Relative paths break when the catalog is moved; embedded PNG bytes
> travel with the file.  The cell Settings dialog's "Library…"
> button does the same embed for end users.

---

## 6. Adding a new icon (when the §2 set genuinely doesn't fit)

The bar for adding a new archetype is high — most "I need a new
icon" cases are actually a §2 entry with a less obvious metaphor
(e.g. "fix broken view" → `bug`, not a new "wrench-with-error"
icon).  Before generating, scroll §2 twice and run the §1 decision
tree to the end.

If you're sure, follow the canonical style guide
[`../host-software-icon-style.md`](../host-software-icon-style.md)
**verbatim**.  Required:

* `viewBox="0 0 48 48"`, `fill="none"`, `aria-hidden="true"`, no
  `width`/`height` on the root.
* A leading XML comment: `<!-- Generic <category> shape —
  placeholder, not the <Vendor> trademark logo -->`.
* 1–4 stroke-only elements (`rect` / `circle` / `path`).
* Every element: `stroke="currentColor"` (never a hex/named
  colour), `stroke-width="2.5"` (one nested detail may use `2`).
* Round `stroke-linecap` and `stroke-linejoin`.
* Content within the 4→44 band of the 48 grid; centred & balanced.
* Rounded-rect radii 1–3.

Tests in `tests/test_icon_library.py` enforce these constraints
plus a non-blank render at 24 px.  Drop your new SVG into the
`icons/` directory and run:

```bash
python scripts/gen_facet_icons.py    # rasterises every SVG → PNG
python -m pytest tests/test_icon_library.py
```

Then:

1. Add the name to the `_ICON_RULES` table in
   `scriptree/shell/icon_assets.py` if any keywords should route
   to it automatically (don't add overly-generic keywords — those
   cause regressions in unrelated tools).
2. Add an entry to **§2** of this doc grouping the new icon under
   the most relevant category, with a one-line "use for" hint.
3. If a multi-leaf suite would benefit, add the new mapping to
   `scripts/refresh_app_icons.py::_OVERRIDES`.
4. Re-embed any catalogs that should adopt the new glyph.

### Trademark gate

Every new icon **must** be a generic archetype of the operation /
category, never a vendor's actual logo, wordmark, or distinctive
trade dress.  When in doubt: simplify further.  The leading XML
comment is part of the contract — `<!-- Generic <X> shape —
placeholder, not the <Vendor> trademark logo -->` reads as the
author's declaration that the glyph is intentionally generic.

---

## 7. Worked example — the ffmpeg / outlook / SolidWorks refresh

The current `scripts/refresh_app_icons.py::_OVERRIDES` table is the
canonical reference for "how to spread variety across a multi-leaf
suite."  Three patterns to copy:

* **Operation-by-operation** (ffmpeg):  every leaf takes the icon
  of *what it does to the video*, not "video, video, video"
  repeated.  `compress→archive, concat→link, convert→convert,
  crop→scissors, extract-audio→audio, extract-frames→image,
  gif→image, resize→ruler, rotate-flip→convert, speed→clock,
  subtitles→document, trim→scissors, volume→audio,
  watermark→image, ffprobe→search, ffmpeg-advanced→settings`.
  The parent `.scriptreetree` carries the category glyph
  (`video`).

* **Verb-keeps-the-meaning-distinct** (outlook migration): every
  leaf relates to email data, but the icon differentiates the
  *action* — `backup→archive, restore→download, inventory→search,
  transfer_pst→upload, transfer_autocomplete→key,
  merge_autocomplete→link`.  Parent tree carries `email`.

* **Vendor-identity-on-the-root-only** (SolidWorks toolkit): the
  toolkit's root `.scriptreetree` keeps the `solidworks` gear,
  but every leaf takes an operation glyph — `force-rebuild→convert,
  hide-all-but-selected→filter, suspend-rebuild→clock,
  visual-perf→chart, fix-blank-views→bug, set-hq→image,
  unshade-for-print→printer, dxf-cleanup→scissors,
  dxf-to-pdf→pdf, gfx-compat→chip, copy-sheets→package,
  checkpoint→pin, run-script→script, sync-hardware→convert`,
  …  The user reads the menu as "ah, the SolidWorks gear, with
  the wrench-replacing-component leaf — that one swaps a part."

Apply the same pattern to any new suite you wrap.
