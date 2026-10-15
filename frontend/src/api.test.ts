import { afterEach, expect, it, vi } from 'vitest';
import { getHealth } from './api';

afterEach(() => vi.unstubAllGlobals());
it('checks the backend contract', async () => {
  const health = { status: 'ok', service: 'spotify-consolidator', stage: 'foundation' };
  vi.stubGlobal('fetch', vi.fn().mockResolvedValue(new Response(JSON.stringify(health))));
  await expect(getHealth()).resolves.toEqual(health);
});
it('reports HTTP failures', async () => {
  vi.stubGlobal('fetch', vi.fn().mockResolvedValue(new Response('', { status: 503 })));
  await expect(getHealth()).rejects.toThrow('unavailable');
});
it('rejects a response from the wrong service', async () => {
  vi.stubGlobal('fetch', vi.fn().mockResolvedValue(new Response('{"status":"ok"}')));
  await expect(getHealth()).rejects.toThrow('unexpected response');
});
