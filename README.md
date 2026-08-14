# NWN Save Editor

Read and edit **Neverwinter Nights** save games — and the file formats behind them.

![The character sheet: abilities as stored and as played, with every bonus attributed](docs/images/character.png)

Two packages:

- **`nwnfile`** — the formats (GFF, ERF, 2DA, TLK, KEY/BIF, TGA, PLT) and the game
  data that gives them meaning: which feat id is Whirlwind Attack, what item
  property 12 does, what a race id is called. No Qt, no application; it reads files.
- **`nwnsaveeditor`** — decoding a `.sav`, staging edits against it, writing a
  verified new save, and the editor window over all of it.

The arrows point one way and tests hold them there: `nwnfile` never imports
`nwnsaveeditor`, and never imports Qt.

## A look at it

Inventory and equipment, with each item's real in-game icon — worked out from the
game's own files, including the ones custom content adds:

![Equipment slots as the game lays them out, creature slots, and the carried bag](docs/images/inventory.png)

The module's persistent script variables — the flags and counters a campaign uses
to remember what you did — searchable and editable:

![Quests & World State: the module's variables, filtered](docs/images/world-state.png)

Portraits are chosen by looking at them. Only 275 of the game's 1,594 are of
people at all, so it opens on the ones that fit this character:

![A grid of portraits, filtered to the ones that fit the character](docs/images/portrait-picker.png)

## Running it

```
pip install -e ".[dev]"
nwn-save-editor
```

`python -m nwnsaveeditor.ui.editor` works the same from a checkout.

```
nwn-save-editor [--game-root PATH] [--user-dir PATH] [SAVE_FOLDER ...]
```

Naming save folders opens exactly those; with none it lists everything under the
user directory's `saves`.

## Where it looks for the game

Two folders matter, and they are not the same thing:

- **the user directory** — your `saves`, `hak`, `portraits` and `override`.
- **the game root** — the installation. Only needed for *names*: items, feats,
  spells and item properties are stored as numbers, and the names come from the
  game's 2DAs and `dialog.tlk`. Without it the editor still opens and still
  edits, but shows raw ids — and says so on startup rather than leaving you to
  wonder.

Each is settled once, in this order:

1. what you passed on the command line,
2. what was saved last time,
3. detection.

Whatever it lands on is written back, so `--game-root` is a **one-time** flag
rather than one you retype every launch. A remembered path that later disappears —
an unplugged drive, an uninstalled game — falls through to detection instead of
pinning the editor to somewhere empty.

### What detection knows

Steam's library folders (not only the default one), GOG and Beamdog installs, and
Wine/CrossOver prefixes — each candidate checked to see whether it really looks
like an NWN root. The user directory differs by platform, which is the part worth
knowing if you move between machines:

| Platform | NWN user directory |
|---|---|
| macOS | `~/Documents/Neverwinter Nights` |
| Windows | `%USERPROFILE%\Documents\Neverwinter Nights` |
| Linux | `~/.local/share/Neverwinter Nights` — **not** `Documents` |

### Item icons

An item's picture is worked out from the game's own files. **Custom content keeps
its icons in haks** — CEP's Robes of Sesustris has one that exists nowhere else —
so the user's hak folder is searched too, and that is **on by default**: without
it every custom item falls back to its type's generic picture, which looks broken
rather than unconfigured. The cost is one index the first time an icon is wanted,
measured at about a second over 112 haks. Both this and "work each item's own icon
out" can be turned off under **Settings…**.

### The settings file

| Platform | Path |
|---|---|
| macOS | `~/Library/Application Support/nwn-save-editor/save_editor.json` |
| Windows | `%APPDATA%\nwn-save-editor\save_editor.json` |
| Linux | `~/.config/nwn-save-editor/save_editor.json` |

```json
{
  "save_editor_theme": "dark",
  "hak_item_icons": true,
  "exact_item_icons": true,
  "enable_class_level_editing": false,
  "game_root": "/path/to/Neverwinter Nights",
  "game_user_dir": "/path/to/Documents/Neverwinter Nights"
}
```

`enable_class_level_editing` is **off by default**: adding a class level is a real
level-up, not a field edit, so it stays behind a switch you turn on deliberately in
**Settings…**. See [docs/save_game_editor.md](docs/save_game_editor.md#class-levels-opt-in).

Edit it by hand or delete it to start over — a missing or malformed file falls
back to detection rather than failing.

### Settings…

The toolbar's **Settings…** shows both folders, what each is for, and lets you
change them — *when they are the editor's to change*.

Opened from an application that has its own game-folder setting, they are not:
that application supplies them, and this file is not used at all. The screen then
shows them read-only and names who is in charge, rather than offering an edit that
would write somewhere the editor never reads. A host opts in by offering
`set_game_paths`, the same way it opts into `portrait_path`.

## Building an app

```
pip install pyinstaller
python scripts/build_app.py
```

Produces a self-contained app with Python, Qt and the game tables inside it —
about 45 MB packaged, 100 MB installed.

| Platform | Artifact |
|---|---|
| macOS | `dist/nwn-save-editor-<ver>-macos-<arch>.dmg` |
| Windows | `dist/nwn-save-editor-<ver>-windows-x64.zip` |
| Linux | `dist/nwn-save-editor-<ver>-linux-<arch>.tar.gz` |

**Each artifact must be built on the OS it targets** — the freeze embeds a Python
interpreter and Qt's native libraries, so there is no cross-building. That goes
for the CPU too: PySide6 ships per-architecture wheels, so an Apple Silicon build
will not launch on an Intel Mac, which is why the name says which.

Nothing is signed. macOS Gatekeeper will ask for right-click → Open the first
time, and Windows SmartScreen will warn; the hooks for adding certificates are
marked in `packaging/nwn-save-editor.spec`.

## Development

```bash
pytest                 # ~940 headless tests; no display needed
ruff check src tests   # lint
```

Tests run offscreen (`QT_QPA_PLATFORM=offscreen`) and need neither a display nor a
real game install; the few that want real game files skip themselves unless you
point `NWN_TEST_NIT_STORE` at some. CI runs the suite on Linux, Windows and macOS
and builds each platform's artifact on every push.

### Checking Windows behaviour from a Mac

A suite cannot catch a platform assumption it shares with the code that made it,
and CI only says so after a push. If CrossOver is installed, `scripts/win_test.sh`
runs the tests against a real Windows Python inside a bottle — genuine `os.name ==
"nt"`, cp1252 as the locale encoding, and `ntpath` as the path flavour:

```bash
scripts/win_test.sh --setup   # once: create the bottle, install Python and Qt
scripts/win_test.sh           # run the tests as Windows sees them
scripts/win_test.sh --shot    # render the main window as Windows draws it
```

`scripts/window_shot.py` is that last one, and it runs natively too, so the same
command on two platforms gives two screenshots of the same window to compare. It
is what caught a tab label clipped by Windows' wider UI font.

Wine is not Windows — file locking, ACLs and Win32 edge cases differ — so this is
a third cheap signal, not a replacement for the Windows CI job.

## Embedding it

Everything the editor asks of a host is one small protocol —
`nwnsaveeditor.ui.editor.host.EditorHost`: where the game is, and how to remember
the light/dark choice. `StandaloneHost` is the whole of what a bare launcher
provides; an application supplies its own and opens `SaveEditorWindow`.

The extras are opt-in: a host that offers `set_game_paths` makes the game folders
editable, `portrait_path` lends its portrait cache, and `set_class_level_editing`
surfaces the class-level toggle. Absent any of them, the editor hides the feature
rather than writing somewhere it never reads — so the standalone and embedded
Settings screens show exactly what that host actually controls.

## Your saves are safe

**Save as New Save…** never touches the original. **Overwrite This Save…** writes
and verifies to a staging folder first, then archives the old save to a timestamped
folder before swapping. See [docs/save_game_editor.md](docs/save_game_editor.md).

## Used by

[Vaultkeeper](https://github.com/yabisiktir/vaultkeeper), an NWN mod installer and
manager, embeds this editor and ships it inside its own application.

## Thanks

To **Surazal**, author of the *NWN Installer Tool*. Its file-format code,
converted to Python, is part of what this is built on — NWN's formats are not
documented by BioWare, and having a known-correct implementation to work from is
why this reads real saves rather than an approximation of them.

## Licence

GPL-3.0-or-later.
