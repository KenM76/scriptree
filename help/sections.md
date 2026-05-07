# Sections

Sections are named, collapsible groups of parameters. They're purely a
rendering hint — they don't affect the argv the tool is invoked with, but
they make large forms far easier to navigate.

## Why sections?

Once a tool has more than about six parameters, a flat form becomes
overwhelming. Sections let you group related parameters together:

```
▼ Input
    File:      [.............] [Browse]
    Encoding:  [utf-8      ▾]
▼ Output
    Format:    [json       ▾]
    Folder:    [.............] [Browse]
▶ Advanced (collapsed)
```

Each section is a collapsible group box in the runner, with its
collapsed/expanded state persisted per tool.

## Creating sections (editor)

In the tool editor, the parameter list has a small section toolbar at the
top: **+§ ✎§ −§**.

- **+§** — adds a new section. Prompts for a name.
- **✎§** — renames an existing section (pick which one from a dropdown).
- **−§** — deletes a section. Any parameters that were in it fall back to
  "no section" (empty string) and render under a synthetic "Other" group.

## Assigning parameters to sections

Select a parameter in the left pane and use the **Section** dropdown in
the property panel. The dropdown lists every section the tool has declared
plus "(none)". Change it to move the parameter between sections.

## Flat mode

A tool with zero declared sections renders as a flat form — exactly the
same as it did before sections existed. This is the v1 look and the
default for brand new tools.

As soon as you add the first section, the runner starts rendering the
form as a sequence of group boxes. Parameters whose section is empty
(i.e. pre-existing params that haven't been assigned yet) land in a
synthetic "Other" group at the bottom so nothing is lost.

## Reordering

In the runner, you can drag individual parameter rows up and down within
a section to rearrange them. The reorder is saved back to the `.scriptree`
file immediately.

You cannot drag a row from one section to another in the runner — that's
an editor-level change. Use the property panel's Section dropdown instead.

## On disk

A `.scriptree` file with sections looks like:

```json
{
  "schema_version": 2,
  "name": "my tool",
  "executable": "...",
  "params": [
    { "id": "in_file", "section": "Input",  ... },
    { "id": "encoding", "section": "Input",  ... },
    { "id": "out_file", "section": "Output", ... }
  ],
  "sections": [
    { "name": "Input",  "collapsed": false },
    { "name": "Output", "collapsed": false }
  ]
}
```

The `sections` array drives the *order* in which sections render and their
initial collapsed state. Each `ParamDef.section` field just names which
section it belongs to. A `.scriptree` without a `sections` array is v1 /
legacy flat mode and loads cleanly.
