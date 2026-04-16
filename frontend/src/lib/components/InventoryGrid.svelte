<script lang="ts">
  import ItemCard from '$components/ItemCard.svelte';
  import type { Item } from '$lib/types';

  let {
    items,
    selectedInstanceId,
    inventoryTargetActive,
    canManageEquipment,
    onItemTap,
    onInventoryTap
  }: {
    items: Item[];
    selectedInstanceId: string | null;
    inventoryTargetActive: boolean;
    canManageEquipment: boolean;
    onItemTap: (item: Item) => void;
    onInventoryTap: () => void | Promise<void>;
  } = $props();
</script>

<section
  role="button"
  tabindex={canManageEquipment ? 0 : -1}
  aria-disabled={!canManageEquipment}
  class:target={inventoryTargetActive}
  class="grid-shell"
  onclick={() => onInventoryTap()}
  onkeydown={(event) => {
    if (event.key === 'Enter' || event.key === ' ') {
      event.preventDefault();
      onInventoryTap();
    }
  }}
>
  {#if items.length === 0}
    <p class="empty">
      {#if inventoryTargetActive}
        Tap here to unequip the selected item.
      {:else}
        No unequipped items right now.
      {/if}
    </p>
  {:else}
    <div class="grid">
      {#each items as item}
        <button
          type="button"
          class:selected={selectedInstanceId === item.instance_id}
          class="item-button"
          onclick={(event) => {
            event.stopPropagation();
            onItemTap(item);
          }}
          disabled={!canManageEquipment}
        >
          <ItemCard {item} />
        </button>
      {/each}
    </div>
  {/if}
</section>

<style>
  .grid-shell {
    min-height: 8rem;
    padding: 0.25rem;
    border-radius: 22px;
    border: 1px dashed rgba(185, 221, 255, 0.22);
    transition:
      border-color 120ms ease,
      background 120ms ease;
  }

  .grid-shell.target {
    border-color: rgba(122, 255, 179, 0.68);
    background: rgba(71, 181, 119, 0.14);
  }

  .grid {
    display: grid;
    gap: 0.85rem;
  }

  .item-button {
    border: 0;
    width: 100%;
    padding: 0;
    border-radius: 18px;
    background: transparent;
    font: inherit;
    text-align: left;
    color: inherit;
  }

  .item-button.selected {
    outline: 2px solid rgba(122, 193, 255, 0.72);
    outline-offset: 2px;
  }

  .item-button:disabled {
    opacity: 0.72;
  }

  .item-button:not(:disabled),
  .grid-shell.target {
    cursor: pointer;
  }

  .empty {
    margin: 0;
    padding: 1rem;
    color: rgba(223, 232, 247, 0.72);
  }

  @media (min-width: 760px) {
    .grid {
      grid-template-columns: repeat(2, minmax(0, 1fr));
    }
  }
</style>
