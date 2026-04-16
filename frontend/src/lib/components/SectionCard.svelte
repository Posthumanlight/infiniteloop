<script lang="ts">
  let { title, eyebrow = '' }: { title: string; eyebrow?: string } = $props();
</script>

<section class="card">
  <header class="card-header">
    {#if eyebrow}
      <p>{eyebrow}</p>
    {/if}
    <h2>{title}</h2>
  </header>
  <div class="card-content">
    <slot />
  </div>
</section>

<style>
  .card {
    position: relative;
    overflow: hidden;
    border: 1px solid rgba(255, 255, 255, 0.12);
    border-radius: 24px;
    background:
      linear-gradient(160deg, rgba(255, 255, 255, 0.08), rgba(255, 255, 255, 0.02)),
      rgba(9, 16, 28, 0.9);
    box-shadow:
      inset 0 1px 0 rgba(255, 255, 255, 0.08),
      0 20px 50px rgba(0, 0, 0, 0.22);
    backdrop-filter: blur(18px);
  }

  .card::after {
    content: '';
    position: absolute;
    inset: auto -30% -70% auto;
    width: 12rem;
    height: 12rem;
    border-radius: 999px;
    background: radial-gradient(circle, rgba(122, 193, 255, 0.18), transparent 68%);
    pointer-events: none;
  }

  .card-header {
    padding: 1.1rem 1.2rem 0.75rem;
  }

  .card-header p {
    margin: 0 0 0.3rem;
    font-size: 0.68rem;
    text-transform: uppercase;
    letter-spacing: 0.18em;
    color: rgba(214, 229, 255, 0.65);
  }

  .card-header h2 {
    margin: 0;
    font-size: 1.05rem;
    font-weight: 700;
  }

  .card-content {
    padding: 0 1.2rem 1.2rem;
  }
</style>
