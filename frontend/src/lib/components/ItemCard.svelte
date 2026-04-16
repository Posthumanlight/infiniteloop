<script lang="ts">
  import type { Item, ItemEffect } from '$lib/types';

  let { item, compact = false }: { item: Item; compact?: boolean } = $props();

  function formatLabel(value: string): string {
    return value
      .replaceAll('_', ' ')
      .replace(/\b\w/g, (char) => char.toUpperCase());
  }

  function describeEffect(effect: ItemEffect): string {
    if (effect.effect_type === 'modify_stat' && effect.stat && effect.value !== null) {
      const sign = effect.value > 0 ? '+' : '';
      const value = Number.isInteger(effect.value) ? effect.value : effect.value.toFixed(1);
      return `${sign}${value} ${formatLabel(effect.stat)}`;
    }
    if (effect.effect_type === 'grant_skill' && effect.skill_id) return `Grants ${formatLabel(effect.skill_id)}`;
    if (effect.effect_type === 'block_skill' && effect.skill_id) return `Blocks ${formatLabel(effect.skill_id)}`;
    if (effect.effect_type === 'grant_passive' && effect.passive_id) return `Grants ${formatLabel(effect.passive_id)}`;
    if (effect.effect_type === 'block_passive' && effect.passive_id) return `Blocks ${formatLabel(effect.passive_id)}`;
    return formatLabel(effect.effect_type);
  }

  function effectLinesFor(item: Item): string[] {
    return item.effects.map(describeEffect);
  }
</script>

<article class:compact class="item-card">
  <header>
    <div>
      <p class="type">{formatLabel(item.item_type)}</p>
      <h3>{item.name}</h3>
    </div>
    <span class="quality">Q{item.quality}</span>
  </header>

  {#if effectLinesFor(item).length > 0}
    <ul>
      {#each effectLinesFor(item) as effectLine}
        <li>{effectLine}</li>
      {/each}
    </ul>
  {:else}
    <p class="empty">No special effects.</p>
  {/if}
</article>

<style>
  .item-card {
    display: grid;
    gap: 0.65rem;
    padding: 0.95rem 1rem;
    border-radius: 18px;
    background: rgba(255, 255, 255, 0.06);
    border: 1px solid rgba(255, 255, 255, 0.09);
    box-shadow: 0 12px 28px rgba(0, 0, 0, 0.16);
  }

  .item-card.compact {
    width: min(18rem, calc(100vw - 2rem));
    padding: 0.8rem 0.9rem;
    box-shadow: 0 18px 34px rgba(0, 0, 0, 0.24);
  }

  header {
    display: flex;
    justify-content: space-between;
    gap: 0.8rem;
    align-items: start;
  }

  .type {
    margin: 0 0 0.25rem;
    color: rgba(212, 230, 255, 0.68);
    font-size: 0.72rem;
    text-transform: uppercase;
    letter-spacing: 0.12em;
  }

  h3 {
    margin: 0;
    font-size: 1rem;
  }

  .quality {
    flex-shrink: 0;
    display: inline-flex;
    align-items: center;
    justify-content: center;
    padding: 0.35rem 0.65rem;
    border-radius: 999px;
    background: rgba(122, 193, 255, 0.14);
    color: #b9ddff;
    font-size: 0.76rem;
    letter-spacing: 0.08em;
    text-transform: uppercase;
  }

  ul {
    margin: 0;
    padding-left: 1.1rem;
    display: grid;
    gap: 0.35rem;
    color: rgba(232, 239, 250, 0.88);
    font-size: 0.9rem;
  }

  .empty {
    margin: 0;
    color: rgba(223, 232, 247, 0.72);
    font-size: 0.88rem;
  }
</style>
