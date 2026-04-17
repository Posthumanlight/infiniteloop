<script lang="ts">
  import type { Skill, SkillEffectDetail } from '$lib/types';

  let { skills }: { skills: Skill[] } = $props();

  function formatTarget(value: string): string {
    return value.replaceAll('_', ' ');
  }

  function formatChance(chance: number | null): string {
    if (chance === null) return '';
    return `${Math.round(chance * 100)}%`;
  }

  function effectLine(effect: SkillEffectDetail): string {
    const chance = formatChance(effect.chance);
    return chance ? `${effect.summary} ${chance}.` : effect.summary;
  }
</script>

{#if skills.length === 0}
  <p class="empty">No skills learned yet.</p>
{:else}
  <div class="stack">
    {#each skills as skill}
      <article class="row">
        <div class="row-head">
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
        </div>

        <div class="detail-block">
          <p class="summary-line">
            {#each skill.summary_parts as part}
              {#if part.kind === 'damage_crit'}
                <span class="crit-value">{part.value}</span>
              {:else if part.kind === 'damage_non_crit'}
                <span class="base-value">{part.value}</span>
              {:else}
                <span>{part.value}</span>
              {/if}
            {/each}
          </p>

          {#each skill.hit_details as hit, index}
            <section class="detail-section">
              <div class="section-label">Formula {skill.hit_details.length > 1 ? index + 1 : ''}</div>
              <code>{hit.formula}</code>

              {#if hit.on_hit_effects.length > 0}
                <div class="section-label">On-Hit Effects</div>
                <ul>
                  {#each hit.on_hit_effects as effect}
                    <li><strong>{effect.name}:</strong> {effectLine(effect)}</li>
                  {/each}
                </ul>
              {/if}
            </section>
          {/each}

          {#if skill.self_effects.length > 0}
            <section class="detail-section">
              <div class="section-label">Buff / Effects</div>
              <ul>
                {#each skill.self_effects as effect}
                  <li><strong>{effect.name}:</strong> {effect.summary}</li>
                {/each}
              </ul>
            </section>
          {/if}

          {#if skill.preview_note}
            <p class="preview-note">{skill.preview_note}</p>
          {/if}
        </div>
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
    display: grid;
    gap: 0.95rem;
    padding: 0.95rem 1rem;
    border-radius: 18px;
    background: rgba(255, 255, 255, 0.05);
    border: 1px solid rgba(255, 255, 255, 0.07);
  }

  .row-head {
    display: flex;
    gap: 1rem;
    justify-content: space-between;
    align-items: start;
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

  .detail-block {
    display: grid;
    gap: 0.75rem;
    padding-top: 0.1rem;
  }

  .summary-line,
  .preview-note {
    margin: 0;
    line-height: 1.5;
  }

  .summary-line {
    color: rgba(238, 244, 255, 0.94);
    font-size: 0.92rem;
  }

  .base-value {
    font-weight: 700;
    color: #eef3ff;
  }

  .crit-value {
    color: #ffd24a;
    font-weight: 700;
  }

  .detail-section {
    display: grid;
    gap: 0.35rem;
    padding: 0.75rem 0.85rem;
    border-radius: 14px;
    background: rgba(10, 18, 31, 0.48);
    border: 1px solid rgba(255, 255, 255, 0.06);
  }

  .section-label {
    color: rgba(185, 204, 232, 0.72);
    font-size: 0.72rem;
    letter-spacing: 0.12em;
    text-transform: uppercase;
  }

  code {
    white-space: pre-wrap;
    word-break: break-word;
    font-family:
      'Consolas',
      'Courier New',
      monospace;
    color: #d7e6ff;
    font-size: 0.82rem;
    line-height: 1.5;
  }

  ul {
    margin: 0;
    padding-left: 1.1rem;
    color: rgba(223, 232, 247, 0.84);
    display: grid;
    gap: 0.35rem;
  }

  li {
    line-height: 1.45;
  }

  .preview-note {
    color: rgba(194, 208, 230, 0.68);
    font-size: 0.82rem;
  }

  .empty {
    margin: 0;
    color: rgba(223, 232, 247, 0.72);
  }
</style>
