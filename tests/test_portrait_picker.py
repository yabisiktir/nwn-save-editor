"""Choosing a portrait by looking at it.

The field used to open the feat/spell ID picker, which for a portrait shows a
column of strings like ``dw_f_07_`` and nothing else — 1,594 of them.
"""

from __future__ import annotations

import pytest

from nwnfile.look_tables import PortraitEntry
from nwnfile.portrait_images import ART_RATIO, PortraitSource, art_height
from nwnsaveeditor.ui.dialogs.portrait_picker_dialog import PortraitPickerDialog

#: A stand-in table: two men, one woman, and a bat.
ENTRIES = [
    PortraitEntry("hu_m_01_", sex=0, race=6),
    PortraitEntry("hu_m_02_", sex=0, race=6),
    PortraitEntry("el_f_01_", sex=1, race=1),
    PortraitEntry("a_bat_", sex=4, race=None),
]


class _Source:
    """Hands back nothing, so the grid falls back to its "no image" cell."""

    def image_bytes(self, _resref, _size="m"):
        return None


def _picker(qtbot, **kw) -> PortraitPickerDialog:
    dialog = PortraitPickerDialog(ENTRIES, _Source(), **kw)
    qtbot.addWidget(dialog)
    return dialog


# -- the padding every portrait ships with ---------------------------------- #
def test_a_portraits_padding_is_measured_not_guessed():
    """The picture is 64x100 inside a 64x128 file; the rest is one flat colour.

    Measured as 27-28 uniform bottom rows on every stock portrait and on the
    owner's own custom one — leaving it in puts a coloured shelf under every face.
    """
    assert art_height(64, 128) == 100
    assert art_height(32, 64) == 50
    assert art_height(128, 256) == 200
    assert pytest.approx(100 / 64) == ART_RATIO


def test_an_already_cropped_portrait_is_left_alone():
    """Nothing to trim when the file is the picture — do not cut into the face."""
    assert art_height(64, 100) == 100
    assert art_height(64, 80) == 80  # shorter than the art ratio: leave it


# -- who the portrait is for ------------------------------------------------ #
def test_it_opens_on_the_portraits_that_fit_this_character(qtbot):
    """Of the base game's 1,594 portraits only 275 are humanoid at all."""
    male = _picker(qtbot, female=False)
    assert [e.resref for e in male.visible_entries()] == ["hu_m_01_", "hu_m_02_"]

    female = _picker(qtbot, female=True)
    assert [e.resref for e in female.visible_entries()] == ["el_f_01_"]


def test_the_other_audiences_are_a_click_away(qtbot):
    dialog = _picker(qtbot, female=False)
    dialog._who_control.set_value("female")
    dialog._set_who()
    assert [e.resref for e in dialog.visible_entries()] == ["el_f_01_"]

    # "Everything" is the only way to reach the bats and barrels, and it does.
    dialog._who_control.set_value("all")
    dialog._set_who()
    assert "a_bat_" in [e.resref for e in dialog.visible_entries()]


def test_the_name_filter_still_works(qtbot):
    dialog = _picker(qtbot, female=False)
    dialog._search.setText("m_02")
    assert [e.resref for e in dialog.visible_entries()] == ["hu_m_02_"]


# -- choosing --------------------------------------------------------------- #
def test_it_opens_on_what_the_character_already_wears(qtbot):
    """So OK without touching anything is a no-op rather than a change."""
    dialog = _picker(qtbot, current="hu_m_02_", female=False)
    assert dialog.selected_resref() == "hu_m_02_"


def test_the_current_portrait_stays_reachable_when_filtered_out(qtbot):
    """Otherwise OK would confirm something that is not on screen.

    The owner's own portrait is a custom one that no ``portraits.2da`` audience
    matches, so this is the normal case, not a corner.
    """
    from PySide6.QtWidgets import QLabel

    dialog = _picker(qtbot, current="el_f_01_", female=False)  # a woman's, on a man
    assert "el_f_01_" not in [e.resref for e in dialog.visible_entries()]
    # It is not in the filtered set, yet it is on screen — pinned in by _render.
    tooltips = {label.toolTip() for label in dialog.findChildren(QLabel)}
    assert "el_f_01_" in tooltips


def test_clicking_changes_the_choice_without_closing(qtbot):
    dialog = _picker(qtbot, current="hu_m_01_", female=False)
    dialog._choose("hu_m_02_")
    assert dialog.selected_resref() == "hu_m_02_"
    assert dialog.result() == 0  # accept() was not called; the dialog is still open


def test_double_clicking_chooses_and_accepts(qtbot):
    """One gesture for "this one" — clicking then OK is two for the same thing."""
    dialog = _picker(qtbot, current="hu_m_01_", female=False)
    dialog._choose_and_accept("hu_m_02_")
    assert dialog.selected_resref() == "hu_m_02_"
    assert dialog.result() == int(dialog.DialogCode.Accepted)


def test_a_portrait_with_no_picture_still_gets_a_cell(qtbot):
    """A missing image must not drop the option — 18 stock portraits have none."""
    dialog = _picker(qtbot, female=False)
    assert len(dialog.visible_entries()) == 2  # both listed despite _Source giving nothing


# -- where the pictures come from ------------------------------------------- #
def test_the_source_looks_past_the_portraits_folder(tmp_path):
    """Stock portraits are in the BIFs as ``po_<resref><size>``, with a prefix the
    loose-file convention does not use — searching only folders finds none."""
    folder = tmp_path / "portraits"
    folder.mkdir()
    (folder / "custom_m.tga").write_bytes(b"TGA-ISH")
    source = PortraitSource(None, [folder], None)
    assert source.image_bytes("custom_", "m") == b"TGA-ISH"
    assert source.image_bytes("nothing_", "m") is None


# -- getting to all of them ------------------------------------------------- #
def _many(count: int) -> list[PortraitEntry]:
    return [PortraitEntry(f"hu_m_{n:03d}_", sex=0, race=6) for n in range(count)]


class _CountingSource:
    """Counts decodes, so a re-render doing them again is visible."""

    def __init__(self):
        self.reads = 0

    def image_bytes(self, _resref, _size="m"):
        self.reads += 1
        return None


def test_show_all_exists_because_sixty_at_a_time_is_twenty_six_clicks(qtbot):
    dialog = PortraitPickerDialog(_many(200), _Source(), female=False)
    qtbot.addWidget(dialog)
    assert len(dialog.visible_entries()) == 200

    dialog._show_all(200)
    assert dialog._shown == 200
    # Everything is now built, so neither button is offered any more.
    assert "showing" not in dialog._count.text()


def test_show_more_still_advances_a_page_at_a_time(qtbot):
    dialog = PortraitPickerDialog(_many(200), _Source(), female=False)
    qtbot.addWidget(dialog)
    before = dialog._shown
    dialog._show_more()
    assert dialog._shown == before + 60


def test_pictures_are_decoded_once_each_not_once_per_render(qtbot):
    """Choosing used to rebuild the grid, re-reading every visible portrait.

    At sixty cells that is a fifth of a second per click; with everything shown,
    nearly a whole one.
    """
    source = _CountingSource()
    dialog = PortraitPickerDialog(_many(10), source, female=False)
    qtbot.addWidget(dialog)
    dialog._fill_some()
    dialog._fill_some()
    first_pass = source.reads
    assert first_pass > 0

    dialog._render()          # a rebuild
    dialog._fill_some()
    dialog._fill_some()
    assert source.reads == first_pass  # served from the cache, not re-read


def test_choosing_does_not_rebuild_the_grid(qtbot):
    """Only two cells change, so only two are restyled."""
    dialog = PortraitPickerDialog(_many(10), _Source(), female=False)
    qtbot.addWidget(dialog)
    generation = dialog._generation
    cells = dict(dialog._cells)

    dialog._choose("hu_m_003_")
    assert dialog.selected_resref() == "hu_m_003_"
    assert dialog._generation == generation      # no re-render happened
    assert dialog._cells == cells                # and the same widgets are in place


def test_a_queued_picture_is_dropped_when_the_grid_is_rebuilt(qtbot):
    """Its label is gone; filling it would touch a deleted widget."""
    dialog = PortraitPickerDialog(_many(100), _Source(), female=False)
    qtbot.addWidget(dialog)
    assert dialog._pending
    dialog._render()
    # The queue belongs to the grid that was just thrown away.
    assert all(resref for _label, resref in dialog._pending)
    dialog._fill_some()  # must not raise on the old labels
