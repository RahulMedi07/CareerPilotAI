import MockAdapter from 'axios-mock-adapter';
import { afterEach, beforeEach, describe, expect, it } from 'vitest';

import { api, getHealth } from '@/lib/api';

/**
 * Regression test for a bug found while wiring the settings page.
 *
 * `main.py` answers 503 when a *required* dependency is down -- and the body of
 * that 503 is the full report naming which one. Axios rejects on 503, so the
 * page replaced its entire diagnostic with the words "503 Service Unavailable"
 * at exactly the moment the detail mattered.
 */
describe('getHealth', () => {
  let mock: MockAdapter;

  const unhealthyReport = {
    overall_status: 'unhealthy',
    app: 'CareerPilot AI',
    version: '0.1.0',
    duration_ms: 12.3,
    timestamp: '2026-09-01T06:00:00+00:00',
    services: [
      { service: 'rag', status: 'unhealthy', required: true, duration_ms: 4.1 },
      { service: 'database', status: 'healthy', required: true, duration_ms: 2.2 },
    ],
  };

  beforeEach(() => {
    mock = new MockAdapter(api);
  });

  afterEach(() => {
    mock.restore();
  });

  it('returns the report on 200', async () => {
    mock.onGet('/health/full').reply(200, { ...unhealthyReport, overall_status: 'healthy' });

    const report = await getHealth();

    expect(report.overall_status).toBe('healthy');
  });

  it('returns the report carried in a 503 body instead of throwing', async () => {
    mock.onGet('/health/full').reply(503, unhealthyReport);

    const report = await getHealth();

    expect(report.overall_status).toBe('unhealthy');
    expect(report.services.map((s) => s.service)).toEqual(['rag', 'database']);
  });

  it('names the service, not `name`', async () => {
    // The inline type on this function said `name` for months. Nothing called
    // it, so nothing disagreed.
    mock.onGet('/health/full').reply(200, unhealthyReport);

    const report = await getHealth();

    expect(report.services[0]).toHaveProperty('service');
    expect(report.services[0]).not.toHaveProperty('name');
  });

  it('still throws on a 503 that is not a health report', async () => {
    mock.onGet('/health/full').reply(503, { detail: 'upstream gone' });

    await expect(getHealth()).rejects.toThrow();
  });

  it('still throws on a 500', async () => {
    mock.onGet('/health/full').reply(500, unhealthyReport);

    await expect(getHealth()).rejects.toThrow();
  });
});
