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
4. Click **Save as New Save…**, type a name, and a new save folder is written next
   to the original. It shows up in the list (and in-game).

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
Expand the **Player character** node. It has **Equipped**, **Carried**, **Skills**,
**Feats** and **Spells**.

- **Item properties — edit a value:** select a magical property under an item and
  click **Edit…** to change its magnitude (e.g. *Ability Bonus: Dexterity* +8 → +12),
  or a Cast-Spell property's uses/day. Only properties whose value is a plain bonus
  are editable; others (damage dice, cast-spell, etc.) are shown read-only.
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
