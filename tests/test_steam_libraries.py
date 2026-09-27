"""Extra Steam libraries from ``libraryfolders.vdf`` (VB ``Paths.SteamLibrary``)."""

from __future__ import annotations

from pathlib import Path

from nwnfile import locations
from nwnfile.locations import HostOS, discover_installs, steam_vdf_libraries

NEW_FORMAT = '''"libraryfolders"
{
\t"0"
\t{
\t\t"path"\t\t"C:\\\\Program Files (x86)\\\\Steam"
\t\t"apps"
\t\t{
\t\t\t"228980"\t\t"123456"
\t\t}
\t}
\t"1"
\t{
\t\t"path"\t\t"D:\\\\SteamLibrary"
\t\t"contentid"\t\t"42"
\t}
}
'''

OLD_FORMAT = '''"LibraryFolders"
{
\t"TimeNextStatsReport"\t\t"1234567"
\t"ContentStatsID"\t\t"-123"
\t"1"\t\t"E:\\\\Games\\\\Steam"
}
'''


def test_both_vdf_formats_are_read(tmp_path: Path) -> None:
    new, old = tmp_path / "new.vdf", tmp_path / "old.vdf"
    new.write_text(NEW_FORMAT)
    old.write_text(OLD_FORMAT)
    assert steam_vdf_libraries(new) == [
        Path(r"C:\Program Files (x86)\Steam"),
        Path(r"D:\SteamLibrary"),
    ]
    assert steam_vdf_libraries(old) == [Path(r"E:\Games\Steam")]
    assert steam_vdf_libraries(tmp_path / "missing.vdf") == []


def test_a_game_on_a_second_library_is_found(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(locations, "_home", lambda: tmp_path)
    default = tmp_path / "Library/Application Support/Steam/steamapps"
    default.mkdir(parents=True)
    other = tmp_path / "Drive2" / "SteamLibrary"
    (default / "libraryfolders.vdf").write_text(
        f'"libraryfolders"\n{{\n\t"1"\n\t{{\n\t\t"path"\t\t"{other}"\n\t}}\n}}\n'
    )
    game = other / "steamapps/common/Neverwinter Nights Enhanced Edition"
    game.mkdir(parents=True)
    monkeypatch.setattr(locations, "looks_like_nwn_root", lambda p: p == game)

    found = discover_installs(HostOS.MACOS, include_wine=False)

    assert [i.root for i in found] == [game]
