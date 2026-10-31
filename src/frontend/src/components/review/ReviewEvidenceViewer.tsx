import React, { useState } from 'react';
import { getImageContentUrl } from '../../api/client';
import './ReviewEvidenceViewer.css';

interface ReviewEvidenceViewerProps {
  imageId?: string | number;
  detectionId: string | number;
}

export const ReviewEvidenceViewer: React.FC<ReviewEvidenceViewerProps> = ({
  imageId,
  detectionId,
}) => {
  const [imageFailed, setImageFailed] = useState<boolean>(false);

  return (
    <div className="ws-evidence-viewer">
      <div className="ws-viewer-header">
        <span className="ws-viewer-title">Evidence &amp; Media Viewport</span>
        {imageId && (
          <span className="ws-viewer-badge">
            Media ID: <code>{String(imageId)}</code>
          </span>
        )}
      </div>

      <div className="ws-viewer-stage">
        {imageId ? (
          !imageFailed ? (
            <img
              src={getImageContentUrl(imageId)}
              alt={`Evidence for detection ${String(detectionId)}`}
              className="ws-viewer-image"
              onError={() => setImageFailed(true)}
            />
          ) : (
            <div className="ws-viewer-fallback">
              <span className="ws-fallback-icon" aria-hidden="true">⚠️</span>
              <div className="ws-fallback-content">
                <strong>Evidence Image Unreachable</strong>
                <span>
                  Could not load media from <code>{getImageContentUrl(imageId)}</code>.
                </span>
              </div>
            </div>
          )
        ) : (
          <div className="ws-viewer-empty">
            <span className="ws-empty-icon" aria-hidden="true">📷</span>
            <div className="ws-empty-content">
              <strong>No Evidence Media Attached</strong>
              <span>This detection record does not include an <code>image_id</code>.</span>
            </div>
          </div>
        )}
      </div>
    </div>
  );
};
