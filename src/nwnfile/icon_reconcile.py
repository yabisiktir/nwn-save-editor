"""Reconcile a character's item *appearances* against the module being played.

Gear made for one content pack (CEP2 + Aielund/Sands-of-Fate) shows default/blank
pictures under another (CEP3 Swordflight), because an item stores its appearance as
*numbers* whose model/icon files are absent there. This module, given two icon
sources — the item's **original** look (resolved across every hak the character's
campaigns load) and what the **target** module actually renders — reports, per item:

* whether the appearance is *broken* in the target (shows the generic fallback);
* the *closest* target appearance that looks like the original (single-part items);
* an *extract* plan: copy the original icon into a free appearance slot so the true
  look survives in every module, colliding with nothing.

It is Qt-free and deterministic; the wizard UI and any CLI sit on top of it. Icons
first: this reasons about the inventory picture, not the in-world model.
"""
from __future__ import annotations

from dataclasses import dataclass, field

_TGA, _PLT, _MDL = 3, 6, 2002
_SINGLE, _COMPOSITE, _ARMOUR = (0, 1), 2, 3
#: Appearance variation numbers are a single byte, so a relocated slot must be
#: 1..254 (255/0 are avoided as engine-reserved). We hand them out high-first —
#: high numbers are least likely to be used by base/CEP content — scanning the
#: whole byte range so a class with many custom items still has room.
_FREE_SLOT_HIGH, _FREE_SLOT_LOW = 254, 1
#: gender/phenotype model prefixes an armour part can ship under; we relocate
#: every one the source has so whatever the character's body asks for is present.
_ARMOUR_PREFIXES = ("pmh0", "pfh0", "pma0", "pfa0", "pmb0", "pfb0", "pmh1", "pfh1")
#: ArmorPart_* GFF field -> the body-part token in its model resref
#: (``p<gender><pheno>0_<token><nnn>``), verified against the real part models.
_ARMOUR_TOKENS = {
    "ArmorPart_Neck": "neck", "ArmorPart_Torso": "chest", "ArmorPart_Belt": "belt",
    "ArmorPart_Pelvis": "pelvis", "ArmorPart_Robe": "robe",
    "ArmorPart_LShoul": "shol", "ArmorPart_RShoul": "shor",
    "ArmorPart_LBicep": "bicepl", "ArmorPart_RBicep": "bicepr",
    "ArmorPart_LFArm": "forel", "ArmorPart_RFArm": "forer",
    "ArmorPart_LHand": "handl", "ArmorPart_RHand": "handr",
    "ArmorPart_LThigh": "legl", "ArmorPart_RThigh": "legr",
    "ArmorPart_LShin": "shinl", "ArmorPart_RShin": "shinr",
    "ArmorPart_LFoot": "footl", "ArmorPart_RFoot": "footr",
}


@dataclass(frozen=True)
class Appearance:
    """An item's appearance-defining fields (only what the icon depends on)."""

    base_item: int
    model_part1: int = 0
    model_part2: int = 0
    model_part3: int = 0
    armor_torso: int = 0
    armor_robe: int = 0
    female: bool = False
    #: every ArmorPart_* field -> its value (for full multi-part armour relocation);
    #: empty for non-armour items or when only torso/robe are known.
    armor_parts: dict = field(default_factory=dict)

    def variant(self) -> dict:
        return {
            "model_part2": self.model_part2, "model_part3": self.model_part3,
            "armor_torso": self.armor_torso, "armor_robe": self.armor_robe,
            "female": self.female,
        }


@dataclass
class CopyOp:
    """Copy one source resource to a new resref (into override)."""

    src_resref: str
    res_type: int
    dst_resref: str


@dataclass
class FieldSet:
    """Set one appearance field to a value (apply mirrors xArmorPart_* itself)."""

    field: str
    value: int


@dataclass
class ExtractPlan:
    """Relocate the original art to a free slot and re-point the item at it."""

    slot: int
    copies: list[CopyOp] = field(default_factory=list)
    fields: list[FieldSet] = field(default_factory=list)


@dataclass
class ItemReport:
    resref: str
    slot: str
    appearance: Appearance
    original_image: object | None
    current_image: object | None
    broken: bool
    match_number: int | None = None
    match_image: object | None = None
    match_score: float | None = None
    match_fields: list[FieldSet] = field(default_factory=list)
    extract: ExtractPlan | None = None


def _downscale(image, n: int = 16) -> list[tuple[int, int, int, int]]:
    """A tiny n*n RGBA thumbnail (nearest-sample), for comparing two icons."""
    w, h = image.width, image.height
    rgba = image.to_rgba()
    out = []
    for gy in range(n):
        for gx in range(n):
            sx = min(w - 1, gx * w // n)
            sy = min(h - 1, gy * h // n)
            i = (sy * w + sx) * 4
            out.append((rgba[i], rgba[i + 1], rgba[i + 2], rgba[i + 3]))
    return out


def similarity(a, b) -> float:
    """1.0 identical, 0.0 unrelated. Compares small thumbnails, weighting colour by
    the overlap of the two silhouettes so shape counts as much as palette."""
    if a is None or b is None:
        return 0.0
    ta, tb = _downscale(a), _downscale(b)
    total = 0.0
    for (ar, ag, ab, aa), (br, bg, bb, ba) in zip(ta, tb, strict=True):
        shape = 1.0 - abs(aa - ba) / 255.0
        if aa < 8 and ba < 8:
            colour = 1.0  # both transparent here — agree
        else:
            d = (abs(ar - br) + abs(ag - bg) + abs(ab - bb)) / (3 * 255.0)
            colour = 1.0 - d
        total += 0.5 * shape + 0.5 * colour
    return total / len(ta)


class IconReconciler:
    def __init__(self, original_src, target_src,
                 original_res=None, target_res=None, body_prefixes=None) -> None:
        self._orig = original_src
        self._target = target_src
        #: optional ResourceStacks for reading models/textures (worn appearance).
        #: Without them, extract plans the inventory icon only.
        self._orig_res = original_res
        self._target_res = target_res
        #: which gender/phenotype body-model prefixes to relocate for armour and
        #: cloaks. ``None`` = all of them (survives an appearance change but many
        #: files); a tuple (e.g. ``("pmh0",)``) = just this character's body, far
        #: fewer files. Falls back to all when a prefix isn't in the source.
        self._body_prefixes = tuple(body_prefixes) if body_prefixes else None
        #: free slots already handed out this run, per resref namespace — so two
        #: items of the same class don't both grab slot 250 and share one model.
        self._reserved: dict[str, set[int]] = {}

    # -- classification ---------------------------------------------------- #
    def report(self, resref: str, slot: str, ap: Appearance) -> ItemReport:
        # Broken = the module has no per-variant icon of its own for this item,
        # but the original art exists somewhere to offer. Both are checked by
        # resource *presence* (no image decoding) — decoding every item's icon
        # just to classify it was the whole cost. Only broken items are decoded.
        v = ap.variant()
        icon_broken = (
            not self._target.has_specific_icon(ap.base_item, ap.model_part1, **v)
            and self._orig.has_specific_icon(ap.base_item, ap.model_part1, **v))
        # Also broken when the item renders an icon fine but the module lacks its
        # worn *model* — e.g. boots whose icon is stock but whose model is custom.
        broken = icon_broken or self._worn_broken(ap)
        if not broken:
            return ItemReport(resref, slot, ap, None, None, False)
        original = self._orig.icon_image(ap.base_item, ap.model_part1, **v)
        current = self._target.icon_image(ap.base_item, ap.model_part1, **v)
        rep = ItemReport(resref, slot, ap, original, current, True)
        self._add_match(rep)
        self._add_extract(rep)
        return rep

    def _worn_broken(self, ap: Appearance) -> bool:
        """True when the source has a worn model for this item that the target
        module lacks — the icon can be fine while the in-world model falls back
        (boots and weapons especially). Needs the resource stacks; skips armour
        (its per-part breakage is handled in extract) and item types with no worn
        model (rings, amulets — nothing to miss)."""
        if self._orig_res is None or self._target_res is None:
            return False
        row = self._target.base_item_row(ap.base_item)
        if row is None:
            return False
        item_class, _default, model_type = row
        if not item_class:
            return False
        if model_type == _COMPOSITE:
            m = f"{item_class}_b_{ap.model_part1:03d}"[:16].lower()
            return self._orig_res.has(m, _MDL) and not self._target_res.has(m, _MDL)
        if model_type in _SINGLE:
            if item_class == "cloak":
                got = self._orig_res.matching(
                    rf"^p[fm][a-z][0-9]_cloak_{ap.model_part1:03d}$", _MDL)
                return bool(got) and not any(self._target_res.has(x, _MDL) for x in got)
            m = f"{item_class}_{ap.model_part1:03d}"[:16].lower()
            return self._orig_res.has(m, _MDL) and not self._target_res.has(m, _MDL)
        return False

    # -- closest match (single-part items only) ---------------------------- #
    def _add_match(self, rep: ItemReport) -> None:
        row = self._target.base_item_row(rep.appearance.base_item)
        if row is None or row[2] not in _SINGLE or rep.original_image is None:
            return
        best_n, best_img, best_score = None, None, -1.0
        for n in range(1, 256):
            img = self._target.specific_image(rep.appearance.base_item, n)
            if img is None:
                continue
            score = similarity(rep.original_image, img)
            if score > best_score:
                best_n, best_img, best_score = n, img, score
        if best_n is not None:
            rep.match_number = best_n
            rep.match_image = best_img
            rep.match_score = best_score
            rep.match_fields = [FieldSet("ModelPart1", best_n)]

    # -- extract & relocate ------------------------------------------------ #
    def _add_extract(self, rep: ItemReport) -> None:
        ap = rep.appearance
        row = self._target.base_item_row(ap.base_item)
        if row is None:
            return
        item_class, _default, model_type = row
        copies: list[CopyOp] = []
        fields: list[FieldSet] = []
        if model_type in _SINGLE and item_class:
            primary = self._extract_single(ap, item_class, copies, fields)
        elif model_type == _COMPOSITE and item_class:
            primary = self._extract_composite(ap, item_class, copies, fields)
        elif model_type == _ARMOUR:
            primary = self._extract_armour(ap, copies, fields)
        else:
            return
        if primary is None or not copies:
            return
        self._add_textures(copies)
        rep.extract = ExtractPlan(primary, copies, fields)

    def _has_source_model(self, resref: str) -> bool:
        return self._orig_res is not None and self._orig_res.has(resref, _MDL)

    def _extract_single(self, ap, item_class, copies, fields):
        slot = self._free_slot(item_class, ap.base_item, 0)
        if slot is None:
            return None
        src = self._orig.specific_resref(ap.base_item, ap.model_part1, **ap.variant())
        if src is None:
            return None
        copies.append(CopyOp(src[0], src[1], f"i{item_class}_{slot:03d}"[:16]))
        fields.append(FieldSet("ModelPart1", slot))
        model = f"{item_class}_{ap.model_part1:03d}"[:16].lower()
        if self._has_source_model(model):
            copies.append(CopyOp(model, _MDL, f"{item_class}_{slot:03d}"[:16].lower()))
        if item_class == "cloak":
            self._add_cloak_models(ap.model_part1, slot, copies)
        return slot

    def _add_cloak_models(self, num: int, slot: int, copies: list) -> None:
        """Cloaks are worn as phenotype body models ``p<gender><pheno>_cloak_<nnn>``
        (note the underscore before the number, unlike armour parts). Relocate every
        gender/phenotype variant the source ships whose art differs in the target."""
        if self._orig_res is None:
            return
        for src in self._orig_res.matching(rf"^p[fm][a-z][0-9]_cloak_{num:03d}$", _MDL):
            if self._body_prefixes and src.split("_")[0] not in self._body_prefixes:
                continue  # minimal mode: only this character's body prefix
            dst = src[: src.rfind("_") + 1] + f"{slot:03d}"
            copies.append(CopyOp(src, _MDL, dst))
            if self._orig_res.has(src, _PLT):
                copies.append(CopyOp(src, _PLT, dst))

    def _extract_composite(self, ap, item_class, copies, fields):
        slot = self._free_slot(item_class, ap.base_item, _COMPOSITE)
        if slot is None:
            return None
        for letter, num, fname in (
            ("b", ap.model_part1, "ModelPart1"),
            ("m", ap.model_part2, "ModelPart2"),
            ("t", ap.model_part3, "ModelPart3"),
        ):
            if not num:
                continue
            icon = f"i{item_class}_{letter}_{num:03d}"[:16]
            for rtype in (_TGA, _PLT):
                if self._orig.raw_resource(icon, rtype) is not None:
                    copies.append(CopyOp(icon, rtype, f"i{item_class}_{letter}_{slot:03d}"[:16]))
                    break
            model = f"{item_class}_{letter}_{num:03d}"[:16].lower()
            if self._has_source_model(model):
                copies.append(CopyOp(
                    model, _MDL, f"{item_class}_{letter}_{slot:03d}"[:16].lower()))
            fields.append(FieldSet(fname, slot))
        return slot

    def _extract_armour(self, ap, copies, fields):
        """Relocate every broken part of the suit — not just the icon part — so the
        whole worn body is reconstructed. The icon part (robe/chest) also carries
        the inventory picture; other parts carry model + matching PLT skin."""
        g = "f" if ap.female else "m"
        icon_field = "ArmorPart_Robe" if ap.armor_robe else "ArmorPart_Torso"
        parts = ap.armor_parts or {icon_field: ap.armor_robe or ap.armor_torso}
        primary = None
        for field_name, token in _ARMOUR_TOKENS.items():
            num = int(parts.get(field_name, 0) or 0)
            if num <= 0:
                continue
            is_icon = field_name == icon_field
            src_prefixes = [
                p for p in (self._body_prefixes or _ARMOUR_PREFIXES)
                if self._has_source_model(f"{p}_{token}{num:03d}"[:16])
            ]
            if not is_icon:
                # relocate a non-icon part when its art differs from what the
                # target renders — absent there, or present as *different* bytes
                # (CEP2 vs CEP3 reuse part numbers for different art). Parts that
                # are byte-identical (base-game body parts) are left alone.
                if not src_prefixes or self._orig_res is None or self._target_res is None:
                    continue
                if not any(self._part_differs(p, token, num) for p in src_prefixes):
                    continue
            slot = self._free_slot(f"armour:{token}", ap.base_item, _ARMOUR)
            if slot is None:
                continue
            for p in src_prefixes:
                s = f"{p}_{token}{num:03d}"[:16].lower()
                d = f"{p}_{token}{slot:03d}"[:16].lower()
                copies.append(CopyOp(s, _MDL, d))
                if self._orig_res is not None and self._orig_res.has(s, _PLT):
                    copies.append(CopyOp(s, _PLT, d))
            if is_icon:
                src = self._orig.specific_resref(
                    ap.base_item, ap.model_part1, **ap.variant())
                if src is not None:
                    copies.append(CopyOp(src[0], src[1], f"ip{g}_{token}{slot:03d}"[:16]))
                primary = slot
            fields.append(FieldSet(field_name, slot))
        return primary

    def _part_differs(self, prefix: str, token: str, num: int) -> bool:
        """True if the target renders a different (or no) model for this armour part
        than the source — i.e. relocating it would change the look."""
        resref = f"{prefix}_{token}{num:03d}"[:16]
        target = self._target_res.read(resref, _MDL)
        if target is None:
            return True
        return target != self._orig_res.read(resref, _MDL)

    def _add_textures(self, copies: list) -> None:
        """Append the dependency textures the target lacks for every model already
        planned — safe, since they keep their own name (the target has nothing
        there). No-op without the resource stacks."""
        if self._orig_res is None or self._target_res is None:
            return
        from nwnfile.resource_stack import model_texture_candidates

        seen = {(op.dst_resref, op.res_type) for op in copies}
        extra: list[CopyOp] = []
        for op in list(copies):
            if op.res_type != _MDL:
                continue
            data = self._orig_res.read(op.src_resref, _MDL)
            if not data:
                continue
            for tok in model_texture_candidates(data):
                rt = self._orig_res.texture_type(tok)
                if rt is not None and not self._target_res.has_texture(tok) \
                        and (tok, rt) not in seen:
                    seen.add((tok, rt))
                    extra.append(CopyOp(tok, rt, tok))
        copies.extend(extra)

    def _free_slot(self, namespace: str, base_item: int, model_type: int) -> int | None:
        """A variant number the target renders nothing for AND not already handed
        out to another item in this run — then reserve it."""
        reserved = self._reserved.setdefault(namespace, set())
        for n in range(_FREE_SLOT_HIGH, _FREE_SLOT_LOW - 1, -1):
            if n in reserved:
                continue
            if model_type == _ARMOUR:
                taken = self._target.specific_image(base_item, 0, armor_robe=n) is not None \
                    or self._target.specific_image(base_item, 0, armor_torso=n) is not None
            else:
                taken = self._target.specific_image(base_item, n) is not None
            if not taken:
                reserved.add(n)
                return n
        return None
