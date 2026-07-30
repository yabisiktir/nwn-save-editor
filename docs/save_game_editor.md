# Save Game Editor — Guide

The **Save Game Viewer** (Tools → Save Game Viewer) can also *edit* a save and write
the result to a **brand-new save**. Your original save is never modified — it is your
backup — so editing is safe to experiment with.

## Quick start

1. **Tools → Save Game Viewer** and pick a save on the left.
2. Click **Edit** (bottom bar) to turn on edit mode. A **pending-changes** panel
   appears at the bottom.
3. Make changes (see below). Each one is *staged* — nothing is written yet — and
   listed in the pending panel, with a ● marker on the thing you changed.
4. Commit your changes one of two ways:
   - **Save as New Save…** — writes a new save folder next to the original (which is
     left untouched). Safest.
   - **Overwrite This Save…** — replaces the selected save in place. The version
     being replaced is first moved to a timestamped folder under
     `…/Neverwinter Nights/vaultkeeper_backups/`, so it stays recoverable. The edited
     save is fully written and verified to a staging folder *before* the old one is
     touched, so a failure never harms it.

Use **Discard All** to drop every staged change, or turn **Edit** off (it asks
before discarding unsaved changes).

## What you can edit

Almost everything is reached by **selecting** a node or **right-clicking** it while
in edit mode.

### Stores (merchant pricing)
Expand an area → **Stores** → select a store → **Edit Store…** (bottom bar). Change
buy markup, sell-back markdown, store gold, identify price, max buy price and the
black-market flag.

### The player character
Expand the **Player character** node. It has **Details**, **Equipped**, **Carried**,
**Skills**, **Feats** and **Spells**.

- **Details:** the core character fields — gold, experience (XP), the six ability
  scores, alignment (Good–Evil / Lawful–Chaotic, 0–100), age, current HP, the
  first/last name, plus the cosmetic **Appearance** (model) and **Portrait**
  (chosen from pickers of valid values). Select one and click **Edit…**.

- **Item properties — edit a value:** select a magical property under an item and
  click **Edit…**. Every field is a dropdown (or a searchable picker for the huge
  feat/spell lists) populated from the game's `iprp_*` tables, so you can change the
  **subtype** (which ability / damage type / spell …), the **value** (`+8`, `1d6`,
  `5 Charges/Use`, `50%` …) and, for Cast-Spell properties, **uses/day** — and can
  only pick values the game recognises, so an edit can't corrupt the item. (To change
  the property *type* itself, remove it and add a new one.)
- **Item properties — add / remove:** right-click an item → **Add a property…** and
  choose a type (Ability/AC/Attack/Enhancement/Skill bonus, saving throws,
  regeneration, or a flag like Haste/Keen/True Seeing/Freedom of Movement/Improved
  Evasion/Darkvision), a subtype and a magnitude. Right-click a property →
  **Remove this property**.
- **Add items:** right-click one of your items → **Add a copy to my inventory** to
  duplicate it. You can also right-click any **store / creature / container** item
  in an area and choose the same — it copies that item into your inventory.
- **Skills:** select a skill → **Edit…** to set its rank.
- **Feats:** right-click **Feats** → **Add a feat…** (a searchable ID + Name list),
  or right-click a feat → **Remove this feat**.
- **Spells:** expand **Spells** → a caster class → a **Known / Memorized** level;
  right-click the level → **Add a spell…**, or right-click a spell → **Remove this
  spell**.

The **Add a feat / spell** picker is a browsable **ID + Name** table: scroll and
click, or type in the search box to filter by name **or** the raw id.

### Raw Data (GFF) — the escape hatch

**Raw Data (GFF)** browses every resource in the save as its decoded field tree, and
edits it directly. It is deliberately unhelpful: it bypasses the friendly editors,
so its changes are marked **raw** in the ledger. A field's *type* is always
preserved, so a raw edit can break the game's rules but not the file.

With **Edit** on, select a node and use the buttons under the tree:

- a scalar leaf → **Edit value…**
- a **list** → **Add blank entry** / **Duplicate entry**
- one of a list's **entries** → also **Remove entry…** (it confirms first)

Adding is the part worth understanding. **Duplicate entry** copies a sibling, which
is the reliable route: the copy already carries the fields, types and struct type
the game expects in that list. **Add blank entry** can only *seed* one — it takes
the first sibling's field set and types and zeroes the values, so you get the right
shape but have to fill it in. The line under the buttons says which one you got.

Removing an entry renumbers every entry after it — `[5]` becomes `[4]`, and so on.
Staged changes follow the entries they were made against, so the ledger keeps
pointing at what you actually edited.

Raw edits touch **one resource only**: editing `module.ifo` does not mirror into
`player.bic` the way the friendly editors do.

## Important: PRC content

If your game uses the **PRC** (Player Resource Consortium), it manages a lot of
character state through its own scripts and the character's hidden *skin* item.
That means:

- **Base-game** feats, skills and spells edit cleanly and persist.
- **PRC** feats, and **PRC prestige-class** spellbooks, are marked **(PRC)**. PRC
  regenerates them from its own data on rest / level-up / area-load, so an edit here
  **may not stick in-game**. The editor warns you before changing one.

Derived stats (AC, attack bonus, saving throws, max HP) are recomputed by the engine
from your abilities, feats and gear — so edit those *sources*, not the numbers.

## Safety model

- **Your original save is never touched** — every save is written to a new folder.
- The character lives inside the save's `module.ifo`; edits are applied there and
  mirrored into the folder's `player.bic`.
- After writing, the new save is re-read and byte-verified; a failed write cleans up
  rather than leaving a corrupt save.

> **Always test an edited save in-game before relying on it**, especially anything
> PRC-related. The editor can't load a save in NWN to confirm it.
