"""003 Phase 3A Audit Protection, Provenance, and Performance Indexes.

Revision ID: 003_phase3_audit_and_indexes
Revises: 002_add_processing_jobs
Create Date: 2026-10-31

Changes:
1. Add performance indexes:
   - camera_telemetry (camera_id, observed_at)
   - monitoring_actions (camera_id, performed_at)
   - cameras (telemetry_status)
2. Add review_status column to encounters (server_default='pending').
3. Add provenance column to review_events (server_default='observed').
4. Protect review_events from cascade deletion on detection deletion (ON DELETE RESTRICT).
5. Ensure dataset_revisions singleton row exists with id=1.
"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa

revision: str = "003_phase3_audit_and_indexes"
down_revision: Union[str, None] = "002_add_processing_jobs"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    dialect = bind.dialect.name

    # 1. Performance Indexes
    op.create_index(
        "ix_telemetry_camera_observed",
        "camera_telemetry",
        ["camera_id", "observed_at"],
    )
    op.create_index(
        "ix_monitoring_camera_performed",
        "monitoring_actions",
        ["camera_id", "performed_at"],
    )
    op.create_index(
        "ix_cameras_telemetry_status",
        "cameras",
        ["telemetry_status"],
    )

    # 2. Add review_status to encounters
    with op.batch_alter_table("encounters") as batch_op:
        batch_op.add_column(
            sa.Column("review_status", sa.String(50), nullable=False, server_default="pending")
        )

    # 3. Add provenance to review_events and update foreign key to RESTRICT
    with op.batch_alter_table("review_events") as batch_op:
        batch_op.add_column(
            sa.Column("provenance", sa.String(50), nullable=False, server_default="observed")
        )
        if dialect != "sqlite":
            try:
                batch_op.drop_constraint("fk_review_events_detection_id", type_="foreignkey")
            except Exception:
                pass
            batch_op.create_foreign_key(
                "fk_review_events_detection_id_restrict",
                "detections",
                ["detection_id"],
                ["id"],
                ondelete="RESTRICT",
            )

    # 4. Initialize Dataset Revision Singleton if not present
    conn = op.get_bind()
    res = conn.execute(sa.text("SELECT id FROM dataset_revisions WHERE id = 1")).fetchone()
    if not res:
        conn.execute(
            sa.text(
                "INSERT INTO dataset_revisions (id, current_revision, updated_at, change_reason) "
                "VALUES (1, 1, CURRENT_TIMESTAMP, 'Initial baseline dataset revision')"
            )
        )


def downgrade() -> None:
    # 1. Drop Indexes
    op.drop_index("ix_cameras_telemetry_status", table_name="cameras")
    op.drop_index("ix_monitoring_camera_performed", table_name="monitoring_actions")
    op.drop_index("ix_telemetry_camera_observed", table_name="camera_telemetry")

    # 2. Drop review_status from encounters
    with op.batch_alter_table("encounters") as batch_op:
        batch_op.drop_column("review_status")

    # 3. Drop provenance from review_events
    with op.batch_alter_table("review_events") as batch_op:
        batch_op.drop_column("provenance")
