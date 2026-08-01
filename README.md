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

With no arguments it finds the game and your saves in the usual places.
`--game-root` and `--user-dir` override that, and save folders can be named
directly. `python -m nwnsaveeditor.ui.editor` works from a checkout.

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
