<script lang="ts">
  import EquipmentBoard from '$components/EquipmentBoard.svelte';
  import InventoryGrid from '$components/InventoryGrid.svelte';
  import SectionCard from '$components/SectionCard.svelte';
  import { moveInventoryItem } from '$lib/api';
  import type { InventoryMoveResponse, InventorySnapshot, Item, ItemEffect } from '$lib/types';

  type Selection =
    | { source: 'inventory'; item: Item }
    | {
        source: 'equipment';
        item: Item;
        slotType: 'weapon' | 'armor' | 'relic';
        slotIndex: number | null;
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

  let selected = $state<Selection | null>(null);
  let movePending = $state(false);
  let moveError = $state('');

  function clearSelection(): void {
    selected = null;
  }

  function canManage(): boolean {
    return inventory.can_manage_equipment && !movePending;
  }

  function isTargetSlot(slotType: 'weapon' | 'armor' | 'relic', slotIndex: number | null, acceptsItemType: string): boolean {
    if (!selected || !canManage()) {
      return false;
    }

    if (selected.item.item_type !== acceptsItemType) {
      return false;
    }

    if (selected.source === 'inventory') {
      return true;
    }

    if (selected.slotType !== slotType) {
      return true;
    }

    if (slotType !== 'relic') {
      return false;
    }

    return selected.slotIndex !== slotIndex;
  }

  function isInventoryTarget(): boolean {
    return selected?.source === 'equipment' && canManage();
  }

  function describeSelection(): string {
    if (!selected) {
      return 'Tap an inventory item, then tap an equipment slot. Tap an equipped item, then tap the inventory area to unequip.';
    }

    if (selected.source === 'inventory') {
      const slotLabel =
        selected.item.item_type === 'weapon'
          ? 'Weapon'
          : selected.item.item_type === 'armor'
            ? 'Armor'
            : 'a Relic slot';
      return `${selected.item.name} selected. Tap ${slotLabel} to equip it.`;
    }

    if (selected.slotType === 'relic') {
      return `${selected.item.name} selected from Relic ${selected.slotIndex !== null ? selected.slotIndex + 1 : '?'}. Tap the inventory area to unequip it or another relic slot to move it.`;
    }

    return `${selected.item.name} selected. Tap the inventory area to unequip it.`;
  }

  function formatLabel(value: string): string {
    return value
      .replaceAll('_', ' ')
      .replace(/\b\w/g, (char) => char.toUpperCase());
  }

  function isPercentStat(stat: string): boolean {
    return stat === 'crit_chance' || stat === 'crit_dmg' || stat.endsWith('_pct');
  }

  function formatEffectValue(stat: string, value: number): string {
    const sign = value > 0 ? '+' : '';
    if (isPercentStat(stat)) {
      return `${sign}${(value * 100).toFixed(1)}%`;
    }
    return `${sign}${Number.isInteger(value) ? value : value.toFixed(1)}`;
  }

  function formatPercentValue(value: number): string {
    const sign = value > 0 ? '+' : '';
    return `${sign}${(value * 100).toFixed(1)}%`;
  }

  function describeEffect(effect: ItemEffect): string {
    if (effect.effect_type === 'modify_stat' && effect.stat && effect.value !== null) {
      return `${formatEffectValue(effect.stat, effect.value)} ${formatLabel(effect.stat)}`;
    }
    if (effect.effect_type === 'modify_stat_percent' && effect.stat && effect.value !== null) {
      return `${formatPercentValue(effect.value)} ${formatLabel(effect.stat)}`;
    }
    if (effect.effect_type === 'grant_skill' && effect.skill_id) return `Grants ${formatLabel(effect.skill_id)}`;
    if (effect.effect_type === 'block_skill' && effect.skill_id) return `Blocks ${formatLabel(effect.skill_id)}`;
    if (effect.effect_type === 'grant_passive' && effect.passive_id) return `Grants ${formatLabel(effect.passive_id)}`;
    if (effect.effect_type === 'block_passive' && effect.passive_id) return `Blocks ${formatLabel(effect.passive_id)}`;
    return formatLabel(effect.effect_type);
  }

  function selectInventoryItem(item: Item): void {
    if (!canManage()) return;
    moveError = '';
    if (selected?.item.instance_id === item.instance_id) {
      clearSelection();
      return;
    }
    selected = { source: 'inventory', item };
  }

  function selectEquippedItem(
    item: Item,
    slotType: 'weapon' | 'armor' | 'relic',
    slotIndex: number | null,
  ): void {
    if (!canManage()) return;
    moveError = '';
    if (selected?.item.instance_id === item.instance_id) {
      clearSelection();
      return;
    }
    selected = {
      source: 'equipment',
      item,
      slotType,
      slotIndex,
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
      clearSelection();
    } catch (error) {
      moveError = error instanceof Error ? error.message : 'Failed to move the selected item.';
    } finally {
      movePending = false;
    }
  }

  async function handleSlotTap(
    slotType: 'weapon' | 'armor' | 'relic',
    slotIndex: number | null,
    acceptsItemType: string,
  ): Promise<void> {
    if (!selected || !canManage()) {
      return;
    }

    if (!isTargetSlot(slotType, slotIndex, acceptsItemType)) {
      return;
    }

    await submitMove({
      instance_id: selected.item.instance_id,
      destination_kind: 'equipment',
      slot_type: slotType,
      slot_index: slotIndex
    });
  }

  async function handleInventoryTap(): Promise<void> {
    if (!selected || selected.source !== 'equipment' || !canManage()) {
      return;
    }

    await submitMove({
      instance_id: selected.item.instance_id,
      destination_kind: 'inventory'
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

  <div class="hint">{describeSelection()}</div>

  <SectionCard title="Equipment" eyebrow="Tap To Equip">
    <EquipmentBoard
      slots={inventory.equipment_slots}
      selectedInstanceId={selected?.item.instance_id ?? null}
      canManageEquipment={canManage()}
      isTargetSlot={isTargetSlot}
      onItemTap={selectEquippedItem}
      onSlotTap={handleSlotTap}
    />
  </SectionCard>

  {#if inventory.item_sets.length > 0}
    <SectionCard title="Item Sets" eyebrow="Bonuses">
      <div class="set-list">
        {#each inventory.item_sets as itemSet}
          <article class="set-card">
            <header>
              <div>
                <p class="set-count">{itemSet.equipped_count} equipped</p>
                <h3>{itemSet.name}</h3>
              </div>
            </header>
            <ul>
              {#each itemSet.bonuses as bonus}
                <li class:active={bonus.active}>
                  <span class="threshold">{bonus.required_count} pieces</span>
                  <span class="state">{bonus.active ? 'Active' : 'Locked'}</span>
                  <span class="bonus-lines">
                    {bonus.effects.map(describeEffect).join(', ')}
                  </span>
                </li>
              {/each}
            </ul>
          </article>
        {/each}
      </div>
    </SectionCard>
  {/if}

  <SectionCard title="Inventory" eyebrow="Tap To Unequip">
    <InventoryGrid
      items={inventory.unequipped_items}
      selectedInstanceId={selected?.item.instance_id ?? null}
      inventoryTargetActive={isInventoryTarget()}
      canManageEquipment={canManage()}
      onItemTap={selectInventoryItem}
      onInventoryTap={handleInventoryTap}
    />
  </SectionCard>
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

  .hint {
    padding: 0.9rem 1rem;
    border-radius: 18px;
    background: rgba(122, 193, 255, 0.12);
    border: 1px solid rgba(122, 193, 255, 0.18);
    color: rgba(228, 239, 252, 0.92);
    font-size: 0.94rem;
  }

  .set-list {
    display: grid;
    gap: 0.8rem;
  }

  .set-card {
    display: grid;
    gap: 0.7rem;
    padding: 0.95rem 1rem;
    border-radius: 18px;
    background: rgba(255, 255, 255, 0.055);
    border: 1px solid rgba(255, 255, 255, 0.09);
  }

  .set-card header {
    display: flex;
    justify-content: space-between;
    gap: 1rem;
  }

  .set-count {
    margin: 0 0 0.25rem;
    color: rgba(255, 210, 74, 0.82);
    font-size: 0.72rem;
    letter-spacing: 0.11em;
    text-transform: uppercase;
  }

  .set-card h3 {
    margin: 0;
    font-size: 1rem;
  }

  .set-card ul {
    margin: 0;
    padding: 0;
    list-style: none;
    display: grid;
    gap: 0.45rem;
  }

  .set-card li {
    display: grid;
    grid-template-columns: auto auto 1fr;
    gap: 0.55rem;
    align-items: center;
    color: rgba(232, 239, 250, 0.7);
    font-size: 0.86rem;
  }

  .set-card li.active {
    color: rgba(242, 248, 255, 0.96);
  }

  .threshold,
  .state {
    padding: 0.18rem 0.45rem;
    border-radius: 999px;
    background: rgba(255, 255, 255, 0.07);
    font-size: 0.72rem;
    text-transform: uppercase;
    letter-spacing: 0.06em;
  }

  .set-card li.active .state {
    background: rgba(93, 214, 142, 0.16);
    color: #9ff0bd;
  }

  .bonus-lines {
    min-width: 0;
  }
</style>
