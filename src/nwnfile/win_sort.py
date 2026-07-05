"""Windows Explorer natural sort — cross-platform reproduction of ``WinCompare``.

The VB app orders file keys with ``WinCompare(x, y) = StrCmpLogicalW(x.lower(),
y.lower())`` (``LazWorks Miscellaneous.vb:30`` → ``WindowsAPI.vb:114``). That is
the Windows shell "logical" comparison: case-insensitive, with embedded digit
runs compared **numerically** ("Mod 2" < "Mod 10"). This ordering is not
cosmetic — it decides install-conflict winners (the greatest key wins), and NWN
mod names routinely carry numeric prefixes, so we must reproduce it exactly on
macOS/Linux where the Win32 API is unavailable.

:func:`win_compare` returns -1/0/1 and is a total order, matching how the VB
comparer is used (``list.sort`` then take the last/first element).
"""

from __future__ import annotations


def _num_value(run: str) -> tuple[int, str]:
    """Numeric comparison key for a digit run: (value-ignoring-leading-zeros)."""
    stripped = run.lstrip("0")
    return (len(stripped), stripped)  # length then lexicographic == numeric order


def win_compare(a: str, b: str) -> int:
    """Compare two strings the way Windows Explorer does (natural, case-insensitive).

    Returns -1 if ``a`` sorts before ``b``, 1 if after, 0 if equal.
    """
    a = a.lower()
    b = b.lower()
    ia = ib = 0
    la, lb = len(a), len(b)

    while ia < la and ib < lb:
        ca, cb = a[ia], b[ib]
        if ca.isdigit() and cb.isdigit():
            ja = ia
            while ja < la and a[ja].isdigit():
                ja += 1
            jb = ib
            while jb < lb and b[jb].isdigit():
                jb += 1
            run_a, run_b = a[ia:ja], b[ib:jb]
            key_a, key_b = _num_value(run_a), _num_value(run_b)
            if key_a != key_b:
                return -1 if key_a < key_b else 1
            # Equal numeric value: the run with fewer leading zeros sorts first
            # (approximates StrCmpLogicalW's tie-break; irrelevant for real names).
            if len(run_a) != len(run_b):
                return -1 if len(run_a) < len(run_b) else 1
            ia, ib = ja, jb
        else:
            if ca != cb:
                return -1 if ca < cb else 1
            ia += 1
            ib += 1

    # Whichever string still has characters is the greater one.
    rem = (la - ia) - (lb - ib)
    return -1 if rem < 0 else (1 if rem > 0 else 0)
