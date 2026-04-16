<script lang="ts">
  import EquipmentBoard from '$components/EquipmentBoard.svelte';
  import InventoryGrid from '$components/InventoryGrid.svelte';
  import ItemCard from '$components/ItemCard.svelte';
  import SectionCard from '$components/SectionCard.svelte';
  import { moveInventoryItem } from '$lib/api';
  import type { InventoryMoveResponse, InventorySnapshot, Item } from '$lib/types';

  type DragSource =
    | { kind: 'inventory'; instanceId: string }
    | { kind: 'equipment'; instanceId: string; slotType: 'weapon' | 'armor' | 'relic'; slotIndex: number | null };

  type DragState = {
    active: boolean;
    source: DragSource | null;
    item: Item | null;
    pointerX: number;
    pointerY: number;
    overDropId: string | null;
  };

  let {
    inventory,
    initData,
    onStateUpdate
  }: {
    inventory: InventorySnapshot;
    initData: string;
    onStateUpdate: (payload: InventoryMoveResponse) => void;
  } = $props();

  let drag = $state<DragState>({
    active: false,
    source: null,
    item: null,
    pointerX: 0,
    pointerY: 0,
    overDropId: null
  });
  let movePending = $state(false);
  let moveError = $state('');

  function resetDrag(): void {
    drag = {
      active: false,
      source: null,
      item: null,
      pointerX: 0,
      pointerY: 0,
      overDropId: null
    };
  }

  function isValidDrop(dropId: string): boolean {
    if (!drag.item || movePending || !inventory.can_manage_equipment) {
      return false;
    }

    if (dropId === 'inventory') {
      return drag.item.equipped_slot !== null;
    }

    const [slotType, rawIndex] = dropId.split(':');
    if (slotType !== drag.item.item_type) {
      return false;
    }

    if (slotType === 'relic') {
      return rawIndex !== undefined;
    }

    return drag.item.item_type === 'weapon' || drag.item.item_type === 'armor';
  }

  function startDrag(event: PointerEvent, source: DragSource, item: Item): void {
    if (!inventory.can_manage_equipment || movePending) return;
    if (event.pointerType === 'mouse' && event.button !== 0) return;

    event.preventDefault();
    const target = event.currentTarget as HTMLElement | null;
    target?.setPointerCapture?.(event.pointerId);

    drag = {
      active: true,
      source,
      item,
      pointerX: event.clientX,
      pointerY: event.clientY,
      overDropId: null
    };
    moveError = '';
  }

  function updateDrag(event: PointerEvent): void {
    if (!drag.active) return;

    drag = {
      ...drag,
      pointerX: event.clientX,
      pointerY: event.clientY
    };

    const hovered = document
      .elementFromPoint(event.clientX, event.clientY)
      ?.closest<HTMLElement>('[data-drop-id]');

    drag = {
      ...drag,
      overDropId: hovered?.dataset.dropId ?? null
    };
  }

  async function submitMove(payload: {
    instance_id: string;
    destination_kind: 'inventory' | 'equipment';
    slot_type?: 'weapon' | 'armor' | 'relic';
    slot_index?: number | null;
  }): Promise<void> {
    movePending = true;
    moveError = '';
    try {
      const nextState = await moveInventoryItem(initData, payload);
      onStateUpdate(nextState);
    } catch (error) {
      moveError = error instanceof Error ? error.message : 'Failed to move the selected item.';
    } finally {
      movePending = false;
    }
  }

  async function endDrag(event: PointerEvent): Promise<void> {
    const target = event.currentTarget as HTMLElement | null;
    if (target?.hasPointerCapture?.(event.pointerId)) {
      target.releasePointerCapture(event.pointerId);
    }

    if (!drag.active || !drag.item) {
      resetDrag();
      return;
    }

    const drop = drag.overDropId;
    const item = drag.item;
    const valid = drop !== null && isValidDrop(drop);
    resetDrag();

    if (!drop || !valid) return;

    if (drop === 'inventory') {
      await submitMove({
        instance_id: item.instance_id,
        destination_kind: 'inventory'
      });
      return;
    }

    const [slotType, rawIndex] = drop.split(':');
    await submitMove({
      instance_id: item.instance_id,
      destination_kind: 'equipment',
      slot_type: slotType as 'weapon' | 'armor' | 'relic',
      slot_index: rawIndex ? Number(rawIndex) : null
    });
  }
</script>

<div class="stack">
  {#if inventory.equipment_lock_reason}
    <div class="notice">{inventory.equipment_lock_reason}</div>
  {/if}

  {#if moveError}
    <div class="error">{moveError}</div>
  {/if}

  <SectionCard title="Equipment" eyebrow="Drag To Equip">
    <EquipmentBoard
      slots={inventory.equipment_slots}
      dragActive={drag.active}
      hoveredDropId={drag.overDropId}
      canManageEquipment={inventory.can_manage_equipment && !movePending}
      {isValidDrop}
      onItemPointerDown={startDrag}
      onItemPointerMove={updateDrag}
      onItemPointerUp={endDrag}
    />
  </SectionCard>

  <SectionCard title="Inventory" eyebrow="Unequipped Items">
    <InventoryGrid
      items={inventory.unequipped_items}
      dragActive={drag.active}
      hoveredDropId={drag.overDropId}
      canManageEquipment={inventory.can_manage_equipment && !movePending}
      {isValidDrop}
      onItemPointerDown={startDrag}
      onItemPointerMove={updateDrag}
      onItemPointerUp={endDrag}
    />
  </SectionCard>

  {#if drag.active && drag.item}
    <div
      class="drag-ghost"
      style={`transform: translate(${drag.pointerX + 12}px, ${drag.pointerY + 12}px);`}
    >
      <ItemCard item={drag.item} compact />
    </div>
  {/if}
</div>

<style>
  .stack {
    position: relative;
    display: grid;
    gap: 1rem;
  }

  .notice,
  .error {
    padding: 0.9rem 1rem;
    border-radius: 18px;
    border: 1px solid rgba(255, 255, 255, 0.1);
    font-size: 0.94rem;
  }

  .notice {
    background: rgba(255, 207, 112, 0.12);
    color: #ffe3b1;
  }

  .error {
    background: rgba(194, 74, 74, 0.16);
    color: #ffd3d3;
  }

  .drag-ghost {
    position: fixed;
    left: 0;
    top: 0;
    z-index: 999;
    pointer-events: none;
    width: min(18rem, calc(100vw - 2rem));
    opacity: 0.95;
  }
</style>
