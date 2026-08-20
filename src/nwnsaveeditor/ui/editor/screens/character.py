"""The Character screen — the core character record, as a skinned NWN sheet.

Layout follows the design prototype's last pass: a header (portrait, name,
class/alignment/deity/gold, XP bar, sheet-skin switcher) above a tab strip of
``Abilities & Combat`` / ``Skills`` / ``Feats`` / ``Effects`` / ``Biography``.

Derived numbers — AC, attack bonus, saving throws, max HP — are shown but never
editable: the engine recomputes them from abilities, feats and gear on load, so
the screen points at the *source* to edit instead. That rule is set out in
``docs/save_game_editor.md``.
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
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from nwnfile.character import (
    _good_evil_word,
    _lawful_chaotic_word,
    class_name,
    is_base_race,
    race_name,
)
from nwnsaveeditor.rules import limits_for, skill_limits
from nwnsaveeditor.ui.editor import tokens as t
from nwnsaveeditor.ui.editor import widgets as w

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
        self._class_skill_set: set[int] = set()  # filled per Skills-tab build
        self._stale_pages: set[str] = set()  # tabs whose page needs a rebuild on show
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
        """Rebuild from the current save, edit gate and staged changes.

        Only the visible tab is rebuilt now; the others are marked stale and
        rebuilt the moment they are shown (see :meth:`_show_tab`). A page is
        hundreds of widgets — 137 feat rows on a real character, a bonuses view
        that runs to ~3800px — and building all six on every edit made editing
        and tab-switching drag. This mirrors how the top-level screens already
        build lazily on first display.
        """
        self._build_header(self._window.character_info())
        self._stale_pages = set(self._page_keys)
        self._show_tab()  # builds the current page and clears its stale flag
        self._mark_dirty_tabs()

    def _show_tab(self) -> None:
        key = self._tabs.value()
        index = self._page_keys.index(key)
        if key in self._stale_pages:
            self._rebuild_page(index, key)
        self._pages.setCurrentIndex(index)

    def _rebuild_page(self, index: int, key: str) -> None:
        # A fresh body per rebuild, handed to the page's scroll area. Clearing
        # and refilling the existing one leaves the QScrollArea sizing its widget
        # from the *old* content: with widgetResizable it does not re-measure when
        # its widget's children are swapped, so a page that grows gets squeezed
        # into the viewport and every panel collapses to a sliver.
        info = self._window.character_info()  # cached on the edit token; cheap
        body = QWidget()
        body.setStyleSheet("background:transparent;")
        layout = QVBoxLayout(body)
        layout.setContentsMargins(0, 0, 8, 0)
        getattr(self, f"_build_{key}")(layout, info)
        w.set_scroll_widget(self._pages.widget(index), body)  # takes ownership of the old
        self._page_bodies[index] = body
        self._stale_pages.discard(key)

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
        from nwnsaveeditor.ui.icons import tga_to_pixmap

        if info is None or not info.portrait_resref:
            return None
        path = self._window.portrait_path(info.portrait_resref, self._window.save)
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
        if self._window.editing and self._window.class_level_editing_enabled():
            add_level = w.small_ghost("+ Add class level…")
            add_level.clicked.connect(self._add_class_level)
            stats.addWidget(add_level)
        stats.addWidget(_sheet_divider())

        pending = self._pending_char_fields()
        editable = self._editable_fields()
        gear = self._ability_gear()
        for field, label in ABILITIES:
            score = self._field_value(field, info.abilities.get(field, 10))
            was = self._original_value(field) if field in pending else None
            # Only offer a stepper for a score the record actually carries:
            # SaveEditor writes a field only when it is present, so a stepper on a
            # missing one would look editable and silently do nothing.
            stats.addWidget(_ability_row(
                field, label, score, was,
                gear=gear.get(field),
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

    def _ability_gear(self) -> dict[str, object]:
        """``field -> AbilityTotal``: where each score comes from, part by part.

        The save holds base scores; the game's sheet adds the racial adjustment
        and everything worn, PRC's invisible skin included. Reading all of it
        back is what lets this show a total instead of a number that looks wrong.
        """
        try:
            rows = self._window.session().ability_breakdown(
                self._window.race_table(), classes=self._window.class_table()
            )
        except Exception:
            return {}
        return {row.field: row for row in rows}

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
        resistance = self._spell_resistance()
        if resistance is not None and resistance.sources:
            fact = _fact("Spell resistance:", str(resistance.effective), accent)
            fact.setToolTip(_resistance_tooltip(resistance))
            line.addWidget(fact)
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
        """The stored base numbers, with what is known to add to them.

        These are the values the record holds, and the same ones the Details tab
        edits — which was the confusion: nothing said whether a "Fortitude" of
        +12 was the base or the total. So each is labelled *base*, and the parts
        that can be attributed honestly are shown beneath it rather than folded
        into a single number the engine might not agree with.
        """
        holder = QWidget()
        holder.setStyleSheet("background:transparent;")
        column = QVBoxLayout(holder)
        column.setContentsMargins(0, 0, 0, 0)
        column.setSpacing(8)
        column.addWidget(w.body(
            "Each ability shows the base score the save stores — the one Details "
            "edits — then the score in play after your race, any PRC templates and "
            "everything you are wearing. Hover a total to see every part of it. "
            "Initiative is derived from Dexterity; the saving throws below are the "
            "values the record stores outright, the same numbers the game shows.",
            t.TEXT_3, 11.5,
        ))
        panel = w.Panel(padding=16)
        stats = QHBoxLayout()
        stats.setSpacing(24)
        # Modifiers come from the scores *in play*. Taken from the stored ones
        # they disagree with both the game and the Abilities rows just above:
        # a Constitution of 14 in the save is 55 on the character, +2 against +22.
        in_play = self._scores_in_play(info)
        dex = ability_modifier(in_play.get("Dex", 10))
        rows = [
            ("Base attack bonus", _signed(info.base_attack_bonus), "stored"),
            ("Initiative", _signed(dex), f"{_signed(dex)} Dex (derived)"),
            # The saving throws are stored outright, like BAB. They are NOT a class
            # base with ability and gear still to add: on a real character the
            # field holds the number the game itself shows (verified against the
            # owner's own save — an in-game Fortitude of 70 is a stored 70, not a
            # base of 43). So it is shown as it stands, not decomposed into parts
            # that would imply a larger total than the game ever displays.
            ("Fortitude save", _signed(info.save_fortitude), "stored"),
            ("Reflex save", _signed(info.save_reflex), "stored"),
            ("Will save", _signed(info.save_will), "stored"),
        ]
        for label, value, source in rows:
            stats.addWidget(_combat_stat(label, value, source))
        stats.addStretch(1)
        panel.body_layout().addLayout(stats)
        column.addWidget(panel)
        column.addWidget(w.body(
            "What each feat adds is not shown, because the save records which feats "
            "you have and never what they do. Attacks per round and off-hand "
            "attacks are not stored at all — a feat like Perfect Two-Weapon "
            "Fighting changes them in the running game only, so there is nothing "
            "here for it to appear as.",
            t.TEXT_3, 11,
        ))
        return holder

    def _spell_resistance(self):
        """Spell resistance and its sources, or ``None`` if it cannot be read."""
        try:
            session = self._window.session()
            names = {feat_id: name for feat_id, name, _base in session.player_feats()}
            return session.spell_resistance(
                self._window.hak_stack(),
                self._window.item_name,
                names.get,
                self._monk_level(),
                self._character_level(),
            )
        except Exception:
            return None

    def _character_level(self) -> int:
        """Total class levels — what PRC's racial resistance feats scale with."""
        try:
            from nwnfile.class_tables import character_classes

            session = self._window.session()
            player = session._player_struct(session._module_tree())
            return sum(level for _id, level in character_classes(player))
        except Exception:
            return 0

    def _monk_level(self) -> int:
        """Monk levels, which is what Diamond Soul's resistance is built from."""
        try:
            from nwnfile.class_tables import character_classes

            session = self._window.session()
            player = session._player_struct(session._module_tree())
            classes = self._window.class_table()
            for class_id, level in character_classes(player):
                if classes is not None and classes.label(class_id).lower() == "monk":
                    return level
        except Exception:
            pass
        return 0

    def _scores_in_play(self, info) -> dict[str, int]:
        """Ability scores after race, class levels, templates and worn gear.

        The single source anything deriving a modifier should use — saving
        throws, initiative and skills all read the same numbers the Abilities
        rows display, so the screen cannot contradict itself.
        """
        scores = {
            field: self._field_value(field, info.abilities.get(field, 10))
            for field, _label in ABILITIES
        }
        for field, row in self._ability_gear().items():
            if field in scores:
                scores[field] += row.added
        return scores

    # -- Skills ------------------------------------------------------------ #
    def _build_details(self, layout: QVBoxLayout, info) -> None:
        """Every editable field on the character record.

        The sheet card carries the ability scores; everything else the record
        stores — gold, XP, alignment, age, current HP, the saving throws, the name
        and the character's look — lives here, so no editable field is unreachable.
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
            ("Identity", ("FirstName", "LastName", "Race", "Appearance_Type", "Portrait")),
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

        # The six ability scores live on the sheet in Abilities & Combat, with
        # their derived modifiers beside them. Repeating them here as bare
        # steppers gave two editors for one value and no reason to prefer either.
        placed.update(field for field, _label in ABILITIES)
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
        elif field.kind == "race":
            button = w.small_ghost(str(self._shown_value(field)))
            button.clicked.connect(lambda _=False, f=field: self._pick_race(f))
            line.addWidget(button)
            if not is_base_race(int(field.value)):
                line.addWidget(w.prc_badge())
        else:
            limits = self._limits(field.field, self._window.character_info())
            box = w.stepper(
                minimum=max(limits.minimum, field.minimum),
                maximum=min(limits.maximum, field.maximum),
                value=int(field.value),
                tooltip=limits.reason,
                width=110,
                on_commit=lambda v, f=field.field: self._set_detail(f, v),
            )
            line.addWidget(box)
        return row

    def _shown_value(self, field):
        if field.kind == "appearance":
            return self._window.look_tables().appearance_name(int(field.value))
        if field.kind == "race":
            return race_name(int(field.value))
        return field.value

    def _pick_race(self, field) -> None:
        """Change the racial type.

        Race is one stored byte, but it is not only cosmetic: the engine reads it
        for racial ability adjustments and favoured class, and PRC builds its own
        races out of scripts and the creature skin. So the picker offers only
        what fits the byte, and says plainly when a choice is PRC's.
        """
        from PySide6.QtWidgets import QDialog, QMessageBox

        from nwnfile.character import race_options
        from nwnsaveeditor.ui.dialogs.id_picker_dialog import IdPickerDialog

        limits = self._limits("Race", self._window.character_info())
        options = [
            (race_id, name if is_base_race(race_id) else f"{name}  (PRC)")
            for race_id, name in race_options().items()
            if limits.minimum <= race_id <= limits.maximum
        ]
        dialog = w.style_dialog(
            IdPickerDialog("Race", options, value_header="Race", parent=self)
        )
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        race_id = dialog.selected_id()
        if race_id is None or race_id == int(field.value):
            return
        if not (is_base_race(race_id) and is_base_race(int(field.value))):
            answer = QMessageBox.warning(
                self, "PRC race",
                "PRC builds its races from its own scripts and the creature skin, "
                "not from this byte alone. Changing to or from one leaves the "
                "racial feats and abilities as they are, and PRC may put the old "
                "race back.\n\nStage it anyway?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            )
            if answer != QMessageBox.StandardButton.Yes:
                return
        self._set_detail("Race", race_id)

    def _set_detail(self, field: str, value: int) -> None:
        self._window.session().set_character_field(field, value, where=field)
        self._window.notify_changed()

    def _pick_look(self, field) -> None:
        from PySide6.QtWidgets import QDialog

        from nwnsaveeditor.ui.dialogs.id_picker_dialog import IdPickerDialog

        looks = self._window.look_tables()
        if field.kind != "appearance":
            self._pick_portrait(field, looks)
            return
        # The picker takes (id, name) pairs. Handing it a mapping iterates the
        # keys, so each "pair" is a bare int and it raises before it ever shows.
        options = sorted(looks.appearance_options().items())
        dialog = w.style_dialog(
            IdPickerDialog(field.display, options, value_header=field.display, parent=self)
        )
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        chosen = dialog.selected_id()
        if chosen is None:
            return
        self._window.session().set_character_field(
            field.field, int(chosen), where=field.display
        )
        self._window.notify_changed()

    def _pick_portrait(self, field, looks) -> None:
        """Portraits are chosen by looking at them, not by reading ``dw_f_07_``."""
        from PySide6.QtWidgets import QDialog

        from nwnsaveeditor.ui.dialogs.portrait_picker_dialog import PortraitPickerDialog

        info = self._window.character_info()
        dialog = w.style_dialog(PortraitPickerDialog(
            looks.portrait_entries(),
            self._window.portrait_source(),
            current=getattr(info, "portrait_resref", "") or "",
            female=bool(self._window.character_is_female()),
            parent=self,
        ))
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        chosen = dialog.selected_resref()
        if not chosen:
            return
        self._window.session().set_character_resref(
            field.field, chosen, where=field.display
        )
        self._window.notify_changed()

    def _class_skills_for(self, info) -> set[int]:
        """The character's class-skill ids, or empty when the tables can't be read
        — in which case every skill takes the generous class-skill cap."""
        stack = self._window.hak_stack()
        if stack is None or info is None:
            return set()
        try:
            from nwnfile.class_skills import class_skill_ids

            return class_skill_ids(stack, [cid for cid, _lvl in getattr(info, "classes", [])])
        except Exception:
            return set()

    def _skill_cap_is_class(self, skill_index: int) -> bool:
        # Unknown class-skill set -> treat as class skill (the generous bound).
        return not self._class_skill_set or skill_index in self._class_skill_set

    def _build_skills(self, layout: QVBoxLayout, info) -> None:
        layout.setSpacing(10)
        self._class_skill_set = self._class_skills_for(info)
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
            "equipped gear; hover one to see every part. The modifier comes from "
            "the ability score in play, which is how your race, class levels and "
            "any PRC templates reach a skill — none of them has skill columns of "
            "its own. Feat and spell effects are not included: the save stores "
            "only ranks, and the rest is the engine's to recompute.",
            t.TEXT_3, 11.5,
        ))
        layout.addStretch(1)

    def _skill_totals(self, skills, info) -> list:
        from nwnsaveeditor import skill_totals

        # The scores in play, not the stored ones: a skill's modifier comes from
        # the ability *after* race, class levels and templates, so the stored
        # score understates every skill of an adjusted character.
        abilities = self._scores_in_play(info)
        try:
            items = self._window.session().player_items()
        except Exception:
            items = []
        return skill_totals.compute(
            skills, abilities, items, self._window.game_root(), self._window.hak_stack()
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
            shown.setToolTip(total.detail())
            line.addWidget(shown)
            line.addSpacing(12)

        if self._window.editing:
            info = self._window.character_info()
            limits = skill_limits(
                strict=self._window.rule_mode() == "strict",
                level=getattr(info, "level", 0) or 0,
                class_skill=self._skill_cap_is_class(skill.index),
            )
            box = w.stepper(
                minimum=limits.minimum,
                maximum=limits.maximum,
                value=min(skill.rank, limits.maximum),
                tooltip=limits.reason,
                width=56,
                on_commit=lambda v, s=skill: self._set_skill(s, v),
            )
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
            # Warm the PRC feat-index in the background now, so the add-feat
            # confirm can classify a class/spellbook feat without a stall.
            self._window.prewarm_prc_index()
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

        from nwnfile.character_reference import default_reference
        from nwnsaveeditor.ui.dialogs.id_picker_dialog import IdPickerDialog

        reference = default_reference()
        feats = reference.all_feat_ids()
        prc = frozenset(fid for fid, _name in feats if not reference.is_base_feat(fid))
        categories, category_of = self._feat_categories(feats)
        dialog = IdPickerDialog(
            "Add a Feat", feats, mark_ids=prc, mark_label="PRC",
            value_header="Feat", categories=categories, category_of=category_of,
            parent=self,
        )
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        feat_id = dialog.selected_id()
        if feat_id is None:
            return
        if not reference.is_base_feat(feat_id):
            advice = self._window.prc_advise(feat_id)
            if not _confirm_prc_feat(self, advice):
                return
        self._window.session().add_feat(feat_id)
        self._window.notify_changed()

    def _feat_categories(self, feats):
        """Tag every feat id as ``taken`` / ``applicable`` / ``other`` for the
        picker's filter, or return no categories if the tables can't be read."""
        stack = self._window.hak_stack()
        if stack is None:
            return (), {}
        from nwnfile.feat_prerequisites import FeatSnapshot, meets_prerequisites

        session = self._window.session()
        snap = session.character_snapshot()
        info = self._window.character_info()
        fields = {  # numeric fields only — player_fields also carries names
            f.field: int(f.value)
            for f in session.player_fields()
            if isinstance(f.value, int)
        }
        char = FeatSnapshot(
            feats=snap.feats, skills=snap.skills, bab=snap.bab,
            abilities=getattr(info, "abilities", {}) or {},
            level=getattr(info, "level", 0) or 0,
            fort_save=fields.get("FortSaveThrow", 0),
        )
        # read feat.2da once — the stack does not cache, and this runs over 16k feats
        feat_table = stack.read_2da("feat") or {}

        class _Cached:
            def read_2da(self, name):
                return feat_table if name.lower() == "feat" else stack.read_2da(name)

        reader = _Cached()
        category_of: dict[int, str] = {}
        for fid, _name in feats:
            if fid in snap.feats:
                category_of[fid] = "taken"
            elif meets_prerequisites(reader, fid, char):
                category_of[fid] = "applicable"
            else:
                category_of[fid] = "other"
        categories = (("all", "All"), ("applicable", "Applicable"), ("taken", "Taken"))
        return categories, category_of

    def _remove_feat(self, feat_id: int, is_base: bool) -> None:
        if not is_base and not _confirm_prc(self, "feat"):
            return
        self._window.session().remove_feat(feat_id)
        self._window.notify_changed()

    # -- class level editing (opt-in) ------------------------------------- #
    def _ability_mod(self, field: str) -> int:
        try:
            score = self._window.character_info().abilities.get(field, 10)
        except Exception:
            score = 10
        return (int(score) - 10) // 2

    def _add_class_level(self) -> None:
        from PySide6.QtWidgets import QDialog, QMessageBox

        from nwnsaveeditor.ui.dialogs.id_picker_dialog import IdPickerDialog

        stack = self._window.hak_stack()
        if stack is None:
            w.message(
                self, QMessageBox.Icon.Warning, "Add class level",
                "The class tables can't be read for this save, so a level cannot "
                "be computed.",
                QMessageBox.StandardButton.Ok,
            )
            return
        strict = self._window.rule_mode() == "strict"
        options, non_player = _class_options(stack, strict)
        # In Free the list widens to every real class; those not meant for players
        # are marked, and never a class absent from the stack (it isn't in options).
        dialog = IdPickerDialog(
            "Add a class level", options, mark_ids=frozenset(non_player),
            mark_label="not a player class", value_header="Class", parent=self,
        )
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        class_id = dialog.selected_id()
        if class_id is None:
            return
        session = self._window.session()
        if not self._confirm_class_choice(session, stack, class_id, class_id in non_player):
            return
        from nwnfile.level_up import LevelUpCalculator

        current = dict(session.player_classes())
        new_total = sum(current.values()) + 1
        gains = LevelUpCalculator(stack).gains(
            class_id, current.get(class_id, 0) + 1, character_level=new_total,
        )
        if gains is None:
            return
        wizard = self._build_level_wizard(gains, new_total)
        if wizard.exec() != QDialog.DialogCode.Accepted:
            return
        self._apply_level(session, class_id, gains, wizard)
        self._window.notify_changed()

    def _confirm_class_choice(self, session, stack, class_id: int, non_player: bool) -> bool:
        """Gate a chosen class on its prerequisites (and a non-player warning).

        Strict blocks a class whose requirements the character does not meet; Free
        warns and lets it through (the save loads either way — the game checks
        prerequisites at level-up, not on load). Unverifiable requirements (spell
        level, module script flags) are shown but never block.
        """
        from PySide6.QtWidgets import QMessageBox

        from nwnfile.character_reference import default_reference
        from nwnfile.class_prerequisites import check_prerequisites

        ref = default_reference()
        result = check_prerequisites(
            stack, class_id, session.character_snapshot(),
            feat_name=ref.feat_name, skill_name=ref.skill_name,
            race_name=self._race_name, class_name=class_name,
        )
        strict = self._window.rule_mode() == "strict"
        name = class_name(class_id)
        parts: list[str] = []
        if non_player:
            parts.append(
                f"{name} is not a player class. The game may not run its features "
                "correctly on a PC."
            )
        if result.unmet:
            parts.append("This character does not meet:\n  • " + "\n  • ".join(result.unmet))
        if result.unverifiable:
            parts.append(
                "Cannot be checked from the save (the game may still require them):\n  • "
                + "\n  • ".join(result.unverifiable)
            )
        if not parts:
            return True  # everything checkable is met, and it is a player class

        if strict and result.unmet:  # Strict refuses an unmet requirement
            w.message(
                self, QMessageBox.Icon.Warning, f"Add {name}",
                "\n\n".join(parts)
                + "\n\nStrict rule mode blocks this. Switch to Free to override.",
                QMessageBox.StandardButton.Ok,
            )
            return False
        answer = w.message(  # Free (or only warnings): let the user decide
            self, QMessageBox.Icon.Question, f"Add {name}",
            "\n\n".join(parts) + "\n\nAdd this class anyway?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        return answer == QMessageBox.StandardButton.Yes

    def _race_name(self, race_id: int) -> str:
        table = self._window.race_table()
        try:
            return table.label(race_id) if table is not None else f"race #{race_id}"
        except Exception:
            return f"race #{race_id}"

    def _wizard_skill_caps(self, session, gains, new_total, skills, strict) -> dict[int, int]:
        """Per-skill rank caps for the wizard: in Strict, a class skill of any of
        the character's classes (including the one being added) caps at level + 3,
        a cross-class skill at half that. Empty in Free — the storable range applies.
        """
        if not strict:
            return {}
        from nwnfile.class_skills import class_skill_ids, skill_rank_cap

        stack = self._window.hak_stack()
        class_ids = [cid for cid, _lvl in session.player_classes()] + [gains.class_id]
        cset = class_skill_ids(stack, class_ids) if stack is not None else set()
        return {
            s.index: skill_rank_cap(new_total, class_skill=not cset or s.index in cset)
            for s in skills
        }

    def _build_level_wizard(self, gains, new_total: int):
        """A :class:`LevelUpWizard` fed the character's own budgets and options."""
        from nwnsaveeditor.rules import skill_limits
        from nwnsaveeditor.ui.dialogs.level_up_wizard import LevelUpWizard

        session = self._window.session()
        try:
            skills = session.player_skills()
        except Exception:
            skills = []
        strict = self._window.rule_mode() == "strict"
        cap = skill_limits(strict=strict, level=new_total).maximum  # Free fallback
        skill_caps = self._wizard_skill_caps(session, gains, new_total, skills, strict)
        feat_options: list[tuple[int, str]] = []
        prc_ids: frozenset[int] = frozenset()
        if gains.general_feat:  # only load the (large) feat list when a feat is due
            from nwnfile.character_reference import default_reference

            reference = default_reference()
            feat_options = list(reference.all_feat_ids())
            prc_ids = frozenset(
                fid for fid, _n in feat_options if not reference.is_base_feat(fid)
            )
        scores = {
            f.field: int(f.value)
            for f in session.player_fields()
            if f.field in ("Str", "Dex", "Con", "Int", "Wis", "Cha")
        }
        current = dict(session.player_classes())
        spells = self._spells_known_options(
            gains.class_id, current.get(gains.class_id, 0), gains.class_level
        )
        return LevelUpWizard(
            gains,
            con_modifier=self._ability_mod("Con"),
            int_modifier=self._ability_mod("Int"),
            new_total_level=new_total,
            skills=skills,
            skill_cap=cap,
            skill_caps=skill_caps,
            feat_options=feat_options,
            prc_feat_ids=prc_ids,
            ability_scores=scores,
            spells_known_options=spells,
            parent=self,
        )

    def _spells_known_options(self, class_id, prev_class_level, new_class_level):
        """``{spell level: (budget, [(id, name)])}`` for a spontaneous caster level.

        Empty unless the class has a ``SpellKnownTable`` granting new spells and its
        castable list is known (``spells.2da``) — PRC classes it can't list are left
        to the spellbook editor.
        """
        from nwnfile.character_reference import default_reference
        from nwnfile.spells_known import spells_known_gained
        from nwnsaveeditor.spell_levels import SpellLevels

        stack = self._window.hak_stack()
        if stack is None:
            return {}
        budget = spells_known_gained(stack, class_id, prev_class_level, new_class_level)
        if not budget:
            return {}
        user = getattr(getattr(self._window._controller, "ctx", None), "game_user_dir", None)
        levels = SpellLevels.for_install(
            self._window.game_root(), (user / "hak") if user else None
        )
        if not levels.describes(class_id):
            return {}  # can't list this class's spells (e.g. a PRC caster)
        ref = default_reference()
        options: dict[int, tuple[int, list[tuple[int, str]]]] = {}
        for spell_level, count in budget.items():
            available = [
                (sid, ref.spell_name(sid))
                for sid in sorted(levels.spells_at(class_id, spell_level))
            ]
            if available:
                options[spell_level] = (count, available)
        return options

    def _apply_level(self, session, class_id: int, gains, wizard) -> None:
        """Commit the level and every choice the wizard gathered, in one act.

        The level and its history entry go first (the history records the choices,
        and its skill deltas are measured against the ranks before they change);
        then the choices are applied to the live character through their own
        editors, so their ledger entries and PRC caveats still show.
        """
        skill_ranks = wizard.skill_allocations()
        chosen_feat = wizard.chosen_feat()
        granted = [fid for fid, _name in gains.granted_feats]
        feats_gained = ([chosen_feat] if chosen_feat is not None else []) + granted
        ability = wizard.chosen_ability()

        session.add_class_level(
            class_id, gains,
            con_modifier=self._ability_mod("Con"),
            int_modifier=self._ability_mod("Int"),
            skill_ranks=skill_ranks, feats=tuple(feats_gained), ability=ability,
            spells_known=wizard.chosen_spells(),
        )
        names = {s.index: s.name for s in session.player_skills()}
        for index, rank in skill_ranks.items():
            session.set_skill_rank(index, rank, where=names.get(index, f"Skill {index}"))
        for feat_id in feats_gained:  # the picked feat and any the class auto-grants
            session.add_feat(feat_id)
        if ability is not None:
            scores = {
                f.field: int(f.value)
                for f in session.player_fields()
                if f.field == ability
            }
            session.set_character_field(
                ability, scores.get(ability, 10) + 1, where=f"{ability} (+1)"
            )

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
        from nwnsaveeditor import active_bonuses

        try:
            session = self._window.session()
            items, feats = session.player_items(), session.player_feats()
        except Exception:
            items, feats = [], []
        return active_bonuses.compute(
            items, feats, info, self._read_effects(),
            name_of=self._window.item_name,
            # Without the game's tables a CostValue that names a thing renders
            # as a magnitude — "Immunity Specific Spell +216" for Flesh to Stone.
            tables=self._window.property_tables(),
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
        from nwnfile.character_reference import default_reference

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
        if self._window.editing:
            # The name used to be editable here *and* under Details → Identity.
            # Two editors for one field means one of them is always showing a
            # stale value, so this one shows and Details edits.
            layout.addWidget(w.body(
                "Edit the name under Details → Identity.", t.TEXT_3, 11.5
            ))

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
        line.addWidget(w.body(str(current), t.GOLD if dirty else t.TEXT, 13))
        return row

    def _set_name(self, field: str, text: str) -> None:
        self._window.session().set_character_name(field, text, where=field)
        self._window.notify_changed()


# --------------------------------------------------------------------------- #
# small builders
# --------------------------------------------------------------------------- #
def _class_options(stack, strict: bool) -> tuple[list[tuple[int, str]], set[int]]:
    """The class picker's rows and which of them are non-player classes.

    Strict offers only player classes (``PlayerClass == 1``). Free widens to every
    real ``classes.2da`` row — a class the game can actually resolve — marking the
    ones not meant for PCs. Never a class id absent from the stack: it isn't a row.
    """
    non_player: set[int] = set()
    options: list[tuple[int, str]] = []
    for class_id, row in sorted((stack.read_2da("classes") or {}).items()):
        label = (row.get("Label") or "").replace("_", " ")
        if label in ("", "****"):
            continue
        if (row.get("PlayerClass") or "") != "1":
            if strict:
                continue
            non_player.add(class_id)
        options.append((class_id, label))
    return options, non_player


def _input_qss() -> str:
    """A field or stepper's chrome, rebuilt per call so it follows the theme."""
    return (
        f"QLineEdit,QSpinBox{{background:{t.INPUT_BG};border:1px solid {t.hairline(0.18)};"
        f"border-radius:5px;color:{t.TEXT};font-family:{t.UI_FAMILY};font-size:12px;"
        f"padding:5px 8px;selection-background-color:{t.gold_tint(0.5)};"
        f"selection-color:{t.GOLD};}}"
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
            w.retire(widget)
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


def _resistance_tooltip(resistance) -> str:
    """Name every source, and say plainly that only one of them counts."""
    applies = resistance.applies
    lines = [f"Spell resistance {resistance.effective}", f"    from {applies.label}"]
    if resistance.overridden:
        lines.append("")
        lines.append("Also present, but doing nothing — resistance does not stack,")
        lines.append("only the greatest source applies:")
        lines += [f"    {s.value}\t{s.label}" for s in resistance.overridden]
    lines.append("")
    lines.append(
        "A caster rolls d20 + caster level + spell penetration against this."
        if not resistance.immune_to_player_casters
        else "Above 66, so no spell a player can cast will get through."
    )
    lines.append(
        "Resistance from the spell of the same name is temporary and is not counted."
    )
    return "\n".join(lines)


_KIND_WORD = {"race": "race", "template": "template", "item": "worn"}


def _breakdown_tooltip(label: str, total, base: int | None = None) -> str:
    """Name every part of an ability score, so the total can be checked.

    ``base`` overrides the stored score, so that while editing the sum shown
    follows the stepper rather than describing the save it came from.
    """
    base = total.base if base is None else base
    lines = [f"{label} {base + total.added} in play", f"    {base}\tbase, as stored in the save"]
    for part in total.components:
        kind = _KIND_WORD.get(part.kind, part.kind)
        lines.append(f"    {part.amount:+d}\t{part.source} ({kind})")
    if not total.attributed:
        lines.append(
            "\nPart of this comes from the PRC skin, whose own registry did not "
            "account for the whole amount; it is shown as the item rather than "
            "split between templates."
        )
    return "\n".join(lines)


def _ability_row(
    field: str, label: str, score: int, was=None, *, limits=None, on_change=None,
    gear=None,
) -> QWidget:
    """One ability: gold initial chip, name, score, and the derived modifier.

    ``was`` is the pre-edit score when this ability has a staged change — the
    design shows it struck through beside the new value. ``on_change`` turns the
    score into a stepper; ``None`` (edit mode off) leaves it read-only.

    ``gear`` is an ``AbilityTotal``: the racial adjustment, each PRC template and
    each worn item that raises this ability. The row shows the total beside the
    stored base — the stored number alone reads far below the game's sheet — and
    names every part in the tooltip, so a disagreement with the game shows up at
    a named contribution rather than as one unexplained number.
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
        low, high = (limits.minimum, limits.maximum) if limits is not None else (1, 255)
        stepper = w.stepper(
            minimum=low,
            maximum=high,
            value=min(score, high),
            tooltip=limits.reason if limits is not None else "",
            width=54,
            on_commit=lambda v, f=field: on_change(f, v),
        )
        line.addWidget(stepper)
    else:
        value = w.body(str(score), t.GOLD if dirty else t.SHEET_TEXT, 15)
        value.setStyleSheet(value.styleSheet() + "font-weight:700;")
        value.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        value.setFixedWidth(34)
        line.addWidget(value)

    # The score in play, after race, templates and gear — what the game's sheet
    # shows. It follows the stored value so the row reads "29 → 62", and the
    # modifier below is taken from it: a modifier derived from the base instead
    # would sit beside the total contradicting it.
    in_play = score
    if gear is not None and gear.components:
        in_play = score + gear.added
        total = w.body(f"→ {in_play}", t.GOLD, 15)
        total.setStyleSheet(total.styleSheet() + "font-weight:700;")
        total.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        total.setFixedWidth(56)
        total.setToolTip(_breakdown_tooltip(label, gear, score))
        line.addWidget(total)
    else:
        line.addSpacing(56)

    modifier = ability_modifier(in_play)
    mod = w.body(_signed(modifier), t.GREEN if modifier >= 0 else t.DANGER, 13)
    mod.setStyleSheet(mod.styleSheet() + "font-weight:700;")
    mod.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
    mod.setFixedWidth(34)
    mod.setToolTip(
        "Derived from the score in play, as the engine derives it."
        if in_play != score
        else "Derived from the score — the engine recomputes it."
    )
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
        w.set_tooltip(source, contribution.source)
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


def _confirm_prc_feat(parent, advice) -> bool:
    """Confirm adding a PRC feat, showing what an edit can actually grant.

    ``advice`` is a :class:`nwnfile.prc_advice.FeatAdvice`, or ``None`` when the
    game data can't be read — then fall back to the generic PRC warning.
    """
    if advice is None:
        return _confirm_prc(parent, "feat")
    from PySide6.QtWidgets import QMessageBox

    answer = QMessageBox.warning(
        parent, f"Add PRC feat: {advice.label}",
        f"{advice.headline}\n\n{advice.direction}\n\n"
        "The edit will be staged either way. Continue?",
        QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
    )
    return answer == QMessageBox.StandardButton.Yes
