"""The backups an overwrite leaves behind, and restoring one.

:meth:`SaveEditor.save_as` with ``overwrite=True`` moves the save it replaces into
``vaultkeeper_backups/<YYYYmmdd-HHMMSS> - <save name>/``. This reads that folder
back and can put a backup returned to the saves folder.
"""

from __future__ import annotations

import re
import shutil
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from vaultkeeper.game.save_game import SaveGame

#: How :meth:`SaveEditor._replace_existing` names a backup folder.
_NAME = re.compile(r"^(?P<stamp>\d{8}-\d{6})(?:\.\d+)? - (?P<name>.+)$")
_STAMP_FORMAT = "%Y%m%d-%H%M%S"


@dataclass
class Backup:
    """One archived save."""

    folder: Path
    original_name: str  #: the save folder's name when it was replaced
    taken: datetime | None

    @property
    def save(self) -> SaveGame:
        """The backup as a readable save."""
        return SaveGame(folder=self.folder)

    @property
    def size(self) -> int:
        try:
            return sum(f.stat().st_size for f in self.folder.rglob("*") if f.is_file())
        except OSError:
            return 0


def list_backups(backup_dir: Path | None) -> list[Backup]:
    """Every backup under ``backup_dir``, newest first."""
    if backup_dir is None or not backup_dir.is_dir():
        return []
    backups: list[Backup] = []
    for folder in backup_dir.iterdir():
        if not folder.is_dir() or not any(folder.glob("*.sav")):
            continue
        match = _NAME.match(folder.name)
        if match is None:
            # Not one of ours, but it is still a save folder — list it plainly
            # rather than hide it.
            backups.append(Backup(folder=folder, original_name=folder.name, taken=None))
            continue
        try:
            taken = datetime.strptime(match["stamp"], _STAMP_FORMAT)
        except ValueError:
            taken = None
        backups.append(
            Backup(folder=folder, original_name=match["name"], taken=taken)
        )
    backups.sort(key=lambda b: (b.taken is not None, b.taken or datetime.min), reverse=True)
    return backups


def restore(backup: Backup, saves_dir: Path, *, name: str | None = None) -> SaveGame:
    """Copy ``backup`` back into ``saves_dir`` as a **new** save folder.

    Deliberately a copy into a free folder rather than a move over the original:
    restoring should never be the thing that destroys what is currently there, and
    the backup itself stays available for a second attempt.
    """
    target_name = name or backup.original_name
    destination = _free_folder(saves_dir, target_name)
    shutil.copytree(backup.folder, destination)
    return SaveGame(folder=destination)


def _free_folder(saves_dir: Path, name: str) -> Path:
    """A ``NNNNNN - name`` folder that does not exist yet."""
    base = name.split(" - ", 1)[1] if " - " in name and name.split(" - ")[0].isdigit() else name
    used = set()
    for folder in saves_dir.glob("* - *"):
        prefix = folder.name.split(" - ", 1)[0]
        if prefix.isdigit():
            used.add(int(prefix))
    number = next(n for n in range(1, 1_000_000) if n not in used)
    return saves_dir / f"{number:06d} - {base}"
