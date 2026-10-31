import React from 'react';
import './ObservationsFilterBar.css';

export interface FilterValues {
  speciesQuery: string;
  cameraQuery: string;
  statusFilter: string;
}

interface ObservationsFilterBarProps {
  filters: FilterValues;
  onFilterChange: (newFilters: FilterValues) => void;
  onResetFilters: () => void;
  filteredCount: number;
  totalLoadedCount: number;
}

export const ObservationsFilterBar: React.FC<ObservationsFilterBarProps> = ({
  filters,
  onFilterChange,
  onResetFilters,
  filteredCount,
  totalLoadedCount,
}) => {
  const hasActiveFilters =
    filters.speciesQuery.trim() !== '' ||
    filters.cameraQuery.trim() !== '' ||
    filters.statusFilter !== '';

  return (
    <div className="ws-filter-bar">
      <div className="ws-filter-header">
        <div className="ws-filter-notice">
          <span className="ws-notice-icon" aria-hidden="true">ℹ️</span>
          <span className="ws-notice-text">
            <strong>Client-Side Filter:</strong> Filtering currently loaded records only. Does not query entire remote database when pagination is active.
          </span>
        </div>
        <div className="ws-filter-count">
          Showing <strong>{filteredCount}</strong> of <strong>{totalLoadedCount}</strong> loaded records
        </div>
      </div>

      <div className="ws-filter-inputs">
        <div className="ws-filter-field">
          <label htmlFor="filter-species" className="ws-field-label">
            Filter Species
          </label>
          <input
            id="filter-species"
            type="text"
            className="ws-input"
            placeholder="Search species name / ID…"
            value={filters.speciesQuery}
            onChange={(e) =>
              onFilterChange({ ...filters, speciesQuery: e.target.value })
            }
          />
        </div>

        <div className="ws-filter-field">
          <label htmlFor="filter-camera" className="ws-field-label">
            Filter Camera
          </label>
          <input
            id="filter-camera"
            type="text"
            className="ws-input"
            placeholder="e.g. CAM-01…"
            value={filters.cameraQuery}
            onChange={(e) =>
              onFilterChange({ ...filters, cameraQuery: e.target.value })
            }
          />
        </div>

        <div className="ws-filter-field">
          <label htmlFor="filter-status" className="ws-field-label">
            Status
          </label>
          <select
            id="filter-status"
            className="ws-select"
            value={filters.statusFilter}
            onChange={(e) =>
              onFilterChange({ ...filters, statusFilter: e.target.value })
            }
          >
            <option value="">All Statuses</option>
            <option value="verified">Verified</option>
            <option value="unreviewed">Unreviewed</option>
            <option value="flagged">Flagged</option>
          </select>
        </div>

        {hasActiveFilters && (
          <div className="ws-filter-action">
            <button
              type="button"
              className="ws-btn-reset"
              onClick={onResetFilters}
            >
              Reset Filters
            </button>
          </div>
        )}
      </div>
    </div>
  );
};
