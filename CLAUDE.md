# Working in nwn-save-editor

Guidance for any AI/automation session (and humans) touching this repo. Read this
before editing UI code.

## Theming — do not neglect it

This editor ships **two themes (dark + light)** and one palette is swapped live at
runtime. Almost every UI bug we have shipped here has been a theming bug. The rules
below are not style preferences — breaking one produces an unreadable screen for
half the users.

1. **Colours are never module constants.** They live in `DARK` / `LIGHT` in
   `src/nwnsaveeditor/ui/editor/tokens.py` and are served from the *active* palette
   through the module's `__getattr__` (PEP 562). Always read a colour as
   `t.APP_BG`, `t.TEXT`, `t.SURFACE`, … at the point you use it. **Never** assign a
   token to a module-level string/constant or bake one into a stylesheet computed at
   import time — that freezes whichever theme was active when the module loaded.

2. **Shared stylesheets are functions, not values.** `widgets.dialog_qss()`,
   `widgets.scroll_area_qss()`, `widgets.scrollbar_qss()`, the screens' tree/input
   QSS — all are *built per call* so a theme switch re-derives them. Follow that
   pattern for any new shared QSS. Don't hardcode hex in a widget; go through a
   token so both themes stay correct.

3. **Widgets bake token colours when built, so a theme switch rebuilds the shell.**
   `SaveEditorWindow._set_theme()` calls `t.set_theme()` then `_build_ui()` —
   there is no restyle-in-place. If a screen holds state worth keeping across the
   rebuild (which resource is open, tree scroll position), implement
   `capture_state()` / `restore_state()` on it (see the raw/character screens).

4. **Every top-level dialog must paint its own background, and every scroll area
   inside one must be transparent.** A `QScrollArea` viewport with no background
   falls back to the **OS palette**: on a dark-mode Mac a light-theme dialog then
   renders a dark body with dark text on it — unreadable. The idiom that avoids it,
   used everywhere except the one dialog that once broke:
   - the dialog paints itself: `self.setStyleSheet(w.dialog_qss())` (which sets
     `QDialog{background:APP_BG}`) or `<DialogClass>{background:%s}` % t.APP_BG;
   - each `QScrollArea` uses `w.scroll_area_qss()` (= `QScrollArea{background:
     transparent}`) so the painted dialog background shows through the viewport.
   Never leave a scroll viewport unstyled.

5. **Verify BOTH themes, and verify under the opposite OS appearance.** An
   offscreen render uses a light-ish default palette and *hides* dark-mode
   leakage. To reproduce a macOS dark-system bug headlessly, force it:
   ```python
   pal = QPalette()
   pal.setColor(QPalette.ColorRole.Window, QColor("#1e1e1e"))
   pal.setColor(QPalette.ColorRole.Base, QColor("#1e1e1e"))
   app.setPalette(pal)
   ```
   Then build the widget in `light` theme and grab it. If the body goes dark, a
   scroll viewport (or some other surface) isn't painting a token background.

6. **Popups are separate top-levels and don't inherit a parent's inline styles —
   theme them by a *scoped* rule on the window/dialog.** `QToolTip` and
   `QMessageBox` fall back to the OS palette otherwise (a reported dark-on-dark
   tooltip in light mode). A `QToolTip{…}` / `QMessageBox{…}` rule *does* reach a
   popup shown for a descendant of the widget carrying it, so `widgets.tooltip_qss()`
   and `widgets.message_box_qss()` are appended to the window's stylesheet (and to
   `dialog_qss()`), never set app-wide — that would restyle a host app's popups when
   embedded. `QFileDialog` is deliberately left native: theming it forces the
   worse non-native picker. Text-selection colour (`selection-background-color` /
   `selection-color`) is also palette-driven — every input QSS sets it to the gold
   tokens so selection isn't OS-blue.

See the module docstring in `tokens.py` for how the palette is authored (OKLCH →
sRGB) and how `set_theme` works.

## Data safety — this is a save editor

A wrong write corrupts someone's character. The write path is built around one
guarantee; keep it.

1. **Never mutate the original save.** Edits are staged in memory as
   `PendingChange`s and only ever written by `SaveEditor.save_as`, which produces a
   **brand-new** save folder (or, for "overwrite", stages + verifies THEN atomically
   swaps and moves the old save to a timestamped `vaultkeeper_backups/`). The source
   is opened read-only. See `src/nwnsaveeditor/save_editor.py` — the "never touch the
   original" contract is stated at the top of that file.
2. **The GFF writer is byte-faithful — keep it so.** An unmodified tree round-trips
   **byte-for-byte** against real `.bic` / `.git` / `module.ifo` (verified). Edit =
   read → mutate only the fields you changed → write. Anything that rewrites more of
   the layout than it was asked to, or that breaks the round-trip, is a regression
   even if the file still loads. There are round-trip tests over thousands of real
   resources — do not weaken them to make a change pass.
3. **Character edits live in the `.sav`'s `module.ifo` `Mod_PlayerList[0]`, mirrored
   into `player.bic`.** Write both. `save_editor.py` captures the original value on
   first touch per field so discard works and reverts are detectable.

## Domain correctness — names come from the game, and PRC bites

1. **Items, feats, spells and properties are stored as numbers.** Their names come
   from the game's 2DAs + `dialog.tlk` (and PRC's `prc8_2das.hak`). With no game
   root the editor shows raw ids — that is **expected**, not a bug to "fix" by
   inventing names. Resolve through the existing readers/tables, never a hardcoded
   map.
2. **PRC content is script/SQLite/skin-managed and can silently revert.** Base-game
   edits stick; PRC feats, PRC-class spells and script-managed item properties may be
   undone by the PRC engine on next load. Edits therefore gate on
   `item_properties.editable_magnitude` / `is_cast_spell`, and PRC-tagged changes are
   confirm-warned in the UI. When you add a new edit type, decide and state whether
   it is base-safe or PRC-risky, and warn rather than write silently.

## Qt lifecycle traps (learned the hard way)

- **Never build a focusable widget inside a `refresh()` / rebuild.** A widget that
  rebuilds the panel it lives in will destroy itself as the user types in it
  ("Internal C++ object already deleted"). This bug was hit three separate times.
  Refresh should update values in place, or rebuild only non-focused, non-editing
  regions.
- **An editing widget must stage on *finish*, not on every keystroke.** Staging an
  edit here calls `notify_changed` → `refresh`, which rebuilds the screen the widget
  lives on — the trap above. A `QSpinBox`/`QLineEdit` wired to `valueChanged`/
  `textChanged` therefore rebuilds itself on *each* keystroke and arrow click: the
  user gets one digit in before the field is recreated (they must click back in for
  the next), and steppers jump out from under the pointer. Reported by a user as
  "it only lets you enter one digit at a time". Fix: commit on `editingFinished`
  (Enter / Tab / focus-out), which fires once the value has settled. Use
  `widgets.commit_on_finish(box, cb)` for spin boxes and `editingFinished` for line
  edits; `valueChanged` is only for a live-preview widget that does **not** trigger a
  rebuild (e.g. the level-up wizard's budget label). `textChanged` on a *filter* box
  is fine — it toggles row visibility and never rebuilds the box. The standard
  editable-number control is `widgets.stepper(...)` (a `Stepper`): a field with flat
  −/+ end-caps that auto-repeat on hold — it replaced the bare `QSpinBox` arrows,
  which a user found too small to see or hit. Its −/+ path stages on **`leaveEvent`**
  (pointer leaving the control), *not* per click or on a debounce timer: the commit
  rebuilds and destroys the control, and releasing + to reach for − takes longer than
  any timer (auto-repeat has its own start delay), so a timer-based commit fired
  mid-gesture and felt "stuck". Typing still commits on `editingFinished`. Do not add
  a `setFocus` in the −/+ handler — it fires a spurious `editingFinished` inside the
  scroll area. Its `.spin` is the inner `QSpinBox` for the full API.
- **Never set an empty tooltip.** `setToolTip("")` does not clear a tooltip — Qt
  pops a tiny blank box on hover, which reads as a bug (a user reported exactly
  this). Any tooltip built from data that can be empty (`Limits.reason` when a field
  has no special bound, a possibly-blank name) must go through
  `widgets.set_tooltip(widget, text)`, which no-ops on blank text. This is *not* a
  theming issue — the tooltip string was genuinely empty.
- **A `QTreeWidgetItem` / `QWidget` reference is dead after the tree rebuilds.**
  Don't stash item references across a refresh; re-find by key.
- **Rebuild only what is on screen.** A page is hundreds of widgets (137 feat rows,
  a bonuses view ~3800px), and an edit rebuilds via `notify_changed`. Two lazy layers
  keep that cheap, and both must be preserved: (1) at the window level,
  `notify_changed` refreshes only the **visible section** and marks the others stale
  (`_stale_screens`), refreshing each on its next `_set_section` — so an edit does not
  redraw the Inventory screen's every item icon while you are on Character; (2) the
  Character screen's `refresh()` rebuilds only the **visible tab** and marks the rest
  stale (`_stale_pages`), rebuilding each in `_show_tab`. Building all screens / all
  six tabs on every edit put a full save's edit at ~460 ms and made tab-switching
  drag; the lazy paths cut it to ~120 ms. If you add a screen or tab, follow the same
  build-on-show pattern; if a test reads a page or screen the user hasn't navigated
  to, activate it first (the `_page` test helper and the `raw` fixture do this).
- **Anything read from the game folder is install-keyed and never held** — go
  through `nwnfile.cache.by_install` (backs the property/look/spell tables, item
  names and icons). A different install is a different key, so there is nothing to
  invalidate. Tests **must** call `cache.clear()` between them (autouse fixture) or
  one test's 2DA content answers another's.

## Testing conventions

- **Real-data tests are `skipif`-guarded and must not assert brittle values.** Tests
  that read the developer's real files key off `REAL_BIC` etc. and skip when absent
  (so CI skips them). Assert shapes and ranges, not exact numbers — a real character
  can be *dying* (`current_hit_points < 0`), which is valid and broke a naive
  `> 0` assertion.
- **GUI tests use `qtbot`; a modal dialog blocks a headless run.** A
  `QMessageBox.information/warning` (or any modal) called on the path under test will
  **hang** `QT_QPA_PLATFORM=offscreen` forever. Steer the code past it (pass the arg
  that suppresses the notice) or monkeypatch the dialog. Patching only a
  `QWidget.__init__` leaves the C++ half unconstructed and also hangs — replace the
  whole class with a fake instead.

## Before you push

Run the same gate CI runs:

```bash
scripts/check.sh
```

It runs `ruff check src tests scripts` then the full pytest suite. A pre-commit
hook lints on every commit — activate it once with:

```bash
git config core.hooksPath .githooks
```

Ruff must pass cleanly; don't redirect its output away and read only pytest — a
lint slip that way is what the guardrail exists to stop.

## Orientation

- The editor is a standalone save editor Vaultkeeper *launches*; it is not part of
  Vaultkeeper. Everything it needs from a host is the small protocol in
  `src/nwnsaveeditor/ui/editor/host.py` (read defensively via `hasattr`/`getattr`).
  Add new host capabilities the same opt-in way (`set_game_paths`,
  `set_extra_save_dirs`, `portrait_path`, …).
- `nwnfile` is the Qt-free format/domain layer; `nwnsaveeditor` is the editor;
  neither may import Vaultkeeper. `tests/test_layers.py` pins those arrows.
