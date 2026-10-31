import React, { useState } from 'react';
import { ReviewDecision, ReviewSubmissionPayload, ReviewItem } from '../../types/review';
import './ReviewDecisionForm.css';

interface ReviewDecisionFormProps {
  item: ReviewItem;
  onSubmitAttempt: (payload: ReviewSubmissionPayload) => void;
  isSubmitting?: boolean;
}

export const ReviewDecisionForm: React.FC<ReviewDecisionFormProps> = ({
  item,
  onSubmitAttempt,
  isSubmitting = false,
}) => {
  const [decision, setDecision] = useState<ReviewDecision>('accept');
  const [correctedTaxonId, setCorrectedTaxonId] = useState<string>('');
  const [reason, setReason] = useState<string>('');
  const [validationError, setValidationError] = useState<string | null>(null);

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    setValidationError(null);

    // Validation rule 1: Needs Correction requires corrected_taxon_id
    if (decision === 'correction' && correctedTaxonId.trim() === '') {
      setValidationError('Corrected Taxon Identifier is required when decision is "Needs Correction".');
      return;
    }

    // Validation rule 2: Reject and Needs Correction require a reason
    if ((decision === 'reject' || decision === 'correction') && reason.trim() === '') {
      setValidationError(
        `A review justification/reason is mandatory when decision is "${
          decision === 'reject' ? 'Reject' : 'Needs Correction'
        }".`
      );
      return;
    }

    const payload: ReviewSubmissionPayload = {
      detection_id: item.id,
      decision,
      corrected_taxon_id: decision === 'correction' ? correctedTaxonId.trim() : undefined,
      reason: reason.trim() !== '' ? reason.trim() : undefined,
      expected_revision: item.detection_revision,
    };

    onSubmitAttempt(payload);
  };

  return (
    <form className="ws-decision-form" onSubmit={handleSubmit} noValidate>
      <div className="ws-form-header">
        <h4 className="ws-form-title">Verification Decision</h4>
        <span className="ws-form-subtitle">
          Evaluate detection for ID: <code>{String(item.id)}</code>
        </span>
      </div>

      {/* Decision Selection Buttons */}
      <div className="ws-decision-group" role="radiogroup" aria-label="Review Decision">
        <button
          type="button"
          className={`ws-decision-btn btn-accept ${decision === 'accept' ? 'is-active' : ''}`}
          onClick={() => {
            setDecision('accept');
            setValidationError(null);
          }}
          aria-checked={decision === 'accept'}
          role="radio"
        >
          <span className="ws-btn-icon" aria-hidden="true">✓</span>
          <span className="ws-btn-label">Accept</span>
          <span className="ws-btn-desc">Verify classification</span>
        </button>

        <button
          type="button"
          className={`ws-decision-btn btn-reject ${decision === 'reject' ? 'is-active' : ''}`}
          onClick={() => {
            setDecision('reject');
            setValidationError(null);
          }}
          aria-checked={decision === 'reject'}
          role="radio"
        >
          <span className="ws-btn-icon" aria-hidden="true">✕</span>
          <span className="ws-btn-label">Reject</span>
          <span className="ws-btn-desc">False positive / discard</span>
        </button>

        <button
          type="button"
          className={`ws-decision-btn btn-correction ${decision === 'correction' ? 'is-active' : ''}`}
          onClick={() => {
            setDecision('correction');
            setValidationError(null);
          }}
          aria-checked={decision === 'correction'}
          role="radio"
        >
          <span className="ws-btn-icon" aria-hidden="true">✎</span>
          <span className="ws-btn-label">Needs Correction</span>
          <span className="ws-btn-desc">Reassign taxon ID</span>
        </button>
      </div>

      {/* Conditional: Taxon Identifier input for Needs Correction */}
      {decision === 'correction' && (
        <div className="ws-form-field">
          <label htmlFor="corrected-taxon-id" className="ws-field-label">
            Corrected Taxon Identifier <span className="ws-required-star">*</span>
          </label>
          <input
            id="corrected-taxon-id"
            type="text"
            className="ws-form-input"
            placeholder="e.g. taxon_panthera_tigris…"
            value={correctedTaxonId}
            onChange={(e) => {
              setCorrectedTaxonId(e.target.value);
              setValidationError(null);
            }}
            required
          />
          <span className="ws-field-hint">
            Must specify standard taxon identifier per working contract specification.
          </span>
        </div>
      )}

      {/* Review Reason Textarea */}
      <div className="ws-form-field">
        <label htmlFor="review-reason" className="ws-field-label">
          Review Justification / Reason{' '}
          {decision === 'accept' ? (
            <span className="ws-optional-tag">(Optional)</span>
          ) : (
            <span className="ws-required-star">* (Mandatory)</span>
          )}
        </label>
        <textarea
          id="review-reason"
          className="ws-form-textarea"
          rows={3}
          placeholder={
            decision === 'accept'
              ? 'Add optional verification notes for this detection…'
              : 'Mandatory: explain why this detection is being rejected or corrected…'
          }
          value={reason}
          onChange={(e) => {
            setReason(e.target.value);
            setValidationError(null);
          }}
        />
      </div>

      {validationError && (
        <div className="ws-form-validation-error" role="alert">
          <span aria-hidden="true">⚠️</span> {validationError}
        </div>
      )}

      {/* Form Submit Footer */}
      <div className="ws-form-footer">
        <button
          type="submit"
          className="ws-btn-submit"
          disabled={isSubmitting}
        >
          {isSubmitting ? 'Submitting Decision…' : 'Submit Verification Decision'}
        </button>
      </div>
    </form>
  );
};
