<script lang="ts">
  import { onMount } from 'svelte';
  import InventoryView from '$components/InventoryView.svelte';
  import SectionCard from '$components/SectionCard.svelte';
  import SkillList from '$components/SkillList.svelte';
  import StatPill from '$components/StatPill.svelte';
  import TagList from '$components/TagList.svelte';
  import { applyHeroUpgrade, bootstrapWebApp } from '$lib/api';
  import { applyTelegramTheme, getTelegramWebApp } from '$lib/telegram';
  import type {
    CharacterSheet,
    HeroUpgradeDelta,
    HeroUpgradePreview,
    InventoryMoveResponse,
    SavedCharacter,
    WebAppBootstrap,
    WebAppTarget,
    WebAppView
  } from '$lib/types';

  let bootstrap: WebAppBootstrap | null = null;
  let activeView: WebAppView = 'character';
  let telegramInitData = '';
  let error = '';
  let loading = true;
  let chooserPending = false;
  let upgradePending = '';

  function minorStatEntries(sheet: CharacterSheet): string[] {
    return Object.entries(sheet.minor_stats)
      .filter(([, value]) => value !== 0)
      .map(([key, value]) => `${formatStatLabel(key)} ${value > 0 ? '+' : ''}${Math.round(value * 100)}%`);
  }

  function passiveEntries(sheet: CharacterSheet): string[] {
    return sheet.passives.map(
      (passive) => `${passive.name} | ${passive.triggers.map((trigger) => trigger.replaceAll('_', ' ')).join(', ')}`
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
      const suffix = details.length > 0 ? ` | ${details.join(' | ')}` : '';
      return `${effect.name}${stacks} | ${effect.remaining_duration}t | ${tag}${suffix}`;
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

  function handleInventoryStateUpdate(payload: InventoryMoveResponse): void {
    if (!bootstrap) return;
    bootstrap = {
      ...bootstrap,
      sheet: payload.sheet,
      inventory: payload.inventory
    };
  }

  function savedCharacterName(character: SavedCharacter): string {
    return character.character_name || `#${character.character_id}`;
  }

  function deltaEntries(delta: HeroUpgradeDelta): string[] {
    const entries: string[] = [];
    if (delta.levels > 0) entries.push(`${delta.levels} level${delta.levels === 1 ? '' : 's'}`);
    entries.push(...delta.skills.map((skill) => `skill ${skill}`));
    entries.push(...delta.passive_skills.map((passive) => `passive ${passive}`));
    entries.push(...delta.items.map((item) => `${item.count} item ${item.blueprint_id}`));
    entries.push(...delta.flags.map((flag) => `flag ${flag.flag_name}`));
    entries.push(
      ...delta.modifiers.map((modifier) =>
        `${modifier.stacks} modifier ${modifier.modifier_id}`
      )
    );
    return entries;
  }

  async function applyUpgrade(upgrade: HeroUpgradePreview): Promise<void> {
    if (!bootstrap?.target) return;
    upgradePending = upgrade.hero_class_id;
    error = '';
    try {
      bootstrap = await applyHeroUpgrade(
        telegramInitData,
        bootstrap.target,
        upgrade.hero_class_id
      );
      activeView = bootstrap.initial_view;
    } catch (err) {
      error = err instanceof Error ? err.message : 'Failed to apply the selected upgrade.';
    } finally {
      upgradePending = '';
    }
  }

  async function loadTarget(target: WebAppTarget): Promise<void> {
    chooserPending = true;
    error = '';
    try {
      const response = await fetch('/api/webapp/bootstrap', {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json'
        },
        body: JSON.stringify({
          init_data: telegramInitData,
          target
        })
      });
      const payload = await response.json().catch(() => null);
      if (!response.ok) {
        const detail =
          payload && typeof payload.detail === 'string'
            ? payload.detail
            : 'Failed to load the selected character.';
        throw new Error(detail);
      }
      bootstrap = payload as WebAppBootstrap;
      activeView = bootstrap.initial_view;
    } catch (err) {
      error = err instanceof Error ? err.message : 'Failed to load the selected character.';
    } finally {
      chooserPending = false;
    }
  }

  function chooseSavedCharacter(character: SavedCharacter): void {
    void loadTarget({
      kind: 'saved',
      character_id: character.character_id
    });
  }

  onMount(async () => {
    const tg = getTelegramWebApp();
    if (!tg) {
      error = 'Open this page inside Telegram to load your character.';
      loading = false;
      return;
    }

    telegramInitData = tg.initData;
    applyTelegramTheme(tg);
    tg.ready();
    tg.expand();

    try {
      bootstrap = await bootstrapWebApp(tg.initData);
      activeView = bootstrap.initial_view;
    } catch (err) {
      error = err instanceof Error ? err.message : 'Failed to load the Mini App.';
    } finally {
      loading = false;
    }
  });
</script>

<svelte:head>
  <title>Infinite Loop Mini App</title>
  <meta
    name="description"
    content="Telegram Mini App character sheet and inventory for Infinite Loop."
  />
</svelte:head>

{#if loading}
  <main class="shell">
    <section class="hero loading-card">
      <p class="eyebrow">Infinite Loop</p>
      <h1>Opening your Mini App...</h1>
      <p>Syncing Telegram identity and loading your current run state.</p>
    </section>
  </main>
{:else if error}
  <main class="shell">
    <section class="hero error-card">
      <p class="eyebrow">Mini App Error</p>
      <h1>We could not open your game view.</h1>
      <p>{error}</p>
    </section>
  </main>
{:else if bootstrap?.mode === 'chooser'}
  <main class="shell">
    <section class="hero">
      <div>
        <p class="eyebrow">Character Browser</p>
        <h1>Choose Character</h1>
        <p class="subtitle">Pick one saved character to inspect.</p>
      </div>
    </section>

    <section class="chooser-grid">
      {#if bootstrap.characters.length === 0}
        <SectionCard title="No Saved Characters" eyebrow="Archive">
          <p class="empty-copy">No saved characters are available for this Telegram account.</p>
        </SectionCard>
      {:else}
        {#each bootstrap.characters as character}
          <button
            type="button"
            class="chooser-card"
            disabled={chooserPending}
            on:click={() => chooseSavedCharacter(character)}
          >
            <span>{character.class_id}</span>
            <strong>{savedCharacterName(character)}</strong>
            <small>Level {character.level}{character.xp > 0 ? ` | ${character.xp} XP` : ''}</small>
          </button>
        {/each}
      {/if}
    </section>
  </main>
{:else if bootstrap?.sheet && bootstrap.inventory && bootstrap.target}
  {@const sheet = bootstrap.sheet}
  <main class="shell">
    <nav class="view-tabs">
      <button class:active={activeView === 'character'} on:click={() => (activeView = 'character')}>
        Character
      </button>
      <button class:active={activeView === 'inventory'} on:click={() => (activeView = 'inventory')}>
        Inventory
      </button>
    </nav>

    <section class="hero">
      <div>
        <p class="eyebrow">{sheet.in_combat ? 'Combat Snapshot' : 'Run Snapshot'}</p>
        <h1>{sheet.display_name}</h1>
        <p class="subtitle">
          {sheet.class_name} | Level {sheet.level}{sheet.xp > 0 ? ` | ${sheet.xp} XP` : ''}
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

    {#if activeView === 'character'}
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

        {#if bootstrap.hero_upgrades.length > 0}
          <SectionCard title="Hero Upgrades" eyebrow="Ascension">
            <div class="upgrade-list">
              {#each bootstrap.hero_upgrades as upgrade}
                {@const gains = deltaEntries(upgrade.gains)}
                {@const losses = deltaEntries(upgrade.losses)}
                <article class="upgrade-row">
                  <div class="upgrade-heading">
                    <div>
                      <h2>{upgrade.name}</h2>
                      <p>{upgrade.description}</p>
                    </div>
                    <span class:ready={upgrade.eligible}>
                      {upgrade.eligible ? 'Ready' : 'Locked'}
                    </span>
                  </div>

                  <div class="check-list">
                    {#each upgrade.checks as check}
                      <span class:met={check.met}>{check.label}</span>
                    {/each}
                  </div>

                  <div class="delta-grid">
                    <div>
                      <strong>Gains</strong>
                      <TagList items={gains} emptyLabel="No explicit gains." />
                    </div>
                    <div>
                      <strong>Losses</strong>
                      <TagList items={losses} emptyLabel="No explicit losses." />
                    </div>
                  </div>

                  <button
                    type="button"
                    class="upgrade-button"
                    disabled={!upgrade.eligible || upgradePending !== ''}
                    on:click={() => applyUpgrade(upgrade)}
                  >
                    {upgradePending === upgrade.hero_class_id ? 'Applying...' : 'Upgrade'}
                  </button>
                </article>
              {/each}
            </div>
          </SectionCard>
        {/if}

      </section>
    {:else}
      <section class="inventory-section">
        <InventoryView
          inventory={bootstrap.inventory}
          initData={telegramInitData}
          target={bootstrap.target}
          onStateUpdate={handleInventoryStateUpdate}
        />
      </section>
    {/if}
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

  .view-tabs {
    display: inline-flex;
    gap: 0.5rem;
    margin-bottom: 1rem;
    padding: 0.35rem;
    border-radius: 999px;
    background: rgba(255, 255, 255, 0.05);
    border: 1px solid rgba(255, 255, 255, 0.1);
  }

  .view-tabs button {
    border: 0;
    padding: 0.7rem 1rem;
    border-radius: 999px;
    background: transparent;
    color: rgba(225, 234, 248, 0.82);
    font: inherit;
  }

  .view-tabs button.active {
    background: rgba(122, 193, 255, 0.16);
    color: #f5f8ff;
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

  .grid,
  .inventory-section,
  .chooser-grid {
    display: grid;
    gap: 1rem;
    margin-top: 1rem;
  }

  .chooser-card {
    display: grid;
    gap: 0.35rem;
    width: 100%;
    padding: 1rem;
    border-radius: 18px;
    border: 1px solid rgba(255, 255, 255, 0.1);
    background: rgba(255, 255, 255, 0.06);
    color: inherit;
    font: inherit;
    text-align: left;
    cursor: pointer;
  }

  .chooser-card:disabled {
    cursor: wait;
    opacity: 0.62;
  }

  .chooser-card span,
  .chooser-card small {
    color: rgba(212, 230, 255, 0.72);
    font-size: 0.78rem;
    text-transform: uppercase;
    letter-spacing: 0.08em;
  }

  .chooser-card strong {
    font-size: 1.1rem;
  }

  .empty-copy {
    margin: 0;
    color: rgba(225, 234, 248, 0.78);
  }

  .stat-grid {
    display: grid;
    grid-template-columns: repeat(2, minmax(0, 1fr));
    gap: 0.8rem;
  }

  .upgrade-list {
    display: grid;
    gap: 0.9rem;
  }

  .upgrade-row {
    display: grid;
    gap: 0.85rem;
    padding: 0.9rem 0;
    border-top: 1px solid rgba(255, 255, 255, 0.08);
  }

  .upgrade-row:first-child {
    padding-top: 0;
    border-top: 0;
  }

  .upgrade-heading {
    display: grid;
    gap: 0.6rem;
  }

  .upgrade-heading h2 {
    margin: 0;
    font-size: 1.1rem;
    letter-spacing: 0;
  }

  .upgrade-heading p {
    margin: 0.25rem 0 0;
    color: rgba(225, 234, 248, 0.76);
  }

  .upgrade-heading span {
    width: fit-content;
    padding: 0.28rem 0.55rem;
    border-radius: 999px;
    background: rgba(255, 255, 255, 0.08);
    color: rgba(225, 234, 248, 0.72);
    font-size: 0.72rem;
    text-transform: uppercase;
    letter-spacing: 0;
  }

  .upgrade-heading span.ready {
    background: rgba(77, 202, 142, 0.16);
    color: #bff7d8;
  }

  .check-list {
    display: flex;
    flex-wrap: wrap;
    gap: 0.45rem;
  }

  .check-list span {
    padding: 0.36rem 0.55rem;
    border-radius: 999px;
    background: rgba(255, 255, 255, 0.06);
    color: rgba(225, 234, 248, 0.66);
    font-size: 0.78rem;
  }

  .check-list span.met {
    background: rgba(77, 202, 142, 0.13);
    color: #c8f8de;
  }

  .delta-grid {
    display: grid;
    gap: 0.75rem;
  }

  .delta-grid strong {
    display: block;
    margin-bottom: 0.45rem;
  }

  .upgrade-button {
    justify-self: start;
    border: 0;
    border-radius: 999px;
    padding: 0.75rem 1rem;
    background: #8bd7ff;
    color: #07101d;
    font: inherit;
    font-weight: 700;
    cursor: pointer;
  }

  .upgrade-button:disabled {
    cursor: not-allowed;
    opacity: 0.55;
  }

  @media (min-width: 760px) {
    .hero {
      grid-template-columns: 1.7fr 1fr;
      align-items: end;
    }

    .grid {
      grid-template-columns: repeat(2, minmax(0, 1fr));
    }

    .chooser-grid {
      grid-template-columns: repeat(3, minmax(0, 1fr));
    }

    .stat-grid {
      grid-template-columns: repeat(3, minmax(0, 1fr));
    }

    .upgrade-heading {
      grid-template-columns: 1fr auto;
      align-items: start;
    }

    .delta-grid {
      grid-template-columns: repeat(2, minmax(0, 1fr));
    }
  }
</style>
