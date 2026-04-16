<script lang="ts">
  import ItemCard from '$components/ItemCard.svelte';
  import type { Item } from '$lib/types';

  type DragSource =
    | { kind: 'inventory'; instanceId: string }
    | { kind: 'equipment'; instanceId: string; slotType: 'weapon' | 'armor' | 'relic'; slotIndex: number | null };

  let {
    items,
    dragActive,
    hoveredDropId,
    canManageEquipment,
    isValidDrop,
    onItemPointerDown,
    onItemPointerMove,
    onItemPointerUp
  }: {
    items: Item[];
    dragActive: boolean;
    hoveredDropId: string | null;
    canManageEquipment: boolean;
    isValidDrop: (dropId: string) => boolean;
    onItemPointerDown: (event: PointerEvent, source: DragSource, item: Item) => void;
    onItemPointerMove: (event: PointerEvent) => void;
    onItemPointerUp: (event: PointerEvent) => void;
  } = $props();
</script>

<section
  class:drag-active={dragActive}
  class:hover-valid={hoveredDropId === 'inventory' && isValidDrop('inventory')}
  class:hover-invalid={hoveredDropId === 'inventory' && !isValidDrop('inventory')}
  class="grid-shell"
  data-drop-id="inventory"
>
  {#if items.length === 0}
    <p class="empty">No unequipped items right now.</p>
  {:else}
    <div class="grid">
      {#each items as item}
        <div
          role="button"
          tabindex="-1"
          class:draggable={canManageEquipment}
          class="drag-anchor"
          onpointerdown={(event) => onItemPointerDown(event, { kind: 'inventory', instanceId: item.instance_id }, item)}
          onpointermove={onItemPointerMove}
          onpointerup={onItemPointerUp}
          onpointercancel={onItemPointerUp}
        >
          <ItemCard {item} />
        </div>
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

  .grid-shell.drag-active {
    background: rgba(255, 255, 255, 0.02);
  }

  .grid-shell.hover-valid {
    border-color: rgba(122, 255, 179, 0.68);
    background: rgba(71, 181, 119, 0.14);
  }

  .grid-shell.hover-invalid {
    border-color: rgba(255, 122, 122, 0.72);
    background: rgba(168, 56, 56, 0.14);
  }

  .grid {
    display: grid;
    gap: 0.85rem;
  }

  .drag-anchor {
    touch-action: none;
  }

  .drag-anchor.draggable {
    cursor: grab;
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
