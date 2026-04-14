<script lang="ts">
  let { label, value }: { label: string; value: string } = $props();
</script>

<div class="pill">
  <span>{label}</span>
  <strong>{value}</strong>
</div>

<style>
  .pill {
    display: grid;
    gap: 0.3rem;
    padding: 0.85rem 0.95rem;
    border-radius: 18px;
    background: rgba(255, 255, 255, 0.06);
    border: 1px solid rgba(255, 255, 255, 0.08);
  }

  .pill span {
    font-size: 0.72rem;
    text-transform: uppercase;
    letter-spacing: 0.12em;
    color: rgba(214, 229, 255, 0.66);
  }

  .pill strong {
    font-size: 1.05rem;
    font-weight: 700;
  }
</style>
