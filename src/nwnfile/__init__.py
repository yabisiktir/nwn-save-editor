"""Neverwinter Nights file formats and the game data that gives them meaning.

Everything here is about *reading NWN's files* — GFF, ERF, 2DA, TLK, KEY/BIF,
TGA, PLT — and about naming what those files contain: which feat id is
Whirlwind Attack, what item property 12 does, what a race id is called.

It knows nothing about installing mods and nothing about editing saves. Both
Vaultkeeper and the save editor are built on it, which is why it is its own
package: a change made for one must not be able to reach into the other.
"""
