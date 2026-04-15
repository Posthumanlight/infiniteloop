<script lang="ts">
  import { onMount } from 'svelte';
  import SectionCard from '$components/SectionCard.svelte';
  import SkillList from '$components/SkillList.svelte';
  import StatPill from '$components/StatPill.svelte';
  import TagList from '$components/TagList.svelte';
  import { bootstrapCharacter } from '$lib/api';
  import { applyTelegramTheme, getTelegramWebApp } from '$lib/telegram';
  import type { CharacterBootstrap, CharacterSheet } from '$lib/types';

  let bootstrap: CharacterBootstrap | null = null;
  let error = '';
  let loading = true;

  function minorStatEntries(sheet: CharacterSheet): string[] {
    return Object.entries(sheet.minor_stats)
      .filter(([, value]) => value !== 0)
      .map(([key, value]) => `${formatStatLabel(key)} ${value > 0 ? '+' : ''}${Math.round(value * 100)}%`);
  }

  function passiveEntries(sheet: CharacterSheet): string[] {
    return sheet.passives.map(
      (passive) => `${passive.name} · ${passive.triggers.map((trigger) => trigger.replaceAll('_', ' ')).join(', ')}`
    );
  }

  function modifierEntries(sheet: CharacterSheet): string[] {
    return sheet.modifiers.map((modifier) =>
      modifier.stack_count > 1 ? `${modifier.name} x${modifier.stack_count}` : modifier.name
    );
  }

  function effectEntries(sheet: CharacterSheet): string[] {
    return sheet.active_effects.map((effect) => {
      const tag = effect.is_buff ? 'buff' : 'debuff';
      const stacks = effect.stack_count > 1 ? ` x${effect.stack_count}` : '';
      const details: string[] = [];
      if (effect.granted_skills.length > 0) {
        details.push(`grants ${effect.granted_skills.join(', ')}`);
      }
      if (effect.blocked_skills.length > 0) {
        details.push(`blocks ${effect.blocked_skills.join(', ')}`);
      }
      const suffix = details.length > 0 ? ` · ${details.join(' · ')}` : '';
      return `${effect.name}${stacks} · ${effect.remaining_duration}t · ${tag}${suffix}`;
    });
  }

  function formatStatLabel(key: string): string {
    if (key === 'crit_chance') return 'Crit Chance';
    if (key === 'crit_dmg') return 'Crit Damage';
    return key
      .replaceAll('_', ' ')
      .replace(/\b\w/g, (char) => char.toUpperCase());
  }

  function statValue(sheet: CharacterSheet, key: string): string {
    const value = sheet.major_stats[key];
    if (value === undefined) return '-';
    if (key === 'crit_chance') return `${Math.round(value * 100)}%`;
    if (key === 'crit_dmg') return `x${value.toFixed(2)}`;
    return Number.isInteger(value) ? `${value}` : value.toFixed(1);
  }

  onMount(async () => {
    const tg = getTelegramWebApp();
    if (!tg) {
      error = 'Open this page inside Telegram to load your character.';
      loading = false;
      return;
    }

    applyTelegramTheme(tg);
    tg.ready();
    tg.expand();

    try {
      bootstrap = await bootstrapCharacter(tg.initData);
    } catch (err) {
      error = err instanceof Error ? err.message : 'Failed to load your character.';
    } finally {
      loading = false;
    }
  });
</script>

<svelte:head>
  <title>Character Sheet</title>
  <meta
    name="description"
    content="Telegram Mini App character sheet for Infinite Loop."
  />
</svelte:head>

{#if loading}
  <main class="shell">
    <section class="hero loading-card">
      <p class="eyebrow">Infinite Loop</p>
      <h1>Opening your character sheet...</h1>
      <p>Syncing Telegram identity and loading your current run state.</p>
    </section>
  </main>
{:else if error}
  <main class="shell">
    <section class="hero error-card">
      <p class="eyebrow">Mini App Error</p>
      <h1>We could not open your character sheet.</h1>
      <p>{error}</p>
    </section>
  </main>
{:else if bootstrap}
  {@const sheet = bootstrap.sheet}
  <main class="shell">
    <section class="hero">
      <div>
        <p class="eyebrow">{sheet.in_combat ? 'Combat Snapshot' : 'Run Snapshot'}</p>
        <h1>{sheet.display_name}</h1>
        <p class="subtitle">
          {sheet.class_name} · Level {sheet.level}{sheet.xp > 0 ? ` · ${sheet.xp} XP` : ''}
        </p>
      </div>

      <div class="resource-ribbon">
        <div>
          <span>HP</span>
          <strong>{sheet.current_hp}/{sheet.max_hp}</strong>
        </div>
        <div>
          <span>Energy</span>
          <strong>{sheet.current_energy}/{sheet.max_energy}</strong>
        </div>
      </div>
    </section>

    <section class="grid">
      <SectionCard title="Core Stats" eyebrow="Major">
        <div class="stat-grid">
          <StatPill label="Attack" value={statValue(sheet, 'attack')} />
          <StatPill label="Speed" value={statValue(sheet, 'speed')} />
          <StatPill label="Resistance" value={statValue(sheet, 'resistance')} />
          <StatPill label="Crit Chance" value={statValue(sheet, 'crit_chance')} />
          <StatPill label="Crit Damage" value={statValue(sheet, 'crit_dmg')} />
          <StatPill label="Mastery" value={statValue(sheet, 'mastery')} />
        </div>
      </SectionCard>

      <SectionCard title="Damage Profile" eyebrow="Minor">
        <TagList items={minorStatEntries(sheet)} emptyLabel="No minor stat bonuses are active." />
      </SectionCard>

      <SectionCard title="Skills" eyebrow="Loadout">
        <SkillList skills={sheet.skills} />
      </SectionCard>

      <SectionCard title="Passives" eyebrow="Always On">
        <TagList items={passiveEntries(sheet)} emptyLabel="No passive abilities learned yet." />
      </SectionCard>

      <SectionCard title="Modifiers" eyebrow="Build">
        <TagList items={modifierEntries(sheet)} emptyLabel="No modifiers are currently attached." />
      </SectionCard>

      <SectionCard title="Active Effects" eyebrow="Status">
        <TagList items={effectEntries(sheet)} emptyLabel="No active buffs or debuffs right now." />
      </SectionCard>

      <SectionCard title="Legacy Text View" eyebrow="Parity Check">
        <pre>{bootstrap.legacy_text}</pre>
      </SectionCard>
    </section>
  </main>
{/if}

<style>
  :global(html) {
    color-scheme: dark;
    font-family:
      'Segoe UI',
      'Trebuchet MS',
      sans-serif;
    background:
      radial-gradient(circle at top, rgba(90, 140, 198, 0.22), transparent 36%),
      linear-gradient(180deg, #142033 0%, #0a1220 55%, #070d16 100%);
    color: #f5f8ff;
  }

  :global(body) {
    margin: 0;
    min-height: 100vh;
    background:
      linear-gradient(135deg, rgba(104, 176, 255, 0.08), transparent 30%),
      radial-gradient(circle at 80% 20%, rgba(162, 210, 255, 0.1), transparent 20%);
  }

  .shell {
    max-width: 72rem;
    margin: 0 auto;
    padding: 1rem 1rem 2rem;
  }

  .hero {
    display: grid;
    gap: 1rem;
    padding: 1.3rem;
    border-radius: 28px;
    background:
      linear-gradient(145deg, rgba(125, 196, 255, 0.16), rgba(255, 255, 255, 0.03)),
      rgba(9, 16, 28, 0.9);
    border: 1px solid rgba(255, 255, 255, 0.12);
    box-shadow: 0 26px 70px rgba(0, 0, 0, 0.24);
  }

  .loading-card,
  .error-card {
    min-height: 12rem;
    align-content: center;
  }

  .eyebrow {
    margin: 0 0 0.45rem;
    font-size: 0.74rem;
    text-transform: uppercase;
    letter-spacing: 0.22em;
    color: rgba(212, 230, 255, 0.72);
  }

  h1 {
    margin: 0;
    font-size: clamp(2rem, 6vw, 3.8rem);
    line-height: 0.96;
    letter-spacing: -0.04em;
  }

  .subtitle {
    margin: 0.55rem 0 0;
    color: rgba(225, 234, 248, 0.82);
    font-size: 1rem;
  }

  .resource-ribbon {
    display: grid;
    grid-template-columns: repeat(2, minmax(0, 1fr));
    gap: 0.8rem;
  }

  .resource-ribbon div {
    padding: 0.95rem 1rem;
    border-radius: 20px;
    background: rgba(255, 255, 255, 0.06);
    border: 1px solid rgba(255, 255, 255, 0.08);
  }

  .resource-ribbon span {
    display: block;
    margin-bottom: 0.3rem;
    color: rgba(212, 230, 255, 0.68);
    font-size: 0.74rem;
    letter-spacing: 0.14em;
    text-transform: uppercase;
  }

  .resource-ribbon strong {
    font-size: 1.2rem;
  }

  .grid {
    display: grid;
    gap: 1rem;
    margin-top: 1rem;
  }

  .stat-grid {
    display: grid;
    grid-template-columns: repeat(2, minmax(0, 1fr));
    gap: 0.8rem;
  }

  pre {
    margin: 0;
    white-space: pre-wrap;
    word-break: break-word;
    font-family:
      'Consolas',
      'Courier New',
      monospace;
    color: rgba(236, 242, 252, 0.82);
    font-size: 0.85rem;
    line-height: 1.5;
  }

  @media (min-width: 760px) {
    .hero {
      grid-template-columns: 1.7fr 1fr;
      align-items: end;
    }

    .grid {
      grid-template-columns: repeat(2, minmax(0, 1fr));
    }

    .stat-grid {
      grid-template-columns: repeat(3, minmax(0, 1fr));
    }
  }
</style>
