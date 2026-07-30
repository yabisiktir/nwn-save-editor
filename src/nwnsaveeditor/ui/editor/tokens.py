"""Design tokens for the Save Game Editor.

These are the tokens from ``docs/design_handoff_save_editor/README.md`` ("Design
Tokens"), which authors colour in OKLCH. Qt stylesheets have no ``oklch()``, so
each value is converted to sRGB hex once, here, and referenced by name everywhere
else — the handoff's OKLCH source is kept in the comment beside each constant so a
token can be re-derived if the design moves.

The editor is a *deliberately self-themed* window: unlike the rest of the app it
does not follow the light/dark palette from :mod:`vaultkeeper.ui.theme`, because
the design is a single dark, gold-accented look that carries the NWN feel. Nothing
here touches the application palette.
"""

from __future__ import annotations

# -- Surfaces ------------------------------------------------------------- #
APP_BG = "#0d0805"  # oklch(0.14 0.012 55)  near-black warm brown
SURFACE = "#110c08"  # oklch(0.16 0.012 55)  raised (toolbar, footer, panels)
SIDEBAR_BG = "#100b08"  # oklch(0.155 0.012 55)
INSET = "#18110d"  # oklch(0.185 0.014 55)  inset panel / input field
ICON_CHIP = "#312620"  # oklch(0.28 0.02 55)   nav icon chip

# -- Accent (gold) -------------------------------------------------------- #
GOLD = "#deaf56"  # oklch(0.78 0.12 82)
GOLD_ON = "#1a1408"  # text drawn *on* a gold fill
_GOLD_TINT = "58, 43, 13"  # oklch(0.3 0.05 82)  -> #3a2b0d
_GOLD_BORDER = "155, 123, 60"  # oklch(0.6 0.09 82) -> #9b7b3c


def gold_tint(alpha: float) -> str:
    """Gold-tinted background fill, e.g. the active nav row (design: .15–.25)."""
    return f"rgba({_GOLD_TINT}, {alpha})"


def gold_border(alpha: float) -> str:
    """Gold border at the design's .4–.5 alphas."""
    return f"rgba({_GOLD_BORDER}, {alpha})"


# -- Text ----------------------------------------------------------------- #
TEXT = "#eeeae7"  # oklch(0.94 0.006 60)
TEXT_HEADING = "#f2ede4"  # headings, as authored
TEXT_2 = "#9e9791"  # oklch(0.68 0.012 60)  secondary
TEXT_3 = "#69625d"  # oklch(0.5 0.012 60)   tertiary

# -- Status --------------------------------------------------------------- #
GREEN = "#55c975"  # oklch(0.75 0.16 150)
DANGER = "#f47b74"  # oklch(0.72 0.15 25)
DANGER_BG = "rgba(66, 28, 25, 0.18)"  # oklch(0.28 0.06 25 / 0.18)
DANGER_BORDER = "rgba(198, 89, 84, 0.45)"  # oklch(0.6 0.14 25 / 0.45)
PRC_AMBER = "#f0a646"  # oklch(0.78 0.14 70)


def hairline(alpha: float = 0.1) -> str:
    """The design's ``rgba(255,255,255,.06–.16)`` hairline borders."""
    return f"rgba(255, 255, 255, {alpha})"


# -- Character-sheet skins (cosmetic only — never change save data) -------- #
#: ``key -> (gradient high, gradient low, border, accent text)``.
SHEET_SKINS: dict[str, tuple[str, str, str, str]] = {
    "leather": ("#312108", "#140801", "rgba(153, 114, 56, 0.55)", "#ddd0b8"),
    "crimson": ("#310d0c", "#110304", "rgba(198, 89, 84, 0.55)", "#e3c8ba"),
    "steel": ("#182029", "#040a11", "rgba(120, 140, 165, 0.55)", "#c9d3de"),
    "verdant": ("#0b2612", "#020c04", "rgba(90, 150, 105, 0.55)", "#cfe0cf"),
}
#: Swatch fill shown in the skin switcher, in the design's order.
SKIN_SWATCHES: tuple[tuple[str, str], ...] = (
    ("leather", "#4a3413"),
    ("crimson", "#5c1c19"),
    ("steel", "#2a3d52"),
    ("verdant", "#1c4a28"),
)

# -- Typography ----------------------------------------------------------- #
#: Display face for the wordmark and section titles. Cinzel was a webfont in the
#: prototype; fall back through faces likely to exist on the user's machine.
DISPLAY_FAMILY = "Cinzel, Optima, Palatino, Georgia, serif"
#: UI face. Inter in the prototype; the platform UI font is the right stand-in.
UI_FAMILY = "Inter, -apple-system, 'Segoe UI', Ubuntu, sans-serif"
MONO_FAMILY = "ui-monospace, Menlo, Consolas, monospace"

# -- Geometry ------------------------------------------------------------- #
TOOLBAR_H = 52
SIDEBAR_W = 236
DETAIL_W = 300
ITEM_CELL = 62
PORTRAIT_W, PORTRAIT_H = 180, 240
NAV_CHIP = 24
SAVE_THUMB = 30
STATUS_DOT = 6

RADIUS_BADGE = 4
RADIUS_CHIP = 6
RADIUS_BUTTON = 7
RADIUS_ROW = 8
RADIUS_PANEL = 10
RADIUS_SHEET = 12

#: Reference window size from the handoff (resizable; sidebar fixed, content scrolls).
WINDOW_W, WINDOW_H = 1400, 900
