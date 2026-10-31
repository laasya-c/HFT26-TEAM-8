import React from 'react';
import { ReviewItem } from '../../types/review';
import './ReviewQueueList.css';

interface ReviewQueueListProps {
  queue: ReviewItem[];
  selectedItem: ReviewItem | null;
  onSelectItem: (item: ReviewItem) => void;
}

export const ReviewQueueList: React.FC<ReviewQueueListProps> = ({
  queue,
  selectedItem,
  onSelectItem,
}) => {
  return (
    <div className="ws-queue-list-card">
      <div className="ws-queue-header">
        <div>
          <h3 className="ws-queue-title">Review Queue</h3>
          <span className="ws-queue-subtitle">
            Detections awaiting expert verification
          </span>
        </div>
        <span className="ws-queue-count-pill">
          {queue.length} {queue.length === 1 ? 'item' : 'items'}
        </span>
      </div>

      <div className="ws-queue-items-container">
        {queue.length === 0 ? (
          <div className="ws-queue-empty">
            <span className="ws-empty-icon" aria-hidden="true">✓</span>
            <div className="ws-empty-text">
              <strong>Review Queue Is Clear</strong>
              <span>No detections are currently pending verification.</span>
            </div>
          </div>
        ) : (
          <ul className="ws-queue-list" role="listbox" aria-label="Review Queue Items">
            {queue.map((item) => {
              const isSelected = selectedItem?.id === item.id;
              const hasEvidence =
                item.image_id !== undefined &&
                item.image_id !== null &&
                item.image_id !== '';

              return (
                <li
                  key={String(item.id)}
                  className={`ws-queue-item ${isSelected ? 'is-selected' : ''}`}
                  onClick={() => onSelectItem(item)}
                  role="option"
                  aria-selected={isSelected}
                  tabIndex={0}
                  onKeyDown={(e) => {
                    if (e.key === 'Enter' || e.key === ' ') {
                      e.preventDefault();
                      onSelectItem(item);
                    }
                  }}
                >
                  <div className="ws-queue-item-top">
                    <span className="ws-queue-item-id">
                      ID: <code>{String(item.id)}</code>
                    </span>
                    {hasEvidence && (
                      <span className="ws-queue-evidence-pill">📷 Evidence</span>
                    )}
                  </div>

                  <div className="ws-queue-item-species">
                    {item.species ? (
                      <strong>{item.species}</strong>
                    ) : (
                      <span className="ws-pending-tag">Unconfirmed Species</span>
                    )}
                  </div>

                  <div className="ws-queue-item-meta">
                    <span>
                      Camera:{' '}
                      {item.camera_id ? (
                        <code>{item.camera_id}</code>
                      ) : (
                        <span className="ws-pending-tag">Unspecified</span>
                      )}
                    </span>
                    {item.status && (
                      <span className="ws-queue-status-tag">{item.status}</span>
                    )}
                  </div>
                </li>
              );
            })}
          </ul>
        )}
      </div>
    </div>
  );
};
