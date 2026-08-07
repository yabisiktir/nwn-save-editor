"""Design tokens for the Save Game Editor.

The dark set comes from the original design, which authored colour in OKLCH. Qt stylesheets have no
``oklch()``, so each value is converted to sRGB hex once, here, and referenced by
name everywhere else. The OKLCH source is kept in the comment beside each token,
so a value can be re-derived rather than guessed at if the design moves.

The editor also offers a **light** set. It is not a second design: it is the same
layout lit from the other side, anchored on the application palette in
:mod:`vaultkeeper.ui.theme` (window ``#f0f0f0``, base ``#ffffff``, near-black
text) so the editor sits beside the rest of Vaultkeeper, warmed a few points
towards the design's brown hue and with the gold accent darkened until it carries
text on a white surface.

Colour tokens are *not* module constants: they live in :data:`DARK` / :data:`LIGHT`
and are served from the active palette through :pep:`562`'s module ``__getattr__``.
Every call site keeps reading ``t.APP_BG``, and :func:`set_theme` swaps the whole
set live. Geometry and typography do not change with the theme, so those stay
plain constants.

Anything that bakes a token into a module-level string would freeze the theme it
was imported under, which is why the editor's shared stylesheets (``widgets``,
the screens' tree/input QSS) are all built by functions rather than assigned once.
"""

from __future__ import annotations

from typing import Any

#: The themes the editor offers, in the order the toolbar shows them.
THEMES = ("dark", "light")

# --------------------------------------------------------------------------- #
# palettes
# --------------------------------------------------------------------------- #
#: The designed dark, gold-accented look — the editor's default.
DARK: dict[str, Any] = {
    # -- Surfaces --------------------------------------------------------- #
    "APP_BG": "#0d0805",  # oklch(0.14 0.012 55)  near-black warm brown
    "SURFACE": "#110c08",  # oklch(0.16 0.012 55)  raised (toolbar, footer, panels)
    "SIDEBAR_BG": "#100b08",  # oklch(0.155 0.012 55)
    "INSET": "#18110d",  # oklch(0.185 0.014 55)  inset panel
    "INPUT_BG": "#1e1713",  # a line edit / spin box / combo field
    "ALT_ROW": "#191310",  # alternate row in a table view
    "ICON_CHIP": "#312620",  # oklch(0.28 0.02 55)   nav icon chip
    # -- Accent (gold) ---------------------------------------------------- #
    "GOLD": "#deaf56",  # oklch(0.78 0.12 82)
    "GOLD_ON": "#1a1408",  # text drawn *on* a gold fill
    "GOLD_HOVER": "#e8bd6d",  # a gold fill under the pointer
    "GOLD_OFF": "#6b552c",  # a disabled gold fill…
    "GOLD_OFF_ON": "#3a3020",  # …and the text on it
    "GOLD_TINT_RGB": "58, 43, 13",  # oklch(0.3 0.05 82)  -> #3a2b0d
    "GOLD_BORDER_RGB": "155, 123, 60",  # oklch(0.6 0.09 82) -> #9b7b3c
    "TREE_HIGHLIGHT": "#3a2b0d",  # opaque twin of gold_tint(1) for QPalette
    "HAIRLINE_RGB": "255, 255, 255",  # hairlines lighten a dark surface…
    # -- Text ------------------------------------------------------------- #
    "TEXT": "#eeeae7",  # oklch(0.94 0.006 60)
    "TEXT_HEADING": "#f2ede4",  # headings, as authored
    "TEXT_2": "#9e9791",  # oklch(0.68 0.012 60)  secondary
    "TEXT_3": "#69625d",  # oklch(0.5 0.012 60)   tertiary
    # -- Status ----------------------------------------------------------- #
    "GREEN": "#55c975",  # oklch(0.75 0.16 150)
    "DANGER": "#f47b74",  # oklch(0.72 0.15 25)
    "DANGER_BG": "rgba(66, 28, 25, 0.18)",  # oklch(0.28 0.06 25 / 0.18)
    "DANGER_BORDER": "rgba(198, 89, 84, 0.45)",  # oklch(0.6 0.14 25 / 0.45)
    "PRC_AMBER": "#f0a646",  # oklch(0.78 0.14 70)
    "PRC_BORDER": "rgba(240, 166, 70, 0.5)",
    # -- Character-sheet skins (cosmetic only — never change save data) ---- #
    #: ``key -> (gradient high, gradient low, border, accent text)``.
    "SHEET_SKINS": {
        "leather": ("#312108", "#140801", "rgba(153, 114, 56, 0.55)", "#ddd0b8"),
        "crimson": ("#310d0c", "#110304", "rgba(198, 89, 84, 0.55)", "#e3c8ba"),
        "steel": ("#182029", "#040a11", "rgba(120, 140, 165, 0.55)", "#c9d3de"),
        "verdant": ("#0b2612", "#020c04", "rgba(90, 150, 105, 0.55)", "#cfe0cf"),
    },
    #: Swatch fill shown in the skin switcher, in the design's order.
    "SKIN_SWATCHES": (
        ("leather", "#4a3413"),
        ("crimson", "#5c1c19"),
        ("steel", "#2a3d52"),
        ("verdant", "#1c4a28"),
    ),
    #: Body text drawn on a sheet skin, which has its own contrast from the page.
    "SHEET_TEXT": "#f1e6d8",
}

#: The light set. Same structure, same hue family, derived from the application
#: palette so the editor does not look like a different program in light mode.
LIGHT: dict[str, Any] = {
    # -- Surfaces --------------------------------------------------------- #
    # The app's light Window is #f0f0f0 and its Base #ffffff; these keep that
    # relationship and add a few points of the design's warm hue.
    "APP_BG": "#f2f0ec",
    "SURFACE": "#faf8f5",  # raised (toolbar, footer) — reads above the page
    "SIDEBAR_BG": "#ebe8e2",  # recessed, so the nav rail still separates
    "INSET": "#ffffff",  # inset panel — the app palette's Base
    "INPUT_BG": "#ffffff",
    "ALT_ROW": "#f5f2ed",
    "ICON_CHIP": "#e7dfd0",
    # -- Accent (gold) ---------------------------------------------------- #
    # The design's #deaf56 carries no text on white (1.8:1). Darkening it to
    # oklch(~0.52 0.1 75) keeps the gold identity at 5.7:1 on the inset surface.
    "GOLD": "#8a5e12",
    "GOLD_ON": "#fff6e4",
    "GOLD_HOVER": "#6f4a0c",  # darker under the pointer, the light-mode direction
    "GOLD_OFF": "#e0d5bd",
    "GOLD_OFF_ON": "#9b9083",
    "GOLD_TINT_RGB": "205, 158, 62",  # a wash *towards* gold, not away from it
    "GOLD_BORDER_RGB": "164, 122, 38",
    "TREE_HIGHLIGHT": "#ebdfc4",
    "HAIRLINE_RGB": "0, 0, 0",  # …and darken a light one, at the same alphas
    # -- Text ------------------------------------------------------------- #
    "TEXT": "#1c1714",
    "TEXT_HEADING": "#120e0b",
    "TEXT_2": "#5b544e",
    "TEXT_3": "#8b837c",
    # -- Status ----------------------------------------------------------- #
    "GREEN": "#1d7a3e",
    "DANGER": "#b3261e",
    "DANGER_BG": "rgba(211, 71, 61, 0.1)",
    "DANGER_BORDER": "rgba(179, 38, 30, 0.35)",
    "PRC_AMBER": "#8a5a08",
    "PRC_BORDER": "rgba(138, 90, 8, 0.45)",
    # -- Character-sheet skins -------------------------------------------- #
    # Parchment rather than tooled leather: the sheet still reads as a card of
    # its own, but a dark card floating on a light page would look like an error.
    "SHEET_SKINS": {
        "leather": ("#f1e4cd", "#dcc9a4", "rgba(153, 114, 56, 0.55)", "#6b4a1c"),
        "crimson": ("#f7dedb", "#e8bdb8", "rgba(180, 80, 76, 0.55)", "#7c2b26"),
        "steel": ("#e5ecf3", "#c9d6e4", "rgba(100, 125, 155, 0.55)", "#2f4560"),
        "verdant": ("#e0f0e3", "#bfdcc6", "rgba(80, 140, 95, 0.55)", "#26542f"),
    },
    "SKIN_SWATCHES": (
        ("leather", "#d8bf8e"),
        ("crimson", "#e0a49c"),
        ("steel", "#a9bed4"),
        ("verdant", "#a6cdae"),
    ),
    "SHEET_TEXT": "#2a211a",
}

_PALETTES = {"dark": DARK, "light": LIGHT}
_theme = "dark"
_active = DARK


def set_theme(name: str) -> str:
    """Make ``name`` the active palette and return the name actually applied.

    An unrecognised name falls back to dark rather than raising: the theme is
    read from a settings file the user can edit, and a bad value there should
    not stop the editor from opening.
    """
    global _theme, _active
    _theme = name if name in _PALETTES else "dark"
    _active = _PALETTES[_theme]
    return _theme


def active_theme() -> str:
    """The active palette's name."""
    return _theme


def __getattr__(name: str) -> Any:
    """Serve colour tokens from the active palette (:pep:`562`)."""
    try:
        return _active[name]
    except KeyError:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}") from None


def __dir__() -> list[str]:
    """Include the palette's tokens, which ``__getattr__`` would otherwise hide."""
    return sorted({*globals(), *_active})


def gold_tint(alpha: float) -> str:
    """Gold-tinted background fill, e.g. the active nav row (design: .15–.25)."""
    return f"rgba({_active['GOLD_TINT_RGB']}, {alpha})"


def gold_border(alpha: float) -> str:
    """Gold border at the design's .4–.5 alphas."""
    return f"rgba({_active['GOLD_BORDER_RGB']}, {alpha})"


def hairline(alpha: float = 0.1) -> str:
    """The design's ``rgba(255,255,255,.06–.16)`` hairline borders.

    Light mode uses black at the same alphas: a hairline is "a little of the
    opposite of the surface", so the alphas the screens pass stay meaningful.
    """
    return f"rgba({_active['HAIRLINE_RGB']}, {alpha})"


def hairline_rgb() -> str:
    """The hairline colour as bare ``r, g, b``, for painting rather than QSS."""
    return _active["HAIRLINE_RGB"]


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

#: Reference window size from the design (resizable; sidebar fixed, content scrolls).
WINDOW_W, WINDOW_H = 1400, 900
