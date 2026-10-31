/**
 * WILDSCOPE API Client
 * Configurable base URL with agreed prefix: /api/v1
 */

import { ApiEnvelope, Observation, EncounterDetail, PaginationParams } from '../types/observations';

// Reads configurable base URL from Vite environment, or defaults to the agreed '/api/v1' prefix
export const API_BASE_URL: string =
  (import.meta.env.VITE_API_BASE_URL as string | undefined) || '/api/v1';

export interface HealthCheckResult {
  connected: boolean;
  message: string;
}

/**
 * Checks connection status against the configured backend /api/v1 health endpoint.
 * Never fabricates mock data; returns explicit connection status.
 */
export async function checkBackendConnection(): Promise<HealthCheckResult> {
  try {
    const controller = new AbortController();
    const timeoutId = setTimeout(() => controller.abort(), 4000);

    const response = await fetch(`${API_BASE_URL}/health`, {
      method: 'GET',
      headers: {
        'Accept': 'application/json',
      },
      signal: controller.signal,
    });

    clearTimeout(timeoutId);

    if (!response.ok) {
      return {
        connected: false,
        message: `Backend returned HTTP ${response.status}`,
      };
    }

    const data = await response.json();
    return {
      connected: true,
      message: typeof data?.status === 'string' ? data.status : 'Connected to /api/v1',
    };
  } catch (error) {
    // When the backend is not yet running or not reachable
    return {
      connected: false,
      message: 'Backend not connected',
    };
  }
}

/**
 * Fetches observation records from GET /api/v1/observations.
 * Only sends confirmed pagination query parameters (limit, offset) if provided.
 */
export async function fetchObservations(
  pagination?: PaginationParams,
  signal?: AbortSignal
): Promise<ApiEnvelope<Observation[]>> {
  const queryParams = new URLSearchParams();
  if (pagination) {
    queryParams.set('limit', pagination.limit.toString());
    queryParams.set('offset', pagination.offset.toString());
  }

  const queryString = queryParams.toString();
  const url = `${API_BASE_URL}/observations${queryString ? `?${queryString}` : ''}`;

  const response = await fetch(url, {
    method: 'GET',
    headers: {
      'Accept': 'application/json',
    },
    signal,
  });

  if (!response.ok) {
    throw new Error(`API responded with status HTTP ${response.status}`);
  }

  const envelope: ApiEnvelope<Observation[]> = await response.json();

  if (!envelope || !Array.isArray(envelope.data)) {
    throw new Error('Invalid response envelope: expected "data" array');
  }

  return envelope;
}

/**
 * Fetches a single encounter's details from GET /api/v1/encounters/{id}.
 */
export async function fetchEncounter(
  id: string | number,
  signal?: AbortSignal
): Promise<ApiEnvelope<EncounterDetail>> {
  const url = `${API_BASE_URL}/encounters/${encodeURIComponent(id)}`;

  const response = await fetch(url, {
    method: 'GET',
    headers: {
      'Accept': 'application/json',
    },
    signal,
  });

  if (!response.ok) {
    throw new Error(`Failed to fetch encounter ${id}: HTTP ${response.status}`);
  }

  const envelope: ApiEnvelope<EncounterDetail> = await response.json();

  if (!envelope || typeof envelope.data !== 'object' || envelope.data === null) {
    throw new Error('Invalid response envelope: expected "data" object');
  }

  return envelope;
}

/**
 * Returns the direct URL for an evidence image content stream.
 */
export function getImageContentUrl(imageId: string | number): string {
  return `${API_BASE_URL}/images/${encodeURIComponent(imageId)}/content`;
}
