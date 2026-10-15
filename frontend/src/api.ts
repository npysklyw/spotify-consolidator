export interface Health { status: 'ok'; service: 'spotify-consolidator'; stage: 'foundation' }

export async function getHealth(): Promise<Health> {
  const response = await fetch('/api/health');
  if (!response.ok) throw new Error('The backend is unavailable. Start it and try again.');
  const data: unknown = await response.json();
  if (typeof data !== 'object' || data === null || !('status' in data) || data.status !== 'ok'
    || !('service' in data) || data.service !== 'spotify-consolidator'
    || !('stage' in data) || data.stage !== 'foundation') {
    throw new Error('The backend returned an unexpected response.');
  }
  return { status: data.status, service: data.service, stage: data.stage };
}
