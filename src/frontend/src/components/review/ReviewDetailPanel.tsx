import React from 'react';
import { ReviewItem } from '../../types/review';
import './ReviewDetailPanel.css';

interface ReviewDetailPanelProps {
  item: ReviewItem;
}

export const ReviewDetailPanel: React.FC<ReviewDetailPanelProps> = ({ item }) => {
  return (
    <div className="ws-review-detail-card">
      <div className="ws-detail-section">
        <h4 className="ws-section-heading">Confirmed Contract Field</h4>
        <div className="ws-attr-row">
          <span className="ws-attr-label">Detection / Encounter ID</span>
          <code className="ws-attr-id">{String(item.id)}</code>
        </div>
      </div>

      <div className="ws-detail-section">
        <h4 className="ws-section-heading">Unconfirmed Detection Attributes</h4>
        <dl className="ws-attr-grid">
          <div className="ws-attr-item">
            <dt>Species Classification</dt>
            <dd>
              {item.species ? (
                <strong>{item.species}</strong>
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
              {item.camera_id ? (
                <code>{item.camera_id}</code>
              ) : (
                <span className="ws-pending-tag">Pending backend confirmation</span>
              )}
            </dd>
          </div>

          <div className="ws-attr-item">
            <dt>Current Verification Status</dt>
            <dd>
              {item.status ? (
                <span className="ws-status-badge">{item.status}</span>
              ) : (
                <span className="ws-pending-tag">Pending confirmation</span>
              )}
            </dd>
          </div>
        </dl>
      </div>

      <div className="ws-detail-section">
        <h4 className="ws-section-heading">Optional Supported Attributes</h4>
        <dl className="ws-attr-grid">
          <div className="ws-attr-item">
            <dt>AI Confidence Score</dt>
            <dd>
              {typeof item.confidence === 'number' ? (
                <span>{(item.confidence * 100).toFixed(1)}%</span>
              ) : (
                <span className="ws-pending-tag">Not provided</span>
              )}
            </dd>
          </div>

          <div className="ws-attr-item">
            <dt>Coordinates</dt>
            <dd>
              {item.coordinates ? (
                <code>
                  {item.coordinates.latitude.toFixed(4)},{' '}
                  {item.coordinates.longitude.toFixed(4)}
                </code>
              ) : (
                <span className="ws-pending-tag">Not provided</span>
              )}
            </dd>
          </div>

          <div className="ws-attr-item full-width">
            <dt>Field Notes</dt>
            <dd>
              {item.notes ? (
                <p className="ws-notes-body">{item.notes}</p>
              ) : (
                <span className="ws-pending-tag">No notes recorded</span>
              )}
            </dd>
          </div>
        </dl>
      </div>
    </div>
  );
};
