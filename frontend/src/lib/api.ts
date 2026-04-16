import type { CharacterBootstrap } from '$lib/types';

export async function bootstrapCharacter(initData: string): Promise<CharacterBootstrap> {
  const response = await fetch('/api/webapp/char/bootstrap', {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json'
    },
    body: JSON.stringify({
      init_data: initData
    })
  });

  if (!response.ok) {
    const payload = await response.json().catch(() => null);
    const detail =
      payload && typeof payload.detail === 'string'
        ? payload.detail
        : 'Failed to load your character sheet.';
    throw new Error(detail);
  }

  return (await response.json()) as CharacterBootstrap;
}
