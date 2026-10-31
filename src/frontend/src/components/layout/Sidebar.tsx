import React from 'react';
import { SectionId, SectionMeta } from '../../types';
import './Sidebar.css';

interface SidebarProps {
  sections: SectionMeta[];
  activeSection: SectionId;
  onSelectSection: (id: SectionId) => void;
}

export const Sidebar: React.FC<SidebarProps> = ({
  sections,
  activeSection,
  onSelectSection,
}) => {
  return (
    <aside className="ws-sidebar" aria-label="Main Navigation">
      <div className="ws-sidebar-brand">
        <div className="ws-brand-icon" aria-hidden="true">
          🌿
        </div>
        <div className="ws-brand-text">
          <h1 className="ws-brand-title">WILDSCOPE</h1>
          <span className="ws-brand-subtitle">Wildlife Monitoring</span>
        </div>
      </div>

      <nav className="ws-sidebar-nav">
        <div className="ws-nav-heading">Platform Modules</div>
        <ul className="ws-nav-list">
          {sections.map((section) => {
            const isActive = activeSection === section.id;
            return (
              <li key={section.id}>
                <button
                  type="button"
                  className={`ws-nav-item ${isActive ? 'active' : ''}`}
                  onClick={() => onSelectSection(section.id)}
                  aria-current={isActive ? 'page' : undefined}
                >
                  <span className="ws-nav-indicator" aria-hidden="true" />
                  <span className="ws-nav-label">{section.label}</span>
                  {section.badge && (
                    <span className="ws-nav-badge">{section.badge}</span>
                  )}
                </button>
              </li>
            );
          })}
        </ul>
      </nav>

      <div className="ws-sidebar-footer">
        <div className="ws-team-info">
          <span className="ws-team-badge">Team 8 · ByteStrom</span>
          <span className="ws-branch-info">Branch: <code>laasya</code></span>
        </div>
      </div>
    </aside>
  );
};
