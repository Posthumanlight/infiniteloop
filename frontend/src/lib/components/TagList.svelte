<script lang="ts">
  let {
    items,
    emptyLabel
  }: {
    items: string[];
    emptyLabel: string;
  } = $props();
</script>

{#if items.length === 0}
  <p class="empty">{emptyLabel}</p>
{:else}
  <div class="tags">
    {#each items as item}
      <span>{item}</span>
    {/each}
  </div>
{/if}

<style>
  .tags {
    display: flex;
    flex-wrap: wrap;
    gap: 0.65rem;
  }

  .tags span {
    padding: 0.55rem 0.8rem;
    border-radius: 999px;
    background: rgba(255, 255, 255, 0.06);
    border: 1px solid rgba(255, 255, 255, 0.08);
    color: rgba(239, 245, 255, 0.92);
    font-size: 0.9rem;
  }

  .empty {
    margin: 0;
    color: rgba(223, 232, 247, 0.72);
  }
</style>
