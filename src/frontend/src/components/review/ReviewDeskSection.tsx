import React, { useState } from 'react';
import {
  ReviewItem,
  ReviewSubmissionPayload,
  ReviewDeskState,
} from '../../types/review';
import { API_BASE_URL } from '../../api/client';
import { ReviewQueueList } from './ReviewQueueList';
import { ReviewEvidenceViewer } from './ReviewEvidenceViewer';
import { ReviewDetailPanel } from './ReviewDetailPanel';
import { ReviewDecisionForm } from './ReviewDecisionForm';
import './ReviewDeskSection.css';

export const ReviewDeskSection: React.FC = () => {
  const [deskState, setDeskState] = useState<ReviewDeskState>('ready');
  const [queue] = useState<ReviewItem[]>([]);
  const [selectedItem, setSelectedItem] = useState<ReviewItem | null>(null);
  const [submissionFeedback, setSubmissionFeedback] = useState<{
    type: 'contract-pending' | 'conflict';
    payload?: ReviewSubmissionPayload;
  } | null>(null);

  const handleSubmitAttempt = (payload: ReviewSubmissionPayload) => {
    // Condition 1: Do not make speculative backend requests or simulate success.
    // Display the prepared working contract payload and explicitly note pending backend route.
    setSubmissionFeedback({
      type: 'contract-pending',
      payload,
    });
  };

  const handleSimulateConflict = () => {
    setDeskState('conflict');
  };

  const handleResetToReady = () => {
    setDeskState('ready');
    setSubmissionFeedback(null);
  };

  return (
    <div className="ws-review-section">
      {/* Contract Notice Banner */}
      <section className="ws-contract-banner" role="status">
        <div className="ws-contract-badge">Backend Contract Status</div>
        <div className="ws-contract-content">
          <strong>Review Queue &amp; Submission Routes Pending Confirmation</strong>
          <p>
            Santosh has confirmed that <code>GET /api/v1/health</code> is implemented, but review queue
            and submission endpoints are currently planned. To prevent breaking assumptions, this interface
            keeps backend-dependent actions isolated behind confirmed contract boundaries.
          </p>
          <div className="ws-contract-chips">
            <span className="ws-chip">Base Prefix: <code>{API_BASE_URL}</code></span>
            <span className="ws-chip">Working Payload: <code>[detection_id, decision, corrected_taxon_id, reason, expected_revision]</code></span>
            <span className="ws-chip pending">HTTP 409 Conflict Handling: Enabled</span>
          </div>
        </div>
      </section>

      {/* State Preview Controls for Interface Verification */}
      <div className="ws-state-controls">
        <span className="ws-controls-label">Test Interface States:</span>
        <button
          type="button"
          className={`ws-state-toggle ${deskState === 'ready' ? 'active' : ''}`}
          onClick={handleResetToReady}
        >
          Queue Ready View
        </button>
        <button
          type="button"
          className={`ws-state-toggle ${deskState === 'loading' ? 'active' : ''}`}
          onClick={() => setDeskState('loading')}
        >
          Loading State
        </button>
        <button
          type="button"
          className={`ws-state-toggle ${deskState === 'empty' ? 'active' : ''}`}
          onClick={() => setDeskState('empty')}
        >
          Empty Queue State
        </button>
        <button
          type="button"
          className={`ws-state-toggle ${deskState === 'unavailable' ? 'active' : ''}`}
          onClick={() => setDeskState('unavailable')}
        >
          Backend Unavailable State
        </button>
        <button
          type="button"
          className={`ws-state-toggle ${deskState === 'conflict' ? 'active' : ''}`}
          onClick={handleSimulateConflict}
        >
          HTTP 409 Conflict State
        </button>
      </div>

      {/* Submission Feedback Notice (No Fake Success) */}
      {submissionFeedback && submissionFeedback.type === 'contract-pending' && (
        <div className="ws-feedback-callout" role="alert">
          <div className="ws-callout-top">
            <span className="ws-callout-icon" aria-hidden="true">📋</span>
            <strong>Submission Prepared — Awaiting Backend Route Confirmation</strong>
          </div>
          <p className="ws-callout-desc">
            The decision was validated against the working contract. Per team rules, no speculative HTTP
            requests were sent, and no fake success was simulated. Once Santosh confirms the endpoint (e.g.{' '}
            <code>POST /api/v1/review/{String(submissionFeedback.payload?.detection_id)}</code>), it will
            transmit this exact payload:
          </p>
          <pre className="ws-payload-preview">
            {JSON.stringify(submissionFeedback.payload, null, 2)}
          </pre>
          <button
            type="button"
            className="ws-btn-dismiss"
            onClick={() => setSubmissionFeedback(null)}
          >
            Dismiss Notice
          </button>
        </div>
      )}

      {/* HTTP 409 Conflict State */}
      {deskState === 'conflict' && (
        <div className="ws-state-view ws-conflict-view" role="alert">
          <div className="ws-conflict-icon" aria-hidden="true">⚠️</div>
          <h3 className="ws-conflict-title">Revision Conflict (HTTP 409)</h3>
          <p className="ws-conflict-desc">
            This detection record was modified by another reviewer or background process since it was loaded.
            Your current local view is stale.
          </p>
          <div className="ws-conflict-resolution">
            <strong>Data Integrity Protection:</strong>
            <span>
              Your pending changes were not committed over concurrent edits. Click below to reload the fresh
              queue from the backend.
            </span>
          </div>
          <button
            type="button"
            className="ws-btn-reload"
            onClick={handleResetToReady}
          >
            ↻ Reload Fresh Queue
          </button>
        </div>
      )}

      {/* Loading State */}
      {deskState === 'loading' && (
        <div className="ws-state-view" role="status">
          <div className="ws-desk-spinner" aria-hidden="true" />
          <h3 className="ws-state-title">Loading Review Queue…</h3>
          <p className="ws-state-desc">
            Checking backend review endpoints at <code>{API_BASE_URL}</code>
          </p>
        </div>
      )}

      {/* Empty State */}
      {deskState === 'empty' && (
        <div className="ws-state-view">
          <div className="ws-state-icon" aria-hidden="true">✓</div>
          <h3 className="ws-state-title">Review Queue Clear</h3>
          <p className="ws-state-desc">
            Zero wildlife detections currently require human review. All recorded encounters have been verified.
          </p>
          <button
            type="button"
            className="ws-btn-secondary"
            onClick={handleResetToReady}
          >
            Return to Review Workspace
          </button>
        </div>
      )}

      {/* Backend Unavailable State */}
      {deskState === 'unavailable' && (
        <div className="ws-state-view ws-unavailable-view" role="alert">
          <div className="ws-state-icon" aria-hidden="true">📡</div>
          <h3 className="ws-state-title">Review Service Unreachable</h3>
          <p className="ws-state-desc">
            Unable to connect to backend review endpoints at <code>{API_BASE_URL}</code>.
            Please ensure Santosh&apos;s FastAPI backend server is running on <code>http://localhost:8000</code>.
          </p>
          <button
            type="button"
            className="ws-btn-secondary"
            onClick={handleResetToReady}
          >
            Retry Connection
          </button>
        </div>
      )}

      {/* Ready Workspace */}
      {deskState === 'ready' && (
        <div className="ws-desk-workspace">
          <div className="ws-desk-sidebar">
            <ReviewQueueList
              queue={queue}
              selectedItem={selectedItem}
              onSelectItem={setSelectedItem}
            />
          </div>

          <div className="ws-desk-main">
            {selectedItem ? (
              <div className="ws-workspace-columns">
                <div className="ws-workspace-left">
                  <ReviewEvidenceViewer
                    imageId={selectedItem.image_id}
                    detectionId={selectedItem.id}
                  />
                  <ReviewDetailPanel item={selectedItem} />
                </div>
                <div className="ws-workspace-right">
                  <ReviewDecisionForm
                    item={selectedItem}
                    onSubmitAttempt={handleSubmitAttempt}
                  />
                </div>
              </div>
            ) : (
              <div className="ws-no-selection-card">
                <div className="ws-no-sel-icon" aria-hidden="true">🔍</div>
                <h3>No Detection Selected</h3>
                <p>
                  The review queue is currently empty because live review records await Santosh&apos;s backend
                  endpoint. Once connected, items in the queue will appear on the left for verification.
                </p>
                <div className="ws-queue-status-box">
                  <span>Backend status: <code>GET /api/v1/health</code> implemented</span>
                  <span>Review queue endpoint: <code>Pending confirmation</code></span>
                </div>
              </div>
            )}
          </div>
        </div>
      )}
    </div>
  );
};
