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
from vaultkeeper.ui.save_editor import tokens as t
from vaultkeeper.ui.save_editor import widgets as w

#: The character screen's tabs, in the prototype's order.
TABS: tuple[tuple[str, str], ...] = (
    ("abilities", "Abilities & Combat"),
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

#: A sentinel ``SpellId``/``CreatorId``: the field is a DWORD, so "none" is all-ones.
_NO_ID = 0xFFFFFFFF


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
            border = t.GOLD if key == self._skin else "rgba(255,255,255,0.25)"
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
        classes = w.body(_classes_line(info), "#f1e6d8", 14)
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
        self._skill_filter.setStyleSheet(_INPUT_QSS)
        self._skill_filter.textChanged.connect(self._apply_skill_filter)
        layout.addWidget(self._skill_filter)

        panel = w.Panel(padding=0)
        panel.body_layout().setSpacing(0)
        self._skill_rows: list[tuple[str, QWidget]] = []
        for skill in skills:
            row = self._skill_row(skill)
            self._skill_rows.append((skill.name.lower(), row))
            panel.body_layout().addWidget(row)
        layout.addWidget(panel)
        layout.addStretch(1)

    def _skill_row(self, skill) -> QWidget:
        pending = {c.key for c in self._pending() if c.kind == "skill"}
        row = QWidget()
        row.setStyleSheet(f"background:transparent;border-bottom:1px solid {t.hairline(0.06)};")
        line = QHBoxLayout(row)
        line.setContentsMargins(14, 8, 14, 8)
        line.setSpacing(12)
        if skill.index in pending:
            line.addWidget(w.status_dot())
        line.addWidget(w.body(skill.name, t.TEXT, 13), 1)

        if self._window.editing:
            box = QSpinBox()
            box.setRange(0, 255)
            box.setValue(skill.rank)
            box.setFixedWidth(64)
            box.setStyleSheet(_INPUT_QSS)
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
        self._feat_filter.setStyleSheet(_INPUT_QSS)
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
        layout.setSpacing(10)
        effects = self._read_effects()
        if not effects:
            layout.addWidget(w.body("No active effects on this character.", t.TEXT_2))
            layout.addStretch(1)
            return
        panel = w.Panel(padding=0)
        panel.body_layout().setSpacing(0)
        for effect in effects:
            panel.body_layout().addWidget(_effect_row(effect))
        layout.addWidget(panel)
        layout.addWidget(w.body(
            "Read-only — the engine derives these from equipped items, active feats "
            "and ongoing spells. To change one, edit the item, feat or spell that "
            "grants it. Effect type ids are shown raw: the names live in the game's "
            "nwscript.nss, which Vaultkeeper does not read yet.",
            t.TEXT_3, 12,
        ))
        layout.addStretch(1)

    def _read_effects(self) -> list[dict]:
        """The player's ``EffectList``, as far as it can be read without guessing."""
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
            effects.append({
                "tag": struct.get("CustomTag") or "",
                "type": struct.get("Type"),
                "subtype": struct.get("SubType"),
                "spell": (
                    reference.spell_name(spell_id)
                    if spell_id is not None and spell_id != _NO_ID
                    else ""
                ),
                "caster_level": struct.get("CasterLevel") or 0,
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
            edit.setStyleSheet(_INPUT_QSS)
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
_INPUT_QSS = (
    f"QLineEdit,QSpinBox{{background:#1e1713;border:1px solid {t.hairline(0.18)};"
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
    area.setStyleSheet("QScrollArea{background:transparent;border:none;}" + w.SCROLLBAR_QSS)
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


def _ability_row(field: str, label: str, score: int, was=None, *, on_change=None) -> QWidget:
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
    line.addWidget(w.body(label, "#f1e6d8", 13.5), 1)

    if dirty:
        old = w.body(str(was), t.TEXT_3, 13)
        old.setStyleSheet(old.styleSheet() + "text-decoration:line-through;")
        old.setToolTip("The value in the save; the edit is staged, not written.")
        line.addWidget(old)

    if on_change is not None:
        stepper = QSpinBox()
        stepper.setRange(1, 100)  # the save-editor's own clamp for an ability score
        stepper.setValue(score)
        stepper.setFixedWidth(62)
        stepper.setStyleSheet(_INPUT_QSS)
        stepper.valueChanged.connect(lambda v, f=field: on_change(f, v))
        line.addWidget(stepper)
    else:
        value = w.body(str(score), t.GOLD if dirty else "#f1e6d8", 15)
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
    strong = w.body(value, "#f1e6d8", 13)
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


def _effect_row(effect: dict) -> QWidget:
    row = QWidget()
    row.setStyleSheet(f"background:transparent;border-bottom:1px solid {t.hairline(0.06)};")
    line = QHBoxLayout(row)
    line.setContentsMargins(14, 9, 14, 9)
    line.setSpacing(12)

    name = effect["tag"] or effect["spell"] or f"Effect type {effect['type']}"
    line.addWidget(w.body(name, t.TEXT, 13), 1)
    if effect["spell"]:
        line.addWidget(w.body(
            f"{effect['spell']} (caster level {effect['caster_level']})", t.TEXT_2, 12.5
        ))
    duration = effect["duration"]
    line.addWidget(w.body(
        "permanent" if not duration else f"{duration:.0f}s left", t.TEXT_2, 12.5
    ))
    line.addWidget(w.mono(f"type {effect['type']}/{effect['subtype']}", t.TEXT_3, 11))
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
