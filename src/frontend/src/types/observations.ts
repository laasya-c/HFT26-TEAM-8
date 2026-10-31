/**
 * WILDSCOPE Observations / Encounters Types
 * Strictly defines supported fields; no arbitrary index signatures
 */

export interface ApiMeta {
  dataset_revision?: string;
  total?: number;
  limit?: number;
  offset?: number;
}

export interface ApiEnvelope<T> {
  data: T;
  meta?: ApiMeta;
}

export interface Coordinates {
  latitude: number;
  longitude: number;
}

export interface Observation {
  // Confirmed contract identifier
  id: string | number;

  // Unconfirmed fields pending backend schema confirmation
  species?: string;
  camera_id?: string;
  status?: string;
  image_id?: string | number;

  // Optional attributes
  confidence?: number;
  location_name?: string;
  coordinates?: Coordinates;
  notes?: string;
}

export type EncounterDetail = Observation;

export interface PaginationParams {
  limit: number;
  offset: number;
}

export type ModuleState =
  | 'loading'
  | 'unavailable'
  | 'error'
  | 'empty'
  | 'success';
