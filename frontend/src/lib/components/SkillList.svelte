<script lang="ts">
  import type { Skill } from '$lib/types';

  let { skills }: { skills: Skill[] } = $props();

  function formatTarget(value: string): string {
    return value.replaceAll('_', ' ');
  }
</script>

{#if skills.length === 0}
  <p class="empty">No skills learned yet.</p>
{:else}
  <div class="stack">
    {#each skills as skill}
      <article class="row">
        <div>
          <h3>
            {skill.name}
            {#if skill.temporary}
              <span class="badge">Temporary</span>
            {/if}
          </h3>
          <p>
            {#if skill.hits.length === 0}
              Utility skill
            {:else}
              {#each skill.hits as hit, index}
                <span>{formatTarget(hit.target_type)}{hit.damage_type ? ` · ${hit.damage_type}` : ''}</span>{#if index < skill.hits.length - 1} / {/if}
              {/each}
            {/if}
          </p>
        </div>
        <strong>{skill.energy_cost > 0 ? `${skill.energy_cost} EN` : 'Free'}</strong>
      </article>
    {/each}
  </div>
{/if}

<style>
  .stack {
    display: grid;
    gap: 0.8rem;
  }

  .row {
    display: flex;
    gap: 1rem;
    justify-content: space-between;
    align-items: start;
    padding: 0.95rem 1rem;
    border-radius: 18px;
    background: rgba(255, 255, 255, 0.05);
    border: 1px solid rgba(255, 255, 255, 0.07);
  }

  .row h3 {
    margin: 0 0 0.25rem;
    font-size: 0.98rem;
  }

  .badge {
    display: inline-flex;
    margin-left: 0.5rem;
    padding: 0.15rem 0.45rem;
    border-radius: 999px;
    background: rgba(255, 201, 107, 0.16);
    color: #ffdca1;
    font-size: 0.72rem;
    letter-spacing: 0.05em;
    text-transform: uppercase;
    vertical-align: middle;
  }

  .row p {
    margin: 0;
    color: rgba(223, 232, 247, 0.78);
    font-size: 0.9rem;
    line-height: 1.4;
  }

  .row strong {
    flex-shrink: 0;
    padding: 0.4rem 0.7rem;
    border-radius: 999px;
    background: rgba(122, 193, 255, 0.12);
    color: #b9ddff;
    font-size: 0.78rem;
    letter-spacing: 0.08em;
  }

  .empty {
    margin: 0;
    color: rgba(223, 232, 247, 0.72);
  }
</style>
