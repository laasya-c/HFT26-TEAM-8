import React from 'react';
import { BackendStatus, SectionMeta } from '../../types';
import { API_BASE_URL } from '../../api/client';
import './OverviewSection.css';

interface OverviewSectionProps {
  sections: SectionMeta[];
  backendStatus: BackendStatus;
  onNavigate: (id: SectionMeta['id']) => void;
}

export const OverviewSection: React.FC<OverviewSectionProps> = ({
  sections,
  backendStatus,
  onNavigate,
}) => {
  return (
    <div className="ws-overview">
      {/* Welcome Banner */}
      <section className="ws-welcome-card">
        <div className="ws-welcome-content">
          <span className="ws-welcome-pill">System Shell v0.1.0</span>
          <h2 className="ws-welcome-title">WILDSCOPE Command Dashboard</h2>
          <p className="ws-welcome-text">
            Welcome to the frontend workspace for Team 8 (ByteStrom). This shell
            establishes the core interface architecture, clean layout, and API
            readiness for all six platform modules.
          </p>
        </div>
        <div className="ws-welcome-status">
          <div className="ws-status-callout">
            <span className="ws-callout-label">Live API Status</span>
            <span
              className={`ws-callout-value ${
                backendStatus.connected ? 'is-connected' : 'is-disconnected'
              }`}
            >
              {backendStatus.connected ? 'Connected' : 'Backend not connected'}
            </span>
            <span className="ws-callout-note">
              Configured prefix: <code>{API_BASE_URL}</code>
            </span>
          </div>
        </div>
      </section>

      {/* Metrics Shell (No fabricated data: displaying awaiting backend status) */}
      <section className="ws-section-block">
        <div className="ws-block-header">
          <h3 className="ws-block-title">Platform Telemetry Outlines</h3>
          <span className="ws-block-subtitle">
            Metric telemetry will populate dynamically once backend services are connected
          </span>
        </div>

        <div className="ws-metrics-grid">
          <div className="ws-metric-card">
            <span className="ws-metric-category">Observations</span>
            <div className="ws-metric-figure">—</div>
            <div className="ws-metric-label">Recorded Encounters</div>
            <div className="ws-metric-target">
              Awaiting <code>{API_BASE_URL}/observations/summary</code>
            </div>
          </div>

          <div className="ws-metric-card">
            <span className="ws-metric-category">Review Desk</span>
            <div className="ws-metric-figure">—</div>
            <div className="ws-metric-label">Pending Verification Queue</div>
            <div className="ws-metric-target">
              Awaiting <code>{API_BASE_URL}/review/queue</code>
            </div>
          </div>

          <div className="ws-metric-card">
            <span className="ws-metric-category">Monitoring</span>
            <div className="ws-metric-figure">—</div>
            <div className="ws-metric-label">Active Sensors &amp; Traps</div>
            <div className="ws-metric-target">
              Awaiting <code>{API_BASE_URL}/monitoring/telemetry</code>
            </div>
          </div>

          <div className="ws-metric-card">
            <span className="ws-metric-category">Spatial &amp; Risk</span>
            <div className="ws-metric-figure">—</div>
            <div className="ws-metric-label">Active Risk Indicators</div>
            <div className="ws-metric-target">
              Awaiting <code>{API_BASE_URL}/spatial/alerts</code>
            </div>
          </div>
        </div>
      </section>

      {/* Platform Modules Architecture Grid */}
      <section className="ws-section-block">
        <div className="ws-block-header">
          <h3 className="ws-block-title">Six Mandated Platform Modules</h3>
          <span className="ws-block-subtitle">
            Select any module to inspect its designated workspace and API route
          </span>
        </div>

        <div className="ws-modules-grid">
          {sections.map((sec) => (
            <div key={sec.id} className="ws-module-card">
              <div className="ws-module-header">
                <h4 className="ws-module-name">{sec.label}</h4>
                {sec.id === 'overview' && (
                  <span className="ws-module-badge current">Active Shell</span>
                )}
              </div>
              <p className="ws-module-desc">{sec.description}</p>
              <div className="ws-module-footer">
                <span className="ws-module-route">
                  Route: <code>{sec.plannedEndpoint}</code>
                </span>
                {sec.id !== 'overview' && (
                  <button
                    type="button"
                    className="ws-module-link"
                    onClick={() => onNavigate(sec.id)}
                  >
                    Open View &rarr;
                  </button>
                )}
              </div>
            </div>
          ))}
        </div>
      </section>
    </div>
  );
};
