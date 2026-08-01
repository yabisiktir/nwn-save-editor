# NWN Save Editor

Read and edit **Neverwinter Nights** save games — and the file formats behind them.

Two packages:

- **`nwnfile`** — the formats (GFF, ERF, 2DA, TLK, KEY/BIF, TGA, PLT) and the game
  data that gives them meaning: which feat id is Whirlwind Attack, what item
  property 12 does, what a race id is called. No Qt, no application; it reads files.
- **`nwnsaveeditor`** — decoding a `.sav`, staging edits against it, writing a
  verified new save, and the editor window over all of it.

The arrows point one way and tests hold them there: `nwnfile` never imports
`nwnsaveeditor`, and never imports Qt.

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

### The settings file

| Platform | Path |
|---|---|
| macOS | `~/Library/Application Support/nwn-save-editor/save_editor.json` |
| Windows | `%APPDATA%\nwn-save-editor\save_editor.json` |
| Linux | `~/.config/nwn-save-editor/save_editor.json` |

```json
{
  "save_editor_theme": "dark",
  "game_root": "/path/to/Neverwinter Nights",
  "game_user_dir": "/path/to/Documents/Neverwinter Nights"
}
```

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

## Embedding it

Everything the editor asks of a host is one small protocol —
`nwnsaveeditor.ui.editor.host.EditorHost`: where the game is, and how to remember
the light/dark choice. `StandaloneHost` is the whole of what a bare launcher
provides; an application supplies its own and opens `SaveEditorWindow`.

## Your saves are safe

**Save as New Save…** never touches the original. **Overwrite This Save…** writes
and verifies to a staging folder first, then archives the old save to a timestamped
folder before swapping. See [docs/save_game_editor.md](docs/save_game_editor.md).

## History

Split out of [Vaultkeeper](../vaultkeeper), an NWN mod installer, where this code
began. Commits touching these files came with it, so `git log` and `git blame`
reach back past the split; anything about the installer stayed behind.
