import React from 'react';
import { BackendStatus, SectionMeta } from '../../types';
import { API_BASE_URL } from '../../api/client';
import './Header.css';

interface HeaderProps {
  currentSection: SectionMeta;
  backendStatus: BackendStatus;
  isCheckingStatus: boolean;
  onRefreshStatus: () => void;
}

export const Header: React.FC<HeaderProps> = ({
  currentSection,
  backendStatus,
  isCheckingStatus,
  onRefreshStatus,
}) => {
  return (
    <header className="ws-header">
      {/* Row 1: Full-width Page Title & Description */}
      <div className="ws-header-top-row">
        <h2 className="ws-header-title">{currentSection.label}</h2>
        <p className="ws-header-desc">{currentSection.description}</p>
      </div>

      {/* Row 2: Status & API Controls Toolbar */}
      <div className="ws-header-bottom-row">
        <div className="ws-header-controls">
          <div className="ws-api-badge" title={`Configured API prefix: ${API_BASE_URL}`}>
            <span className="ws-api-label">API Prefix:</span>
            <code className="ws-api-prefix">{API_BASE_URL}</code>
          </div>

          <div
            className={`ws-status-badge ${
              backendStatus.connected ? 'status-online' : 'status-offline'
            }`}
            role="status"
            aria-live="polite"
          >
            <span className="ws-status-dot" aria-hidden="true" />
            <span className="ws-status-text">
              {backendStatus.connected
                ? backendStatus.message
                : 'Backend not connected'}
            </span>
          </div>

          <button
            type="button"
            className="ws-refresh-btn"
            onClick={onRefreshStatus}
            disabled={isCheckingStatus}
            title="Check connection to backend /api/v1/health"
          >
            {isCheckingStatus ? 'Checking…' : 'Check API'}
          </button>
        </div>
      </div>
    </header>
  );
};
