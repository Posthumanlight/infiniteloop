<script lang="ts">
  import ItemCard from '$components/ItemCard.svelte';
  import type { EquipmentSlot, Item } from '$lib/types';

  let {
    slots,
    selectedInstanceId,
    canManageEquipment,
    isTargetSlot,
    onItemTap,
    onSlotTap
  }: {
    slots: EquipmentSlot[];
    selectedInstanceId: string | null;
    canManageEquipment: boolean;
    isTargetSlot: (
      slotType: 'weapon' | 'armor' | 'relic',
      slotIndex: number | null,
      acceptsItemType: string,
    ) => boolean;
    onItemTap: (
      item: Item,
      slotType: 'weapon' | 'armor' | 'relic',
      slotIndex: number | null,
    ) => void;
    onSlotTap: (
      slotType: 'weapon' | 'armor' | 'relic',
      slotIndex: number | null,
      acceptsItemType: string,
    ) => void | Promise<void>;
  } = $props();
</script>

<div class="board">
  {#each slots as slot}
    <section
      class:target={isTargetSlot(slot.slot_type, slot.slot_index, slot.accepts_item_type)}
      class:occupied={slot.item !== null}
      class="slot"
    >
      <header>
        <p>{slot.label}</p>
        <span>{slot.accepts_item_type}</span>
      </header>

      {#if slot.item}
        {@const equippedItem = slot.item}
        <button
          type="button"
          class:selected={selectedInstanceId === equippedItem.instance_id}
          class="slot-button"
          onclick={() => onItemTap(equippedItem, slot.slot_type, slot.slot_index)}
          disabled={!canManageEquipment}
        >
          <ItemCard item={equippedItem} />
        </button>
      {:else}
        <button
          type="button"
          class="placeholder"
          onclick={() => onSlotTap(slot.slot_type, slot.slot_index, slot.accepts_item_type)}
          disabled={!canManageEquipment}
        >
          Tap to equip {slot.accepts_item_type}.
        </button>
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

  .slot.target {
    border-color: rgba(122, 255, 179, 0.68);
    background: rgba(71, 181, 119, 0.14);
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

  .slot-button,
  .placeholder {
    border: 0;
    width: 100%;
    font: inherit;
    text-align: left;
    background: transparent;
    color: inherit;
    padding: 0;
  }

  .slot-button {
    border-radius: 18px;
  }

  .slot-button.selected {
    outline: 2px solid rgba(122, 193, 255, 0.72);
    outline-offset: 2px;
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

  .slot-button:disabled,
  .placeholder:disabled {
    opacity: 0.72;
  }

  .slot-button:not(:disabled),
  .placeholder:not(:disabled) {
    cursor: pointer;
  }

  @media (min-width: 760px) {
    .board {
      grid-template-columns: repeat(2, minmax(0, 1fr));
    }
  }
</style>
