import { AxiosError, AxiosHeaders } from 'axios';
import { describe, expect, it } from 'vitest';

import { API_URL, describeApiError } from '@/lib/api';

/**
 * `describeApiError` is the only thing standing between a reader and
 * "Request failed with status code 422". Every page routes its failures
 * through it, so its behaviour is worth pinning down.
 */

function axiosErrorWith(status: number, data: unknown): AxiosError {
  const error = new AxiosError('Request failed');
  error.response = {
    status,
    statusText: status === 404 ? 'Not Found' : '',
    data,
    headers: new AxiosHeaders(),
    config: { headers: new AxiosHeaders() },
  };
  return error;
}

describe('describeApiError', () => {
  it('names the address when the backend cannot be reached', () => {
    // No `response` at all is what axios gives for a refused connection.
    // "Network Error" tells the reader nothing they can act on; the address
    // tells them what to go and start.
    const error = new AxiosError('Network Error');

    expect(describeApiError(error)).toBe(
      `Could not reach the backend at ${API_URL}. Is it running?`,
    );
  });

  it("passes FastAPI's own detail through untouched", () => {
    const error = axiosErrorWith(404, { detail: "No application 'x'." });

    expect(describeApiError(error)).toBe("No application 'x'.");
  });

  it('digs the message out of a Pydantic validation array', () => {
    // 422 bodies arrive as a list of objects, not a string. Rendering the
    // array directly would put "[object Object]" on the screen.
    const error = axiosErrorWith(422, {
      detail: [{ loc: ['body', 'job_description'], msg: 'Field required' }],
    });

    expect(describeApiError(error)).toBe('Field required');
  });

  it('falls back to the status line when there is no detail', () => {
    const error = axiosErrorWith(404, {});

    expect(describeApiError(error)).toBe('404 Not Found');
  });

  it('handles a plain Error', () => {
    expect(describeApiError(new Error('boom'))).toBe('boom');
  });

  it('never returns an empty string', () => {
    expect(describeApiError('a bare string')).toBe('Unknown error.');
  });
});
