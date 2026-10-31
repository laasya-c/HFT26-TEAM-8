import React, { useState, useEffect, useCallback, useMemo } from 'react';
import {
  Observation,
  ApiMeta,
  PaginationParams,
  ModuleState,
} from '../../types/observations';
import { fetchObservations, API_BASE_URL } from '../../api/client';
import {
  ObservationsFilterBar,
  FilterValues,
} from './ObservationsFilterBar';
import { ObservationsList } from './ObservationsList';
import { ObservationDetailPanel } from './ObservationDetailPanel';
import './ObservationsSection.css';

const DEFAULT_LIMIT = 20;

export const ObservationsSection: React.FC = () => {
  const [state, setState] = useState<ModuleState>('loading');
  const [errorMessage, setErrorMessage] = useState<string>('');
  const [observations, setObservations] = useState<Observation[]>([]);
  const [meta, setMeta] = useState<ApiMeta | undefined>(undefined);
  const [pagination, setPagination] = useState<PaginationParams>({
    limit: DEFAULT_LIMIT,
    offset: 0,
  });

  const [selectedObservation, setSelectedObservation] =
    useState<Observation | null>(null);

  const [filters, setFilters] = useState<FilterValues>({
    speciesQuery: '',
    cameraQuery: '',
    statusFilter: '',
  });

  const loadObservations = useCallback(async (currentPagination: PaginationParams) => {
    setState('loading');
    setErrorMessage('');

    const controller = new AbortController();

    try {
      const envelope = await fetchObservations(currentPagination, controller.signal);
      const loadedData = envelope.data;

      setObservations(loadedData);
      setMeta(envelope.meta);

      if (loadedData.length === 0) {
        setState('empty');
      } else {
        setState('success');
        // Keep selected observation if still in list, else set to first item
        setSelectedObservation((prev) => {
          if (!prev) return loadedData[0];
          const exists = loadedData.find((item) => item.id === prev.id);
          return exists || loadedData[0];
        });
      }
    } catch (err) {
      if ((err as Error).name === 'AbortError') return;

      const message = (err as Error).message || 'Unknown network error';

      // Check whether this was a connection failure to backend
      if (
        message.includes('Failed to fetch') ||
        message.includes('NetworkError') ||
        message.includes('fetch failed')
      ) {
        setState('unavailable');
        setErrorMessage(
          `Unable to reach backend service at ${API_BASE_URL}/observations. Please verify the backend is running.`
        );
      } else {
        setState('error');
        setErrorMessage(message);
      }
    }
  }, []);

  useEffect(() => {
    loadObservations(pagination);
  }, [loadObservations, pagination]);

  const handlePageChange = (newOffset: number) => {
    setPagination((prev) => ({ ...prev, offset: newOffset }));
  };

  const handleResetFilters = () => {
    setFilters({
      speciesQuery: '',
      cameraQuery: '',
      statusFilter: '',
    });
  };

  // Safe client-side filtering on currently loaded records only
  const filteredObservations = useMemo(() => {
    return observations.filter((obs) => {
      if (filters.speciesQuery.trim() !== '') {
        const query = filters.speciesQuery.toLowerCase();
        const speciesVal = (obs.species || '').toLowerCase();
        const idVal = String(obs.id).toLowerCase();
        if (!speciesVal.includes(query) && !idVal.includes(query)) {
          return false;
        }
      }

      if (filters.cameraQuery.trim() !== '') {
        const camQuery = filters.cameraQuery.toLowerCase();
        const camVal = (obs.camera_id || '').toLowerCase();
        if (!camVal.includes(camQuery)) {
          return false;
        }
      }

      if (filters.statusFilter !== '') {
        const statusVal = (obs.status || '').toLowerCase();
        if (statusVal !== filters.statusFilter.toLowerCase()) {
          return false;
        }
      }

      return true;
    });
  }, [observations, filters]);

  return (
    <div className="ws-obs-section">
      {/* Top Section Header */}
      <div className="ws-obs-header">
        <div>
          <span className="ws-obs-badge">Field Telemetry</span>
          <h2 className="ws-obs-title">Observations &amp; Encounters</h2>
          <p className="ws-obs-desc">
            Raw wildlife encounters, camera trap detections, and species records via{' '}
            <code>{API_BASE_URL}/observations</code>.
          </p>
        </div>

        <div className="ws-obs-controls">
          <button
            type="button"
            className="ws-btn-refresh"
            onClick={() => loadObservations(pagination)}
            disabled={state === 'loading'}
          >
            {state === 'loading' ? 'Refreshing…' : '↻ Refresh Data'}
          </button>
        </div>
      </div>

      {/* State Rendering */}
      {state === 'loading' && (
        <div className="ws-state-card ws-state-loading" role="status">
          <div className="ws-spinner" aria-hidden="true" />
          <h3 className="ws-state-heading">Loading Observations…</h3>
          <p className="ws-state-msg">
            Querying <code>{API_BASE_URL}/observations?limit={pagination.limit}&amp;offset={pagination.offset}</code>
          </p>
        </div>
      )}

      {state === 'unavailable' && (
        <div className="ws-state-card ws-state-unavailable" role="alert">
          <div className="ws-state-icon">📡</div>
          <h3 className="ws-state-heading">Backend Service Unreachable</h3>
          <p className="ws-state-msg">{errorMessage}</p>
          <div className="ws-state-notice">
            <strong>Data Integrity Notice:</strong> No mock observations are generated. Live wildlife data will display as soon as your backend team connects the endpoint.
          </div>
          <button
            type="button"
            className="ws-btn-primary"
            onClick={() => loadObservations(pagination)}
          >
            Retry Connection
          </button>
        </div>
      )}

      {state === 'error' && (
        <div className="ws-state-card ws-state-error" role="alert">
          <div className="ws-state-icon">⚠️</div>
          <h3 className="ws-state-heading">API Error Response</h3>
          <p className="ws-state-msg">{errorMessage}</p>
          <button
            type="button"
            className="ws-btn-primary"
            onClick={() => loadObservations(pagination)}
          >
            Retry Request
          </button>
        </div>
      )}

      {state === 'empty' && (
        <div className="ws-state-card ws-state-empty">
          <div className="ws-state-icon">🔍</div>
          <h3 className="ws-state-heading">No Observations Returned</h3>
          <p className="ws-state-msg">
            The backend returned 0 observation records for this query.
            {meta?.dataset_revision && (
              <> Dataset Revision: <code>{meta.dataset_revision}</code></>
            )}
          </p>
          <button
            type="button"
            className="ws-btn-secondary"
            onClick={() => loadObservations(pagination)}
          >
            Check Again
          </button>
        </div>
      )}

      {state === 'success' && (
        <div className="ws-obs-content">
          <ObservationsFilterBar
            filters={filters}
            onFilterChange={setFilters}
            onResetFilters={handleResetFilters}
            filteredCount={filteredObservations.length}
            totalLoadedCount={observations.length}
          />

          <div
            className={`ws-obs-grid ${
              selectedObservation ? 'has-selection' : ''
            }`}
          >
            <div className="ws-obs-master">
              {filteredObservations.length > 0 ? (
                <ObservationsList
                  observations={filteredObservations}
                  selectedObservation={selectedObservation}
                  onSelectObservation={setSelectedObservation}
                  pagination={pagination}
                  meta={meta}
                  onPageChange={handlePageChange}
                />
              ) : (
                <div className="ws-filter-empty">
                  <h4>No matching observations in current batch</h4>
                  <p>Try adjusting your search criteria or reset filters.</p>
                  <button
                    type="button"
                    className="ws-btn-reset"
                    onClick={handleResetFilters}
                  >
                    Reset Filters
                  </button>
                </div>
              )}
            </div>

            {selectedObservation && (
              <div className="ws-obs-detail">
                <ObservationDetailPanel
                  observation={selectedObservation}
                  onClose={() => setSelectedObservation(null)}
                />
              </div>
            )}
          </div>
        </div>
      )}
    </div>
  );
};
