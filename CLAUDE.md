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

See the module docstring in `tokens.py` for how the palette is authored (OKLCH →
sRGB) and how `set_theme` works.

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
