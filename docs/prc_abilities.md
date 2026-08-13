# PRC feats and abilities: what a save-edit can and can't grant

The Save Game Editor writes what the save *stores* — your feat list, skills,
spells, item properties, character fields. The **Player Resource Consortium
(PRC)** does not read most of its abilities straight off those stored fields. It
runs its own scripts that turn a feat or class level into a working ability, and
it keeps the result in places a save-edit does not touch: item properties baked
onto a hidden *skin* item, event-hook registrations, and a persistent spellbook
kept in an SQLite database.

So when you add a PRC feat in the editor, the game will *list* it, but whether the
**effect** actually works depends on how PRC implements that particular feat.
They fall into four buckets.

## 1. Passive `GetHasFeat` checks — works from the edit

PRC reads the feat live, at the moment the relevant thing happens (a spell
resolves on you, an attack lands). Nothing is set up in advance, so the feat
sitting in your list is all PRC needs.

- **Example:** *Master's Gift* — `prc_effect_inc` checks
  `GetHasFeat(FEAT_MASTERS_GIFT, oTarget)` when an arcane spell's effect is
  applied to you, and doubles the duration of non-hostile arcane spells.
- **Direction:** add the feat; it just works. (If it seems not to, the effect is
  often subtle rather than absent.)

## 2. Feat effects PRC re-applies on re-evaluation — works after a refresh

PRC's `prc_feats` engine re-evaluates your character on **login / module entry,
level-up, and equipping an item**. It reads `GetHasFeat` and (re)applies each
feat: adds bonuses onto your skin, registers on-hit / on-equip event hooks,
grants bonus feats. Because it reads `GetHasFeat`, it *does* pick up a feat you
added in the editor — the next time it runs.

- **Example:** *Dragonfire Strike* — the toggle shows in your radial immediately;
  the on-hit fire damage needs `prc_dragfire_atk` registered as your equip hook,
  which `PRCFeat_AddEventHooks` does on the strength of
  `GetHasFeat(FEAT_DRAGONFIRE_STRIKE)`.
- **Direction:** add the feat, then **re-enter the module and re-equip your
  weapon** so PRC re-evaluates you and wires the hook.

## 3. Class-gated features — need the class, not just the feat

Some class features check a marker PRC sets from **class levels**, not from the
feat. Without the class levels the feat does nothing — in the editor *or*
in-game.

- **Example:** *Skullclan Hunter — Divine Strike* (sneak attacks vs. undead) is
  gated on `PRC_AllowSkullClan`, which PRC sets from having Skullclan Hunter
  levels; the on-hit sneak is applied by the `prc_skullclan` equip/on-hit script.
- **Direction:** add the **class levels** as well, then re-evaluate (bucket 2).

## 4. Spellbook spell-like abilities — not from a feat-add

Spells you cast through a PRC spellbook (Archivist, Mystic, Warmage, Dread
Necromancer, …) are built at **level-up** from the class's spell list, by
`SetupSpells` in `inc_newspellbook`. `AddSpellUse` writes two things: a
feat-granting item property onto your **skin** (`AddSkinFeat`) and rows into a
persistent **spellbook** kept in an EE object-scoped SQLite database (embedded in
the `.sav`, with a companion `prc_data.sqlite3`). None of that comes from the
feat list, so adding the feat lists it but never makes it castable.

- **Example:** *Archivist / Mystic Darkfire.* The "Extended / Silent / Still"
  variants are metamagic forms of the base ability, not standalone spells.
- **Direction:** gain it **in-game through the class** (level-up, or a PRC
  learn / convocation option). The editor cannot reliably synthesise the
  spellbook + skin state, and PRC's load-time reconciliation may wipe anything
  hand-injected that doesn't match what it expects.

## Which bucket is a given feat in? Read it from your installed PRC

You do **not** need the PRC source repository, and you do not need to decompile
anything. A PRC install already carries everything, in the haks the editor
already opens:

- **The 2das** (`prc8_2das.hak`) give the coarse split:
  - `feat.2da` — a **SpellID** column means the feat is an *active* ability (it
    appears in your radial and casts something); no SpellID means it is passive.
  - `cls_feat_*.2da` — tells you the feat is a **class feature** (bucket 3, and it
    names the class + the level it is granted at).
  - the class spell tables (`cls_spell_*`, `cls_spgn_*`, `cls_spkn_*`) — tells you
    the ability is a **spellbook member** (bucket 4, level-up only).
- **The source scripts** — PRC ships its full `.nss` source inside the haks
  (`prc8_scripts.hak`, `prc8_include.hak`, `prc8_nsb.hak`, `prc8_psionics.hak`).
  They show the exact mechanism:
  - a bare `GetHasFeat(FEAT_X)` check → bucket 1,
  - `AddEventScript` / `AddSkinFeat` reached from `prc_feats` → bucket 2,
  - a class marker (`PRC_Allow…`) → bucket 3,
  - the newspellbook (`inc_newspellbook` / `SetupSpells` / `AddSpellUse`) →
    bucket 4.

The compiled `.ncs` bytecode would be opaque, but PRC bundles the readable source
next to its data, so the classification is derivable entirely from the installed
game — the same haks the editor reads for item icons and 2da lookups.

## Forcing the re-evaluation in-game (better than re-equip / re-enter)

For buckets 2–4, the effect only appears once PRC re-evaluates the character.
Re-entering the module and re-equipping triggers the on-hit/on-equip path, but the
thorough way is to force a full re-level. Use the **player chat command** (no DM,
no debug build needed), handled in `scripts/prc_onplayerchat.nss`:

- **`/relevel`** — type it once and PRC asks you to confirm; type **`/relevel`
  again** and it drops you to level 1 and re-levels back to your current XP
  (`ResetCharacterXPAndRemoveSpells`: `SetXP(1)` then `SetXP(oldXP)`). Re-running
  the level-up rebuilds PRC's managed state — the spellbook, the skin bonuses, the
  event hooks. It **keeps your XP but clears PRC spell selections**, so you re-pick
  spells as you re-level.
- **`/resetSpells`** (also type twice) — clears just the PRC spell choices without
  re-leveling, when spells are all you need rebuilt.

So the practical workflow with this editor: **edit the feat or class level here,
load the save, then `/relevel` twice in-game** — the edit provides the character
data and the relevel makes PRC evaluate it, which is exactly the gap the buckets
describe. Treat it as a re-level (you re-pick spells), not a silent refresh.

> **Not `~~dm_relevel`.** PRC also has a `~~dm_relevel <level>` DM/debug command
> (`include/prc_inc_chat_dm.nss`), but its branch is gated on the compile-time
> `DEBUG` constant *only* — being a DM does **not** enable it — so in a normal
> release build it just replies "This command only works if DEBUG = TRUE". That is
> why typing it does nothing. Use `/relevel` instead.

## Rule of thumb

> A save-edit reliably grants a PRC ability only when PRC reads the feat **live**
> (bucket 1) or **rebuilds it from your feat list on re-evaluation** (bucket 2).
> When PRC builds the ability at level-up from a **class** — a class-gated feature
> (bucket 3) or a spellbook spell (bucket 4) — the ability lives in state the save
> does not hold, and the reliable path is to gain it in-game.

The editor tags PRC feats and spells **(PRC)** and warns before staging one for
exactly this reason: base-game entries edit cleanly and stick; PRC-managed ones
may need a re-evaluation, the underlying class, or an in-game level-up to take
effect.
