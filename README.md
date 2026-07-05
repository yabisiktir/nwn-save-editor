# Vaultkeeper

Cross-platform **Neverwinter Nights** mod installer and manager — a ground-up,
faithful successor to the Windows-only VB.NET *NWN Installer Tool* (NIT), built to
run natively on **macOS, Windows and Linux** (including **Wine/CrossOver** and
**network** game locations).

> Status: **early rehaul (Phase 0 — foundations).** Not yet usable as an app.
> See [`../rehaul/00_MASTER_PLAN.md`](../rehaul/00_MASTER_PLAN.md) for the full
> plan and phased roadmap, and [`../rehaul/04_DECISIONS_ADDENDUM.md`](../rehaul/04_DECISIONS_ADDENDUM.md)
> for the decisions driving this repo.

## Why a rewrite

The original is ~127k lines of VB.NET + a WinForms control library and is
Windows-only. A prior port attempt was a UI shell over an incomplete/incorrect
backend. Vaultkeeper rebuilds the domain core (profile database, file-mapping
engine, install engine, play tracking) from the documented ground truth, while
reusing the genuinely good parts of the earlier attempt.

## Technology

- **Python 3.11–3.13** (PySide6 wheels not yet available for 3.14).
- **PySide6** (Qt for Python, LGPL) for the GUI.
- Native binary parsers (GFF/BIC/ERF/TGA) in pure Python.
- A small set of bundled native tools (`7zz`, `ffmpeg`) declared in
  [`external/tools.toml`](external/tools.toml).

## Design principles that differ from the original

- **Config isolation.** Vaultkeeper keeps its own store/config and does **not**
  silently rewrite the game's `nwn.ini` / `settings.tml`. Game-file changes are
  explicit and user-confirmed (manual sync + startup validation).
- **Cross-platform paths** are first-class: native Win/mac/Linux, Wine/CrossOver
  prefixes, and network/UNC locations.
- **Explicit dependencies.** Every runtime and bundled-binary dependency is
  declared in `pyproject.toml` / `external/tools.toml`, not just prose.

## Development

```bash
# Use a 3.11–3.13 interpreter (PySide6 constraint).
python3.12 -m venv .venv
source .venv/bin/activate           # Windows: .venv\Scripts\activate
pip install -e ".[dev]"

pytest                               # run tests
ruff check .                         # lint
mypy                                 # type-check

python -m vaultkeeper                # Phase 0: prints discovered installs + store
```

## Layout

```
src/vaultkeeper/
  app_paths.py      # Vaultkeeper's own isolated store/config layout
  game/
    editions.py     # NWN edition identity (EE / Diamond)
    locations.py    # cross-platform install discovery (native/Wine/network)
  config/           # settings (isolated store)            [growing]
  core/             # domain: FileKey, Mapper, ProfileData  [Phase 1+]
  persistence/      # native store + legacy NRBF import     [later]
tests/              # headless unit tests
external/           # bundled-binary manifest
docs/               # phase notes
```

## Credit

Based on the *NWN Installer Tool* by Louis (LazWorks).
