"""The Save Game Editor's own guide.

Separate from :mod:`vaultkeeper.ui.dialogs.save_editor_help`, which documents the
read-only viewer's tree-and-right-click interaction. This one describes the
sectioned editor: where each thing lives, what the edit gate does, and which
edits the game will quietly undo.
"""

from __future__ import annotations

from PySide6.QtWidgets import QDialog, QDialogButtonBox, QTextBrowser, QVBoxLayout, QWidget

from vaultkeeper.ui.save_editor import tokens as t

_HELP = f"""
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
      editable; the items are not, but any of them can be <b>copied into your own
      inventory</b>.</li>
  <li><b>Raw Data (GFF)</b> — every resource in the save, as its raw field tree.
      Scalar values can be edited here; a field's type is always preserved.</li>
  <li><b>Backups &amp; Diff</b> — what an overwrite archived, and what differs
      between a backup and the save you have now.</li>
</ul>

<h3>What the game recomputes</h3>
<p>Armour class, attack bonus, the final saving throws and maximum hit points are
worked out by the engine when the save loads. Editing your abilities, feats, gear
or the <i>base</i> saves changes them; there is nothing to edit in the totals
themselves, so the editor does not pretend otherwise.</p>

<h3 class="warn">PRC</h3>
<p>If your game uses the PRC, it manages much of the character through its own
scripts and a hidden <i>skin</i> item. Base-game feats, skills and spells edit
cleanly. Anything marked <b>(PRC)</b> is rebuilt by PRC on rest, level-up or area
load, so an edit there may not stick — the editor warns before staging one.</p>

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
"""


class EditorGuideDialog(QDialog):
    """A scrollable guide to the sectioned save editor."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Save Game Editor — Guide")
        self.resize(620, 700)
        self.setStyleSheet(f"QDialog{{background:{t.APP_BG};}}")
        layout = QVBoxLayout(self)
        browser = QTextBrowser()
        browser.setHtml(_HELP)
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
