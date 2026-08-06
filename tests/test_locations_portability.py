"""``is_network_path`` must answer about the string, not about the host.

This function had no tests at all, which is how it shipped broken: it used
``PurePath`` — an alias for ``PureWindowsPath`` when the code runs on Windows,
where the root component is ``"\\"`` and never ``"/"``. The POSIX branch below
therefore matched nothing there, and every ``/Volumes``, ``/mnt``, ``/media`` and
``/net`` path was reported as local. It was correct on macOS and Linux, so
development never saw it.

The property to hold on to is that these are questions about a *string* whose
convention is already known, so the answer must be identical on all three
platforms. Every case here is asserted unconditionally for that reason — no
``skipif``, because a guard that only runs on the broken platform is a guard that
tells you too late.
"""

from __future__ import annotations

from pathlib import PurePosixPath, PureWindowsPath

import pytest

from nwnfile.locations import is_network_path


@pytest.mark.parametrize(
    "path",
    [
        "/Volumes/share/NWN",  # macOS SMB/AFP
        "/mnt/nas/NWN",  # Linux
        "/media/usb/NWN",  # Linux removable
        "/net/host/NWN",  # autofs
        r"\\host\share\NWN",  # Windows UNC
        "//host/share/NWN",  # UNC, forward slashes
    ],
)
def test_network_locations_are_detected_on_every_host(path: str) -> None:
    assert is_network_path(path) is True


@pytest.mark.parametrize(
    "path",
    [
        "/Users/x/Documents/NWN",
        "/home/x/.local/share/NWN",
        "/opt/nwn",
        "C:/Program Files/NWN",
        r"C:\Program Files\NWN",
        "relative/Volumes/NWN",  # only matches at the root
    ],
)
def test_local_locations_are_not_mistaken_for_network(path: str) -> None:
    assert is_network_path(path) is False


@pytest.mark.parametrize("root", ["/Volumes", "/mnt", "/media", "/net"])
def test_a_bare_mount_root_counts_as_network(root: str) -> None:
    # Recording behaviour rather than endorsing it: the mount root on its own
    # holds no share, but the check is advisory — it only suppresses auto-scans
    # and raises an availability warning — and erring towards "network" there
    # costs nothing. Written down so a future change to it is a decision.
    assert is_network_path(root) is True


def test_the_flavours_really_do_disagree() -> None:
    # Pins the reason the fix is the path flavour rather than the parsing: the
    # two readings of one string differ, and plain PurePath is whichever the
    # host happens to use.
    assert PurePosixPath("/mnt/nas").parts[0] == "/"
    assert PureWindowsPath("/mnt/nas").parts[0] == "\\"
