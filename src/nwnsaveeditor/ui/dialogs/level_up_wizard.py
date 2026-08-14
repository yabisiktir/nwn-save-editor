"""A step-by-step wizard for adding a class level.

Adding a level is not one decision — it is a stack of them: confirm the
deterministic gains (HP, attack, saves, any auto-granted feats), then make the
*choices* the level opens up: spend the skill-point budget, pick a general feat
if one is due, raise an ability if one is due. A single confirm box could only
recite the numbers and send the player off to other tabs to make the choices by
hand; the wizard gathers them here, against the budget the level actually grants,
so applying the level is one coherent act.

The wizard is deliberately ignorant of the save: it takes plain values in and
hands plain choices back (:meth:`skill_allocations`, :meth:`chosen_feat`,
:meth:`chosen_ability`). The caller applies them through the session, which keeps
this dialog easy to construct and to test.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QButtonGroup,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QRadioButton,
    QScrollArea,
    QSpinBox,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
    QWizard,
    QWizardPage,
)

from nwnsaveeditor.ui.editor import tokens as t  # pure colour constants, no Qt cycle

_ABILITIES = (
    ("Str", "Strength"), ("Dex", "Dexterity"), ("Con", "Constitution"),
    ("Int", "Intelligence"), ("Wis", "Wisdom"), ("Cha", "Charisma"),
)
_ID_ROLE = Qt.ItemDataRole.UserRole


class _Skill:
    """The bit of an ``EditableSkill`` the wizard needs (index, name, rank)."""

    __slots__ = ("index", "name", "rank")

    def __init__(self, index: int, name: str, rank: int) -> None:
        self.index, self.name, self.rank = index, name, int(rank)


class LevelUpWizard(QWizard):
    """Confirm a level's gains and gather the choices it opens up."""

    def __init__(
        self,
        gains,
        *,
        con_modifier: int,
        int_modifier: int,
        new_total_level: int,
        skills: Iterable[object] = (),
        skill_cap: int = 255,
        skill_caps: dict[int, int] | None = None,
        feat_options: Sequence[tuple[int, str]] = (),
        prc_feat_ids: frozenset[int] = frozenset(),
        ability_scores: dict[str, int] | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        from nwnsaveeditor.ui.editor import widgets as w

        self._gains = gains
        self._con_mod = con_modifier
        self._skill_cap = skill_cap  # fallback cap; skill_caps overrides per skill
        self._skill_caps = dict(skill_caps or {})
        self._skills = [_Skill(s.index, s.name, s.rank) for s in skills]
        self._ability_scores = dict(ability_scores or {})
        self._skill_boxes: dict[int, QSpinBox] = {}
        self._skill_budget = gains.skill_points(int_modifier)
        self._feat_group: _FeatChoice | None = None
        self._ability_choice: _AbilityChoice | None = None

        self.setWindowTitle(f"Add {gains.class_name} level {gains.class_level}")
        self.setWizardStyle(QWizard.WizardStyle.ModernStyle)
        self.setOption(QWizard.WizardOption.NoBackButtonOnStartPage, True)
        self.setStyleSheet(w.dialog_qss())
        self.resize(520, 560)

        self.addPage(self._summary_page(new_total_level))
        if self._skill_budget > 0 and self._skills:
            self.addPage(self._skill_page())
        if gains.general_feat and feat_options:
            self._feat_group = _FeatChoice(feat_options, prc_feat_ids)
            self.addPage(self._feat_page())
        if gains.ability_increase:
            self._ability_choice = _AbilityChoice(self._ability_scores)
            self.addPage(self._ability_page())

    # -- pages ------------------------------------------------------------- #
    def _summary_page(self, new_total_level: int):
        from nwnsaveeditor.ui.editor import widgets as w

        g = self._gains
        page = QWizardPage()
        page.setTitle(f"Level {g.class_level} in {g.class_name}")
        page.setSubTitle("What this level grants. Later steps gather the choices it opens up.")
        box = QVBoxLayout(page)
        hp = g.hit_points(self._con_mod)
        box.addWidget(w.body(
            f"+{hp} HP · +{g.bab_gain} attack bonus · "
            f"+{g.fort_gain} Fortitude / +{g.ref_gain} Reflex / +{g.will_gain} Will.",
            t.TEXT, 13,
        ))
        budget_line = f"{self._skill_budget} skill point" + ("s" if self._skill_budget != 1 else "")
        extras = []
        if g.general_feat:
            extras.append("a general feat")
        if g.ability_increase:
            extras.append("an ability point")
        tail = (" · " + ", ".join(extras)) if extras else ""
        box.addWidget(w.body(f"{budget_line} to spend{tail}.", t.TEXT_2, 12.5))
        if g.granted_feats:
            box.addWidget(w.body(
                "Automatically granted: " + ", ".join(n for _i, n in g.granted_feats) + ".",
                t.TEXT_2, 12.5,
            ))
        if not g.is_base_class:
            box.addWidget(_note(
                "This is a PRC class. The numbers above apply to the save, but its "
                "script-managed features (a prestige spellbook, on-hit or skin "
                "abilities) are rebuilt in-game — once in play, type /relevel in "
                "chat (again to confirm) to re-level and wake them up. It preserves "
                "XP but clears PRC spell choices, so you re-pick spells.",
            ))
        if new_total_level > 40:
            box.addWidget(_note(
                f"Total level {new_total_level} passes the base cap of 40 (PRC extends "
                "it to 60). Make sure your module allows it before loading the save.",
            ))
        box.addStretch(1)
        return page

    def _skill_page(self):
        from nwnsaveeditor.ui.editor import widgets as w

        page = self._skill_page_widget = _BudgetPage(self._remaining)
        page.setTitle("Spend skill points")
        page.setSubTitle("Raise ranks up to the budget. Unspent points are simply left unspent.")
        outer = QVBoxLayout(page)
        self._remaining_label = QLabel()
        self._remaining_label.setStyleSheet(f"color:{t.TEXT};font-weight:700;")
        outer.addWidget(self._remaining_label)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        holder = QWidget()
        rows = QVBoxLayout(holder)
        rows.setContentsMargins(0, 0, 8, 0)
        for skill in sorted(self._skills, key=lambda s: s.name.lower()):
            line = QHBoxLayout()
            line.addWidget(w.body(skill.name, t.TEXT, 13), 1)
            spin = QSpinBox()
            cap = self._skill_caps.get(skill.index, self._skill_cap)
            spin.setRange(skill.rank, max(skill.rank, cap))
            spin.setToolTip(f"caps at {cap}")
            spin.setValue(skill.rank)
            spin.setFixedWidth(70)
            spin.valueChanged.connect(self._on_skill_changed)
            self._skill_boxes[skill.index] = spin
            line.addWidget(spin)
            rows.addLayout(line)
        rows.addStretch(1)
        scroll.setWidget(holder)
        outer.addWidget(scroll, 1)
        page.setLayout(outer)
        self._refresh_remaining()
        return page

    def _feat_page(self):
        assert self._feat_group is not None
        page = _CompletePage(self._feat_group.is_complete)
        page.setTitle("Choose a general feat")
        page.setSubTitle("This level grants a feat. Pick one, or leave it for the Feats tab.")
        self._feat_group.build(page)
        return page

    def _ability_page(self):
        assert self._ability_choice is not None
        page = QWizardPage()
        page.setTitle("Raise an ability")
        page.setSubTitle("This character level grants +1 to an ability score.")
        self._ability_choice.build(page)
        return page

    # -- live budget ------------------------------------------------------- #
    def _on_skill_changed(self, _value: int) -> None:
        self._refresh_remaining()
        self._skill_page_widget.completeChanged.emit()  # re-check Next/Finish

    def _spent(self) -> int:
        return sum(
            box.value() - skill.rank
            for skill in self._skills
            if (box := self._skill_boxes.get(skill.index)) is not None
        )

    def _remaining(self) -> int:
        return self._skill_budget - self._spent()

    def _refresh_remaining(self) -> None:
        left = self._remaining()
        self._remaining_label.setText(
            f"{left} of {self._skill_budget} point" + ("s" if self._skill_budget != 1 else "")
            + " remaining" + ("  —  over budget" if left < 0 else "")
        )
        colour = "#e06c6c" if left < 0 else t.TEXT
        self._remaining_label.setStyleSheet(f"color:{colour};font-weight:700;")

    # -- results ----------------------------------------------------------- #
    def skill_allocations(self) -> dict[int, int]:
        """``{skill_index: new_rank}`` for every skill the player raised."""
        out: dict[int, int] = {}
        for skill in self._skills:
            box = self._skill_boxes.get(skill.index)
            if box is not None and box.value() != skill.rank:
                out[skill.index] = box.value()
        return out

    def chosen_feat(self) -> int | None:
        return self._feat_group.chosen() if self._feat_group else None

    def chosen_ability(self) -> str | None:
        return self._ability_choice.chosen() if self._ability_choice else None


class _BudgetPage(QWizardPage):
    """A page that stays incomplete while a budget callback is negative."""

    def __init__(self, remaining) -> None:
        super().__init__()
        self._remaining = remaining

    def isComplete(self) -> bool:  # noqa: N802 (Qt override)
        return self._remaining() >= 0


class _CompletePage(QWizardPage):
    """A page whose completeness is delegated to a callback."""

    def __init__(self, is_complete) -> None:
        super().__init__()
        self._is_complete = is_complete

    def isComplete(self) -> bool:  # noqa: N802 (Qt override)
        return self._is_complete()


class _FeatChoice:
    """A filterable feat list on a page; picking is optional (a 'no feat' row)."""

    def __init__(self, options: Sequence[tuple[int, str]], prc_ids: frozenset[int]) -> None:
        self._options = list(options)
        self._prc_ids = prc_ids
        self._tree: QTreeWidget | None = None

    def build(self, page: QWizardPage) -> None:
        box = QVBoxLayout(page)
        self._filter = QLineEdit()
        self._filter.setPlaceholderText("Filter feats by name or id…")
        self._filter.textChanged.connect(self._apply_filter)
        box.addWidget(self._filter)
        tree = QTreeWidget()
        tree.setColumnCount(2)
        tree.setHeaderLabels(["ID", "Feat"])
        tree.setRootIsDecorated(False)
        skip = QTreeWidgetItem(["", "— pick later, in the Feats tab —"])
        skip.setData(0, _ID_ROLE, None)
        tree.addTopLevelItem(skip)
        for fid, name in self._options:
            label = f"{name}  (PRC)" if fid in self._prc_ids else name
            row = QTreeWidgetItem([str(fid), label])
            row.setData(0, _ID_ROLE, fid)
            tree.addTopLevelItem(row)
        tree.setCurrentItem(skip)
        from nwnsaveeditor.ui.editor import widgets as w

        w.apply_tree_palette(tree)
        box.addWidget(tree, 1)
        self._tree = tree

    def _apply_filter(self, text: str) -> None:
        needle = text.strip().lower()
        assert self._tree is not None
        for i in range(self._tree.topLevelItemCount()):
            row = self._tree.topLevelItem(i)
            if row.data(0, _ID_ROLE) is None:
                continue  # the 'pick later' row always shows
            row.setHidden(needle not in f"{row.text(0)} {row.text(1)}".lower())

    def is_complete(self) -> bool:
        return True  # 'pick later' is a valid choice, so the page is always complete

    def chosen(self) -> int | None:
        if self._tree is None:
            return None
        row = self._tree.currentItem()
        return row.data(0, _ID_ROLE) if row is not None else None


class _AbilityChoice:
    """Six radios (Str…Cha) plus a 'not now' option for the ability point."""

    def __init__(self, scores: dict[str, int]) -> None:
        self._scores = scores
        self._group: QButtonGroup | None = None
        self._buttons: list[tuple[str | None, QRadioButton]] = []

    def build(self, page: QWizardPage) -> None:
        box = QVBoxLayout(page)
        self._group = QButtonGroup(page)
        for field, label in _ABILITIES:
            score = self._scores.get(field)
            suffix = f"  ({score} → {score + 1})" if score is not None else ""
            btn = QRadioButton(f"{label}{suffix}")
            self._group.addButton(btn)
            self._buttons.append((field, btn))
            box.addWidget(btn)
        later = QRadioButton("Not now — leave it for the Details tab")
        later.setChecked(True)
        self._group.addButton(later)
        self._buttons.append((None, later))
        box.addStretch(1)

    def chosen(self) -> str | None:
        for field, btn in self._buttons:
            if btn.isChecked():
                return field
        return None


def _note(text: str):
    from nwnsaveeditor.ui.editor import widgets as w

    label = w.body(text, t.TEXT_3, 11.5)
    label.setWordWrap(True)
    return label
