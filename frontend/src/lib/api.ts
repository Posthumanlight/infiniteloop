import type {
  InventoryDissolveResponse,
  InventoryMoveResponse,
  WebAppTarget,
  WebAppBootstrap
} from '$lib/types';

async function parseJson<T>(response: Response, fallbackMessage: string): Promise<T> {
  if (!response.ok) {
    const payload = await response.json().catch(() => null);
    const detail =
      payload && typeof payload.detail === 'string'
        ? payload.detail
        : fallbackMessage;
    throw new Error(detail);
  }

  return (await response.json()) as T;
}

export async function bootstrapWebApp(initData: string): Promise<WebAppBootstrap> {
  const response = await fetch('/api/webapp/bootstrap', {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json'
    },
    body: JSON.stringify({
      init_data: initData
    })
  });

  return parseJson<WebAppBootstrap>(response, 'Failed to load the Mini App.');
}

export async function moveInventoryItem(
  initData: string,
  target: WebAppTarget,
  payload: {
    instance_id: string;
    destination_kind: 'inventory' | 'equipment';
    slot_type?: 'weapon' | 'armor' | 'relic';
    slot_index?: number | null;
  }
): Promise<InventoryMoveResponse> {
  const response = await fetch('/api/webapp/inventory/move', {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json'
    },
    body: JSON.stringify({
      init_data: initData,
      target,
      ...payload
    })
  });

  return parseJson<InventoryMoveResponse>(response, 'Failed to move the selected item.');
}

export async function dissolveInventoryItems(
  initData: string,
  target: WebAppTarget,
  instanceIds: string[],
): Promise<InventoryDissolveResponse> {
  const response = await fetch('/api/webapp/inventory/dissolve', {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json'
    },
    body: JSON.stringify({
      init_data: initData,
      target,
      instance_ids: instanceIds
    })
  });

  return parseJson<InventoryDissolveResponse>(response, 'Failed to dissolve selected items.');
}
