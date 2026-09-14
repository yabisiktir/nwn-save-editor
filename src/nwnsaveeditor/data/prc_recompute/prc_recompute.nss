//::///////////////////////////////////////////////
//:: prc_recompute
//:: Tag-based item script: recompute PRC-managed features on activation.
//::
//:: Behind the "Recompute PRC Features" widget the editor can add to a character.
//:: The item's Tag is "prc_recompute", so activating its Unique Power runs this
//:: (the module fires the item's tag-named script — PRC content relies on tag-based
//:: scripting). Generic: no class/template/build assumptions.
//::
//:: Two passes, because PRC keeps its managed state in two kinds of place:
//::   1. EvalPRCFeats — re-runs the whole PRC maintenance pass (feats, the invisible
//::      skin, class scripts and applied templates). Non-destructive: keeps level
//::      and spells, unlike /relevel. We clear the module's running-event flag first
//::      so PRC's template/class scripts take their *rebuild* branch — the one that
//::      re-applies persistent state — which gates on GetRunningEvent()==FALSE (true
//::      on a natural module load, but not inside this item-activate event). The flag
//::      is restored after the delayed template scripts have run.
//::   2. Re-equip the held weapons — on-hit / on-equip class powers are wired onto the
//::      *weapon* when PRC re-evaluates you on equip, so cycling the weapon re-applies
//::      them. A full /relevel (twice, in chat) remains the last resort for anything
//::      PRC only builds at level-up.
//::///////////////////////////////////////////////
#include "prc_inc_function"
#include "x2_inc_switches"

//:: The module local int GetRunningEvent() reads (see inc_eventhook). FALSE means
//:: "not inside an event" — the context PRC's rebuild path expects.
const string PRC_RUNNING_EVENT = "prc_eventhook_running";

void _recycle(object oPC, int nSlot)
{
    object oItem = GetItemInSlot(nSlot, oPC);
    if (GetIsObjectValid(oItem))
    {
        AssignCommand(oPC, ActionUnequipItem(oItem));
        AssignCommand(oPC, ActionEquipItem(oItem, nSlot));
    }
}

void main()
{
    if (GetUserDefinedItemEventNumber() != X2_ITEM_EVENT_ACTIVATE)
        return;

    object oPC = GetItemActivator();
    if (!GetIsObjectValid(oPC))
        oPC = OBJECT_SELF;

    SendMessageToPC(oPC, "Recomputing PRC features (feats, skin, templates)...");

    object oMod = GetModule();
    int nSaved = GetLocalInt(oMod, PRC_RUNNING_EVENT);
    SetLocalInt(oMod, PRC_RUNNING_EVENT, FALSE);
    EvalPRCFeats(oPC);
    DelayCommand(1.0, SetLocalInt(oMod, PRC_RUNNING_EVENT, nSaved));

    // Re-wire on-hit / on-equip weapon powers once the feat pass has settled.
    DelayCommand(1.5, _recycle(oPC, INVENTORY_SLOT_RIGHTHAND));
    DelayCommand(1.5, _recycle(oPC, INVENTORY_SLOT_LEFTHAND));

    DelayCommand(2.5, SendMessageToPC(oPC,
        "PRC features recomputed. If a class power is still missing, unequip and " +
        "re-equip that item, or type /relevel twice in chat for a full rebuild."));
}
