import React from 'react';
import { Observation, ApiMeta, PaginationParams } from '../../types/observations';
import './ObservationsList.css';

interface ObservationsListProps {
  observations: Observation[];
  selectedObservation: Observation | null;
  onSelectObservation: (obs: Observation) => void;
  pagination: PaginationParams;
  meta?: ApiMeta;
  onPageChange: (newOffset: number) => void;
  isLoading?: boolean;
}

export const ObservationsList: React.FC<ObservationsListProps> = ({
  observations,
  selectedObservation,
  onSelectObservation,
  pagination,
  meta,
  onPageChange,
  isLoading = false,
}) => {
  const hasValidTotal = typeof meta?.total === 'number';
  const total = hasValidTotal ? (meta!.total as number) : null;
  const currentOffset = pagination.offset;
  const currentLimit = pagination.limit;

  const canGoPrevious = hasValidTotal && currentOffset > 0 && !isLoading;
  const canGoNext =
    hasValidTotal && currentOffset + currentLimit < total! && !isLoading;

  const handlePrevious = () => {
    if (canGoPrevious) {
      onPageChange(Math.max(0, currentOffset - currentLimit));
    }
  };

  const handleNext = () => {
    if (canGoNext) {
      onPageChange(currentOffset + currentLimit);
    }
  };

  return (
    <div className="ws-list-container">
      <div className="ws-table-wrapper">
        <table className="ws-table" aria-label="Observations Table">
          <thead>
            <tr>
              <th>ID (Confirmed)</th>
              <th>Species (Unconfirmed Field)</th>
              <th>Time (Unconfirmed Field)</th>
              <th>Camera ID (Unconfirmed Field)</th>
              <th>Status (Unconfirmed Field)</th>
              <th>Evidence</th>
            </tr>
          </thead>
          <tbody>
            {observations.map((obs) => {
              const isSelected = selectedObservation?.id === obs.id;
              const hasEvidence =
                obs.image_id !== undefined &&
                obs.image_id !== null &&
                obs.image_id !== '';

              return (
                <tr
                  key={String(obs.id)}
                  className={`ws-table-row ${isSelected ? 'is-selected' : ''}`}
                  onClick={() => onSelectObservation(obs)}
                  tabIndex={0}
                  role="button"
                  aria-pressed={isSelected}
                  onKeyDown={(e) => {
                    if (e.key === 'Enter' || e.key === ' ') {
                      e.preventDefault();
                      onSelectObservation(obs);
                    }
                  }}
                >
                  <td className="ws-cell-id">
                    <code>{String(obs.id)}</code>
                  </td>
                  <td className="ws-cell-species">
                    {obs.species ? (
                      <span className="ws-species-name">{obs.species}</span>
                    ) : (
                      <span className="ws-value-pending">Pending confirmation</span>
                    )}
                  </td>
                  <td className="ws-cell-time">
                    <span className="ws-value-pending">
                      Unavailable (Field pending confirmation)
                    </span>
                  </td>
                  <td className="ws-cell-camera">
                    {obs.camera_id ? (
                      <code>{obs.camera_id}</code>
                    ) : (
                      <span className="ws-value-pending">Pending confirmation</span>
                    )}
                  </td>
                  <td className="ws-cell-status">
                    {obs.status ? (
                      <span
                        className={`ws-status-tag status-${String(
                          obs.status
                        ).toLowerCase()}`}
                      >
                        {obs.status}
                      </span>
                    ) : (
                      <span className="ws-value-pending">Pending confirmation</span>
                    )}
                  </td>
                  <td className="ws-cell-evidence">
                    {hasEvidence ? (
                      <span className="ws-evidence-badge">
                        📷 Attached
                      </span>
                    ) : (
                      <span className="ws-evidence-none">None</span>
                    )}
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>

      {/* Pagination Container */}
      <div className="ws-pagination-bar">
        {hasValidTotal ? (
          <>
            <div className="ws-pagination-info">
              <span>
                Showing records <strong>{currentOffset + 1}</strong> –{' '}
                <strong>{Math.min(currentOffset + observations.length, total!)}</strong> of{' '}
                <strong>{total}</strong>
              </span>
              {meta?.dataset_revision && (
                <span className="ws-revision-tag">
                  Revision: <code>{meta.dataset_revision}</code>
                </span>
              )}
            </div>

            <div className="ws-pagination-actions">
              <button
                type="button"
                className="ws-page-btn"
                onClick={handlePrevious}
                disabled={!canGoPrevious}
                aria-label="Previous page"
              >
                &larr; Previous
              </button>
              <span className="ws-page-index">
                Page {Math.floor(currentOffset / currentLimit) + 1}
              </span>
              <button
                type="button"
                className="ws-page-btn"
                onClick={handleNext}
                disabled={!canGoNext}
                aria-label="Next page"
              >
                Next &rarr;
              </button>
            </div>
          </>
        ) : (
          <div className="ws-pagination-unavailable-box">
            <span className="ws-unavailable-tag">
              ℹ️ Pagination unavailable: <code>total</code> metadata was not returned by backend. Loaded {observations.length} records.
            </span>
            {meta?.dataset_revision && (
              <span className="ws-revision-tag">
                Revision: <code>{meta.dataset_revision}</code>
              </span>
            )}
          </div>
        )}
      </div>
    </div>
  );
};
