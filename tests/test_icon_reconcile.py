"""The Qt-free appearance-reconcile engine (nwnfile.icon_reconcile)."""
from __future__ import annotations

from nwnfile.icon_reconcile import Appearance, IconReconciler, similarity


class FImg:
    has_alpha = True

    def __init__(self, colour: tuple[int, int, int], size: int = 8) -> None:
        self.width = self.height = size
        self._rgba = bytes(colour + (255,)) * (size * size)

    def to_rgba(self) -> bytes:
        return self._rgba


_FALLBACK = FImg((10, 10, 10))


class FakeSource:
    """Models which per-variant icons a content set has for a base item."""

    def __init__(self, rows: dict, icons: dict, raw: dict | None = None) -> None:
        self.rows = rows          # base -> (ItemClass, DefaultIcon, ModelType)
        self.icons = icons        # (base, model_part) -> FImg
        self.raw = raw or {}      # (resref, res_type) -> bytes

    def base_item_row(self, base):
        return self.rows.get(base)

    def specific_image(self, base, model_part, **variant):
        return self.icons.get((base, model_part))

    def icon_image(self, base, model_part, **variant):
        img = self.icons.get((base, model_part))
        return img if img is not None else (_FALLBACK if base in self.rows else None)

    def specific_resref(self, base, model_part, **variant):
        if (base, model_part) in self.icons:
            return f"i{self.rows[base][0]}_{model_part:03d}", 3
        return None

    def raw_resource(self, resref, res_type):
        return self.raw.get((resref, res_type))


def test_similarity_is_1_for_identical_and_lower_for_different():
    red, blue = FImg((200, 0, 0)), FImg((0, 0, 200))
    assert similarity(red, red) == 1.0
    assert similarity(red, blue) < similarity(red, red)
    assert similarity(red, blue) < 0.8


def test_an_item_absent_from_the_module_is_broken():
    rows = {52: ("it_ring", "iit_ring", 0)}
    orig = FakeSource(rows, {(52, 130): FImg((200, 0, 0))},
                      raw={("iit_ring_130", 3): b"ART"})
    target = FakeSource(rows, {(52, 1): FImg((0, 200, 0))})
    rep = IconReconciler(orig, target).report("ring", "equip", Appearance(52, 130))
    assert rep.broken is True


def test_an_item_the_module_has_is_not_broken():
    rows = {52: ("it_ring", "iit_ring", 0)}
    src = FakeSource(rows, {(52, 5): FImg((1, 2, 3))})
    rep = IconReconciler(src, src).report("ring", "equip", Appearance(52, 5))
    assert rep.broken is False
    assert rep.match_number is None and rep.extract is None


def test_match_picks_the_closest_available_appearance():
    rows = {52: ("it_ring", "iit_ring", 0)}
    orig = FakeSource(rows, {(52, 130): FImg((200, 0, 0))},
                      raw={("iit_ring_130", 3): b"ART"})
    # target has a green ring (1) and a near-red ring (14); 14 should win
    target = FakeSource(rows, {(52, 1): FImg((0, 200, 0)), (52, 14): FImg((190, 10, 10))})
    rep = IconReconciler(orig, target).report("ring", "equip", Appearance(52, 130))
    assert rep.match_number == 14
    assert rep.match_fields[0].field == "ModelPart1"
    assert rep.match_fields[0].value == 14


def test_extract_plans_a_free_slot_and_a_copy():
    rows = {52: ("it_ring", "iit_ring", 0)}
    orig = FakeSource(rows, {(52, 130): FImg((200, 0, 0))},
                      raw={("iit_ring_130", 3): b"ART"})
    target = FakeSource(rows, {(52, 1): FImg((0, 200, 0))})
    rep = IconReconciler(orig, target).report("ring", "equip", Appearance(52, 130))
    assert rep.extract is not None
    assert rep.extract.slot == 250  # first free high slot
    op = rep.extract.copies[0]
    assert op.src_resref == "iit_ring_130" and op.dst_resref == "iit_ring_250"
    assert rep.extract.fields[0].field == "ModelPart1"
    assert rep.extract.fields[0].value == 250


def test_armour_extract_uses_the_robe_part_and_no_match():
    rows = {16: ("AArCl", "iit_chest", 3)}
    orig = FakeSource(rows, {(16, 0): FImg((200, 200, 200))},
                      raw={("ipm_robe171", 3): b"ROBE"})
    # specific_resref for armour must resolve the robe icon
    orig.icons[(16, 0)] = FImg((200, 200, 200))
    orig.specific_resref = lambda b, m, **v: ("ipm_robe171", 3)  # type: ignore[assignment]
    target = FakeSource(rows, {})
    rep = IconReconciler(orig, target).report(
        "robe", "equip", Appearance(16, 0, armor_robe=171))
    assert rep.broken is True
    assert rep.match_number is None  # armour is not single-part
    assert rep.extract is not None
    assert rep.extract.copies[0].dst_resref == "ipm_robe250"
    assert rep.extract.fields[0].field == "ArmorPart_Robe"


# -- worn 3D model planning -------------------------------------------------- #
class FakeRes:
    """A stand-in ResourceStack: source has models (with a texture token) and the
    target lacks that texture."""

    def __init__(self, models: dict, source_tex: set, target_tex: set):
        self.models = models          # (resref,2002) -> bytes
        self.source_tex = source_tex  # resrefs that are textures in source
        self.target_tex = target_tex  # resrefs the target has

    def has(self, resref, res_type):
        if res_type == 2002:
            return (resref.lower(), 2002) in self.models
        return resref.lower() in self.source_tex

    def read(self, resref, res_type):
        return self.models.get((resref.lower(), res_type))

    def texture_type(self, resref):
        return 3 if resref.lower() in self.source_tex else None

    def has_texture(self, resref):
        return resref.lower() in self.target_tex

    def matching(self, pattern, res_type):
        import re
        rx = re.compile(pattern)
        return sorted(r for (r, t) in self.models if t == res_type and rx.match(r))


def test_extract_plans_weapon_models_and_missing_textures():
    rows = {53: ("wswsc", "iwswsc", 2)}  # a composite (weapon) base item
    orig = FakeSource(rows, {(53, 112): FImg((1, 1, 1))},
                      raw={("iwswsc_b_112", 3): b"i", ("iwswsc_m_142", 3): b"i",
                           ("iwswsc_t_182", 3): b"i"})
    target = FakeSource(rows, {})
    model = b"...wswsc_b_112 al_shny_gld_tex al_leather04_tex pommel_1..."
    orig_res = FakeRes(
        models={("wswsc_b_112", 2002): model, ("wswsc_m_142", 2002): model,
                ("wswsc_t_182", 2002): model},
        source_tex={"al_shny_gld_tex", "al_leather04_tex"},
        target_tex=set())
    target_res = FakeRes({}, set(), target_tex={"al_shny_gld_tex"})  # gold present, leather absent

    rec = IconReconciler(orig, target, orig_res, target_res)
    from nwnfile.icon_reconcile import Appearance as A
    rep = rec.report("godwind", "worn", A(53, 112, 142, 182))
    dsts = {(c.dst_resref, c.res_type) for c in rep.extract.copies}
    # the three weapon part models, relocated to the free slot
    assert ("wswsc_b_250", 2002) in dsts
    assert ("wswsc_m_250", 2002) in dsts
    assert ("wswsc_t_250", 2002) in dsts
    # the missing texture is carried (under its own name); the present one is not
    assert ("al_leather04_tex", 3) in dsts
    assert ("al_shny_gld_tex", 3) not in dsts


def test_two_broken_items_of_one_class_get_distinct_slots():
    rows = {52: ("it_ring", "iit_ring", 0)}
    orig = FakeSource(rows, {(52, 130): FImg((200, 0, 0)), (52, 131): FImg((0, 200, 0))},
                      raw={("iit_ring_130", 3): b"A", ("iit_ring_131", 3): b"B"})
    target = FakeSource(rows, {})
    rec = IconReconciler(orig, target)
    a = rec.report("ring_a", "worn", Appearance(52, 130))
    b = rec.report("ring_b", "worn", Appearance(52, 131))
    assert a.extract.slot != b.extract.slot  # not both 250


def test_cloak_relocates_phenotype_worn_models():
    rows = {80: ("cloak", "icloak", 1)}  # cloak: layered, phenotype worn models
    orig = FakeSource(rows, {(80, 20): FImg((3, 3, 3))},
                      raw={("icloak_020", 3): b"i"})
    target = FakeSource(rows, {})
    orig_res = FakeRes(
        models={("pmh0_cloak_020", 2002): b"m", ("pfh0_cloak_020", 2002): b"m"},
        source_tex=set(), target_tex=set())
    target_res = FakeRes({}, set(), set())
    rec = IconReconciler(orig, target, orig_res, target_res)
    rep = rec.report("cloakX", "worn", Appearance(80, 20))
    dsts = {c.dst_resref for c in rep.extract.copies if c.res_type == 2002}
    assert dsts == {"pmh0_cloak_250", "pfh0_cloak_250"}  # underscore before the number
