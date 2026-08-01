"""A small dialog to edit a merchant's pricing settings (the first save edit).

Prefilled from a :class:`~nwnsaveeditor.save_area.Store`; :meth:`values` returns
the edited scalar settings ready for :meth:`SaveEditor.set_store_fields`. The dialog
only collects values — writing the (new) save is the caller's job.
"""

from __future__ import annotations

from PySide6.QtWidgets import (
    QCheckBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QLabel,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from nwnsaveeditor.save_area import Store

_BILLION = 2_000_000_000


class StoreEditDialog(QDialog):
    """Edit a store's markup/markdown/gold/identify/max-buy/black-market."""

    def __init__(self, store: Store, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle(f"Edit Store — {store.name}")
        layout = QVBoxLayout(self)
        layout.addWidget(QLabel(f"<b>{store.name}</b>" + (f"  [{store.tag}]" if store.tag else "")))
        form = QFormLayout()
        layout.addLayout(form)

        self._markup = self._percent(store.markup)
        form.addRow("Buy markup (%):", self._markup)
        self._markdown = self._percent(store.markdown)
        form.addRow("Sell-back markdown (%):", self._markdown)

        self._store_gold = self._gold(store.store_gold, "Unlimited")
        form.addRow("Store gold:", self._store_gold)
        self._identify = self._gold(store.identify_price, "None")
        form.addRow("Identify price:", self._identify)
        self._max_buy = self._gold(store.max_buy_price, "No limit")
        form.addRow("Max buy price:", self._max_buy)

        self._black_market = QCheckBox("Black market (buys stolen/illegal goods)")
        self._black_market.setChecked(store.black_market)
        form.addRow(self._black_market)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    @staticmethod
    def _percent(value: int) -> QSpinBox:
        box = QSpinBox()
        box.setRange(0, 10000)
        box.setSuffix(" %")
        box.setValue(max(0, value))
        return box

    @staticmethod
    def _gold(value: int, sentinel_text: str) -> QSpinBox:
        """A gold spin box where the minimum ``-1`` shows ``sentinel_text``."""
        box = QSpinBox()
        box.setRange(-1, _BILLION)
        box.setSpecialValueText(sentinel_text)  # shown when value == -1 (the minimum)
        box.setValue(value if value >= -1 else -1)
        return box

    def values(self) -> dict[str, object]:
        """The edited settings, keyed for :meth:`SaveEditor.set_store_fields`."""
        return {
            "markup": self._markup.value(),
            "markdown": self._markdown.value(),
            "store_gold": self._store_gold.value(),
            "identify_price": self._identify.value(),
            "max_buy_price": self._max_buy.value(),
            "black_market": self._black_market.isChecked(),
        }
