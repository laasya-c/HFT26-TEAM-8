/**
 * WILDSCOPE Review Desk Types
 * Working contract reference pending backend confirmation
 */

import { Coordinates } from './observations';

export type ReviewDecision = 'accept' | 'reject' | 'correction';

export interface ReviewItem {
  // Confirmed contract identifier
  id: string | number;

  // Unconfirmed fields pending backend confirmation
  species?: string;
  camera_id?: string;
  status?: string;
  image_id?: string | number;

  // Optional attributes
  confidence?: number;
  location_name?: string;
  coordinates?: Coordinates;
  notes?: string;

  // Optional record revision for conflict tracking (if supported by backend)
  detection_revision?: string;
}

export interface ReviewSubmissionPayload {
  detection_id: string | number;
  decision: ReviewDecision;
  corrected_taxon_id?: string;
  reason?: string;
  expected_revision?: string;
}

export type ReviewDeskState =
  | 'loading'
  | 'empty'
  | 'unavailable'
  | 'error'
  | 'conflict'
  | 'ready';
