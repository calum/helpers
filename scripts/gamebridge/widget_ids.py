"""
Named widget component constants for GameBridge routines.

Each constant is a ``(group_id, child_id)`` tuple that can be passed directly
to ``GameState.find_widget``:

    from scripts.gamebridge.widget_ids import BankDepositBox
    btn = game.find_widget(*BankDepositBox.DEPOSIT_INV)

How the IDs are derived
-----------------------
RuneLite's ``InterfaceID.java`` (runelite-api/src/main/java/net/runelite/api/gameval/)
encodes every component as a packed 32-bit int:

    packed = (group_id << 16) | child_id

So ``0x00c0_001f`` decodes as group_id=0x00c0=192, child_id=0x001f=31.

Each class here corresponds to the same-named nested class in ``InterfaceID.java``.
The inline hex comment is the original Java constant, making it trivial to
verify or update if RuneLite changes the IDs in a future version.

Keeping in sync
---------------
When a RuneLite update changes a component ID:
1. Find the new hex value in InterfaceID.java (the nested class matching this class name).
2. Update the tuple and the comment on the same line.
3. No other files need changing.
"""
from __future__ import annotations


class BankDepositBox:
    """
    The bank deposit box interface (mine cart, deposit chests, etc.).

    Java source: ``InterfaceID.BankDepositbox``  (group 192 = 0x00c0)
    Exposed by GameBridge when ``exposeWidgets`` is enabled.
    """
    GROUP = 192

    # Deposit action buttons
    DEPOSIT_ALL_BUTTONS = (192, 0x1d)  # 0x00c0_001d — container holding the three deposit buttons
    DEPOSIT_WORN        = (192, 0x1e)  # 0x00c0_001e — "Deposit worn items" button
    DEPOSIT_INV         = (192, 0x1f)  # 0x00c0_001f — "Deposit inventory" button
    DEPOSIT_LOOTINGBAG  = (192, 0x20)  # 0x00c0_0020 — "Deposit looting bag" button


class Bankmain:
    """
    The standard bank interface.

    Java source: ``InterfaceID.Bankmain``  (group 12 = 0x000c)
    Exposed by GameBridge when ``exposeWidgets`` is enabled.
    """
    GROUP = 12

    # Items
    ITEMS = (12, 0x0c)  # 0x000c_000c — bank items container (dynamic children = bank slots)

    # Deposit buttons (shown in the bank interface itself)
    DEPOSITINV   = (12, 0x30)  # 0x000c_0030 — "Deposit inventory" button
    DEPOSITWORN  = (12, 0x31)  # 0x000c_0031 — "Deposit worn items" button

    # Toggle buttons (the small icons next to quantity selectors)
    DEPOSITINV_TOGGLE   = (12, 0x7f)  # 0x000c_007f — inventory deposit toggle
    DEPOSITWORN_TOGGLE  = (12, 0x80)  # 0x000c_0080 — worn deposit toggle


class Inventory:
    """
    The inventory panel.

    Java source: ``InterfaceID.Inventory``  (group 149 = 0x0095)
    Exposed by GameBridge when ``exposeWidgets`` is enabled.
    Dynamic children of ``ITEMS`` are the 28 individual item slots.
    """
    GROUP = 149

    ITEMS = (149, 0x00)  # 0x0095_0000 — inventory container (dynamic children = item slots)


class Smithing:
    """
    The smithing production dialog ("What would you like to make?"), shown when clicking
    an Anvil.

    Java source: ``InterfaceID.Smithing``  (group 312 = 0x0138)
    Exposed by GameBridge via ``exposeInterfaces`` (default on).

    Item slots are searched by ``itemId`` rather than a fixed ``childId`` because the
    anvil shows every item smithable from the current metal, and the slot index depends
    on which tab/row the player has scrolled to.
    """
    GROUP = 312


class Wornitems:
    """
    The worn-equipment (equipment) panel.

    Java source: ``InterfaceID.Wornitems``  (group 387 = 0x0183)
    Exposed by GameBridge when ``exposeWidgets`` is enabled.

    Slot numbering matches the RS equipment slot indices (not consecutive):
    0=head 1=cape 2=neck 3=weapon 4=body 5=shield 7=legs 9=hands 10=feet 12=ring 13=ammo
    """
    GROUP = 387

    SLOT0  = (387, 0x0f)  # 0x0183_000f — head
    SLOT1  = (387, 0x10)  # 0x0183_0010 — cape
    SLOT2  = (387, 0x11)  # 0x0183_0011 — neck
    SLOT3  = (387, 0x12)  # 0x0183_0012 — weapon / left hand
    SLOT4  = (387, 0x13)  # 0x0183_0013 — body / torso
    SLOT5  = (387, 0x14)  # 0x0183_0014 — shield / off-hand
    SLOT7  = (387, 0x15)  # 0x0183_0015 — legs
    SLOT9  = (387, 0x16)  # 0x0183_0016 — hands / gloves
    SLOT10 = (387, 0x17)  # 0x0183_0017 — feet / boots
    SLOT12 = (387, 0x18)  # 0x0183_0018 — ring
    SLOT13 = (387, 0x19)  # 0x0183_0019 — ammo
