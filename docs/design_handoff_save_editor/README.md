# Handoff: VaultKeeper Save Game Editor UI

## Overview
A desktop save-game editor for **Neverwinter Nights: Enhanced Edition**, designed to live inside the
existing VaultKeeper Python/Qt application (`Tools → Save Game Viewer`, extended into a full editor).

The UI lets a player open a `.sav` / `.bic` save, inspect and edit the player character, inventory,
spellbook, companions, quest/world variables, party state and area contents, review every pending
change in one ledger, and commit either as a **new save** or as an **in-place overwrite** with an
automatic timestamped backup. Nothing is written until the user commits; every edit is staged.

The design's organising idea: **the app mirrors the in-game character sheet** so players recognise it,
but wraps it in a staging/ledger safety layer that no in-game screen has, because a save edit spans
multiple binary files (`module.ifo`, `player.bic`, area `.git` files) and can corrupt a save.

## About the Design Files
The file in this bundle (`VaultKeeper Save Editor - Nav Options.dc.html`) is a **design reference
created in HTML** — an interactive prototype showing intended look, layout and behavior. It is **not
production code to port**. Do not attempt to translate the HTML/JS into the app.

The task is to **recreate these designs in VaultKeeper's existing environment**: Python + Qt
(PySide/PyQt), following the codebase's established widget patterns, theming (`theme.py` and the
existing dialog/view conventions under `src/vaultkeeper/`) and its test conventions
(see `tests/test_save_editor.py`, `test_character_viewer.py`, `test_inventory_view.py`,
`test_contents_view.py`). Colors and typography below are targets to approximate with Qt
stylesheets/palettes, not literal CSS to inject.

## Fidelity
**High-fidelity.** Final layout, hierarchy, copy, colors, typography, interaction states and flows.
Recreate the structure and visual weight faithfully. Where Qt's native controls differ from the
prototype's custom widgets, prefer the native control that carries the same meaning over a
pixel-exact reproduction.

## Global Shell

Window: 1400 × 900 reference size (resizable; sidebar fixed, content scrolls).
Background `oklch(0.14 0.012 55)` (near-black warm brown), text `oklch(0.94 0.006 60)`.

**Top toolbar** — 52px tall, background `oklch(0.16 0.012 55)`, 1px bottom border `rgba(255,255,255,.08)`:
- Wordmark `VAULTKEEPER`, 700 15px Cinzel serif, color gold `oklch(0.78 0.12 82)`, letter-spacing .04em
- Vertical 1px divider, then the open save's name + path
- **Open Save…** (ghost button) — opens the file picker dialog
- **Rule mode segmented control**: `Strict` / `Free` (see Interactions)
- **Undo** / **Redo** ghost buttons — dim + disabled when the ledger has nothing to undo/redo
- **Edit** pill toggle — label becomes `Editing ✓` and turns gold when on
- **Save as New…** (gold primary), **Overwrite…** (ghost). Both inert unless Edit is on.

**Left sidebar** — 236px fixed, background `oklch(0.155 0.012 55)`, right border `rgba(255,255,255,.08)`,
padding 14px 12px, 14px gaps, scrolls:
- `OPEN SAVES` cap-label section listing loaded saves as 30px thumbnail + name + meta rows.
  Active row: background `oklch(0.3 0.05 82 / 0.15)`, border `oklch(0.6 0.09 82 / 0.4)`, radius 8.
  Inactive rows at opacity .55.
- `SECTIONS` nav list, then an `ADVANCED` group. Each row: 24px square icon chip
  (`oklch(0.28 0.02 55)` bg, gold 700 9.5px 2-letter code), 500 12.5px label, and a 6px gold dot
  when that section has unsaved changes. Active row uses the same gold-tinted treatment as above.
- Nav order: Character (CH), Inventory & Equipment (IE), Spellbook (SP), Companions (CO),
  Quests & World State (QW), Party & Campaign (PC) · then ADVANCED: Area Contents (AC),
  Raw GFF (GF), Backups & Diff (BD).

**Content area** — flex 1, scrolls. Each screen has a title row, an optional tab strip
(11px 16px tabs, 2px gold bottom border when active), and collapsible sections.

**Pending-changes footer** — only visible when Edit is on. `flex:none`, top border
`rgba(255,255,255,.1)`, background `oklch(0.16 0.012 55)`, padding 10px 20px:
`PENDING CHANGES (n)` cap-label, up to 3 sample change chips, and a **Review all** button that
opens the ledger slide-over.

## Screens / Views

### 1. Character (CH)
**Purpose:** edit the core character record — the fields the spec calls *Details*.
**Layout:** tab strip (`Sheet`, `Abilities & Saves`, `Skills`, `Feats`, `Effects`), then content.
- **Sheet tab:** a skinned "character sheet" card — flex row, gap 20, radius 12, padding 18,
  background/border from the active skin (default *Leather*:
  `linear-gradient(160deg, oklch(0.26 0.045 75), oklch(0.15 0.03 65))`, border
  `oklch(0.58 0.09 75 / 0.55)`, accent text `#ddd0b8`). 180×240 portrait slot on the left
  (diagonal-hatch placeholder), stat stack on the right: race/alignment line, name, class & level,
  XP, gold, HP, age.
  **Skin switcher:** four 22px circular swatches (Leather / Crimson / Steel / Verdant) with a 2px
  gold ring on the active one. Skins are a cosmetic preference only — they never change data.
  Other skins: Crimson `oklch(0.22 0.06 25)→oklch(0.13 0.03 20)`, accent `#e3c8ba`;
  Steel `oklch(0.24 0.02 250)→oklch(0.14 0.02 250)`, accent `#c9d3de`;
  Verdant `oklch(0.24 0.05 150)→oklch(0.14 0.03 150)`, accent `#cfe0cf`.
- **Abilities & Saves:** six ability steppers (STR/DEX/CON/INT/WIS/CHA) with derived modifier shown
  read-only beside each; alignment dual sliders (Good–Evil, Lawful–Chaotic, 0–100) whose numeric value
  resolves to a word pair ("Lawful Good"); a combat block (`oklch(0.185 0.014 55)` panel, radius 10)
  showing **read-only derived stats**: Base Attack, Initiative, AC, saving throws — each with its
  source in small text beneath ("BAB 14 (Paladin)", "+3 Dex").
- **Skills:** searchable table of skills, rank steppers, class/cross-class marker.
- **Feats:** two-pane. Left = current feats list with a search box and per-row `×` remove;
  `Add a feat…` opens a browsable **ID + Name** table filtering on name *or* raw id.
  Right = detail pane for the selected feat (name, `Feat code NNNN` in mono, description).
  PRC feats carry a `(PRC)` badge — 700 8.5px, color `oklch(0.78 0.14 70)`, 1px border at .5 alpha,
  radius 4 — and their detail pane shows a warning that PRC regenerates them from its own data on
  rest / level-up / area-load, so the edit may not stick in-game.
- **Effects:** read-only list of active effects, with the note "the engine derives these from equipped
  items, active feats and ongoing spells."

### 2. Inventory & Equipment (IE)
**Purpose:** equipped slots, carried bag, and per-item magical properties.
**Layout:** left column (paper-doll + bag), right detail panel 300px fixed
(`oklch(0.16 0.012 55)`, radius 10).
- **Equipment slots:** 62×62 squares, radius 8. Empty = dashed border + slot label; filled = solid
  `oklch(0.6 0.09 82 / 0.5)` border + item code; selected = solid gold border. Tooltip = item name.
- **Carried:** grid of the same 62px cells, sparsely filled.
- **Item detail panel:** item name, base type, then the **properties list** (`oklch(0.185 0.014 55)`
  panel, radius 10). Each property row shows type, subtype and value. In edit mode each row gets a
  `×` remove and an `Edit…`; **every field is a dropdown or searchable picker populated from the
  game's `iprp_*` tables**, so an edit cannot produce a value the engine doesn't recognise.
  Cast-Spell properties additionally expose uses/day. Changing a property *type* is not supported —
  remove and add.
- `Add a property…` opens a searchable catalog (Ability/AC/Attack/Enhancement/Skill bonus, saving
  throws, regeneration, and flags: Haste, Keen, True Seeing, Freedom of Movement, Improved Evasion,
  Darkvision) → pick subtype → pick magnitude. Newly added properties render in gold with a ● marker
  until committed.
- **Important:** the detail panel is *swappable per context*. An item selected in a store, creature or
  container renders a different panel whose primary action is **Add a copy to my inventory** (no
  property editing). Once copied, the button is replaced by a gold `● Copy added to inventory`
  confirmation. Do not share one panel across contexts — cross-context edits must be impossible.

### 3. Spellbook (SP)
**Purpose:** known and memorized spells per caster class and level.
**Layout:** caster-class selector → level selector → two-pane prepared list / add-spell catalog.
- Prepared list rows: spell name, level, `×` remove in edit mode. Empty state: "No spells prepared…".
- `Add a spell…` uses the same searchable ID + Name picker pattern as feats, with a `Done` button
  to close it.
- PRC prestige-class spellbooks are flagged `(PRC)` with the same badge and the same
  "may not stick in-game" warning.

### 4. Companions (CO)
**Purpose:** edit henchmen, familiars and summons alongside the PC.
**Layout:** left list of companions (name, kind, class & level), right detail with HP, XP, faction,
tag (mono) and a notes line. Familiars/summons warn that the engine may respawn them on rest.
Each companion has its own inventory and spellbook, reached through the same IE/SP screens scoped to
that creature.

### 5. Quests & World State (QW)
**Purpose:** journal entries and module variables.
**Layout:** tabs (`Journal` / `Variables`). Journal = quest list with state/entry id.
Variables = scope selector (module / area / player) + search box + typed rows
(boolean, int, float, string) with type-appropriate editors.

### 6. Party & Campaign (PC)
**Purpose:** party gold, campaign-level state, module + area the save resides in.

### 7. Area Contents (AC) — Advanced
**Purpose:** browse an area's placeables, creatures, stores and containers, and edit store pricing.
- Tree: area → Stores / Creatures / Containers → items.
- **Edit Store…** exposes buy markup, sell-back markdown, store gold, identify price, max buy price,
  and the black-market flag.
- Any item found here offers **Add a copy to my inventory**.

### 8. Raw GFF (GF) — Advanced
**Purpose:** escape hatch. Tree of the raw GFF structure with node path, field type and value.
Read-mostly; edits here bypass the friendly editors and are marked as raw in the ledger.

### 9. Backups & Diff (BD) — Advanced
**Purpose:** list backups under `…/Neverwinter Nights/vaultkeeper_backups/`, restore one, and diff a
backup against the current save field-by-field.

## Dialogs & Overlays

### Open Save dialog (680px)
List of discovered saves with name, module, timestamp, size and a **state**: normal, `readonly`,
or `corrupt`. Primary button label follows state — `Open` / `Open read-only`; **disabled for
corrupt**. Search field filters the list.

### Change ledger (slide-over from the right)
Every staged change as a row: section, field, `old → new`, and per-row **Discard** / **Undo**.
- **Undone changes stay visible but struck through** and are excluded from the write count — the user
  must be able to see what they backed out of.
- Footer: `Discard all` (ghost, disabled when empty) and a gold **Save** that jumps straight to the
  overwrite dialog.

### Save dialog (560px)
Two modes driven by one `saveMode` state: `new` and `overwrite`.
- Title/subtitle swap: "Save as a new file — The original file is left untouched." vs
  "Overwrite this save — <name>.sav will be rewritten in place."
- `WRITING` cap-label + key/value list: **Changes to write**, **Undone (not written)** (dimmed at 0),
  **Rule mode** ("Strict — derived values recomputed" / "Free — raw values written as entered"),
  **Target** filename in mono.
- New-save mode adds a **NEW FILE NAME** mono text input.
- Checkbox: *Back up the current file first (recommended)*, checked by default. When checked in
  overwrite mode, it reveals the resolved backup path in mono
  (`…/Neverwinter Nights/vaultkeeper_backups/<timestamp>/<save>.sav`) plus the guarantee: the edited
  save is written and byte-verified in a staging folder before the old one is moved there, so a
  failed write never touches the original.
- Unchecking it in overwrite mode shows: "Without a backup this overwrite cannot be undone from
  inside VaultKeeper."
- Free mode shows a red-tinted warning block (`oklch(0.28 0.06 25 / 0.18)` bg, border
  `oklch(0.6 0.14 25 / 0.45)`, radius 9): values that break D&D rules are written exactly as entered
  and the game may clamp or reject them on load.
- Footer: `Review changes` (returns to the ledger), `Cancel`, and gold
  `Write new file` / `Overwrite save` — disabled when there is nothing to write.

## Interactions & Behavior

- **Edit mode is a global gate.** With Edit off the app is a viewer: no steppers, no `×` buttons, no
  `Add…` actions, no pending footer, and Save/Overwrite are inert. Turning Edit off with staged
  changes must prompt before discarding.
- **Nothing writes until commit.** Every edit stages into the ledger; the touched thing gets a ● marker
  and its sidebar section gets a gold dot.
- **Strict vs Free rule mode** cascades through the app:
  - *Strict* (default): rule violations are blocked at the input; derived values are recomputed by the
    engine; the raw AC override is locked.
  - *Free*: violations are allowed and written verbatim; the raw AC override unlocks; the save dialog
    shows the rule-mode line and the red warning.
  - **Open design question for the team:** the raw AC override contradicts the spec's guidance that
    derived stats (AC, attack bonus, saves, max HP) are recomputed by the engine and only their
    *sources* should be edited. Decide whether to keep it as a deliberate escape hatch or drop it.
- **Undo / Redo** operate on the ledger, not on files. Buttons dim and disable at the ends of the stack.
- **PRC guard:** editing anything flagged `(PRC)` warns before staging.
- **Searchable pickers** (feats, spells, item properties) filter on display name *or* raw numeric id,
  and are the only way to add those records — no free text entry.
- Hover on interactive rows: subtle background lift. Focus: 1px gold ring. Disabled: opacity .45.

## State Management

Prototype state, as a guide to what the real controller needs:
```
section          active sidebar screen key
tab / subTab     per-screen tab selection
editA            edit mode on/off
strictA          true = Strict rule mode, false = Free
dialog           null | 'open' | 'save'
saveMode         'new' | 'overwrite'
reviewOpen       ledger slide-over visible
changes[]        staged changes (section, field, old, new, id, raw?)
discardedIds[]   discarded change ids
undoCount        entries undone but still displayed
backupOnWrite    backup-before-overwrite checkbox
newSaveName      target filename for save-as-new
openSelected     highlighted row in the Open dialog
selectedItemKeys per-context selected item ({ player: 'weapon', store: …, … })
pendingNewProps  item properties added but not committed
removedPropIds   properties marked for removal
pendingNewSpells / removedSpellIds   same pattern for spells
copiedItemKeys   items copied into inventory this session
sheetSkin        cosmetic character-sheet skin
```
Derived, never stored: AC, attack bonus, saving throws, max HP, ability modifiers, the
`activeCount = changes − discarded − undone` write count.

Data the real implementation must supply: parsed GFF for `module.ifo`, `player.bic` and area files;
2DA-backed lookup tables (`iprp_*`, feat, spell, appearance, portrait lists) for every picker;
the backup folder listing; and a diff between a backup and the current save.

## Design Tokens

Colors (OKLCH as authored — convert to hex/Qt palette entries):
```
app background      oklch(0.14 0.012 55)
raised surface      oklch(0.16 0.012 55)
sidebar             oklch(0.155 0.012 55)
inset panel / field oklch(0.185 0.014 55)
icon chip           oklch(0.28 0.02 55)
gold (accent)       oklch(0.78 0.12 82)
gold on-color text  #1a1408
gold tint bg        oklch(0.3 0.05 82 / 0.15–0.25)
gold border         oklch(0.6 0.09 82 / 0.4–0.5)
text primary        oklch(0.94 0.006 60)   (headings also #f2ede4)
text secondary      oklch(0.68 0.012 60)
text tertiary       oklch(0.5 0.012 60)
success / green     oklch(0.75 0.16 150)
danger text         oklch(0.72 0.15 25)
danger bg / border  oklch(0.28 0.06 25 / 0.18) / oklch(0.6 0.14 25 / 0.45)
PRC amber           oklch(0.78 0.14 70)
hairline borders    rgba(255,255,255,.06 / .08 / .1 / .12 / .14 / .16)
```

Typography:
```
display / headings  Cinzel serif — 700 15px (wordmark, .04em tracking), 600 16px (section titles)
UI                  Inter — 500/600 11–13.5px; body copy 12–13.5px at 1.6 line-height
cap labels          600 11px, letter-spacing .04em, text-secondary, uppercase
mono                ui-monospace / Menlo — 10.5–12.5px for ids, codes, paths, filenames
```

Spacing: 2 · 4 · 6 · 8 · 10 · 12 · 14 · 16 · 18 · 20 · 24 px. Section gap 16–20; panel padding 14–18;
row padding 8–11px vertical / 10–14px horizontal.

Radii: 4 (badges) · 5–6 (small chips) · 7 (buttons, inputs) · 8 (nav rows, item cells) ·
9–10 (panels) · 12 (character sheet) · 50% (skin swatches, status dots).

Sizes: toolbar 52px · sidebar 236px · detail panels 300px · item cells 62px · portrait 180×240 ·
nav icon chip 24px · save thumbnail 30px · status dot 6px.

Shadow: `0 8px 30px rgba(0,0,0,.5)` on the app card and modals. Modal widths: 560 (save) / 680 (open).

## Assets
No external assets. All imagery in the prototype is a placeholder:
- Character portrait and save thumbnails are diagonal repeating-linear-gradient hatches.
- Item icons are 2–3 letter text codes in a cell.
- Nav icons are 2-letter text codes in a chip.

The real implementation should use the game's own portrait and item-icon resources, which VaultKeeper
already reads (see `tests/test_item_icons.py`, `test_hak_portraits.py`,
`test_installed_portraits.py`, `test_tga_reader.py`). Fonts Cinzel and Inter were webfonts in the
prototype; substitute the app's existing display/UI font pairing if it has one.

## Source of Truth
This design was built against `docs/save_game_editor.md` in the VaultKeeper repo. Where the two
disagree, **the spec wins** — it describes the actual write path, PRC caveats and safety model. The
one known divergence is the Free-mode raw AC override, flagged above.

## Files
- `VaultKeeper Save Editor - Nav Options.dc.html` — the full interactive prototype. Open it in a
  browser: toggle Edit, switch Strict/Free, stage changes, open the ledger and both save dialogs.
- `support.js` — runtime for the prototype only. **Not part of the design.** Required for the HTML
  file to run; contains nothing to implement.
