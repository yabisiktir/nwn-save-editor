"""The Character screen — the core character record, as a skinned NWN sheet.

Layout follows the handoff prototype's latest pass: a header (portrait, name,
class/alignment/deity/gold, XP bar, sheet-skin switcher) above a tab strip of
``Abilities & Combat`` / ``Skills`` / ``Feats`` / ``Effects`` / ``Biography``.
(The handoff README describes an earlier ``Sheet`` / ``Abilities & Saves`` split;
the prototype is the later iteration, so it wins.)

Derived numbers — AC, attack bonus, saving throws, max HP — are shown but never
editable: the engine recomputes them from abilities, feats and gear on load, so
the screen points at the *source* to edit instead. That is the rule
``docs/save_game_editor.md`` sets, and the handoff defers to it.
"""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QScrollArea,
    QSizePolicy,
    QSpinBox,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from vaultkeeper.game.character import (
    _good_evil_word,
    _lawful_chaotic_word,
    class_name,
    race_name,
)
from vaultkeeper.game.rules import limits_for, skill_limits
from vaultkeeper.ui.save_editor import tokens as t
from vaultkeeper.ui.save_editor import widgets as w

#: The character screen's tabs, in the prototype's order.
TABS: tuple[tuple[str, str], ...] = (
    ("abilities", "Abilities & Combat"),
    ("details", "Details"),
    ("skills", "Skills"),
    ("feats", "Feats"),
    ("effects", "Effects"),
    ("biography", "Biography"),
)

#: ``(save-editor field, display name)`` for the six ability scores, in NWN order.
ABILITIES: tuple[tuple[str, str], ...] = (
    ("Str", "Strength"), ("Dex", "Dexterity"), ("Con", "Constitution"),
    ("Int", "Intelligence"), ("Wis", "Wisdom"), ("Cha", "Charisma"),
)

#: The Effects tab's two views: what the save stores, and what it adds up to.
EFFECT_VIEWS: tuple[tuple[str, str], ...] = (
    ("active", "Active effects"),
    ("bonuses", "Active bonuses"),
)

#: A sentinel ``SpellId``/``CreatorId``: the field is a DWORD, so "none" is all-ones.
_NO_ID = 0xFFFFFFFF

#: Width of the "which item grants this" column in the computed bonuses view.
_SOURCE_COLUMN = 176

#: Printed under the computed view. It is the point of the view, not a footnote:
#: a number whose scope is unstated is worse than no number at all.
_SCOPE_NOTE = (
    "Scope: these are the bonuses your equipped gear grants, read straight off the "
    "items. NWN does not stack two item bonuses of the same kind — it applies the "
    "largest and drops the rest — and the save does not record which one it picked, "
    "so a group with more than one source shows both the largest and the sum rather "
    "than picking for you. Feats, class abilities and untagged spell effects are "
    "listed but carry no number: working out what they contribute means running the "
    "game's rules, which this editor does not do."
)


def ability_modifier(score: int) -> int:
    """D&D ability modifier: ``(score - 10) / 2``, rounded toward negative infinity."""
    return (score - 10) // 2


def _signed(value: int) -> str:
    return f"+{value}" if value >= 0 else str(value)


class CharacterScreen(QWidget):
    """The Character section."""

    def __init__(self, window, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._window = window
        self._skin = "leather"
        self._effects_view = "active"
        self.setStyleSheet(f"background:{t.APP_BG};")

        outer = QVBoxLayout(self)
        outer.setContentsMargins(26, 22, 26, 22)
        outer.setSpacing(20)

        self._header = QWidget()
        self._header.setStyleSheet("background:transparent;")
        outer.addWidget(self._header)

        self._tabs = w.TabStrip(TABS)
        self._tabs.changed.connect(lambda _: self._show_tab())
        outer.addWidget(self._tabs)

        self._pages = QStackedWidget()
        self._pages.setStyleSheet("background:transparent;")
        self._page_keys: list[str] = []
        self._page_bodies: list[QWidget] = []
        for key, _label in TABS:
            # Each page scrolls in its own right: a character can carry well over a
            # hundred feats, and a QStackedWidget's sizeHint is the largest of its
            # pages — unscrolled, one long tab would force the whole window taller.
            body = QWidget()
            body.setStyleSheet("background:transparent;")
            QVBoxLayout(body).setContentsMargins(0, 0, 8, 0)
            self._pages.addWidget(_scroll(body))
            self._page_keys.append(key)
            self._page_bodies.append(body)
        outer.addWidget(self._pages, 1)

        self.refresh()

    # -- rebuilding ------------------------------------------------------- #
    def refresh(self) -> None:
        """Rebuild from the current save, edit gate and staged changes."""
        info = self._window.character_info()
        self._build_header(info)
        for index, key in enumerate(self._page_keys):
            body = self._page_bodies[index]
            _clear(body.layout())
            builder = getattr(self, f"_build_{key}")
            builder(body.layout(), info)
        self._show_tab()
        self._mark_dirty_tabs()

    def _show_tab(self) -> None:
        self._pages.setCurrentIndex(self._page_keys.index(self._tabs.value()))

    def _mark_dirty_tabs(self) -> None:
        """Put the design's ``●`` on tabs holding staged changes."""
        kinds = {c.kind for c in self._pending()}
        keys = {c.key for c in self._pending() if c.kind == "char-field"}
        self._tabs.set_dirty(
            "abilities", any(k in keys for k, _ in ABILITIES) or "CurrentHitPoints" in keys
        )
        self._tabs.set_dirty("skills", "skill" in kinds)
        self._tabs.set_dirty("feats", "feat" in kinds)
        self._tabs.set_dirty("biography", bool(keys & {"FirstName", "LastName"}))

    def _pending(self):
        session = self._window._session
        return session.pending_changes() if session is not None else []

    def _pending_char_fields(self) -> set[str]:
        return {c.key for c in self._pending() if c.kind == "char-field"}

    def _editable_fields(self) -> set[str]:
        """Character fields this save's record actually carries."""
        try:
            return {f.field for f in self._window.session().player_fields()}
        except Exception:
            return set()

    def _original_value(self, field: str):
        """What ``field`` held before the staged edit, for the ``old → new`` display."""
        session = self._window._session
        return session.original_field_value(field) if session is not None else None

    def _field_value(self, name: str, default: int = 0) -> int:
        """A character field's *staged* value (so edits show before they're written)."""
        try:
            field = next(f for f in self._window.session().player_fields() if f.field == name)
        except (StopIteration, Exception):
            return default
        try:
            return int(field.value)
        except (TypeError, ValueError):
            return default

    # -- header ----------------------------------------------------------- #
    def _build_header(self, info) -> None:
        _clear(self._header.layout())
        layout = self._header.layout() or QHBoxLayout(self._header)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(18)

        layout.addWidget(self._portrait(info, 76))

        column = QVBoxLayout()
        column.setSpacing(8)
        name = w.heading(_display_name(info), 22)
        column.addWidget(name)

        facts = QHBoxLayout()
        facts.setSpacing(12)
        if info is not None:
            facts.addWidget(w.body(_classes_line(info), t.TEXT_2, 13))
            facts.addWidget(_alignment_badge(
                self._field_value("LawfulChaotic", info.alignment_lawful_chaotic),
                self._field_value("GoodEvil", info.alignment_good_evil),
            ))
            if info.deity:
                facts.addWidget(w.body(f"Deity: {info.deity}", t.TEXT_2, 13))
            facts.addWidget(w.body(
                f"Gold: {self._field_value('Gold', info.gold):,}", t.TEXT_2, 13
            ))
        facts.addStretch(1)
        column.addLayout(facts)

        if info is not None:
            column.addWidget(_xp_bar(self._field_value("Experience", info.experience), info.level))
        column.addLayout(self._skin_switcher())
        column.addStretch(1)
        layout.addLayout(column, 1)

    def _portrait(self, info, box: int) -> QLabel:
        """The character's portrait TGA, or a hatched placeholder like the design."""
        label = QLabel()
        label.setFixedSize(box, box)
        label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        label.setStyleSheet(
            f"background:{t.ICON_CHIP};border:1px solid {t.gold_border(0.4)};"
            f"border-radius:{t.RADIUS_PANEL}px;color:{t.TEXT_3};"
            f"font-family:{t.MONO_FAMILY};font-size:8px;font-weight:600;"
        )
        pixmap = self._portrait_pixmap(info, box)
        if pixmap is None:
            label.setText("PORTRAIT")
        else:
            label.setPixmap(pixmap)
        return label

    def _portrait_pixmap(self, info, box: int):
        from vaultkeeper.ui.dialogs.character_viewer import tga_to_pixmap

        controller = self._window._controller
        save = self._window.save
        if info is None or not info.portrait_resref or controller is None or save is None:
            return None
        resolve = getattr(controller, "portrait_path", None)
        if resolve is None:
            return None
        path = resolve(info.portrait_resref, extra_dirs=[save.folder])
        return tga_to_pixmap(path, box=box) if path is not None else None

    def _skin_switcher(self) -> QHBoxLayout:
        """Four cosmetic sheet skins. A skin never changes save data."""
        row = QHBoxLayout()
        row.setSpacing(6)
        row.addWidget(w.cap_label("Sheet skin"))
        for key, swatch in t.SKIN_SWATCHES:
            button = QLabel()
            button.setFixedSize(22, 22)
            button.setCursor(Qt.CursorShape.PointingHandCursor)
            button.setToolTip(f"{key.title()} sheet skin (appearance only)")
            border = t.GOLD if key == self._skin else t.hairline(0.25)
            button.setStyleSheet(
                f"background:{swatch};border:2px solid {border};border-radius:11px;"
            )
            button.mousePressEvent = lambda _e, k=key: self._set_skin(k)
            row.addWidget(button)
        row.addStretch(1)
        return row

    def _set_skin(self, key: str) -> None:
        self._skin = key
        self.refresh()

    # -- Abilities & Combat ----------------------------------------------- #
    def _build_abilities(self, layout: QVBoxLayout, info) -> None:
        layout.setSpacing(14)
        if info is None:
            layout.addWidget(w.body("This save has no readable character record.", t.TEXT_2))
            layout.addStretch(1)
            return
        layout.addWidget(self._sheet_card(info))
        layout.addWidget(self._combat_panel(info))
        layout.addStretch(1)

    def _sheet_card(self, info) -> QFrame:
        """The skinned character sheet: art, identity, ability rows, AC/HP."""
        high, low, border, accent = t.SHEET_SKINS[self._skin]
        card = _SheetCard()
        card.setStyleSheet(
            f"_SheetCard{{background:qlineargradient(x1:0,y1:0,x2:0.6,y2:1,"
            f"stop:0 {high},stop:1 {low});border:1px solid {border};"
            f"border-radius:{t.RADIUS_SHEET}px;}}"
        )
        row = QHBoxLayout(card)
        row.setContentsMargins(18, 18, 18, 18)
        row.setSpacing(20)

        art = QLabel("CHARACTER ART")
        art.setFixedSize(t.PORTRAIT_W, t.PORTRAIT_H)
        art.setAlignment(Qt.AlignmentFlag.AlignCenter)
        art.setStyleSheet(
            f"background:{t.ICON_CHIP};border:1px solid {border};border-radius:8px;"
            f"color:{t.TEXT_3};font-family:{t.MONO_FAMILY};font-size:9px;font-weight:600;"
        )
        pixmap = self._portrait_pixmap(info, t.PORTRAIT_W)
        if pixmap is not None:
            art.setPixmap(pixmap)
        row.addWidget(art, 0, Qt.AlignmentFlag.AlignTop)

        stats = QVBoxLayout()
        stats.setSpacing(10)
        law = self._field_value("LawfulChaotic", info.alignment_lawful_chaotic)
        good = self._field_value("GoodEvil", info.alignment_good_evil)
        stats.addWidget(w.body(
            f"{race_name(info.race_id)}, {_lawful_chaotic_word(law)} {_good_evil_word(good)}",
            accent, 13,
        ))
        classes = w.body(_classes_line(info), t.SHEET_TEXT, 14)
        classes.setStyleSheet(classes.styleSheet() + "font-weight:600;")
        stats.addWidget(classes)
        stats.addWidget(_sheet_divider())

        pending = self._pending_char_fields()
        editable = self._editable_fields()
        for field, label in ABILITIES:
            score = self._field_value(field, info.abilities.get(field, 10))
            was = self._original_value(field) if field in pending else None
            # Only offer a stepper for a score the record actually carries:
            # SaveEditor writes a field only when it is present, so a stepper on a
            # missing one would look editable and silently do nothing.
            stats.addWidget(_ability_row(
                field, label, score, was,
                limits=self._limits(field, info),
                on_change=(
                    self._set_ability
                    if self._window.editing and field in editable
                    else None
                ),
            ))
        stats.addWidget(_sheet_divider())
        stats.addLayout(self._ac_hp_row(info, accent))
        stats.addStretch(1)
        row.addLayout(stats, 1)
        return card

    def _limits(self, field: str, info):
        """The range this field may take under the current rule mode."""
        session = self._window._session
        gff_type = None
        if session is not None:
            try:
                player = session._player_struct(session._module_tree())
                entry = player.fields.get(field)
                gff_type = entry.type if entry is not None else None
            except Exception:
                gff_type = None
        return limits_for(
            field, gff_type,
            strict=self._window.rule_mode() == "strict",
            level=getattr(info, "level", 0) or 0,
            max_hit_points=getattr(info, "hit_points", 0) or 0,
        )

    def _set_ability(self, field: str, score: int) -> None:
        display = next(label for key, label in ABILITIES if key == field)
        self._window.session().set_character_field(field, score, where=display)
        self._window.notify_changed()

    def _ac_hp_row(self, info, accent: str) -> QVBoxLayout:
        """AC and HP, with the design's "edit the source, not the total" note."""
        box = QVBoxLayout()
        box.setSpacing(6)
        line = QHBoxLayout()
        line.setSpacing(20)
        line.addWidget(_fact("AC:", str(info.armor_class), accent))
        current = self._field_value("CurrentHitPoints", info.current_hit_points)
        line.addWidget(_fact("HP:", f"{current} / {info.hit_points}", accent))
        line.addStretch(1)
        box.addLayout(line)
        box.addWidget(w.body(
            "AC and max HP are computed by the engine from your abilities, feats and "
            "gear — edit those sources, not these totals. Current HP is editable on "
            "the sheet's own field.",
            t.TEXT_3, 10.5,
        ))
        return box

    def _combat_panel(self, info) -> QWidget:
        """Read-only derived stats, each with the source it comes from."""
        holder = QWidget()
        holder.setStyleSheet("background:transparent;")
        column = QVBoxLayout(holder)
        column.setContentsMargins(0, 0, 0, 0)
        column.setSpacing(8)
        column.addWidget(w.body(
            "Computed from abilities, feats & gear — see the Effects tab; edit the "
            "sources, not these totals.",
            t.TEXT_3, 11.5,
        ))
        panel = w.Panel(padding=16)
        stats = QHBoxLayout()
        stats.setSpacing(24)
        dex = ability_modifier(self._field_value("Dex", info.abilities.get("Dex", 10)))
        for label, value, source in (
            ("Base attack", _signed(info.base_attack_bonus), f"BAB {info.base_attack_bonus}"),
            ("Initiative", _signed(dex), f"{_signed(dex)} Dex"),
            ("Fortitude", _signed(info.save_fortitude), "base + Con"),
            ("Reflex", _signed(info.save_reflex), "base + Dex"),
            ("Will", _signed(info.save_will), "base + Wis"),
        ):
            stats.addWidget(_combat_stat(label, value, source))
        stats.addStretch(1)
        panel.body_layout().addLayout(stats)
        column.addWidget(panel)
        return holder

    # -- Skills ------------------------------------------------------------ #
    def _build_details(self, layout: QVBoxLayout, info) -> None:
        """Every editable field on the character record.

        The sheet card carries the ability scores; everything else the record
        stores — gold, XP, alignment, age, current HP, the base saves, the name and
        the character's look — lives here, so no editable field is unreachable.
        """
        layout.setSpacing(12)
        try:
            fields = self._window.session().player_fields()
        except Exception:
            fields = []
        if not fields:
            layout.addWidget(w.body("This save has no readable character record.", t.TEXT_2))
            layout.addStretch(1)
            return

        pending = self._pending_char_fields()
        groups: list[tuple[str, tuple[str, ...]]] = [
            ("Progress", ("Gold", "Experience")),
            ("Alignment & age", ("GoodEvil", "LawfulChaotic", "Age")),
            ("Health & saves", (
                "CurrentHitPoints", "FortSaveThrow", "RefSaveThrow", "WillSaveThrow",
            )),
            ("Identity", ("FirstName", "LastName", "Appearance_Type", "Portrait")),
        ]
        by_name = {f.field: f for f in fields}
        placed: set[str] = set()
        for title, names in groups:
            present = [by_name[n] for n in names if n in by_name]
            if not present:
                continue
            layout.addWidget(w.cap_label(title))
            panel = w.Panel(padding=0)
            panel.body_layout().setSpacing(0)
            for field in present:
                panel.body_layout().addWidget(self._detail_row(field, field.field in pending))
                placed.add(field.field)
            layout.addWidget(panel)

        rest = [f for f in fields if f.field not in placed]
        if rest:
            layout.addWidget(w.cap_label("Other"))
            panel = w.Panel(padding=0)
            panel.body_layout().setSpacing(0)
            for field in rest:
                panel.body_layout().addWidget(self._detail_row(field, field.field in pending))
            layout.addWidget(panel)

        layout.addWidget(w.body(
            "These are the values the save stores. The engine recomputes what it "
            "derives from them — armour class, attack bonus, maximum hit points and "
            "the final saving throws — when the save is loaded.",
            t.TEXT_3, 11.5,
        ))
        layout.addStretch(1)

    def _detail_row(self, field, dirty: bool) -> QWidget:
        row = QWidget()
        row.setStyleSheet(
            f"background:{t.gold_tint(0.12) if dirty else 'transparent'};"
            f"border-bottom:1px solid {t.hairline(0.06)};"
        )
        line = QHBoxLayout(row)
        line.setContentsMargins(14, 8, 14, 8)
        line.setSpacing(12)
        if dirty:
            line.addWidget(w.status_dot())
        line.addWidget(w.body(field.display, t.GOLD if dirty else t.TEXT, 13), 1)

        if not self._window.editing:
            shown = self._shown_value(field)
            label = w.body(str(shown), t.TEXT_2, 13)
            label.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            line.addWidget(label)
            return row

        if field.kind == "name":
            edit = QLineEdit(str(field.value))
            edit.setStyleSheet(_input_qss())
            edit.setFixedWidth(220)
            edit.editingFinished.connect(
                lambda e=edit, f=field.field: self._set_name(f, e.text())
            )
            line.addWidget(edit)
        elif field.kind in ("appearance", "resref"):
            button = w.small_ghost(str(self._shown_value(field)))
            button.clicked.connect(lambda _=False, f=field: self._pick_look(f))
            line.addWidget(button)
        else:
            limits = self._limits(field.field, self._window.character_info())
            box = QSpinBox()
            box.setRange(
                max(limits.minimum, field.minimum), min(limits.maximum, field.maximum)
            )
            box.setToolTip(limits.reason)
            box.setValue(int(field.value))
            box.setFixedWidth(120)
            box.setStyleSheet(_input_qss())
            box.valueChanged.connect(
                lambda v, f=field.field: self._set_detail(f, v)
            )
            line.addWidget(box)
        return row

    def _shown_value(self, field):
        if field.kind == "appearance":
            return self._window.look_tables().appearance_name(int(field.value))
        return field.value

    def _set_detail(self, field: str, value: int) -> None:
        self._window.session().set_character_field(field, value, where=field)
        self._window.notify_changed()

    def _pick_look(self, field) -> None:
        from PySide6.QtWidgets import QDialog

        from vaultkeeper.ui.dialogs.id_picker_dialog import IdPickerDialog

        looks = self._window.look_tables()
        if field.kind == "appearance":
            options = looks.appearance_options()
        else:
            options = dict(enumerate(looks.portrait_resrefs()))
        dialog = w.style_dialog(
            IdPickerDialog(field.display, options, value_header=field.display, parent=self)
        )
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        chosen = dialog.selected_id()
        if chosen is None:
            return
        session = self._window.session()
        if field.kind == "appearance":
            session.set_character_field(field.field, int(chosen), where=field.display)
        else:
            session.set_character_resref(
                field.field, looks.portrait_resrefs()[int(chosen)], where=field.display
            )
        self._window.notify_changed()

    def _build_skills(self, layout: QVBoxLayout, info) -> None:
        layout.setSpacing(10)
        try:
            skills = self._window.session().player_skills()
        except Exception:
            skills = []
        if not skills:
            layout.addWidget(w.body("This character has no skill list.", t.TEXT_2))
            layout.addStretch(1)
            return

        self._skill_filter = QLineEdit()
        self._skill_filter.setPlaceholderText("Filter skills…")
        self._skill_filter.setStyleSheet(_input_qss())
        self._skill_filter.textChanged.connect(self._apply_skill_filter)
        layout.addWidget(self._skill_filter)

        totals = {x.index: x for x in self._skill_totals(skills, info)}
        header = QHBoxLayout()
        header.setContentsMargins(14, 0, 14, 0)
        header.addWidget(w.cap_label("Skill"), 1)
        header.addWidget(w.cap_label("Breakdown"))
        header.addSpacing(12)
        header.addWidget(w.cap_label("Total"))
        header.addSpacing(12)
        header.addWidget(w.cap_label("Rank"))
        layout.addLayout(header)

        panel = w.Panel(padding=0)
        panel.body_layout().setSpacing(0)
        self._skill_rows: list[tuple[str, QWidget]] = []
        # Skill order in the record is by id, which reads as random; sort by name.
        for skill in sorted(skills, key=lambda s: s.name.lower()):
            row = self._skill_row(skill, totals.get(skill.index))
            self._skill_rows.append((skill.name.lower(), row))
            panel.body_layout().addWidget(row)
        layout.addWidget(panel)
        layout.addWidget(w.body(
            "Total is rank + the skill's key ability modifier + bonuses from "
            "equipped gear. Feat and spell effects are not included — the save "
            "stores only ranks, and the rest is the engine's to recompute.",
            t.TEXT_3, 11.5,
        ))
        layout.addStretch(1)

    def _skill_totals(self, skills, info) -> list:
        from vaultkeeper.game import skill_totals

        abilities = dict(getattr(info, "abilities", {}) or {})
        try:
            items = self._window.session().player_items()
        except Exception:
            items = []
        return skill_totals.compute(
            skills, abilities, items, self._window.game_root()
        )

    def _skill_row(self, skill, total=None) -> QWidget:
        pending = {c.key for c in self._pending() if c.kind == "skill"}
        row = QWidget()
        row.setStyleSheet(f"background:transparent;border-bottom:1px solid {t.hairline(0.06)};")
        line = QHBoxLayout(row)
        line.setContentsMargins(14, 8, 14, 8)
        line.setSpacing(12)
        if skill.index in pending:
            line.addWidget(w.status_dot())
        line.addWidget(w.body(skill.name, t.TEXT, 13), 1)
        if total is not None:
            breakdown = w.mono(total.breakdown, t.TEXT_3, 11)
            line.addWidget(breakdown)
            line.addSpacing(12)
            shown = w.body(str(total.total), t.TEXT, 13)
            shown.setFixedWidth(46)
            shown.setStyleSheet(shown.styleSheet() + "font-weight:700;")
            shown.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            shown.setToolTip("rank + key ability + gear")
            line.addWidget(shown)
            line.addSpacing(12)

        if self._window.editing:
            info = self._window.character_info()
            limits = skill_limits(
                strict=self._window.rule_mode() == "strict",
                level=getattr(info, "level", 0) or 0,
            )
            box = QSpinBox()
            box.setRange(limits.minimum, limits.maximum)
            box.setToolTip(limits.reason)
            box.setValue(min(skill.rank, limits.maximum))
            box.setFixedWidth(64)
            box.setStyleSheet(_input_qss())
            box.valueChanged.connect(lambda v, s=skill: self._set_skill(s, v))
            line.addWidget(box)
        else:
            rank = w.body(str(skill.rank), t.TEXT, 13)
            rank.setFixedWidth(64)
            rank.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            line.addWidget(rank)
        return row

    def _set_skill(self, skill, rank: int) -> None:
        self._window.session().set_skill_rank(skill.index, rank, where=skill.name)
        self._window.notify_changed()

    def _apply_skill_filter(self, text: str) -> None:
        needle = text.strip().lower()
        for name, row in self._skill_rows:
            row.setVisible(needle in name)

    # -- Feats -------------------------------------------------------------- #
    def _build_feats(self, layout: QVBoxLayout, info) -> None:
        layout.setSpacing(10)
        try:
            feats = self._window.session().player_feats()
        except Exception:
            feats = []
        header = QHBoxLayout()
        header.addWidget(w.body(f"{len(feats)} feats", t.TEXT_2, 12))
        header.addStretch(1)
        if self._window.editing:
            add = w.small_ghost("+ Add a feat…")
            add.clicked.connect(self._add_feat)
            header.addWidget(add)
        layout.addLayout(header)

        self._feat_filter = QLineEdit()
        self._feat_filter.setPlaceholderText("Filter feats by name or id…")
        self._feat_filter.setStyleSheet(_input_qss())
        self._feat_filter.textChanged.connect(self._apply_feat_filter)
        layout.addWidget(self._feat_filter)

        added = {c.key[1] for c in self._pending() if c.kind == "feat"}
        panel = w.Panel(padding=0)
        panel.body_layout().setSpacing(0)
        self._feat_rows: list[tuple[str, QWidget]] = []
        for feat_id, name, is_base in feats:
            row = self._feat_row(feat_id, name, is_base, feat_id in added)
            self._feat_rows.append((f"{name.lower()} {feat_id}", row))
            panel.body_layout().addWidget(row)
        layout.addWidget(panel)
        layout.addStretch(1)

    def _feat_row(self, feat_id: int, name: str, is_base: bool, dirty: bool) -> QWidget:
        row = QWidget()
        row.setStyleSheet(f"background:transparent;border-bottom:1px solid {t.hairline(0.06)};")
        line = QHBoxLayout(row)
        line.setContentsMargins(14, 7, 14, 7)
        line.setSpacing(10)
        if dirty:
            line.addWidget(w.status_dot())
        line.addWidget(w.body(name, t.TEXT, 13), 1)
        if not is_base:
            line.addWidget(w.prc_badge())
        line.addWidget(w.mono(str(feat_id), t.TEXT_3, 11))
        if self._window.editing:
            remove = w.small_ghost("×")
            remove.setToolTip(f"Remove {name}")
            remove.clicked.connect(lambda _=False, i=feat_id, b=is_base: self._remove_feat(i, b))
            line.addWidget(remove)
        return row

    def _apply_feat_filter(self, text: str) -> None:
        needle = text.strip().lower()
        for haystack, row in self._feat_rows:
            row.setVisible(needle in haystack)

    def _add_feat(self) -> None:
        from PySide6.QtWidgets import QDialog

        from vaultkeeper.game.character_reference import default_reference
        from vaultkeeper.ui.dialogs.id_picker_dialog import IdPickerDialog

        reference = default_reference()
        feats = reference.all_feat_ids()
        prc = frozenset(fid for fid, _name in feats if not reference.is_base_feat(fid))
        dialog = IdPickerDialog(
            "Add a Feat", feats, mark_ids=prc, mark_label="PRC",
            value_header="Feat", parent=self,
        )
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        feat_id = dialog.selected_id()
        if feat_id is None:
            return
        if not reference.is_base_feat(feat_id) and not _confirm_prc(self, "feat"):
            return
        self._window.session().add_feat(feat_id)
        self._window.notify_changed()

    def _remove_feat(self, feat_id: int, is_base: bool) -> None:
        if not is_base and not _confirm_prc(self, "feat"):
            return
        self._window.session().remove_feat(feat_id)
        self._window.notify_changed()

    # -- Effects ------------------------------------------------------------ #
    def _build_effects(self, layout: QVBoxLayout, info) -> None:
        """Two answers to two different questions, behind one switch.

        ``Active effects`` is what the save literally stores; ``Active bonuses``
        is the computed "where do my numbers come from" view. The raw list alone
        does not answer the second question, and the computed one cannot replace
        the first, so neither is allowed to hide the other.
        """
        layout.setSpacing(12)
        switch = w.SegmentedControl(EFFECT_VIEWS)
        switch.set_value(self._effects_view)
        switch.changed.connect(lambda _: self._set_effects_view(switch.value()))
        row = QHBoxLayout()
        row.addWidget(switch)
        row.addStretch(1)
        layout.addLayout(row)

        if self._effects_view == "bonuses":
            self._build_bonuses(layout, info)
        else:
            self._build_active_effects(layout)

    def _set_effects_view(self, key: str) -> None:
        self._effects_view = key
        self.refresh()

    def _build_active_effects(self, layout: QVBoxLayout) -> None:
        effects = self._read_effects()
        if not effects:
            layout.addWidget(w.body("No active effects on this character.", t.TEXT_2))
            layout.addStretch(1)
            return
        panel = w.Panel(padding=0)
        panel.body_layout().setSpacing(0)
        # An effect can be stamped on a character many times over — the owner's
        # save carries three identical EffectHolyTouch entries. Collapsing them
        # the way the item panel collapses repeated properties keeps the list
        # about what is running rather than about how often it was applied.
        for effect, repeats in _collapse_effects(effects):
            panel.body_layout().addWidget(_effect_row(effect, repeats))
        layout.addWidget(panel)
        layout.addWidget(w.body(
            "Read-only — the engine derives these from equipped items, active feats "
            "and ongoing spells. To change one, edit the item, feat or spell that "
            "grants it. Effect types are shown as raw ids on purpose: the number a "
            "save stores is the engine's internal effect type, which is a different "
            "enum from the EFFECT_TYPE_* constants scripts see, so naming them from "
            "those would be confidently wrong.",
            t.TEXT_3, 12,
        ))
        layout.addStretch(1)

    # -- Effects → Active bonuses ------------------------------------------- #
    def _build_bonuses(self, layout: QVBoxLayout, info) -> None:
        """The computed view: every bonus this save can actually attribute."""
        bonuses = self._active_bonuses(info)
        layout.addWidget(w.body(
            "Where your numbers come from, as far as the save says. Each line names "
            "the item that grants it.",
            t.TEXT_2, 12.5,
        ))
        for category, groups in bonuses.by_category():
            layout.addWidget(w.cap_label(category))
            panel = w.Panel(padding=0)
            panel.body_layout().setSpacing(0)
            for group in groups:
                panel.body_layout().addWidget(_bonus_group_row(group))
            layout.addWidget(panel)

        if not bonuses.groups:
            layout.addWidget(w.body(
                "Nothing equipped on this character grants a magical property.",
                t.TEXT_2, 12.5,
            ))
        layout.addWidget(self._bonus_sources_panel(bonuses))
        layout.addWidget(w.body(_SCOPE_NOTE, t.TEXT_3, 11.5))
        layout.addStretch(1)

    def _bonus_sources_panel(self, bonuses) -> QWidget:
        """Classes, feats and ongoing effects — the sources that can't be summed."""
        holder = QWidget()
        holder.setStyleSheet("background:transparent;")
        column = QVBoxLayout(holder)
        column.setContentsMargins(0, 0, 0, 0)
        column.setSpacing(10)

        column.addWidget(w.cap_label("Classes"))
        panel = w.Panel(padding=14)
        panel.body_layout().setSpacing(6)
        panel.body_layout().addWidget(w.body(
            " · ".join(bonuses.classes) or "—", t.TEXT, 13
        ))
        facts = QHBoxLayout()
        facts.setSpacing(20)
        for label, value in bonuses.class_facts:
            facts.addWidget(_combat_stat(label, value, "stored on the record"))
        facts.addStretch(1)
        panel.body_layout().addLayout(facts)
        panel.body_layout().addWidget(w.body(
            "These four are the numbers the record stores, quoted as-is — what the "
            "engine folded into them before writing is not recorded. Everything "
            "else a class grants — bonus attacks, sneak dice, aura effects — it "
            "recomputes on load and never writes down at all.",
            t.TEXT_3, 11.5,
        ))
        column.addWidget(panel)

        column.addWidget(w.cap_label("Feats"))
        feats = w.Panel(padding=14)
        feats.body_layout().addWidget(w.body(
            f"{bonuses.feat_count} feats on this character. The save records which "
            "feats you have, never what each one contributes — that is the rules "
            "engine's arithmetic, so no feat is credited with a number here. Feats "
            "handed out by your gear are listed above under "
            "\"Feats granted by gear\".",
            t.TEXT_2, 12.5,
        ))
        column.addWidget(feats)

        column.addWidget(w.cap_label("Ongoing effects"))
        effects = w.Panel(padding=14)
        effects.body_layout().setSpacing(6)
        named = [e for e in bonuses.spell_effects if e.attributed]
        unnamed = [e for e in bonuses.spell_effects if not e.attributed]
        for effect in named:
            effects.body_layout().addWidget(w.body(
                f"{effect.name} — caster level {effect.caster_level}", t.TEXT, 12.5
            ))
        if not bonuses.spell_effects:
            effects.body_layout().addWidget(w.body("None running.", t.TEXT_2, 12.5))
        elif unnamed:
            effects.body_layout().addWidget(w.body(
                f"{len(unnamed)} of the {len(bonuses.spell_effects)} effects on this "
                "character name no spell. What each one changes is stored against the "
                "engine's internal effect enum, which this editor deliberately does "
                "not guess at — see the Active effects view for the raw entries.",
                t.TEXT_2, 12.5,
            ))
        column.addWidget(effects)
        return holder

    def _active_bonuses(self, info):
        from vaultkeeper.game import active_bonuses

        try:
            session = self._window.session()
            items, feats = session.player_items(), session.player_feats()
        except Exception:
            items, feats = [], []
        return active_bonuses.compute(
            items, feats, info, self._read_effects(), name_of=self._window.item_name,
        )

    def _read_effects(self) -> list[dict]:
        """The player's ``EffectList``, as far as it can be read without guessing.

        Deliberately does *not* name the effect type. The ``Type`` a save stores is
        the engine's internal effect enum, which does not share numbering with the
        ``EFFECT_TYPE_*`` constants in the game's ``nwscript.nss`` — those are what
        ``GetEffectType()`` hands to scripts. Checked against the owner's save: its
        three ``EffectHolyTouch`` effects carry ``Type`` 13 and 83, which in
        ``nwscript.nss`` are ``DEAF`` and ``CUTSCENEGHOST``. Mapping through that
        table would print confident nonsense, so the raw ids stand until the real
        serialized enum is sourced.
        """
        from vaultkeeper.game.character_reference import default_reference

        try:
            session = self._window.session()
            player = session._player_struct(session._module_tree())
        except Exception:
            return []
        effect_list = player.get("EffectList")
        if effect_list is None:
            return []
        reference = default_reference()
        effects = []
        for struct in effect_list.structs:
            spell_id = struct.get("SpellId")
            duration = struct.get("Duration") or 0.0
            # CasterLevel is a DWORD, so "unset" arrives as all-ones rather than 0 —
            # on the owner's save several effects carry 4294967295. Printing that as
            # a caster level would be nonsense, so it reads as "no caster level".
            caster = struct.get("CasterLevel") or 0
            effects.append({
                "tag": struct.get("CustomTag") or "",
                "type": struct.get("Type"),
                "subtype": struct.get("SubType"),
                "spell": (
                    reference.spell_name(spell_id)
                    if spell_id is not None and spell_id != _NO_ID
                    else ""
                ),
                "caster_level": 0 if caster == _NO_ID else caster,
                "duration": duration,
            })
        return effects

    # -- Biography ---------------------------------------------------------- #
    def _build_biography(self, layout: QVBoxLayout, info) -> None:
        layout.setSpacing(12)
        if info is None:
            layout.addWidget(w.body("This save has no readable character record.", t.TEXT_2))
            layout.addStretch(1)
            return
        pending = self._pending_char_fields()
        grid = w.Panel(padding=14)
        rows = grid.body_layout()
        for field, label in (("FirstName", "First name"), ("LastName", "Last name")):
            rows.addWidget(self._name_row(field, label, field in pending))
        layout.addWidget(grid)

        layout.addWidget(w.cap_label("Biography"))
        text = w.body(info.biography or "(no biography written)", t.TEXT_2, 13)
        text.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Minimum)
        bio = w.Panel(padding=14)
        bio.body_layout().addWidget(text)
        layout.addWidget(bio)
        layout.addStretch(1)

    def _name_row(self, field: str, label: str, dirty: bool) -> QWidget:
        row = QWidget()
        row.setStyleSheet("background:transparent;")
        line = QHBoxLayout(row)
        line.setContentsMargins(0, 0, 0, 0)
        line.setSpacing(10)
        if dirty:
            line.addWidget(w.status_dot())
        line.addWidget(w.body(label, t.TEXT_2, 13), 1)
        try:
            current = next(
                f for f in self._window.session().player_fields() if f.field == field
            ).value
        except Exception:
            current = ""
        if self._window.editing:
            edit = QLineEdit(str(current))
            edit.setStyleSheet(_input_qss())
            edit.setFixedWidth(220)
            edit.editingFinished.connect(lambda e=edit, f=field: self._set_name(f, e.text()))
            line.addWidget(edit)
        else:
            line.addWidget(w.body(str(current), t.TEXT, 13))
        return row

    def _set_name(self, field: str, text: str) -> None:
        self._window.session().set_character_name(field, text, where=field)
        self._window.notify_changed()


# --------------------------------------------------------------------------- #
# small builders
# --------------------------------------------------------------------------- #
def _input_qss() -> str:
    """A field or stepper's chrome, rebuilt per call so it follows the theme."""
    return (
        f"QLineEdit,QSpinBox{{background:{t.INPUT_BG};border:1px solid {t.hairline(0.18)};"
        f"border-radius:5px;color:{t.TEXT};font-family:{t.UI_FAMILY};font-size:12px;"
        f"padding:5px 8px;}}"
        f"QLineEdit:focus,QSpinBox:focus{{border-color:{t.gold_border(0.5)};}}"
    )


class _SheetCard(QFrame):
    """The skinned sheet. Named so its stylesheet can't leak onto child labels."""


def _scroll(body: QWidget) -> QScrollArea:
    """Wrap a tab body so it scrolls instead of stretching the window."""
    area = QScrollArea()
    area.setWidgetResizable(True)
    area.setFrameShape(QScrollArea.Shape.NoFrame)
    area.setStyleSheet(w.scroll_area_qss())
    area.setWidget(body)
    return area


def _clear(layout) -> None:
    """Remove every item from ``layout`` (used when a screen rebuilds)."""
    if layout is None:
        return
    while layout.count():
        item = layout.takeAt(0)
        widget = item.widget()
        if widget is not None:
            # Taking the item out of the layout does not unparent the widget, so
            # without this it keeps painting at its old geometry until the deferred
            # delete runs — the rebuilt content draws on top of the old.
            widget.setParent(None)
            widget.deleteLater()
        elif item.layout() is not None:
            _clear(item.layout())


def _display_name(info) -> str:
    return info.name.strip() if info is not None and info.name.strip() else "(unnamed)"


def _classes_line(info) -> str:
    return ", ".join(f"{class_name(cid)} {level}" for cid, level in info.classes) or "—"


def _alignment_badge(law: int, good: int) -> QLabel:
    badge = QLabel(f"{_lawful_chaotic_word(law)} {_good_evil_word(good)}")
    badge.setStyleSheet(
        f"color:{t.GOLD};background:{t.gold_tint(0.18)};border:1px solid {t.gold_border(0.4)};"
        f"border-radius:{t.RADIUS_BADGE}px;padding:2px 7px;"
        f"font-family:{t.UI_FAMILY};font-size:11px;font-weight:600;"
    )
    return badge


def _xp_bar(experience: int, level: int) -> QWidget:
    """XP with a progress bar toward the next level (NWN: level N needs N(N-1)/2 · 1000)."""
    holder = QWidget()
    holder.setStyleSheet("background:transparent;")
    holder.setFixedWidth(340)
    row = QHBoxLayout(holder)
    row.setContentsMargins(0, 0, 0, 0)
    row.setSpacing(8)

    this_level = level * (level - 1) // 2 * 1000
    next_level = (level + 1) * level // 2 * 1000
    span = max(1, next_level - this_level)
    fraction = min(1.0, max(0.0, (experience - this_level) / span))

    track = QFrame()
    track.setFixedHeight(6)
    track.setStyleSheet(f"background:{t.hairline(0.08)};border-radius:3px;")
    fill = QFrame(track)
    fill.setStyleSheet(f"background:{t.GOLD};border-radius:3px;")
    track_layout = QHBoxLayout(track)
    track_layout.setContentsMargins(0, 0, 0, 0)
    track_layout.addWidget(fill, int(fraction * 1000))
    track_layout.addStretch(max(1, int((1 - fraction) * 1000)))
    row.addWidget(track, 1)
    row.addWidget(w.mono(f"XP {experience:,} / {next_level:,}", t.TEXT_3, 11))
    return holder


def _sheet_divider() -> QFrame:
    line = QFrame()
    line.setFixedHeight(1)
    line.setStyleSheet(f"background:{t.hairline(0.12)};border:none;")
    return line


def _ability_row(
    field: str, label: str, score: int, was=None, *, limits=None, on_change=None
) -> QWidget:
    """One ability: gold initial chip, name, score, and the derived modifier.

    ``was`` is the pre-edit score when this ability has a staged change — the
    design shows it struck through beside the new value. ``on_change`` turns the
    score into a stepper; ``None`` (edit mode off) leaves it read-only.
    """
    dirty = was is not None
    row = QWidget()
    row.setStyleSheet(
        f"background:{t.gold_tint(0.12) if dirty else 'transparent'};"
        f"border-bottom:1px solid {t.hairline(0.08)};border-radius:6px;"
    )
    line = QHBoxLayout(row)
    line.setContentsMargins(4, 5, 4, 5)
    line.setSpacing(10)
    if dirty:
        line.addWidget(w.status_dot())

    chip = QLabel(field[0].upper())
    chip.setFixedSize(22, 22)
    chip.setAlignment(Qt.AlignmentFlag.AlignCenter)
    chip.setStyleSheet(
        f"border:1px solid {t.GOLD};border-radius:11px;color:{t.GOLD};"
        f"font-family:{t.UI_FAMILY};font-size:9px;font-weight:700;"
    )
    line.addWidget(chip)
    line.addWidget(w.body(label, t.SHEET_TEXT, 13.5), 1)

    if dirty:
        old = w.body(str(was), t.TEXT_3, 13)
        old.setStyleSheet(old.styleSheet() + "text-decoration:line-through;")
        old.setToolTip("The value in the save; the edit is staged, not written.")
        line.addWidget(old)

    if on_change is not None:
        stepper = QSpinBox()
        if limits is not None:
            stepper.setRange(limits.minimum, limits.maximum)
            stepper.setToolTip(limits.reason)
        else:
            stepper.setRange(1, 255)
        stepper.setValue(min(score, stepper.maximum()))
        stepper.setFixedWidth(62)
        stepper.setStyleSheet(_input_qss())
        stepper.valueChanged.connect(lambda v, f=field: on_change(f, v))
        line.addWidget(stepper)
    else:
        value = w.body(str(score), t.GOLD if dirty else t.SHEET_TEXT, 15)
        value.setStyleSheet(value.styleSheet() + "font-weight:700;")
        value.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        value.setFixedWidth(34)
        line.addWidget(value)

    modifier = ability_modifier(score)
    mod = w.body(_signed(modifier), t.GREEN if modifier >= 0 else t.DANGER, 13)
    mod.setStyleSheet(mod.styleSheet() + "font-weight:700;")
    mod.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
    mod.setFixedWidth(34)
    mod.setToolTip("Derived from the score — the engine recomputes it.")
    line.addWidget(mod)
    return row


def _fact(label: str, value: str, accent: str) -> QWidget:
    holder = QWidget()
    holder.setStyleSheet("background:transparent;")
    row = QHBoxLayout(holder)
    row.setContentsMargins(0, 0, 0, 0)
    row.setSpacing(5)
    row.addWidget(w.body(label, accent, 13))
    strong = w.body(value, t.SHEET_TEXT, 13)
    strong.setStyleSheet(strong.styleSheet() + "font-weight:700;")
    row.addWidget(strong)
    return holder


def _combat_stat(label: str, value: str, source: str) -> QWidget:
    holder = QWidget()
    holder.setStyleSheet("background:transparent;")
    holder.setMinimumWidth(120)
    column = QVBoxLayout(holder)
    column.setContentsMargins(0, 0, 0, 0)
    column.setSpacing(2)
    column.addWidget(w.cap_label(label))
    big = w.body(value, t.TEXT, 17)
    big.setStyleSheet(big.styleSheet() + "font-weight:700;")
    column.addWidget(big)
    column.addWidget(w.body(source, t.TEXT_3, 10.5))
    return holder


def _collapse_effects(effects: list[dict]) -> list[tuple[dict, int]]:
    """Fold effects that are identical in every field the row shows into ``N×``."""
    order: list[tuple] = []
    seen: dict[tuple, list] = {}
    for effect in effects:
        key = tuple(sorted(effect.items(), key=lambda kv: kv[0]))
        if key in seen:
            seen[key][1] += 1
        else:
            seen[key] = [effect, 1]
            order.append(key)
    return [(seen[key][0], seen[key][1]) for key in order]


def _effect_row(effect: dict, repeats: int = 1) -> QWidget:
    """One effect, meaningful parts first and the raw ids kept deliberately small.

    The spell that cast it, how long it has left and at what caster level are what
    a player can act on; ``Type``/``SubType`` are engine internals that must stay
    visible (they are all the save says about the untagged ones) without leading.
    """
    row = QWidget()
    row.setStyleSheet(f"background:transparent;border-bottom:1px solid {t.hairline(0.06)};")
    line = QHBoxLayout(row)
    line.setContentsMargins(14, 9, 14, 9)
    line.setSpacing(12)

    # With no spell and no tag the type id is genuinely all the save says, so it
    # names the row rather than leaving a column of identical "unnamed" lines.
    name = effect["spell"] or effect["tag"] or f"Effect type {effect['type']}"
    if repeats > 1:
        name = f"{repeats}×  {name}"
    title = w.body(name, t.TEXT, 13)
    if repeats > 1:
        title.setToolTip(f"The save carries {repeats} identical copies of this effect.")
    line.addWidget(title, 1)

    # The tag only earns its own column when it is not already the row's name.
    if effect["spell"] and effect["tag"]:
        line.addWidget(w.body(effect["tag"], t.TEXT_2, 12))
    caster = effect.get("caster_level")
    if caster:
        line.addWidget(w.body(f"caster level {caster}", t.TEXT_2, 12.5))
    duration = effect["duration"]
    line.addWidget(w.body(
        "permanent" if not duration else f"{duration:.0f}s left", t.TEXT_2, 12.5
    ))

    raw = w.mono(f"type {effect['type']}/{effect['subtype']}", t.TEXT_3, 10.5)
    raw.setToolTip(
        "The engine's internal effect type and subtype, exactly as the save stores "
        "them. They are not the EFFECT_TYPE_* constants scripts use — that is a "
        "different enum — so this editor shows the numbers rather than a wrong name."
    )
    line.addWidget(raw)
    return row


def _bonus_group_row(group) -> QWidget:
    """One thing a number feeds into, with every source that feeds it."""
    row = QWidget()
    row.setStyleSheet(f"background:transparent;border-bottom:1px solid {t.hairline(0.06)};")
    column = QVBoxLayout(row)
    column.setContentsMargins(14, 9, 14, 9)
    column.setSpacing(5)

    head = QHBoxLayout()
    head.setSpacing(10)
    subject = w.body(group.subject, t.TEXT, 13)
    subject.setStyleSheet(subject.styleSheet() + "font-weight:600;")
    head.addWidget(subject, 1)
    summary = w.body(group.summary, t.GOLD, 12.5)
    summary.setStyleSheet(summary.styleSheet() + "font-weight:700;")
    if group.largest is not None and group.total != group.largest:
        summary.setToolTip(
            "NWN applies only the largest item bonus of a given kind, so the sum is "
            "shown beside it rather than instead of it — the save does not record "
            "which the engine used."
        )
    head.addWidget(summary)
    column.addLayout(head)

    for contribution in group.contributions:
        line = QHBoxLayout()
        line.setContentsMargins(10, 0, 0, 0)
        line.setSpacing(8)
        # A fixed column keeps the descriptions aligned; item names run from four
        # characters to thirty, and a ragged left edge makes the list unreadable.
        source = w.body(contribution.source, t.TEXT_3, 11.5)
        source.setFixedWidth(_SOURCE_COLUMN)
        source.setToolTip(contribution.source)
        line.addWidget(source)
        line.addWidget(w.body(contribution.label, t.TEXT_2, 12), 1)
        if contribution.amount is not None:
            amount = w.mono(_signed(contribution.amount), t.TEXT_2, 11.5)
            if contribution.amount < 0:
                # NWN names these "Decreased …" and stores the size of the penalty
                # as a positive CostValue, so the description reads "+10" where the
                # effect is -10. Say which one this column is.
                amount.setToolTip(
                    "A penalty. The property is stored as a positive magnitude on a "
                    "\"Decreased …\" property, which is why its description reads +."
                )
            line.addWidget(amount)
        column.addLayout(line)
    return row


def _confirm_prc(parent, what: str) -> bool:
    """PRC regenerates its own content, so warn before staging an edit to it."""
    from PySide6.QtWidgets import QMessageBox

    answer = QMessageBox.warning(
        parent, f"PRC {what}",
        f"This {what} is managed by the PRC, which regenerates it from its own data "
        f"on rest, level-up or area load.\n\nThe edit will be staged, but it may not "
        f"stick in-game. Continue?",
        QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
    )
    return answer == QMessageBox.StandardButton.Yes
