/**
 * WILDSCOPE Navigation & System Types
 */

export type SectionId =
  | 'overview'
  | 'observations'
  | 'review-desk'
  | 'monitoring'
  | 'spatial-risk'
  | 'research-assistant';

export interface SectionMeta {
  id: SectionId;
  label: string;
  badge?: string;
  description: string;
  plannedEndpoint: string;
}

export interface BackendStatus {
  connected: boolean;
  message: string;
  checkedAt: string | null;
}
