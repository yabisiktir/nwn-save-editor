"""The Save Game Editor's own guide.

Describes the sectioned editor: where each thing lives, what the edit gate does,
and which edits the game will quietly undo.
"""

from __future__ import annotations

from PySide6.QtWidgets import QDialog, QDialogButtonBox, QTextBrowser, QVBoxLayout, QWidget

from nwnsaveeditor.ui.editor import tokens as t
from nwnsaveeditor.ui.editor import widgets as w


def _help_html() -> str:
    """The guide's copy, built per call so its colours follow the theme."""
    return f"""
<style>
  body {{ color:{t.TEXT}; font-size:13px; line-height:1.55; }}
  h2 {{ color:{t.GOLD}; font-size:17px; margin:0 0 6px 0; }}
  h3 {{ color:{t.TEXT_HEADING}; font-size:13.5px; margin:16px 0 4px 0; }}
  b {{ color:{t.TEXT_HEADING}; }}
  li {{ margin-bottom:4px; }}
  .warn {{ color:{t.PRC_AMBER}; }}
  code {{ color:{t.TEXT_2}; }}
</style>

<h2>Save Game Editor</h2>
<p>Open a save, turn on <b>Edit</b>, change what you like, then commit. Nothing is
written until you commit, and your original save is never modified unless you
explicitly choose <b>Overwrite…</b> — which keeps a timestamped backup first.</p>

<h3>The toolbar</h3>
<ul>
  <li><b>Open Save…</b> — pick a save. Saves that cannot be decoded are listed but
      cannot be opened; saves in a folder you cannot write are marked read-only.</li>
  <li><b>Strict / Free</b> — Strict holds edits to the game's rules (a skill caps
      at level + 3, current HP cannot exceed maximum, alignment stays 0–100). Free
      lifts those. Neither lets a value exceed what the field can physically hold:
      Free is for breaking rules, not files.</li>
  <li><b>Undo / Redo</b> — step through your staged edits. A run of changes to the
      same value counts as one step.</li>
  <li><b>Edit</b> — the gate. With it off the window is a viewer: no steppers, no
      remove buttons, no commit.</li>
</ul>

<h3>Where things are</h3>
<ul>
  <li><b>Character</b> — the sheet and six tabs. <b>Details</b> holds every stored
      field: gold, experience, alignment, age, current HP, the base saving throws,
      name, appearance and portrait. <b>Skills</b> shows each skill's total
      alongside its rank. <b>Feats</b> adds and removes. <b>Effects</b> is
      read-only.</li>
  <li><b>Inventory &amp; Equipment</b> — the paperdoll, then what you carry, grouped
      by the bag each item sits in. Select an item to edit its magical properties;
      every field comes from the game's own tables, so an edit cannot produce a
      value the engine does not recognise.</li>
  <li><b>Spellbook</b> — per caster class and spell level.</li>
  <li><b>Quests &amp; World State</b> — the module's persistent variables.</li>
  <li><b>Party &amp; Campaign</b> — this save's summary and the module's party
      settings.</li>
  <li><b>Area Contents</b> — stores, creatures and containers. Store pricing is
      editable, and so are the magical properties of any item in the world: a
      chest's loot and a creature's gear use the same property editor your own
      items do. Editing one changes the <i>area</i>; <b>copying it into your own
      inventory</b> instead leaves the world untouched.
      Whole items can be added and removed too: <b>Duplicate here</b> and
      <b>Remove from the world…</b> on a selected item, and <b>Place an item
      here…</b> on a selected store, creature or container puts a copy of one of
      yours into it. Removing an item renumbers everything after it in the same
      list, and anything you have already staged against one of those follows the
      item it belongs to.</li>
  <li><b>Raw Data (GFF)</b> — every resource in the save, as its raw field tree.
      Scalar values can be edited here; a field's type is always preserved. A
      list of structs can also gain and lose entries: <b>Duplicate entry</b>
      copies a sibling, which is the reliable way to add one, while <b>Add blank
      entry</b> only seeds the sibling's fields at zero and leaves filling them
      in to you. Removing an entry moves every later one up a place.
      <b>Property reference ›</b> folds out beside the tree: what every item
      property means, the values it accepts, and which of your items carry it —
      so a raw <code>CostValue</code> can be read without leaving the tree.</li>
  <li><b>Backups &amp; Diff</b> — what an overwrite archived, and what differs
      between a backup and the save you have now.</li>
</ul>

<h3>What the game recomputes</h3>
<p>Armour class, attack bonus and maximum hit points are worked out by the engine
when the save loads. Editing your abilities, feats and gear changes them; there is
nothing to edit in the totals themselves, so the editor does not pretend
otherwise. The saving throws are different — the record stores them outright (on a
real character the field holds the number the game shows, not a base with more to
add), so Details edits them directly.</p>

<h3 class="warn">PRC</h3>
<p>If your game uses the PRC, it manages much of the character through its own
scripts and a hidden <i>skin</i> item. Base-game feats, skills and spells edit
cleanly. Anything marked <b>(PRC)</b> is rebuilt by PRC on rest, level-up or area
load, so an edit there may not stick — the editor warns before staging one.</p>
<p>Whether an added PRC feat's <i>effect</i> actually works depends on how PRC
implements that feat:</p>
<ul>
  <li><b>Passive feats</b> PRC reads live (e.g. Master's Gift) — these
      <b>work from the edit</b>.</li>
  <li><b>On-hit / on-equip feats</b> (e.g. Dragonfire Strike) — PRC wires these
      when it re-evaluates you, so <b>add the feat, then re-enter the module and
      re-equip your weapon</b>.</li>
  <li><b>Class features</b> (e.g. Skullclan Hunter's Divine Strike vs. undead) —
      need the <b>class levels</b>, not just the feat.</li>
  <li><b>Spellbook abilities</b> (e.g. Archivist / Mystic Darkfire) — built at
      level-up from the class spell list into PRC's own spellbook, so a feat-add
      can't grant them. <b>Gain them in-game.</b></li>
</ul>
<p>In short: an edit reliably grants a PRC ability only when PRC reads the feat
live or rebuilds it from your feat list; abilities PRC builds at level-up from a
<i>class</i> live in state the save does not hold, and are best gained in-game.</p>
<p>To make an edit take effect without replaying, PRC's DM/debug chat commands can
force a re-evaluation: in DM mode, type <code>~~dm_relevel &lt;level&gt;</code> to
re-level (keeping XP) and rebuild PRC's managed state, or <code>~~dm_exec
&lt;script&gt;</code> to run a script. Edit here, then <code>~~dm_relevel</code>
in-game.</p>

<h3>Committing</h3>
<ul>
  <li><b>Review…</b> lists every staged change, with <b>Discard</b> per row.
      Anything you undo stays listed, struck through, and is not written.</li>
  <li><b>Save as New…</b> writes a brand-new save and leaves the original alone.</li>
  <li><b>Overwrite…</b> replaces the save. The edited copy is written and verified
      in a staging folder <i>before</i> the old one is moved to
      <code>vaultkeeper_backups</code>, so a failed write never damages what you
      had.</li>
</ul>
<p><b>Test an edited save in-game before relying on it</b>, especially anything
PRC-related.</p>

<h3>Thanks</h3>
<p>To <b>Surazal</b>, author of the <i>NWN Installer Tool</i>. Its
file-format code, converted to Python, is part of what this editor is built on.</p>
"""


class EditorGuideDialog(QDialog):
    """A scrollable guide to the sectioned save editor."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Save Game Editor — Guide")
        self.resize(620, 700)
        # dialog_qss carries the QDialog background plus the Close button's colours,
        # which would otherwise come from the application palette.
        self.setStyleSheet(w.dialog_qss())
        layout = QVBoxLayout(self)
        browser = QTextBrowser()
        browser.setHtml(_help_html())
        browser.setOpenExternalLinks(False)
        browser.setStyleSheet(
            f"QTextBrowser{{background:{t.INSET};border:1px solid "
            f"{t.hairline(0.08)};border-radius:8px;padding:12px;color:{t.TEXT};}}"
        )
        layout.addWidget(browser, 1)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        buttons.rejected.connect(self.reject)
        buttons.accepted.connect(self.accept)
        layout.addWidget(buttons)
