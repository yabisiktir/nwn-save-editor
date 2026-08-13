"""The Save Game Editor's global shell — toolbar, sidebar, content, pending footer.

This is the frame the editor was designed around; the screens that fill
it live in :mod:`nwnsaveeditor.ui.editor.screens` and are added one at a time.
Sections with no screen yet render the design's centred empty-state card.

Editing is a *global gate*: with Edit off the window is a viewer — the pending
footer is hidden and Save/Overwrite are inert. Nothing is written until the user
commits, and committing goes through the same
:class:`~nwnsaveeditor.save_editor.SaveEditor` the read-only viewer uses, so the
staging, byte-verification and backup guarantees are unchanged.
"""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from nwnsaveeditor.save_game import SaveGame, scan_save_games
from nwnsaveeditor.ui.editor import tokens as t
from nwnsaveeditor.ui.editor import widgets as w
from nwnsaveeditor.ui.editor.appicon import app_icon
from nwnsaveeditor.ui.editor.sections import (
    SECTION_BLURBS,
    SECTIONS,
    Section,
    by_key,
    section_for_kind,
)
from nwnsaveeditor.ui.icons import item_icon_source, tga_to_pixmap

#: How tall the sidebar's save list may grow before it scrolls (~4 rows).
_SAVES_LIST_MAX_H = 196

#: "not built yet", distinct from a cached ``None`` meaning "tried and unavailable".
#: how wide one footer pending-change sample may get before it is elided.
_CHIP_WIDTH = 300


def _save_label_text(save: SaveGame | None) -> str:
    if save is None:
        return "No save open"
    return f"{save.name}  —  {save.location or 'no location'}"


class _LazyScreens(dict):
    """Section screens, built the first time they are asked for.

    Building all nine up front cost ~2.4s on the owner's save — every one re-reads
    the character, and Raw Data enumerates all 134 resources — so opening the
    editor stalled before showing anything. ``dict.get`` deliberately does *not*
    build, so a refresh only touches screens that already exist.
    """

    def __init__(self, build) -> None:
        super().__init__()
        self._build = build

    def __missing__(self, key: str):
        screen = self._build(key)
        self[key] = screen
        return screen  # freshly built, so already current


def _saved_theme(controller) -> str:
    """The theme the editor should open with.

    An embedding host may dictate the theme through an optional ``editor_theme()``
    (the same opt-in pattern as ``portrait_path``): Vaultkeeper returns its own
    light/dark so the editor matches the app it was launched from rather than
    looking out of place. Standalone — or any host without it — falls back to the
    editor's own remembered light/dark choice, defaulting to dark.
    """
    host_theme = getattr(controller, "editor_theme", None)
    if callable(host_theme):
        try:
            value = host_theme()
            if value in ("dark", "light"):
                return value
        except Exception:
            pass
    try:
        return controller._settings().save_editor_theme
    except Exception:
        return "dark"


def _icon_source(controller):
    """The item-icon source, or ``None``.

    Icons are decoration: they need a configured game folder and the controller's
    settings, and the editor must still work without either.
    """
    if controller is None:
        return None
    try:
        return item_icon_source(controller)
    except Exception:
        return None


def _base_name(name: str) -> str:
    """``"000012 - Kaelen"`` -> ``"Kaelen"`` (drop the game's numeric prefix)."""
    _, sep, rest = name.partition(" - ")
    return rest if sep else name


def _next_save_folder(saves_dir: Path, name: str) -> Path:
    """The next free ``NNNNNN - name`` folder, matching how the game numbers saves."""
    used = set()
    for folder in saves_dir.glob("* - *"):
        prefix = folder.name.split(" - ", 1)[0]
        if prefix.isdigit():
            used.add(int(prefix))
    number = next(n for n in range(1, 1_000_000) if n not in used)
    return saves_dir / f"{number:06d} - {name}"


class SaveEditorWindow(QMainWindow):
    """The full-window save editor."""

    def __init__(
        self, saves: list[SaveGame], controller=None, parent: QWidget | None = None
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("Save Game Editor")
        self.setWindowIcon(app_icon())
        self.resize(t.WINDOW_W, t.WINDOW_H)
        self._controller = controller
        self._saves = list(saves)
        self._current: SaveGame | None = None
        self._session = None  # SaveEditor, built on the first edit
        self._races = None  # RaceTable for the open save's haks
        self._classes = None  # ClassTable for the open save's haks
        self._editing = False
        self._nav_rows: dict[str, w.NavRow] = {}
        self._save_rows: list[_SaveRow] = []
        self._screens: dict[str, QWidget] = {}
        self._char_cache = None  # CharacterInfo for _char_cache_for
        self._char_cache_for: Path | None = None
        self._rebuilding = False
        self._icons = _icon_source(controller)
        self._prc_advisor = None  # built + cached on first PRC-feat classification
        self._prc_cache_path = None
        self._prc_prewarm = None  # background thread building the membership index
        # Set the theme first: everything below reads token colours as it builds.
        t.set_theme(_saved_theme(controller))

        self._build_ui()
        if self._saves:
            self._select_save(self._saves[0])
        self._set_section("character")
        self._sync_edit_state()
        self._install_shortcuts()

    def _build_ui(self) -> None:
        """Build the whole window from the current palette.

        Called again when the theme changes: every widget bakes its token colours
        into a stylesheet as it is constructed, so re-setting a few stylesheets
        would leave buttons and labels wearing the old palette.
        """
        self._nav_rows.clear()
        self._save_rows.clear()
        self._screens.clear()

        self.setStyleSheet(f"QMainWindow{{background:{t.APP_BG};}}")
        root = QWidget()
        root.setStyleSheet(f"background:{t.APP_BG};")
        self.setCentralWidget(root)  # replaces and deletes any previous central widget
        outer = QVBoxLayout(root)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        outer.addWidget(self._build_toolbar())
        middle = QHBoxLayout()
        middle.setContentsMargins(0, 0, 0, 0)
        middle.setSpacing(0)
        middle.addWidget(self._build_sidebar())
        middle.addWidget(self._build_content(), 1)
        outer.addLayout(middle, 1)
        outer.addWidget(self._build_footer())

        from nwnsaveeditor.ui.editor.ledger import ChangeLedger

        ledger = getattr(self, "_ledger", None)
        if ledger is not None:
            w.retire(ledger)
        self._ledger = ChangeLedger(self)

    # -- toolbar ---------------------------------------------------------- #
    def _build_toolbar(self) -> QWidget:
        bar = self._toolbar = QWidget()
        bar.setFixedHeight(t.TOOLBAR_H)
        bar.setStyleSheet(
            f"background:{t.SURFACE};border-bottom:1px solid {t.hairline(0.08)};"
        )
        layout = QHBoxLayout(bar)
        layout.setContentsMargins(20, 0, 20, 0)
        layout.setSpacing(12)

        from nwnsaveeditor.ui.editor.host import wordmark_for

        wordmark = self._wordmark = QLabel(wordmark_for(self._controller))
        wordmark.setStyleSheet(
            f"font-family:{t.DISPLAY_FAMILY};font-size:15px;font-weight:700;"
            f"letter-spacing:0.04em;color:{t.GOLD};background:transparent;"
        )
        layout.addWidget(wordmark)
        layout.addWidget(w.vline())

        # Built fresh on every theme rebuild, so seed it from the current save
        # rather than leaving a rebuilt toolbar claiming nothing is open.
        self._save_label = w.body(_save_label_text(self._current), t.TEXT_2, 12.5)
        self._save_label.setWordWrap(False)
        layout.addWidget(self._save_label)
        layout.addStretch(1)

        self._open_btn = w.ghost_button("Open Save…")
        self._open_btn.setToolTip("Open another save  (Ctrl+O)")
        self._open_btn.clicked.connect(self._choose_save)
        layout.addWidget(self._open_btn)
        guide = w.ghost_button("Guide…")
        guide.setToolTip("How the save editor works  (F1)")
        guide.clicked.connect(self._show_guide)
        layout.addWidget(guide)
        settings = w.ghost_button("Settings…")
        settings.setToolTip("Which game folders the editor is reading  (Ctrl+,)")
        settings.clicked.connect(self._show_settings)
        layout.addWidget(settings)

        self._rule_mode = w.SegmentedControl((("strict", "Strict"), ("free", "Free")))
        self._rule_mode.changed.connect(lambda _: self._refresh_screens())
        self._rule_mode.setToolTip(
            "Strict blocks values that break the game's rules. Free writes them as "
            "entered — the game may clamp or reject them on load."
        )
        layout.addWidget(self._rule_mode)

        self._undo_btn = w.ghost_button("Undo")
        self._undo_btn.setToolTip("Undo the last staged change  (Ctrl+Z)")
        self._redo_btn = w.ghost_button("Redo")
        self._redo_btn.setToolTip("Redo an undone change  (Ctrl+Shift+Z)")
        self._theme_toggle = w.SegmentedControl((("dark", "Dark"), ("light", "Light")))
        self._theme_toggle.set_value(t.active_theme())
        self._theme_toggle.setToolTip("The editor's colour theme")
        self._theme_toggle.changed.connect(lambda _: self._set_theme(self._theme_toggle.value()))
        layout.addWidget(self._theme_toggle)

        self._undo_btn.clicked.connect(self._undo)
        self._redo_btn.clicked.connect(self._redo)
        for button in (self._undo_btn, self._redo_btn):
            button.setEnabled(False)  # until there is something on the stack
            layout.addWidget(button)

        self._edit_toggle = w.pill_toggle("Edit")
        self._edit_toggle.setToolTip("Enter or leave edit mode  (Ctrl+E)")
        self._edit_toggle.toggled.connect(self._set_edit_mode)
        layout.addWidget(self._edit_toggle)

        self._save_new_btn = w.gold_button("Save as New…")
        self._save_new_btn.setToolTip("Write the staged changes to a new save folder  (Ctrl+S)")
        self._save_new_btn.clicked.connect(self._save_as_new)
        layout.addWidget(self._save_new_btn)
        self._overwrite_btn = w.ghost_button("Overwrite…")
        self._overwrite_btn.setToolTip("Replace this save in place, with a backup  (Ctrl+Shift+S)")
        self._overwrite_btn.clicked.connect(self._overwrite_current)
        layout.addWidget(self._overwrite_btn)
        return bar

    # -- sidebar ---------------------------------------------------------- #
    def _build_sidebar(self) -> QWidget:
        side = self._sidebar = QWidget()
        side.setFixedWidth(t.SIDEBAR_W)
        side.setStyleSheet(
            f"background:{t.SIDEBAR_BG};border-right:1px solid {t.hairline(0.08)};"
        )
        layout = QVBoxLayout(side)
        layout.setContentsMargins(12, 14, 12, 14)
        layout.setSpacing(14)

        layout.addWidget(w.cap_label("Open saves"))
        # The design shows a couple of saves; a real install has dozens, so the
        # list scrolls within a capped height rather than pushing SECTIONS off the
        # bottom of the sidebar.
        saves_holder = QWidget()
        saves_holder.setStyleSheet("background:transparent;")
        self._saves_box = QVBoxLayout(saves_holder)
        self._saves_box.setContentsMargins(0, 0, 0, 0)
        self._saves_box.setSpacing(4)
        saves_scroll = QScrollArea()
        saves_scroll.setWidgetResizable(True)
        saves_scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        saves_scroll.setMaximumHeight(_SAVES_LIST_MAX_H)
        saves_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        saves_scroll.setStyleSheet(w.scroll_area_qss())
        saves_scroll.setWidget(saves_holder)
        layout.addWidget(saves_scroll)
        for save in self._saves:
            row = _SaveRow(save)
            row.clicked.connect(lambda _=False, s=save: self._select_save(s))
            self._save_rows.append(row)
            self._saves_box.addWidget(row)
        self._saves_box.addStretch(1)

        layout.addWidget(w.cap_label("Sections"))
        nav = QVBoxLayout()
        nav.setSpacing(3)
        layout.addLayout(nav)
        advanced = QVBoxLayout()
        advanced.setSpacing(3)
        for section in SECTIONS:
            row = w.NavRow(section.key, section.label, section.code)
            row.clicked.connect(lambda _=False, k=section.key: self._set_section(k))
            self._nav_rows[section.key] = row
            (advanced if section.advanced else nav).addWidget(row)
        layout.addWidget(w.cap_label("Advanced"))
        layout.addLayout(advanced)
        layout.addStretch(1)
        return side

    # -- content ---------------------------------------------------------- #
    def _build_content(self) -> QWidget:
        self._stack = QStackedWidget()
        self._stack.setStyleSheet(f"background:{t.APP_BG};")
        # Screens are built on first display — see _LazyScreens.
        self._screens = _LazyScreens(self._make_screen)
        return self._stack

    def _make_screen(self, key: str) -> QWidget:
        """Build one section's screen and put it in the stack."""
        section = by_key(key)
        screen = self._build_screen(section) if section else QWidget()
        self._stack.addWidget(screen)
        return screen

    def _build_screen(self, section: Section) -> QWidget:
        """A section's screen, or the design's empty-state card if it has none yet."""
        builder = self._screen_builders().get(section.key)
        if builder is not None:
            return builder()
        return _empty_state(section, SECTION_BLURBS.get(section.key, ""))

    def _screen_builders(self) -> dict[str, object]:
        """Screens that exist. Sections absent from this map render an empty state."""
        from nwnsaveeditor.ui.editor.screens.area import AreaScreen
        from nwnsaveeditor.ui.editor.screens.backups import BackupsScreen
        from nwnsaveeditor.ui.editor.screens.character import CharacterScreen
        from nwnsaveeditor.ui.editor.screens.inventory import InventoryScreen
        from nwnsaveeditor.ui.editor.screens.party import PartyScreen
        from nwnsaveeditor.ui.editor.screens.quests import QuestsScreen
        from nwnsaveeditor.ui.editor.screens.raw import RawScreen
        from nwnsaveeditor.ui.editor.screens.spellbook import SpellbookScreen

        return {
            "character": lambda: CharacterScreen(self),
            "inventory": lambda: InventoryScreen(self),
            "spellbook": lambda: SpellbookScreen(self),
            "quests": lambda: QuestsScreen(self),
            "party": lambda: PartyScreen(self),
            "area": lambda: AreaScreen(self),
            "raw": lambda: RawScreen(self),
            "backups": lambda: BackupsScreen(self),
        }

    # -- the API screens are built against ------------------------------- #
    # Screens take the window and use only what follows, so a screen never has to
    # reach into the shell's widgets.
    @property
    def editing(self) -> bool:
        """Whether the global edit gate is open."""
        return self._editing

    @property
    def save(self) -> SaveGame | None:
        """The selected save."""
        return self._current

    def session(self):
        """The :class:`~nwnsaveeditor.save_editor.SaveEditor` for the selection."""
        return self._ensure_session()

    def rule_mode(self) -> str:
        """``"strict"`` or ``"free"`` — the toolbar's rule-mode choice."""
        return self._rule_mode.value()

    def character_is_female(self) -> bool:
        """Whether the character is a woman — armour is pictured as worn, so a
        suit has a different inventory icon on each body."""
        from nwnfile.formats.bic_reader import Gender

        info = self.character_info()
        return info is not None and info.gender is Gender.FEMALE

    def character_info(self):
        """The selected save's parsed character record, or ``None``.

        Read from ``player.bic``, which the save keeps as a mirror of the
        authoritative ``module.ifo`` record, and cached per save because parsing
        walks the whole inventory.
        """
        from nwnfile.formats.bic_reader import BicFileReader

        save = self._current
        if save is None or save.player_bic is None:
            return None
        if self._char_cache_for != save.folder:
            info = BicFileReader().read_file(save.player_bic)
            if info is not None:
                self._resolver().resolve_character(info)
            self._char_cache = info
            self._char_cache_for = save.folder
        return self._char_cache

    def _resolver(self):
        from nwnfile.item_names import resolver_for

        return resolver_for(self._game_root())

    def item_name(self, item) -> str:
        """An item's display name: its own name first, else its strref.

        Many items store only a strref and would otherwise show as
        "(unnamed: <resref>)", so that is resolved through dialog.tlk. But an
        item that carries a ``LocalizedName`` has been *named by the module*,
        and that name wins: the strref usually points at the base item's entry,
        so preferring it renamed "Robes of Sesustris" to "White Robe of the
        Archmagi" and "Tuxedo of Infiltration" to "Leather Armor" — 105 of the
        169 items on a real character, each one unfindable by its actual name.
        """
        name = getattr(item, "name", "") or ""
        if getattr(item, "named", False):
            return name
        strref = getattr(item, "name_strref", -1)
        if strref is not None and strref >= 0:
            resolved = self._resolver().name_for(strref)
            if resolved:
                return resolved
        return name

    def game_root(self):
        """The configured game folder, or ``None`` — screens need it for 2DAs."""
        return self._game_root()

    def portrait_path(self, resref: str, save=None):
        """Find a character's portrait TGA, or ``None``.

        A host that knows more — one tracking portraits its own mod installs
        added, or ones extracted out of haks — can supply ``portrait_path`` and
        it is preferred. Without one the editor looks where NWN itself keeps
        them, which is what it needs to work standalone: this used to delegate
        the search entirely to the host, so running the editor on its own showed
        no portrait at all even when the file was sitting in ``portraits/``.
        """
        from nwnfile.character import resolve_portrait

        if not resref:
            return None
        host_lookup = getattr(self._controller, "portrait_path", None)
        if host_lookup is not None:
            try:
                return host_lookup(
                    resref, extra_dirs=[save.folder] if save is not None else []
                )
            except Exception:
                pass  # fall through to our own search rather than showing nothing
        return resolve_portrait(resref, self.portrait_dirs(save))

    def portrait_dirs(self, save=None) -> list:
        """Where NWN keeps portraits, nearest first.

        The save folder comes first: a save can carry its own copy. ``ovr`` is
        Enhanced Edition's override; the plain ``override`` and ``portraits``
        folders are where both editions look.
        """
        dirs = [save.folder] if save is not None else []
        user = getattr(getattr(self._controller, "ctx", None), "game_user_dir", None)
        if user is not None:
            dirs += [user / "ovr", user / "override", user / "portraits"]
        root = self._game_root()
        if root is not None:
            dirs += [root / "ovr", root / "override", root / "portraits"]
        return [d for d in dirs if d is not None and d.is_dir()]

    def portrait_source(self):
        """Where portrait pictures come from, for the current install.

        Portraits live in three different places under two different naming
        conventions — see :mod:`nwnfile.portrait_images`.
        """
        from nwnfile.portrait_images import portrait_source_for

        try:
            return portrait_source_for(
                self._game_root(),
                tuple(self.portrait_dirs(self.save)),
                self._hak_dir(),
            )
        except Exception:
            return None

    def look_tables(self):
        """appearance.2da / portraits.2da options for the current install."""
        from nwnfile.look_tables import LookTables

        try:
            return LookTables.for_install(self._game_root(), self._hak_dir())
        except Exception:
            return None

    def hak_stack(self):
        """The open save's own hak search path, or ``None``.

        Read from its ``Mod_HakList`` rather than guessed: which haks a module
        uses, and in what order, differs from save to save, and the tables that
        decide a character's race and item names live in them.
        """
        from nwnfile.hak_stack import HakStack, hak_names_from_module

        session = self.session()
        if session is None:
            return None
        try:
            names = hak_names_from_module(session.module_root())
        except Exception:
            return None
        return HakStack.for_module(names, self._hak_dir(), self._game_root())

    def _prc_cache_dir(self):
        """Where the PRC feat-index cache lives (regenerable, editor-owned)."""
        from pathlib import Path

        from nwnsaveeditor.ui.editor.host import default_settings_dir

        return Path(default_settings_dir()) / "prc_cache"

    def _prc_advisor_for(self):
        """The PrcAdvisor for the open save, seeded from the on-disk index if cached."""
        if self._prc_advisor is not None:
            return self._prc_advisor
        stack = self.hak_stack()
        if stack is None:
            return None
        from nwnfile.prc_advice import (
            PrcAdvisor,
            hak_fingerprint,
            load_membership_index,
        )

        advisor = PrcAdvisor(stack)
        fingerprint = hak_fingerprint(stack.haks)
        self._prc_cache_path = self._prc_cache_dir() / f"prc_feat_index_{fingerprint}.json"
        cached = load_membership_index(self._prc_cache_path)
        if cached is not None:
            advisor.seed_membership(cached)
        self._prc_advisor = advisor
        return advisor

    def prewarm_prc_index(self) -> None:
        """Build the PRC membership index in the background, so the add-feat confirm
        never blocks. A no-op once it is ready or already building."""
        advisor = self._prc_advisor_for()
        if advisor is None or advisor.membership_ready():
            return
        if self._prc_prewarm is not None and self._prc_prewarm.is_alive():
            return
        import threading

        cache_path = self._prc_cache_path

        def build() -> None:
            from nwnfile.prc_advice import save_membership_index

            try:
                index = advisor.membership_index()  # the expensive scan, off the UI
            except Exception:
                return
            if cache_path is not None:
                save_membership_index(cache_path, index)

        self._prc_prewarm = threading.Thread(target=build, daemon=True)
        self._prc_prewarm.start()

    def prc_advise(self, feat_id: int):
        """Classify a PRC feat for the add-feat confirm, or ``None`` if unreadable.

        Fast for base/standalone feats; a class/spellbook feat needs the membership
        index, which :meth:`prewarm_prc_index` builds in the background and this
        caches to disk — so only the very first classification on a new install
        ever waits (under a wait cursor), and it is remembered thereafter.
        """
        advisor = self._prc_advisor_for()
        if advisor is None:
            return None
        from PySide6.QtCore import Qt
        from PySide6.QtGui import QCursor
        from PySide6.QtWidgets import QApplication

        from nwnfile.prc_advice import save_membership_index

        building = not advisor.membership_ready()
        if building:
            QApplication.setOverrideCursor(QCursor(Qt.CursorShape.WaitCursor))
        try:
            advice = advisor.advise(feat_id)
        finally:
            if building:
                QApplication.restoreOverrideCursor()
        # If reaching the verdict built the index (a class/spellbook feat, no
        # prewarm done yet), persist it. The lock makes a concurrent prewarm safe.
        if building and advisor.membership_ready() and self._prc_cache_path is not None:
            save_membership_index(self._prc_cache_path, advisor.membership_index())
        return advice

    def class_level_editing_enabled(self) -> bool:
        """Whether the opt-in class-level editing is turned on (default off)."""
        try:
            settings = self._controller._settings()
        except Exception:
            return False
        return bool(getattr(settings, "enable_class_level_editing", False))

    def race_table(self):
        """``racialtypes.2da`` for this save, giving each race's ability adjustment."""
        from nwnfile.races import RaceTable

        stack = self.hak_stack()
        if stack is None:
            return None
        if self._races is None or self._races.stack != stack:
            self._races = RaceTable(stack)
        return self._races

    def class_table(self):
        """``classes.2da`` and the stat gains each class grants as it levels."""
        from nwnfile.class_tables import ClassTable

        stack = self.hak_stack()
        if stack is None:
            return None
        if self._classes is None or self._classes.stack != stack:
            self._classes = ClassTable(stack)
        return self._classes

    def _hak_dir(self):
        user = getattr(getattr(self._controller, "ctx", None), "game_user_dir", None)
        return (user / "hak") if user is not None else None

    def _game_root(self):
        return getattr(getattr(self._controller, "ctx", None), "game_root", None)

    def property_tables(self):
        """The game's ``iprp_*`` option tables, or ``None`` if they can't be read.

        Every item-property editor is populated from these, so an edit can only
        produce a value the engine recognises.
        """
        from nwnfile.item_property_tables import ItemPropertyTables

        try:
            return ItemPropertyTables.for_install(self._game_root(), self._hak_dir())
        except Exception:
            return None

    def notify_changed(self) -> None:
        """A screen staged an edit: refresh the footer, the dots and the screens."""
        self._refresh_pending()
        self._refresh_screens()

    def _refresh_screens(self) -> None:
        """Re-render every screen that has been built.

        Only screens the user has actually visited exist (see _LazyScreens), so
        this is a handful at most — iterating the dict never builds a new one.
        """
        for screen in list(self.values_of_built_screens()):
            refresh = getattr(screen, "refresh", None)
            if callable(refresh):
                self._safely(refresh)

    def values_of_built_screens(self):
        """The screens constructed so far, without building any more."""
        return list(dict.values(self._screens))

    def _safely(self, rebuild) -> None:
        """Run a rebuild without deleting the widget Qt is dispatching to.

        A refresh tears down and recreates a screen's widgets, and it is almost
        always triggered *by* one of them — a spin box's valueChanged, an item
        cell's mousePressEvent. Tearing down synchronously destroys the widget the
        event is still being delivered to, which crashes: PySide hands ownership
        back to Python on setParent(None), so the object dies immediately rather
        than at deleteLater() time. Deferring to the next turn of the event loop
        lets the current event finish first.
        """
        if self._rebuilding:
            return  # already inside a rebuild; do not re-enter
        self._rebuilding = True
        try:
            rebuild()
        finally:
            self._rebuilding = False

    # -- footer ----------------------------------------------------------- #
    def _build_footer(self) -> QWidget:
        self._footer = QWidget()
        self._footer.setStyleSheet(
            f"background:{t.SURFACE};border-top:1px solid {t.hairline(0.1)};"
        )
        layout = QHBoxLayout(self._footer)
        layout.setContentsMargins(20, 10, 20, 10)
        layout.setSpacing(16)
        self._pending_caption = w.cap_label("Pending changes (0)")
        layout.addWidget(self._pending_caption)
        self._pending_samples = QHBoxLayout()
        self._pending_samples.setSpacing(16)
        layout.addLayout(self._pending_samples)
        layout.addStretch(1)
        self._review_btn = w.ghost_button("Review…")
        self._review_btn.clicked.connect(self._toggle_ledger)
        layout.addWidget(self._review_btn)
        self._discard_btn = w.ghost_button("Discard All")
        self._discard_btn.clicked.connect(self._discard_all)
        layout.addWidget(self._discard_btn)
        return self._footer

    # -- save selection --------------------------------------------------- #
    def _select_save(self, save: SaveGame) -> bool:
        """Make ``save`` current. ``False`` if the user kept their staged edits."""
        if save is self._current:
            return True
        if not self._confirm_discard("Switching saves"):
            self._sync_save_rows()
            return False
        self._current = save
        self._session = None
        self._save_label.setText(_save_label_text(save))
        self._sync_save_rows()
        self._refresh_pending()
        # Screens are built once, before any save is selected, so they must be
        # re-rendered here or they keep showing the empty state forever.
        self._refresh_screens()
        return True

    def _sync_save_rows(self) -> None:
        for row in self._save_rows:
            row.setChecked(row.save is self._current)

    def _choose_save(self) -> None:
        from nwnsaveeditor.ui.editor.dialogs import OpenSaveDialog

        dialog = OpenSaveDialog(self._saves, self)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        chosen = dialog.selected_save()
        if chosen is not None:
            self._select_save(chosen)

    # -- keyboard shortcuts ----------------------------------------------- #
    def _install_shortcuts(self) -> None:
        """Window-wide keys, in Vaultkeeper's Ctrl-idiom (parented to the window
        so they survive a theme rebuild of the central widget).

        Only modifier/function keys are bound — a bare printable key would fire
        ahead of a focused text field (a known Qt trap in this app)."""
        from PySide6.QtGui import QKeySequence, QShortcut

        specs = (
            ("Ctrl+O", self._choose_save),        # open another save
            ("Ctrl+E", self._toggle_edit),        # enter/leave edit mode
            ("Ctrl+S", self._shortcut_save_new),  # save as a new folder (primary)
            ("Ctrl+Shift+S", self._shortcut_overwrite),  # overwrite this save
            ("Ctrl+Z", self._undo),
            ("Ctrl+Shift+Z", self._redo),
            ("Ctrl+Y", self._redo),               # the Windows redo idiom too
            ("Ctrl+,", self._show_settings),      # preferences
            ("F1", self._show_guide),             # help
        )
        for keys, handler in specs:
            QShortcut(QKeySequence(keys), self, activated=handler)

    def _toggle_edit(self) -> None:
        if self._current is not None:  # clicking runs _set_edit_mode + discard guard
            self._edit_toggle.click()

    def _shortcut_save_new(self) -> None:
        if self._save_new_btn.isEnabled():  # only when there is something to save
            self._save_as_new()

    def _shortcut_overwrite(self) -> None:
        if self._overwrite_btn.isEnabled():
            self._overwrite_current()

    # -- edit mode -------------------------------------------------------- #
    def _set_edit_mode(self, on: bool) -> None:
        if not on and not self._confirm_discard("Leaving edit mode"):
            self._edit_toggle.setChecked(True)  # user kept their changes
            return
        self._editing = on
        self._edit_toggle.setText("Editing ✓" if on else "Edit")
        self._sync_edit_state()
        # The gate decides whether screens draw steppers, × buttons and Add…
        # actions at all, so they have to be rebuilt when it moves.
        self._refresh_screens()

    def _sync_edit_state(self) -> None:
        """Apply the global edit gate to everything it controls."""
        self._footer.setVisible(self._editing)
        has_edits = self._session is not None and self._session.has_edits
        for button in (self._save_new_btn, self._overwrite_btn):
            button.setEnabled(self._editing and has_edits)
        self._discard_btn.setEnabled(has_edits)

    def _ensure_session(self):
        """The edit session for the selected save, created on first use."""
        from nwnsaveeditor.save_editor import SaveEditor

        if self._session is None:
            if self._current is None:
                raise RuntimeError("no save selected")
            self._session = SaveEditor(self._current)
        return self._session

    def _confirm_discard(self, what: str) -> bool:
        """Ask before dropping staged changes. ``True`` means "go ahead"."""
        if self._session is None or not self._session.has_edits:
            return True
        answer = QMessageBox.question(
            self, "Discard changes?",
            f"{what} discards {len(self._session.pending_changes())} staged change(s).\n\n"
            "Discard them?",
            QMessageBox.StandardButton.Discard | QMessageBox.StandardButton.Cancel,
        )
        if answer != QMessageBox.StandardButton.Discard:
            return False
        self._session.discard()
        self._refresh_pending()
        return True

    def _undo(self) -> None:
        if self._session is not None and self._session.undo():
            self.notify_changed()

    def _redo(self) -> None:
        if self._session is not None and self._session.redo():
            self.notify_changed()

    def _show_guide(self) -> None:
        from nwnsaveeditor.ui.editor.guide import EditorGuideDialog

        EditorGuideDialog(self).exec()

    def _show_settings(self) -> None:
        from nwnsaveeditor.ui.editor.settings import SettingsDialog

        SettingsDialog(self, self).exec()

    def forget_game_tables(self) -> None:
        """Rebuild after the game folders changed.

        Nothing here holds the tables any more — they are keyed on the install
        (see :mod:`nwnfile.cache`), so a new folder simply reads as a different
        key. What this does is rebuild the shell, because *screens* can still
        hold things derived from the old folder, and a list of which ones is
        exactly the kind of thing that gets forgotten. The theme switch already
        rebuilds for the same reason.
        """
        self._icons = _icon_source(self._controller)
        self._build_ui()

    def reload_icons(self) -> None:
        """Rebuild after the icon options changed.

        The source caches what it has already decoded and, with hak search on,
        an index of every hak — so it is replaced rather than asked again, and
        the shell rebuilt because screens hold the pixmaps it produced.
        """
        self._icons = _icon_source(self._controller)
        self._build_ui()

    def _set_theme(self, name: str) -> None:
        """Switch the editor's palette and rebuild the window in it.

        Widgets bake token colours into their stylesheets when they are built, so
        the whole shell is reconstructed rather than restyled. Per-screen selection
        is not preserved — a theme change is rare, and rebuilding is far safer than
        chasing every baked-in colour.
        """
        if name == t.active_theme():
            return
        t.set_theme(name)
        if self._controller is not None and hasattr(self._controller, "set_save_editor_theme"):
            self._controller.set_save_editor_theme(name)

        section = next(
            (key for key, row in self._nav_rows.items() if row.isChecked()), "character"
        )
        rule_mode = self._rule_mode.value()
        editing = self._editing

        self._build_ui()

        self._rule_mode.set_value(rule_mode)
        self._theme_toggle.set_value(name)
        # Restore the gate without re-running _set_edit_mode, which would offer to
        # discard the very changes the user is still working on.
        self._edit_toggle.blockSignals(True)
        self._edit_toggle.setChecked(editing)
        self._edit_toggle.setText("Editing ✓" if editing else "Edit")
        self._edit_toggle.blockSignals(False)
        self._editing = editing

        self._sync_save_rows()
        self._set_section(section)
        self._refresh_pending()
        self._refresh_screens()

    def _toggle_ledger(self) -> None:
        self._ledger.toggle()

    def resizeEvent(self, event) -> None:  # noqa: N802 - Qt override
        super().resizeEvent(event)
        if getattr(self, "_ledger", None) is not None and self._ledger.isVisible():
            self._ledger.reposition()

    def _discard_all(self) -> None:
        if self._session is None or not self._session.has_edits:
            return
        if self._confirm_discard("Discard All"):
            self._refresh_pending()

    # -- pending changes -------------------------------------------------- #
    def _refresh_pending(self) -> None:
        """Update the footer caption, its sample chips, and the sidebar dirty dots."""
        changes = self._session.pending_changes() if self._session is not None else []
        self._pending_caption.setText(f"PENDING CHANGES ({len(changes)})")
        while self._pending_samples.count():
            chip = self._pending_samples.takeAt(0).widget()
            if chip is not None:
                # Unparent now, not just deleteLater: a widget awaiting deletion is
                # still a visible child and keeps painting at its old geometry, so
                # the outgoing chips show through the incoming ones.
                w.retire(chip)
        for change in changes[:3]:  # the design shows up to three samples
            chip = w.body(f"●  {change.where}: {change.summary}", t.TEXT, 12)
            chip.setWordWrap(False)
            # w.body opts into heightForWidth so wrapping copy measures correctly.
            # A non-wrapping chip sharing a row must not shrink that way, or the
            # layout squeezes it until its glyphs overlap (a long raw GFF path
            # does it easily). Take the width back and cut the text short instead.
            policy = chip.sizePolicy()
            policy.setHeightForWidth(False)
            chip.setSizePolicy(policy)
            chip.setText(chip.fontMetrics().elidedText(
                chip.text(), Qt.TextElideMode.ElideRight, _CHIP_WIDTH
            ))
            self._pending_samples.addWidget(chip)

        dirty = {section_for_kind(change.kind) for change in changes}
        for key, row in self._nav_rows.items():
            row.set_dirty(key in dirty)
        session = self._session
        self._undo_btn.setEnabled(bool(session is not None and session.can_undo))
        self._redo_btn.setEnabled(bool(session is not None and session.can_redo))
        self._review_btn.setEnabled(bool(changes) or bool(
            session is not None and session.undone_changes()
        ))
        if self._ledger.isVisible():
            self._ledger.refresh()
        self._sync_edit_state()

    # -- sections --------------------------------------------------------- #
    def _set_section(self, key: str) -> None:
        for nav_key, row in self._nav_rows.items():
            row.setChecked(nav_key == key)
        screen = self._screens[key]  # builds on first display
        self._stack.setCurrentWidget(screen)

    # -- committing ------------------------------------------------------- #
    def _save_as_new(self) -> None:
        from nwnsaveeditor.save_editor import SaveEditError

        if self._session is None or not self._session.has_edits or self._current is None:
            return
        dialog = self._save_dialog("new")
        if dialog.exec() != QDialog.DialogCode.Accepted:
            if dialog.review_requested:
                self._ledger.toggle()
            return
        name = dialog.new_name()
        if not name:
            return
        try:
            new_save = self._session.save_as(
                _next_save_folder(self._current.folder.parent, name)
            )
        except (SaveEditError, OSError) as exc:
            QMessageBox.critical(self, "Save failed", str(exc))
            return
        QMessageBox.information(
            self, "Saved",
            f"Saved as “{new_save.name}”.\nYour original save is unchanged.",
        )
        self._session = None
        self.add_save(new_save)

    def _overwrite_current(self) -> None:
        """Replace the selected save, keeping a timestamped backup."""
        from nwnsaveeditor.save_editor import SaveEditError

        if self._session is None or not self._session.has_edits or self._current is None:
            return
        save = self._current
        backup_dir = save.folder.parent.parent / "vaultkeeper_backups"
        dialog = self._save_dialog("overwrite")
        if dialog.exec() != QDialog.DialogCode.Accepted:
            if dialog.review_requested:
                self._ledger.toggle()
            return
        keep_backup = dialog.backup_wanted()
        try:
            self._session.save_as(
                save.folder, overwrite=True,
                backup_dir=backup_dir if keep_backup else None,
            )
        except (SaveEditError, OSError) as exc:
            QMessageBox.critical(self, "Overwrite failed", str(exc))
            return
        if keep_backup:
            message = f"“{save.name}” was replaced.\nThe previous version is in:\n{backup_dir}"
        else:
            message = (
                f"“{save.name}” was replaced.\nNo backup was kept — the previous "
                "version is gone."
            )
        QMessageBox.information(self, "Saved", message)
        self._session = None
        self._refresh_pending()

    def add_save(self, save: SaveGame) -> None:
        """Put a newly written or restored save in the sidebar and select it.

        If the user declines to drop staged edits, the previously selected save
        stays selected — nulling it first would otherwise strand the window with
        no current save at all.
        """
        self._saves.insert(0, save)
        row = _SaveRow(save)
        row.clicked.connect(lambda _=False, s=save: self._select_save(s))
        self._save_rows.insert(0, row)
        self._saves_box.insertWidget(0, row)

        previous = self._current
        self._current = None  # so _select_save does not early-return on identity
        if not self._select_save(save):
            self._current = previous
            self._sync_save_rows()

    def _save_dialog(self, mode: str):
        """Build the Save dialog for ``mode``, primed with what will be written."""
        from nwnsaveeditor.ui.editor.dialogs import SaveDialog

        save = self._current
        session = self._session
        return SaveDialog(
            mode=mode,
            save_name=save.name,
            default_name=f"{_base_name(save.name)} (edited)",
            change_count=len(session.pending_changes()),
            undone_count=session.undone_count,
            rule_mode=self._rule_mode.value(),
            backup_dir=save.folder.parent.parent / "vaultkeeper_backups",
            parent=self,
        )

    # -- entry point ------------------------------------------------------ #
    @classmethod
    def show_for(cls, controller, parent: QWidget | None = None) -> SaveEditorWindow:
        """Open the editor over the install's ``saves`` folder."""
        user = getattr(controller.ctx, "game_user_dir", None)
        saves = scan_save_games(user / "saves" if user is not None else None)
        window = cls(saves, controller, parent)
        window.show()
        return window


class _SaveRow(QPushButton):
    """A row in the sidebar's ``OPEN SAVES`` list: thumbnail, name and meta line."""

    def __init__(self, save: SaveGame, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.save = save
        self.setCheckable(True)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setToolTip(str(save.folder))
        self.setMinimumHeight(t.SAVE_THUMB + 16)
        self.setStyleSheet(
            f"_SaveRow{{text-align:left;padding:0;border-radius:{t.RADIUS_ROW}px;"
            f"border:1px solid transparent;background:transparent;}}"
            f"_SaveRow:hover{{background:{t.hairline(0.05)};}}"
            f"_SaveRow:checked{{border-color:{t.gold_border(0.4)};"
            f"background:{t.gold_tint(0.15)};}}"
        )
        layout = QHBoxLayout(self)
        layout.setContentsMargins(8, 6, 8, 6)
        layout.setSpacing(9)
        layout.addWidget(_save_thumbnail(save))

        text = QVBoxLayout()
        text.setContentsMargins(0, 0, 0, 0)
        text.setSpacing(1)
        self._name = QLabel(_base_name(save.name))
        self._name.setStyleSheet(
            f"font-family:{t.UI_FAMILY};font-size:12px;font-weight:600;"
            f"color:{t.TEXT};background:transparent;"
        )
        text.addWidget(self._name)
        meta = QLabel(save.location or "—")
        meta.setStyleSheet(
            f"font-family:{t.UI_FAMILY};font-size:10.5px;color:{t.TEXT_3};"
            f"background:transparent;"
        )
        text.addWidget(meta)
        layout.addLayout(text, 1)

    def setChecked(self, checked: bool) -> None:  # noqa: N802 - Qt override
        super().setChecked(checked)
        # A child QLabel can't be recoloured by the ``:checked`` rule above.
        self._name.setStyleSheet(
            f"font-family:{t.UI_FAMILY};font-size:12px;font-weight:600;"
            f"color:{t.GOLD if checked else t.TEXT};background:transparent;"
        )


#: Decoded save thumbnails, keyed by path. A TGA decode costs ~33ms and the
#: sidebar rebuilds whole (on every theme switch), so 15 saves cost half a second
#: each time for images that never change.
_THUMBNAILS: dict[Path, object] = {}


def _thumbnail_pixmap(save: SaveGame):
    shot = save.screenshot
    if shot is None:
        return None
    if shot not in _THUMBNAILS:
        _THUMBNAILS[shot] = tga_to_pixmap(shot, box=t.SAVE_THUMB)
    return _THUMBNAILS[shot]


def _save_thumbnail(save: SaveGame) -> QLabel:
    """The save's in-game screenshot at thumbnail size, or a placeholder chip."""
    thumb = QLabel()
    thumb.setFixedSize(t.SAVE_THUMB, t.SAVE_THUMB)
    thumb.setAlignment(Qt.AlignmentFlag.AlignCenter)
    thumb.setStyleSheet(
        f"background:{t.ICON_CHIP};border-radius:{t.RADIUS_CHIP}px;"
        f"color:{t.TEXT_3};font-family:{t.UI_FAMILY};font-size:9px;font-weight:700;"
    )
    pixmap = _thumbnail_pixmap(save)
    if pixmap is None:
        thumb.setText("SV")
    else:
        thumb.setPixmap(pixmap)
    return thumb


def _empty_state(section: Section, blurb: str) -> QWidget:
    """The centred card shown for a section whose screen isn't built yet."""
    page = QWidget()
    page.setStyleSheet(f"background:{t.APP_BG};")

    # The card is a fixed-width container centred by the surrounding stretches.
    # Centring the *labels* individually with an alignment flag would make the
    # layout use each one's sizeHint, and a wrapping label's sizeHint is one line.
    card = QWidget()
    card.setFixedWidth(420)
    card.setStyleSheet("background:transparent;")
    inner = QVBoxLayout(card)
    inner.setContentsMargins(0, 0, 0, 0)
    inner.setSpacing(10)

    chip = QLabel(section.code)
    chip.setFixedSize(48, 48)
    chip.setAlignment(Qt.AlignmentFlag.AlignCenter)
    chip.setStyleSheet(
        f"border:1px solid {t.gold_border(0.4)};background:{t.gold_tint(0.12)};"
        f"color:{t.GOLD};border-radius:{t.RADIUS_PANEL}px;"
        f"font-family:{t.UI_FAMILY};font-size:15px;font-weight:700;"
    )
    inner.addWidget(chip, 0, Qt.AlignmentFlag.AlignHCenter)

    title = w.heading(section.label)
    title.setAlignment(Qt.AlignmentFlag.AlignCenter)
    inner.addWidget(title)

    text = w.body(blurb, t.TEXT_2, 13)
    text.setAlignment(Qt.AlignmentFlag.AlignCenter)
    inner.addWidget(text)

    row = QHBoxLayout()
    row.addStretch(1)
    row.addWidget(card)
    row.addStretch(1)

    layout = QVBoxLayout(page)
    layout.setContentsMargins(40, 40, 40, 40)
    layout.addStretch(1)
    layout.addLayout(row)
    layout.addStretch(1)
    return page


def scrollable(inner: QWidget) -> QScrollArea:
    """Wrap a screen so its content scrolls, as the design's content area does."""
    area = QScrollArea()
    area.setWidgetResizable(True)
    area.setFrameShape(QScrollArea.Shape.NoFrame)
    area.setStyleSheet(w.scroll_area_qss(t.APP_BG))
    area.setWidget(inner)
    return area
