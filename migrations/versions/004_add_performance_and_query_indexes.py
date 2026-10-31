"""004 Add performance and query indexes for detections, review events, and image frames.

Revision ID: 004_add_performance_and_query_indexes
Revises: 003_phase3_audit_and_indexes
Create Date: 2026-10-31

Adds indexes for frequently queried and filtered columns:
- detections (review_status, created_at): Speeds up observation listing by review state.
- detections (taxon_id, created_at): Speeds up observation listing by species taxonomy.
- detections (image_id): Optimizes relational joins from ImageFrame.
- detections (encounter_id): Optimizes encounter member queries.
- review_events (detection_id, created_at): Speeds up review audit trail retrieval.
- image_frames (source_media_id): Optimizes camera join queries.
"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa

revision: str = "004_add_performance_and_query_indexes"
down_revision: Union[str, None] = "003_phase3_audit_and_indexes"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 1. Detection query and filter indexes
    op.create_index(
        "ix_detections_review_status_created",
        "detections",
        ["review_status", "created_at"],
    )
    op.create_index(
        "ix_detections_taxon_id_created",
        "detections",
        ["taxon_id", "created_at"],
    )
    op.create_index(
        "ix_detections_image_id",
        "detections",
        ["image_id"],
    )
    op.create_index(
        "ix_detections_encounter_id",
        "detections",
        ["encounter_id"],
    )

    # 2. Review audit trail index
    op.create_index(
        "ix_review_events_detection_created",
        "review_events",
        ["detection_id", "created_at"],
    )

    # 3. Image frames media reference index
    op.create_index(
        "ix_image_frames_source_media",
        "image_frames",
        ["source_media_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_image_frames_source_media", table_name="image_frames")
    op.drop_index("ix_review_events_detection_created", table_name="review_events")
    op.drop_index("ix_detections_encounter_id", table_name="detections")
    op.drop_index("ix_detections_image_id", table_name="detections")
    op.drop_index("ix_detections_taxon_id_created", table_name="detections")
    op.drop_index("ix_detections_review_status_created", table_name="detections")
