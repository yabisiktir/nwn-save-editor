"""The screenshot script is a smoke check, so it has to keep working.

``scripts/window_shot.py`` builds the real main window and paints it to a PNG.
Its value is catching what assertions cannot -- a clipped label, an empty panel,
a theme that renders invisible -- by producing something a person can look at,
and by producing it on Windows from a Mac (see ``scripts/win_test.sh --shot``).
The clipped "Abilities & Combat" tab was found exactly that way.

What is checked here is the script's contract: that it still imports, that its
options are the ones the shell wrapper passes, and that an empty run fails
loudly instead of quietly photographing a blank frame. The end-to-end run needs
real saves, so it stays a command somebody runs rather than a test -- looking at
the picture is the whole point, and a test cannot do that part.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture(scope="module")
def window_shot():
    sys.path.insert(0, str(_ROOT / "scripts"))
    import window_shot as module

    return module


def test_its_arguments_stay_what_the_wrapper_passes(window_shot):
    # win_test.sh --shot calls this with --prefix, --user-dir and --game-root;
    # renaming one here would break that quietly, since the wrapper cannot
    # type-check itself.
    args = window_shot.parse_args(
        ["--prefix", "win-", "--user-dir", "/u", "--game-root", "/g"]
    )
    assert args.prefix == "win-"
    assert args.user_dir == Path("/u")
    assert args.game_root == Path("/g")
    assert args.out == window_shot.DEFAULT_OUT

    wrapper = (_ROOT / "scripts" / "win_test.sh").read_text(encoding="utf-8")
    for flag in ("--prefix win-", "--user-dir", "--game-root", "window_shot.py"):
        assert flag in wrapper, flag


def test_a_run_with_no_saves_fails_rather_than_photographing_nothing(
    window_shot, qtbot, tmp_path
):
    # An empty window would produce a PNG and a zero exit status while showing
    # none of what the screenshot exists to show — a green smoke check for a
    # screen with nothing on it. It has to count as a failure.
    empty = tmp_path / "user"
    (empty / "saves").mkdir(parents=True)

    failures = window_shot.main(
        ["--out", str(tmp_path / "shots"), "--user-dir", str(empty), "--settle", "0"]
    )
    assert failures == 1
    assert not list((tmp_path / "shots").glob("*.png"))


def test_the_output_directory_is_ignored_by_git(window_shot):
    # The default lands in build/, which .gitignore covers. A screenshot is
    # output, not source, and committing one by reflex is how a repo ends up
    # with somebody's save folder in it.
    default = window_shot.DEFAULT_OUT.relative_to(_ROOT)
    assert default.parts[0] == "build"
    ignored = (_ROOT / ".gitignore").read_text(encoding="utf-8").splitlines()
    assert any(line.strip() in {"build/", "/build/"} for line in ignored)
