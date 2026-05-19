# .scriptreering Format Specification

**Status:** DRAFT — 2026-05-04
**Owner:** shell-engineer
**Stability:** v1 — stable. Future schema additions are additive; old readers MUST ignore unknown fields.

---

## 1. Overview

A `.scriptreering` file captures either a **master-hexagon group** (the master window plus
all of its member hexagons) or a **single standalone hexagon**, so the cluster or individual
hex can be recreated in one operation.  The format is a single UTF-8 JSON file (no BOM,
2-space indent by convention).

The file is designed for hand-inspection and operator scripting. Field names are verbose and
self-documenting. Unknown fields are silently ignored; readers MUST NOT error on them.

**Single-hex ring** (standalone case): when a standalone hexagon is saved, the `master`
section describes the hex itself with an additional `"role": "standalone"` field, and
`members` is an empty array.  `load_ring()` detects this field and spawns one standalone
hex instead of a master.  Example:

```jsonc
{
  "format": "scriptreering",
  "version": 1,
  "saved_at": "2026-05-04T20:00:00Z",
  "saved_by_brand": "ScripTree",
  "master": {
    "role": "standalone",
    "shape": "hexagon",
    "orientation": "flat-top",
    "size_px": 56,
    "transparency": 0.85,
    "always_on_top": true,
    "position": { "x": 300, "y": 200 },
    "catalog_path": null
  },
  "members": []
}
```

The `"role"` field in the `master` section is optional; its absence or any value other than
`"standalone"` means the file is a normal master-ring file.

---

## 2. File Extension and Naming Convention

| Situation | Convention |
|-----------|-----------|
| Single saved group | `<descriptive-name>.scriptreering` |
| Default save directory | `<USERPROFILE>/Documents/<BRAND>/rings/` |
| Auto-load directory | Paths stored in `<APPDATA>/<BRAND>/autoload_rings.json` |

The extension `.scriptreering` is distinct from `.scriptreetree` (catalog) and `.scriptree`
(single-tool definition). Each extension has a unique MIME type in the application manifest.

---

## 3. Top-Level Schema

```jsonc
{
  "format": "scriptreering",           // string — always this literal value
  "version": 1,                        // integer — increment on breaking changes
  "saved_at": "2026-05-04T14:32:00Z", // ISO-8601 UTC timestamp
  "saved_by_brand": "ScripTree",       // appName at save time — informational only
  "master": { ... },                   // master-hexagon descriptor (see §4)
  "members": [ ... ]                   // array of member-hexagon descriptors (see §5)
}
```

| Field | Type | Required | Notes |
|-------|------|----------|-------|
| `format` | string | yes | Must be `"scriptreering"`. Readers detect the format via this field. |
| `version` | integer | yes | `1` for this version. Readers that do not know a version SHOULD warn and attempt to load anyway. |
| `saved_at` | string | yes | ISO-8601 timestamp (UTC preferred). Informational — not used for load decisions. |
| `saved_by_brand` | string | no | The `appName` value from `branding.config.json` at save time. Informational — NOT a load gate. A renamed build can load a ring saved under a different brand name without errors. |
| `master` | object | yes | Single master-hexagon descriptor. See §4. |
| `members` | array | yes | Zero or more member-hexagon descriptors. See §5. Minimum 0 (a ring with no members loads just the master). |

---

## 4. Master-Hexagon Descriptor

```jsonc
{
  "shape": "hexagon",
  "orientation": "flat-top",
  "size_px": 56,
  "transparency": 0.85,
  "always_on_top": true,
  "position": { "x": 700, "y": 100 }
}
```

| Field | Type | Required | Notes |
|-------|------|----------|-------|
| `shape` | string | yes | `"hexagon"` or `"square"`. Passed to `compute_polygon()`. |
| `orientation` | string | yes | `"flat-top"` or `"pointy-top"`. Ignored for `"square"`. |
| `size_px` | integer | yes | Widget logical size in pixels. Valid range 32–96 (clamped at load). |
| `transparency` | number | yes | Fill alpha multiplier. Valid range 0.30–1.00 (clamped at load). |
| `always_on_top` | boolean | yes | Whether the window carries `Qt.WindowStaysOnTopHint`. |
| `position` | object | yes | Saved screen coordinates at save time. Keys: `"x"` (int), `"y"` (int). Clamped at load (see §7). |

---

## 5. Member-Hexagon Descriptor

A member descriptor extends the master descriptor with two additional fields.

```jsonc
{
  "shape": "hexagon",
  "orientation": "flat-top",
  "size_px": 56,
  "transparency": 0.85,
  "always_on_top": true,
  "position": { "x": 250, "y": 200 },
  "preferred_position": { "x": 250, "y": 200 },
  "catalog_path": "sample-catalog/system.scriptreetree",
  "is_positioned": true
}
```

All fields from §4 apply plus:

| Field | Type | Required | Notes |
|-------|------|----------|-------|
| `preferred_position` | object | yes | The position stored in `master._members[member_id]` — the target used by collapse/expand. Keys: `"x"` (int), `"y"` (int). Clamped at load (see §7). |
| `catalog_path` | string | no | Path to the `.scriptreetree` or `.scriptree` file bound to this member. `null` or absent = use default/sample catalog. Resolution order: (1) absolute path as-is, (2) relative path resolved against project root, (3) relative path resolved against `<APPDATA>/<BRAND>/catalogs/`. Absent or `null` if no catalog is bound. |
| `is_positioned` | boolean | yes | `true` = member was inside the contiguous honeycomb cluster (in `master._positioned`) at save time. `false` = member was separated (in `master._members` but not in `master._positioned`). Used to correctly rebuild `_positioned` on load. |

---

## 6. Per-Hex Field Details

### 6.1 `shape`

Valid values: `"hexagon"`, `"square"`. Unknown values MUST be replaced with `"hexagon"` at load
time and a warning logged. The field maps directly to `CellWindow._shape`.

### 6.2 `orientation`

Valid values: `"flat-top"`, `"pointy-top"`. Invalid values MUST be replaced with `"flat-top"`.
Ignored when `shape == "square"`.

### 6.3 `size_px`

Clamped to `[32, 96]` at load. Values outside this range are silently clamped without error.

### 6.4 `transparency`

Clamped to `[0.30, 1.00]` at load. Values outside this range are silently clamped.

### 6.5 `always_on_top`

Boolean. Any non-boolean value (e.g. `"true"` string from hand-editing) is coerced via
`_coerce_bool()` using the same rules as QSettings values.

### 6.6 `position` and `preferred_position`

Both use `{ "x": <int>, "y": <int> }`. At load time ALL positions are clamped to the
nearest available screen geometry (see §7). If a key is missing or null, the position
defaults to `(100, 100)`.

### 6.7 `catalog_path`

Resolution order:
1. If the value is an absolute path and the file exists on disk, use it as-is.
2. If the value is a relative path, resolve it against the project root (the directory
   containing `branding/branding.config.json`, located by walking up from `apps/shell/`).
   If the resolved file exists, use it.
3. If step 2 fails, resolve against `<APPDATA>/<BRAND>/catalogs/`. If the resolved file
   exists, use it.
4. If all three steps fail, log a warning and treat as `null` (no catalog bound).

A `null` or absent `catalog_path` is valid and means: use the default/sample catalog.

---

## 7. Position Clamping at Load Time

All `position` and `preferred_position` values undergo clamping at load time. The algorithm
is applied independently to each position.

**Algorithm:**

```python
def _clamp_position(x: int, y: int, size_px: int) -> tuple[int, int]:
    from PySide6.QtCore import QPoint
    from PySide6.QtGui import QGuiApplication

    pt = QPoint(x + size_px // 2, y + size_px // 2)  # test the centre point
    screen = QGuiApplication.screenAt(pt)
    if screen is None:
        screen = QGuiApplication.primaryScreen()
    if screen is None:
        return (max(0, x), max(0, y))

    avail = screen.availableGeometry()
    clamped_x = max(avail.left(), min(x, avail.right() - size_px))
    clamped_y = max(avail.top(), min(y, avail.bottom() - size_px))
    return (clamped_x, clamped_y)
```

**Rules:**
- The centre point of the widget (`x + size_px // 2`, `y + size_px // 2`) is used to
  identify which screen the widget nominally belongs to.
- `QGuiApplication.screenAt()` returns `None` if the centre is off all monitors. In that
  case, fall back to the primary screen.
- The top-left `(x, y)` is clamped so the entire widget fits within `availableGeometry()`
  (which excludes taskbar and other reserved areas).
- **Relative offset preservation:** the master's clamped position is computed first. Each
  member's `position` clamp is independent. For `preferred_position`, the same clamping
  is applied. The intent is that if a ring was saved on a multi-monitor setup and is
  loaded on a single-monitor machine, every hex appears on the primary screen rather than
  off-screen, even if the relative layout is lost.

---

## 8. Autoload Configuration

Auto-load is implemented as a JSON file per scope:

| Scope | Config file location |
|-------|---------------------|
| `user` | `<APPDATA>/<BRAND>/autoload_rings.json` |
| `system` | `<PROGRAMDATA>/<BRAND>/autoload_rings.json` |

`<BRAND>` is the runtime value of `branding.appName` (not the save-time `saved_by_brand`).

**Config file format:**

```json
{
  "format": "scriptreering-autoload",
  "version": 1,
  "rings": [
    "C:/Users/Example/Documents/ScripTree/rings/dev-tools.scriptreering",
    "C:/Users/Example/Documents/ScripTree/rings/build-tools.scriptreering"
  ]
}
```

Entries are absolute paths. Relative paths are resolved against the config file's directory.
Entries whose files no longer exist are skipped at load time with a warning; they are NOT
automatically removed from the config file (preserves intent across removable media etc.).

---

## 9. Windows Autostart Registration

When auto-load is enabled via the "For current user only" or "For all users" menu items,
the application also registers a Windows Run-key entry so the shell launches at login.

| Scope | Registry hive | Subkey |
|-------|--------------|--------|
| `user` | `HKEY_CURRENT_USER` | `Software\Microsoft\Windows\CurrentVersion\Run` |
| `system` | `HKEY_LOCAL_MACHINE` | `Software\Microsoft\Windows\CurrentVersion\Run` |

**Value name:** `branding.appName` (e.g. `"ScripTree"`).
**Value data:** `"<sys.executable>" -m apps.shell.main --autoload-rings`

The `system` scope requires administrator elevation. If the calling process is not elevated,
the application relaunches the command via `ShellExecuteEx` with verb `"runas"` to trigger
a UAC prompt. The elevated process runs `--register-autostart-system <ring-path>` and exits.

**Uninstall responsibility:** removing the autostart entry requires calling
`remove_autoload_ring(path, scope)`. Simply deleting the `.scriptreering` file does NOT
remove the Run-key entry. See §12 for the risk note.

---

## 10. Backward Compatibility

1. **Unknown top-level keys** are silently ignored. A reader for version 1 MUST NOT fail
   when it encounters a key added in a future version.
2. **Unknown `shape` values** are coerced to `"hexagon"`.
3. **Unknown `orientation` values** are coerced to `"flat-top"`.
4. **`saved_by_brand` mismatch** is NOT a load error — it is informational only.
5. **`version > 1`:** readers SHOULD attempt to load and log a warning that the file
   was saved with a newer version. A load failure from an unknown-version file MUST
   surface a clear error to the user, not a silent no-op.
6. **Missing optional fields** (e.g. `catalog_path` absent) fall back to the defaults
   documented in §5 and §6.

---

## 11. Complete Example (2-member group, all fields)

```jsonc
{
  "format": "scriptreering",
  "version": 1,
  "saved_at": "2026-05-04T14:32:00Z",
  "saved_by_brand": "ScripTree",
  "master": {
    "shape": "hexagon",
    "orientation": "flat-top",
    "size_px": 56,
    "transparency": 0.85,
    "always_on_top": true,
    "position": { "x": 700, "y": 100 }
  },
  "members": [
    {
      "shape": "hexagon",
      "orientation": "flat-top",
      "size_px": 56,
      "transparency": 0.85,
      "always_on_top": true,
      "position": { "x": 250, "y": 200 },
      "preferred_position": { "x": 250, "y": 200 },
      "catalog_path": "sample-catalog/system.scriptreetree",
      "is_positioned": true
    },
    {
      "shape": "hexagon",
      "orientation": "flat-top",
      "size_px": 56,
      "transparency": 0.85,
      "always_on_top": true,
      "position": { "x": 450, "y": 200 },
      "preferred_position": { "x": 450, "y": 200 },
      "catalog_path": null,
      "is_positioned": true
    }
  ]
}
```

---

## 12. What This Means for End Users

- **To save a group:** right-click the master hexagon → "Save group as ring…". A file
  dialog opens to a sensible default directory. Saving creates a `.scriptreering` file you
  can rename and share.
- **To save a standalone hex:** right-click the standalone hexagon → "Save as ring…".
  Creates a single-hex ring file.  The hex's position and catalog binding are saved.
- **To load a group or single-hex ring:** right-click any hexagon → "Load ring…". The
  loaded master (or standalone) and any members appear at their saved positions (adjusted for
  the current monitor layout).
- **To restore on login:** right-click any hexagon (master or standalone) → "Auto-load on
  startup" → choose "For current user only" (no admin required) or "For all users" (requires
  admin UAC prompt). A Windows Run-key entry is added so the application launches
  automatically. The ring is re-loaded from the saved file path.

**Risk:** if you move or rename the `.scriptreering` file after enabling auto-load, the
auto-load config still points to the old path. Update the config by disabling and
re-enabling auto-load after moving the file. Uninstalling the application does NOT
automatically remove the Run-key entry — the user must manually remove it via
"Auto-load on startup → Disabled" before uninstalling, or delete the Run-key entry in
`regedit.exe` under `HKCU\Software\Microsoft\Windows\CurrentVersion\Run`.

---

## 13. What This Means for Tool Authors / Operators

- **Catalog paths in rings** are resolved relative to the project root first. Operators
  deploying ScripTree in a fixed directory can use relative `catalog_path` values that
  survive relocation within the same drive root. Absolute paths are preserved as-is.
- **The ring file is self-contained metadata** — it does not embed catalog content.
  Moving a ring file without moving its referenced catalogs will cause the catalog
  resolution to fall back to the user's catalog directory or emit a warning.
- **System-scope autoload** (`"For all users"`) writes to `HKEY_LOCAL_MACHINE`. It
  requires administrator rights and affects every user who logs into the machine. Use
  with caution in multi-user environments.
- **Ring files are safe to check into version control** — they contain only window
  positions and catalog paths (no secrets, no user-identifiable data beyond filesystem
  paths which operators should review).

---

## 14. Cell appearance — what lives where (v0.2.7+)

A `.scriptreering` file is purely a **layout** record: positions,
sizes, transparency, shapes, and which catalog each cell points at.

**Cell appearance — icon, text label, scale, opacity — does NOT live
in this file.** It lives in the bound catalog (`.scriptree` /
`.scriptreetree`) under a top-level `cell` sub-object. See
[`scriptree_format.md`](scriptree_format.md) and
[`scriptreetree_format.md`](scriptreetree_format.md) → "`cell`
sub-object".

This split has two benefits:

1. **Catalog-portable visuals.** Embedding an icon into a catalog
   means anyone who opens that catalog (in any ring, on any machine)
   sees the same label. Storing it on the ring would mean every ring
   that loads the catalog needs a fresh copy.
2. **Layout decoupled from identity.** A user can save many
   `.scriptreering` files referencing the same catalog without
   duplicating its label data, and rebranding the catalog updates
   every ring instantly.

When a cell is rendered from a `.scriptreering`, the loader reads
position/size/transparency from this file but defers icon/text/scale/
opacity entirely to the catalog's `cell` sub-object. If the catalog
omits the sub-object, the cell uses defaults (auto-derived letters,
scale 1.00, opacity 1.00) — identical to the legacy behaviour.

## 15. Version History

| Version | Date | Summary |
|---------|------|---------|
| v1 DRAFT | 2026-05-04 | Initial format. Master + members, position clamping, autoload config, Windows Run-key registration. |
| v1.1     | 2026-05-04 | Standalone-hex ring support: `master.role = "standalone"` + empty members list. No version bump (additive/backward-compatible). Save as ring + Auto-load on startup added to standalone right-click menu. Double-right-click opens composite editor for all hex roles. |
| v1.2     | 2026-05-07 | Cell appearance (icon / text / scale / opacity) promoted to the **catalog** JSON (`.scriptree` / `.scriptreetree`) as a top-level `cell` sub-object. Ring files do not carry icon/scale/opacity — they reference catalogs via `catalog_path` and inherit the cell's appearance from there. No format change here; this is a documentation note. |
