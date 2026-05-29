# Host-Software Facet Icon Style — LLM Authoring Guide

**The monochrome line-icon system for host-software / category facets**
(SolidWorks, Microsoft Office, AutoCAD, Inventor, Revit, Command Line, …).
Portable, brand-neutral, hand-off ready. This one file *is* the package.

The transferable asset is the *style mechanics* (a `currentColor`,
fixed-stroke, trademark-safe line glyph on a 48 grid). The specific
metaphors are an example set — extend with the same rules.

---

## 0. How to hand this off

1. **As a doc** — drop this file into the target program's repo
   (`docs/guides/host-software-icon-style.md` or `ICON_STYLE.md`).
2. **As an LLM system-prompt fragment** — paste §8 ("LLM Operating
   Contract") into the other program's icon-generating agent. It is
   standalone imperative rules + a copy-paste SVG template.
3. **As a generator/reviewer rubric** — §3/§4 + §9 (anti-patterns) are
   exact enough to drive or check a generator deterministically.

No fonts, no raster assets, no color values, no dependencies — every
icon is a tiny hand-writable SVG that inherits its color from context.

---

## 1. What these icons are (and are not)

Each is a small, **single-color outline glyph** that tags *which host
software a marketplace app integrates with* (or a capability category
like "Command Line"). It renders as a calm line mark inside a neutral
rounded chip, with the software name beneath it.

**Critical scope boundary:** the SVG is **only the glyph**. The chip
background, padding, the text label, and the card are supplied by the
*surrounding component* — never by the SVG. An icon file contains a
transparent, color-inheriting line drawing and nothing else. Do not bake
a background, a fill, a label, or a brand color into the SVG.

These are deliberately **generic category metaphors**, never a vendor's
real logo (see §5 — this is a hard legal rule, not a stylistic one).

---

## 2. The invariant skeleton (never changes)

Every icon is exactly this shape:

```
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 48 48" fill="none" aria-hidden="true">
  <!-- Generic <category> shape — placeholder, not the <Vendor> trademark logo -->
  …1–4 stroke-only elements…
</svg>
```

Fixed forever:

- **Canvas:** `viewBox="0 0 48 48"`. Author on the 48 grid. No
  `width`/`height` attrs — it scales to its container.
- **`fill="none"`** on the root; every element is **stroke-only**.
- **`stroke="currentColor"`** on every element — never a hex, never a
  named color. The icon inherits the surrounding text color (free
  light/dark theming, zero variants). (§7)
- **`stroke-width="2.5"`** — the canonical weight. A *secondary, nested*
  detail may drop to `2` for hierarchy (e.g. an inner door inside an
  outer building); never go below 2 or above 2.5.
- **`stroke-linecap="round"`** on open paths;
  **`stroke-linejoin="round"`** on closed/cornered shapes. Round always.
- **`aria-hidden="true"`** — the visible software-name label is the
  accessible text; the glyph is decorative. (Standalone use: §7.)
- **A mandatory leading XML comment** stating the shape is generic and
  **not** the vendor trademark. This comment is part of the spec (§5).

If a proposed icon doesn't fit this skeleton, fix the icon — not the
skeleton.

---

## 3. Geometry & composition rules

- **1–4 elements.** `rect`, `circle`, and `path` only. Low count is the
  style — if it needs more than ~4 primitives, the metaphor is too
  literal; simplify it.
- **Generous inset.** Live content sits roughly in the **4 → 44** band
  of the 48 grid (≈ 8% margin). Nothing touches the edge.
- **Centered & balanced.** The composition is visually centered in the
  48 box; symmetric where the metaphor allows.
- **Soft, small corners.** Rounded-rect radii are small (`rx="1"` to
  `"3"`) — softened, never pill-shaped.
- **Reads at chip size.** The glyph is shown ~24–28px inside a ~40px
  chip. Validate every icon shrunk to ~24px: outline still legible, no
  detail collapses. If it muddies, remove detail.
- **Stroke weight is the texture.** Consistent 2.5 across the whole set
  is what makes six different shapes feel like one family. Do not vary
  it per icon for "balance" — vary the geometry instead.

---

## 4. The reference set (study these, then match them)

The shipped set — the canonical examples of the style. Each is a
*category archetype*, not a product portrait:

| Facet | Metaphor | Primitives |
|-------|----------|------------|
| SolidWorks | a **gear** (mechanical CAD) | `circle` hub + 8 spoke `path` lines |
| Microsoft Office | a **2×2 grid** (an app/office suite) | 4 rounded `rect`s |
| AutoCAD | a **triangle + crossbar** (2D drafting / T-square) | a triangle `path` + one rule `path` |
| Inventor | an **isometric box with edges** (3D modeling) | hex outline `path` + interior edges `path` |
| Revit | a **building with roof + windows** (BIM) | body `rect` + roofline `path` + mullions `path` + door `rect` |
| Command Line | a **terminal window with `›` prompt + line** | window `rect` + chevron `path` + prompt-line `path` |

The rule the set encodes: **map software → its functional *category* →
an archetypal everyday object for that category.** Mechanical CAD → gear.
Office suite → grid of tiles. 2D drafting → drafting triangle. 3D/solid
modeling → isometric box. BIM/architecture → building. Shell/automation
→ terminal. Pick the most universally-recognized object for the category,
not a clever or product-specific reference.

---

## 5. The trademark-safe rule (hard requirement, not a preference)

Every icon **must** be a *generic* representation of the software
category and **must never** reproduce, approximate, or evoke the
vendor's actual logo, wordmark, or trade dress.

- Mandatory leading SVG comment:
  `<!-- Generic <category> shape — placeholder, not the <Vendor> trademark logo -->`
  (for non-vendor categories: `<!-- … generic, no trademark risk -->`).
- No vendor color, no logo silhouette, no stylized initial, no
  distinctive product mark. A gear is fine for a CAD tool; the CAD
  vendor's actual emblem is not.
- This protects the marketplace legally (a store displaying many
  third-party-integrated products must not imply endorsement or infringe
  marks). Treat it as a release gate: an icon that looks like the real
  logo is a defect, however polished.

When in doubt, make it *more* generic.

---

## 6. Worked template (copy, fill 2 fields)

```
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 48 48" fill="none" aria-hidden="true">
  <!-- Generic CATEGORY shape — placeholder, not the VENDOR trademark logo -->
  <path d="…" stroke="currentColor" stroke-width="2.5" stroke-linejoin="round"/>
  <path d="…" stroke="currentColor" stroke-width="2.5" stroke-linecap="round"/>
</svg>
```

Fill `CATEGORY`/`VENDOR` in the comment and the 1–4 stroke elements.
Use `stroke-linejoin="round"` on closed/cornered shapes, `linecap`
`round` on open strokes. Keep within the 4→44 band. No `fill`, no color,
no background, no `width`/`height`.

Real example (Command Line):

```
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 48 48" fill="none" aria-hidden="true">
  <!-- Terminal/CLI prompt shape — generic, no trademark risk -->
  <rect x="4" y="8" width="40" height="32" rx="3" stroke="currentColor" stroke-width="2.5"/>
  <path d="M12 20l6 4-6 4" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"/>
  <path d="M24 28h12" stroke="currentColor" stroke-width="2.5" stroke-linecap="round"/>
</svg>
```

---

## 7. Color, theming, accessibility

- **`currentColor` is the whole theming strategy.** The icon takes the
  CSS `color` of its context — dark glyph on a light chip in light mode,
  light glyph on a dark chip in dark mode — with **no per-theme files**.
  Never hardcode a stroke color "to be safe"; that breaks theming.
- **Contrast is the container's job**, not the icon's. The chip provides
  the background and ensures glyph/chip contrast; the SVG just draws.
- `aria-hidden="true"` because the software name is shown as text beside
  it. If an icon is ever used *with no adjacent label*, drop
  `aria-hidden` and add `<title>SoftwareName</title>` as the first child.
- No shipped fonts, no images, no external refs — it renders anywhere
  SVG does, at any size, in any color, offline.

---

## 8. LLM Operating Contract (paste into another program's system prompt)

> **Host-software / category facet icons.** Emit each as a standalone
> SVG: `viewBox="0 0 48 48"`, `fill="none"`, `aria-hidden="true"`, a
> leading comment `<!-- Generic <category> shape — placeholder, not the
> <Vendor> trademark logo -->`, then **1–4 stroke-only elements**
> (`rect`/`circle`/`path`). Every element: `stroke="currentColor"`
> (NEVER a literal/hex/named color), `stroke-width="2.5"` (a nested
> secondary detail may use `2`; never other values), round
> `stroke-linecap`/`stroke-linejoin`. Content stays within the 4→44
> band of the 48 grid, centered, balanced; rounded-rect radii 1–3. The
> glyph is a **generic archetype of the software's functional category**
> (mechanical-CAD→gear, office-suite→2×2 grid, 2D-drafting→triangle/
> T-square, 3D-modeling→isometric box, BIM→building, shell→terminal) and
> must **never** resemble the vendor's real logo/wordmark/trade dress —
> when unsure, make it more generic. The SVG contains ONLY the glyph: no
> background, no fill, no label, no color, no `width`/`height` — the
> surrounding component supplies the chip and the text label. Must read
> at ~24px. One stroke weight across the whole set is what makes
> different shapes one family — vary geometry, never the weight.

---

## 9. Anti-patterns (reject in review)

- ✗ A literal/hex/named stroke color instead of `currentColor`
  (breaks theming).
- ✗ Any `fill` on a shape, or a background rect — these are line glyphs.
- ✗ The vendor's real logo, wordmark, brand color, or a near-copy
  (legal defect — §5).
- ✗ Missing the "generic … not the trademark" comment.
- ✗ Stroke width other than 2.5 (or 2 for a single nested detail).
- ✗ Square/miter caps & joins (must be round).
- ✗ >4 primitives / fine detail that dies at ~24px / photographic or
  filled-icon styles.
- ✗ A label, chip, or padding baked into the SVG.
- ✗ `width`/`height` hardcoded on the `<svg>` (breaks responsive sizing).
- ✗ Edge-touching geometry (keep the ~4px inset).

---

## 10. Extending the set / another program

- The **skeleton + the category-archetype + trademark-safe rules are the
  asset**; the six metaphors are just examples. A new program keeps
  §2/§3/§5 verbatim and adds glyphs for its own categories under §4's
  "software → category → archetypal object" rule.
- **One archetype per category, fixed program-wide** before you
  generate — so the 30th facet still agrees with the 1st (e.g. *every*
  spreadsheet-class tool gets the grid; don't reinvent per product).
- New glyphs must pass: 1–4 primitives, `currentColor`, 2.5 stroke,
  round caps, readable at 24px, demonstrably not the real logo. If a
  metaphor can't be done that simply, pick a more universal object.
- Keep this style strictly separate from any *colored* product-tile
  iconography: those are filled gradient squares; these are bare
  `currentColor` line glyphs. Never mix the two rule sets in one file.

The discipline, not the specific shapes: *one 48-grid line glyph,
single inherited color, fixed round 2.5 stroke, a generic category
archetype that is provably not the trademark, glyph-only (no chrome).*
Hold that and any number of facet icons stay one coherent, legally-safe
family across authors and programs.

---

*End of guide. This file is the deliverable — copy it as-is to reuse the
style elsewhere.*
