import React from 'react';
import { SectionMeta } from '../../types';
import './SectionPlaceholder.css';

interface SectionPlaceholderProps {
  section: SectionMeta;
  onBackToOverview: () => void;
}

export const SectionPlaceholder: React.FC<SectionPlaceholderProps> = ({
  section,
  onBackToOverview,
}) => {
  return (
    <div className="ws-placeholder-container">
      <div className="ws-placeholder-card">
        <div className="ws-placeholder-tag">Module Workspace</div>
        <h2 className="ws-placeholder-title">{section.label}</h2>
        <p className="ws-placeholder-desc">{section.description}</p>

        <div className="ws-placeholder-info-box">
          <div className="ws-info-row">
            <span className="ws-info-label">Designated Route</span>
            <code className="ws-info-value">{section.plannedEndpoint}</code>
          </div>
          <div className="ws-info-row">
            <span className="ws-info-label">Implementation Status</span>
            <span className="ws-info-value ws-status-pill">
              Shell ready &bull; Awaiting feature build
            </span>
          </div>
          <div className="ws-info-row">
            <span className="ws-info-label">Data Policy</span>
            <span className="ws-info-value">
              Awaiting live telemetry &bull; No fabricated data
            </span>
          </div>
        </div>

        <div className="ws-placeholder-actions">
          <button
            type="button"
            className="ws-btn-primary"
            onClick={onBackToOverview}
          >
            &larr; Back to Overview
          </button>
        </div>
      </div>
    </div>
  );
};
