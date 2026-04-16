<script lang="ts">
  import ItemCard from '$components/ItemCard.svelte';
  import type { EquipmentSlot, Item } from '$lib/types';

  type DragSource =
    | { kind: 'inventory'; instanceId: string }
    | { kind: 'equipment'; instanceId: string; slotType: 'weapon' | 'armor' | 'relic'; slotIndex: number | null };

  let {
    slots,
    dragActive,
    hoveredDropId,
    canManageEquipment,
    isValidDrop,
    onItemPointerDown,
    onItemPointerMove,
    onItemPointerUp
  }: {
    slots: EquipmentSlot[];
    dragActive: boolean;
    hoveredDropId: string | null;
    canManageEquipment: boolean;
    isValidDrop: (dropId: string) => boolean;
    onItemPointerDown: (event: PointerEvent, source: DragSource, item: Item) => void;
    onItemPointerMove: (event: PointerEvent) => void;
    onItemPointerUp: (event: PointerEvent) => void;
  } = $props();

  function dropId(slot: EquipmentSlot): string {
    return slot.slot_type === 'relic' ? `relic:${slot.slot_index}` : slot.slot_type;
  }
</script>

<div class="board">
  {#each slots as slot}
    {@const slotDropId = dropId(slot)}
    <section
      class:drag-active={dragActive}
      class:hover-valid={hoveredDropId === slotDropId && isValidDrop(slotDropId)}
      class:hover-invalid={hoveredDropId === slotDropId && !isValidDrop(slotDropId)}
      class:occupied={slot.item !== null}
      class="slot"
      data-drop-id={slotDropId}
    >
      <header>
        <p>{slot.label}</p>
        <span>{slot.accepts_item_type}</span>
      </header>

      {#if slot.item}
        {@const equippedItem = slot.item}
        <div
          role="button"
          tabindex="-1"
          class:draggable={canManageEquipment}
          class="drag-anchor"
          onpointerdown={(event) =>
            onItemPointerDown(
              event,
              {
                kind: 'equipment',
                instanceId: equippedItem.instance_id,
                slotType: slot.slot_type,
                slotIndex: slot.slot_index
              },
              equippedItem
            )}
          onpointermove={onItemPointerMove}
          onpointerup={onItemPointerUp}
          onpointercancel={onItemPointerUp}
        >
          <ItemCard item={equippedItem} />
        </div>
      {:else}
        <div class="placeholder">Drop {slot.accepts_item_type} here.</div>
      {/if}
    </section>
  {/each}
</div>

<style>
  .board {
    display: grid;
    gap: 0.9rem;
  }

  .slot {
    display: grid;
    gap: 0.85rem;
    min-height: 8.25rem;
    padding: 0.9rem;
    border-radius: 22px;
    border: 1px dashed rgba(185, 221, 255, 0.22);
    background: rgba(255, 255, 255, 0.03);
    transition:
      border-color 120ms ease,
      background 120ms ease,
      transform 120ms ease;
  }

  .slot.drag-active {
    transform: translateY(-1px);
  }

  .slot.hover-valid {
    border-color: rgba(122, 255, 179, 0.68);
    background: rgba(71, 181, 119, 0.14);
  }

  .slot.hover-invalid {
    border-color: rgba(255, 122, 122, 0.72);
    background: rgba(168, 56, 56, 0.14);
  }

  .slot.occupied {
    border-style: solid;
  }

  header {
    display: flex;
    justify-content: space-between;
    gap: 0.75rem;
    align-items: baseline;
  }

  header p,
  header span {
    margin: 0;
  }

  header p {
    font-size: 0.92rem;
    font-weight: 700;
  }

  header span {
    color: rgba(212, 230, 255, 0.64);
    font-size: 0.72rem;
    text-transform: uppercase;
    letter-spacing: 0.12em;
  }

  .placeholder {
    align-content: center;
    min-height: 4.6rem;
    padding: 0.85rem;
    border-radius: 16px;
    color: rgba(223, 232, 247, 0.68);
    background: rgba(255, 255, 255, 0.03);
    font-size: 0.92rem;
    text-align: center;
  }

  .drag-anchor {
    touch-action: none;
  }

  .drag-anchor.draggable {
    cursor: grab;
  }

  @media (min-width: 760px) {
    .board {
      grid-template-columns: repeat(2, minmax(0, 1fr));
    }
  }
</style>
