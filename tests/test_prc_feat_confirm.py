"""The add-feat confirm shows the PRC classifier's verdict + direction."""

from __future__ import annotations

import pytest

pytest.importorskip("PySide6")

from nwnfile.prc_advice import FeatAdvice  # noqa: E402
from nwnsaveeditor.ui.editor.screens.character import _confirm_prc_feat  # noqa: E402


def _advice() -> FeatAdvice:
    return FeatAdvice(
        14373, "Archivist Darkfire", "spellbook", "Archivist", True,
        "Spellbook ability, cast through the Archivist spellbook.",
        "A feat-add can't grant this. Gain it in-game via the Archivist class.",
    )


def test_confirm_shows_the_verdict_and_direction(qtbot, monkeypatch):
    from PySide6.QtWidgets import QMessageBox

    shown: dict[str, str] = {}

    def fake(parent, title, text, *a, **k):
        shown["title"], shown["text"] = title, text
        return QMessageBox.StandardButton.Yes

    monkeypatch.setattr(QMessageBox, "warning", fake)
    assert _confirm_prc_feat(None, _advice()) is True
    assert "Archivist Darkfire" in shown["title"]
    assert "can't grant" in shown["text"]
    assert "Archivist spellbook" in shown["text"]


def test_declining_returns_false(qtbot, monkeypatch):
    from PySide6.QtWidgets import QMessageBox

    monkeypatch.setattr(
        QMessageBox, "warning", lambda *a, **k: QMessageBox.StandardButton.No
    )
    assert _confirm_prc_feat(None, _advice()) is False


def test_falls_back_to_the_generic_warning_when_advice_is_none(qtbot, monkeypatch):
    from PySide6.QtWidgets import QMessageBox

    seen: dict[str, str] = {}

    def fake(parent, title, text, *a, **k):
        seen["title"] = title
        return QMessageBox.StandardButton.Yes

    monkeypatch.setattr(QMessageBox, "warning", fake)
    assert _confirm_prc_feat(None, None) is True
    assert seen["title"] == "PRC feat"  # the generic warning
