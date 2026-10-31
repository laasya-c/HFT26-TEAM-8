import React, { useState, useEffect, useCallback } from 'react';
import { SectionId, SectionMeta, BackendStatus } from './types';
import { API_BASE_URL, checkBackendConnection } from './api/client';
import { Sidebar } from './components/layout/Sidebar';
import { Header } from './components/layout/Header';
import { OverviewSection } from './components/sections/OverviewSection';
import { SectionPlaceholder } from './components/sections/SectionPlaceholder';
import { ObservationsSection } from './components/observations/ObservationsSection';
import { ReviewDeskSection } from './components/review/ReviewDeskSection';
import './App.css';

const SECTIONS: SectionMeta[] = [
  {
    id: 'overview',
    label: 'Overview',
    description: 'Central command and high-level summary of wildlife activity.',
    plannedEndpoint: `${API_BASE_URL}/overview`,
  },
  {
    id: 'observations',
    label: 'Observations / Encounters',
    description: 'Field sightings, camera encounter logs, and species verification.',
    plannedEndpoint: `${API_BASE_URL}/observations`,
  },
  {
    id: 'review-desk',
    label: 'Review Desk',
    description: 'Verification queue for flagged sightings and detection quality checks.',
    plannedEndpoint: `${API_BASE_URL}/review`,
  },
  {
    id: 'monitoring',
    label: 'Monitoring',
    description: 'Sensor health, telemetry streams, and camera trap connectivity.',
    plannedEndpoint: `${API_BASE_URL}/monitoring`,
  },
  {
    id: 'spatial-risk',
    label: 'Spatial & Risk',
    description: 'Territory maps, perimeter boundaries, and risk alert zones.',
    plannedEndpoint: `${API_BASE_URL}/spatial`,
  },
  {
    id: 'research-assistant',
    label: 'Research Assistant',
    description: 'Analytical queries, biodiversity reports, and ecological insights.',
    plannedEndpoint: `${API_BASE_URL}/research`,
  },
];

export const App: React.FC = () => {
  const [activeSectionId, setActiveSectionId] = useState<SectionId>('overview');
  const [backendStatus, setBackendStatus] = useState<BackendStatus>({
    connected: false,
    message: 'Backend not connected',
    checkedAt: null,
  });
  const [isCheckingStatus, setIsCheckingStatus] = useState<boolean>(false);

  const verifyBackend = useCallback(async () => {
    setIsCheckingStatus(true);
    const result = await checkBackendConnection();
    setBackendStatus({
      connected: result.connected,
      message: result.message,
      checkedAt: new Date().toLocaleTimeString(),
    });
    setIsCheckingStatus(false);
  }, []);

  useEffect(() => {
    // Check initial connection status on load
    verifyBackend();
  }, [verifyBackend]);

  const currentSection =
    SECTIONS.find((sec) => sec.id === activeSectionId) || SECTIONS[0];

  return (
    <div className="ws-app-layout">
      <Sidebar
        sections={SECTIONS}
        activeSection={activeSectionId}
        onSelectSection={setActiveSectionId}
      />

      <div className="ws-main-stage">
        <Header
          currentSection={currentSection}
          backendStatus={backendStatus}
          isCheckingStatus={isCheckingStatus}
          onRefreshStatus={verifyBackend}
        />

        <main className="ws-content-viewport">
          {activeSectionId === 'overview' && (
            <OverviewSection
              sections={SECTIONS}
              backendStatus={backendStatus}
              onNavigate={setActiveSectionId}
            />
          )}
          {activeSectionId === 'observations' && <ObservationsSection />}
          {activeSectionId === 'review-desk' && <ReviewDeskSection />}
          {activeSectionId !== 'overview' &&
            activeSectionId !== 'observations' &&
            activeSectionId !== 'review-desk' && (
              <SectionPlaceholder
                section={currentSection}
                onBackToOverview={() => setActiveSectionId('overview')}
              />
            )}
        </main>
      </div>
    </div>
  );
};

export default App;
