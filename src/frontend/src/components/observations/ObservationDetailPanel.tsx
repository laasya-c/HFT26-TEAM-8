import React, { useState, useEffect } from 'react';
import { Observation, EncounterDetail } from '../../types/observations';
import { fetchEncounter, getImageContentUrl } from '../../api/client';
import './ObservationDetailPanel.css';

interface ObservationDetailPanelProps {
  observation: Observation;
  onClose: () => void;
}

export const ObservationDetailPanel: React.FC<ObservationDetailPanelProps> = ({
  observation,
  onClose,
}) => {
  const [detail, setDetail] = useState<EncounterDetail>(observation);
  const [isLoadingDetail, setIsLoadingDetail] = useState<boolean>(false);
  const [detailError, setDetailError] = useState<string | null>(null);
  const [imageFailed, setImageFailed] = useState<boolean>(false);

  useEffect(() => {
    // When the selected observation changes, fetch detailed encounter data
    let isMounted = true;
    const controller = new AbortController();

    async function loadDetail() {
      setIsLoadingDetail(true);
      setDetailError(null);
      setImageFailed(false);

      try {
        const envelope = await fetchEncounter(observation.id, controller.signal);
        if (isMounted) {
          setDetail(envelope.data);
        }
      } catch (err) {
        if (isMounted && (err as Error).name !== 'AbortError') {
          setDetailError((err as Error).message);
        }
      } finally {
        if (isMounted) {
          setIsLoadingDetail(false);
        }
      }
    }

    loadDetail();

    return () => {
      isMounted = false;
      controller.abort();
    };
  }, [observation.id]);

  const imageId = detail.image_id;

  return (
    <aside className="ws-detail-panel" aria-label="Observation Details">
      <div className="ws-detail-header">
        <div>
          <span className="ws-detail-eyebrow">Encounter Record</span>
          <h3 className="ws-detail-title">
            {detail.species || 'Unconfirmed Species'}
          </h3>
        </div>
        <button
          type="button"
          className="ws-detail-close"
          onClick={onClose}
          aria-label="Close details"
        >
          &times;
        </button>
      </div>

      <div className="ws-detail-body">
        {isLoadingDetail && (
          <div className="ws-detail-loading-banner">
            Fetching encounter details from <code>/api/v1/encounters/{String(observation.id)}</code>…
          </div>
        )}

        {detailError && (
          <div className="ws-detail-error-banner">
            Notice: Encounter detail request returned: <em>{detailError}</em>. Displaying base record.
          </div>
        )}

        {/* Evidence Image Viewer */}
        <section className="ws-detail-section">
          <h4 className="ws-section-heading">Evidence / Media Stream</h4>
          {imageId ? (
            <div className="ws-evidence-frame">
              {!imageFailed ? (
                <img
                  src={getImageContentUrl(imageId)}
                  alt={`Evidence for encounter ${String(detail.id)}`}
                  className="ws-evidence-img"
                  onError={() => setImageFailed(true)}
                />
              ) : (
                <div className="ws-evidence-fallback">
                  <span className="ws-fallback-icon">⚠️</span>
                  <span>
                    Unable to load image content from <code>{getImageContentUrl(imageId)}</code>.
                  </span>
                </div>
              )}
              <div className="ws-evidence-meta">
                <span>Evidence ID: <code>{String(imageId)}</code></span>
                <span>Endpoint: <code>/api/v1/images/{String(imageId)}/content</code></span>
              </div>
            </div>
          ) : (
            <div className="ws-evidence-empty">
              <span className="ws-empty-icon">📷</span>
              <span>No image evidence attached to this observation record</span>
            </div>
          )}
        </section>

        {/* Confirmed Contract Field */}
        <section className="ws-detail-section">
          <h4 className="ws-section-heading">Confirmed Contract Field</h4>
          <dl className="ws-attr-list">
            <div className="ws-attr-item">
              <dt>Encounter ID</dt>
              <dd><code>{String(detail.id)}</code></dd>
            </div>
          </dl>
        </section>

        {/* Unconfirmed Fields (Pending Contract Confirmation) */}
        <section className="ws-detail-section">
          <h4 className="ws-section-heading">Unconfirmed Fields (Pending Backend Confirmation)</h4>
          <dl className="ws-attr-list">
            <div className="ws-attr-item">
              <dt>Species Field</dt>
              <dd>
                {detail.species ? (
                  <strong>{detail.species}</strong>
                ) : (
                  <span className="ws-pending-tag">Pending backend confirmation</span>
                )}
              </dd>
            </div>

            <div className="ws-attr-item">
              <dt>Observation Time</dt>
              <dd>
                <span className="ws-pending-tag">
                  Unavailable (Field pending backend confirmation)
                </span>
              </dd>
            </div>

            <div className="ws-attr-item">
              <dt>Camera Identifier</dt>
              <dd>
                {detail.camera_id ? (
                  <code>{detail.camera_id}</code>
                ) : (
                  <span className="ws-pending-tag">Pending backend confirmation</span>
                )}
              </dd>
            </div>

            <div className="ws-attr-item">
              <dt>Verification Status</dt>
              <dd>
                {detail.status ? (
                  <span className="ws-status-value">{detail.status}</span>
                ) : (
                  <span className="ws-pending-tag">Pending backend confirmation</span>
                )}
              </dd>
            </div>
          </dl>
        </section>

        {/* Optional Supported Telemetry Attributes */}
        <section className="ws-detail-section">
          <h4 className="ws-section-heading">Optional Supported Attributes</h4>
          <dl className="ws-attr-list">
            <div className="ws-attr-item">
              <dt>AI Confidence Score</dt>
              <dd>
                {typeof detail.confidence === 'number' ? (
                  <span>{(detail.confidence * 100).toFixed(1)}%</span>
                ) : (
                  <span className="ws-pending-tag">Not provided</span>
                )}
              </dd>
            </div>

            <div className="ws-attr-item">
              <dt>Location Name</dt>
              <dd>
                {detail.location_name ? (
                  <span>{detail.location_name}</span>
                ) : (
                  <span className="ws-pending-tag">Not provided</span>
                )}
              </dd>
            </div>

            <div className="ws-attr-item">
              <dt>Spatial Coordinates</dt>
              <dd>
                {detail.coordinates &&
                typeof detail.coordinates.latitude === 'number' &&
                typeof detail.coordinates.longitude === 'number' ? (
                  <code>
                    {detail.coordinates.latitude.toFixed(4)},{' '}
                    {detail.coordinates.longitude.toFixed(4)}
                  </code>
                ) : (
                  <span className="ws-pending-tag">Not provided</span>
                )}
              </dd>
            </div>

            <div className="ws-attr-item">
              <dt>Field Notes</dt>
              <dd>
                {detail.notes ? (
                  <p className="ws-notes-text">{detail.notes}</p>
                ) : (
                  <span className="ws-pending-tag">No notes recorded</span>
                )}
              </dd>
            </div>
          </dl>
        </section>
      </div>
    </aside>
  );
};
