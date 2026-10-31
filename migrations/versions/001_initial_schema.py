"""001 Initial Schema for WILDSCOPE Platform.

Revision ID: 001_initial_schema
Revises: None
Create Date: 2026-10-31

Creates initial tables for:
- cameras
- camera_telemetry
- monitoring_actions
- media_assets
- image_frames
- prediction_runs
- encounters
- detections
- encounter_members
- review_events
- dataset_revisions
- ground_truth_annotations
"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa

revision: str = "001_initial_schema"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 1. Cameras
    op.create_table(
        "cameras",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("label", sa.String(200), nullable=False),
        sa.Column("timezone", sa.String(100), nullable=False, server_default="UTC"),
        sa.Column("latitude", sa.Float(), nullable=True),
        sa.Column("longitude", sa.Float(), nullable=True),
        sa.Column("telemetry_status", sa.String(50), nullable=False, server_default="unknown"),
        sa.Column("last_heartbeat_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("active_camera_days", sa.Float(), nullable=True),
        sa.Column("provenance", sa.String(50), nullable=False, server_default="observed"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )

    # 2. Camera Telemetry
    op.create_table(
        "camera_telemetry",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("camera_id", sa.String(36), sa.ForeignKey("cameras.id", ondelete="CASCADE"), nullable=False),
        sa.Column("observed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("battery_level", sa.Float(), nullable=True),
        sa.Column("signal_strength", sa.Float(), nullable=True),
        sa.Column("error_codes", sa.JSON(), nullable=False),
        sa.Column("raw_payload", sa.JSON(), nullable=True),
        sa.Column("source", sa.String(100), nullable=False, server_default="satellite_relay"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )

    # 3. Monitoring Actions
    op.create_table(
        "monitoring_actions",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("camera_id", sa.String(36), sa.ForeignKey("cameras.id", ondelete="CASCADE"), nullable=False),
        sa.Column("action_type", sa.String(100), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("performed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("baseline_start", sa.DateTime(timezone=True), nullable=True),
        sa.Column("baseline_end", sa.DateTime(timezone=True), nullable=True),
        sa.Column("post_start", sa.DateTime(timezone=True), nullable=True),
        sa.Column("post_end", sa.DateTime(timezone=True), nullable=True),
        sa.Column("source", sa.String(100), nullable=False, server_default="field_ranger"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )

    # 4. Media Assets
    op.create_table(
        "media_assets",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("type", sa.String(20), nullable=False),
        sa.Column("camera_id", sa.String(36), sa.ForeignKey("cameras.id", ondelete="SET NULL"), nullable=True),
        sa.Column("storage_key", sa.String(512), nullable=False),
        sa.Column("content_hash", sa.String(64), nullable=False, index=True),
        sa.Column("raw_timestamp", sa.String(100), nullable=True),
        sa.Column("captured_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("timezone_source", sa.String(100), nullable=True),
        sa.Column("provenance", sa.String(50), nullable=False, server_default="observed"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )

    # 5. Image Frames
    op.create_table(
        "image_frames",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("source_media_id", sa.String(36), sa.ForeignKey("media_assets.id", ondelete="CASCADE"), nullable=False),
        sa.Column("frame_offset_ms", sa.Integer(), nullable=True),
        sa.Column("width", sa.Integer(), nullable=True),
        sa.Column("height", sa.Integer(), nullable=True),
        sa.Column("orientation", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("content_url", sa.String(512), nullable=False),
        sa.Column("quality_flags", sa.JSON(), nullable=False),
        sa.Column("provenance", sa.String(50), nullable=False, server_default="observed"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )

    # 6. Prediction Runs
    op.create_table(
        "prediction_runs",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("model_name", sa.String(100), nullable=False),
        sa.Column("model_version", sa.String(100), nullable=False),
        sa.Column("input_content_hash", sa.String(64), nullable=True),
        sa.Column("model_artifact_hash", sa.String(64), nullable=True),
        sa.Column("settings_hash", sa.String(64), nullable=True),
        sa.Column("device", sa.String(50), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("status", sa.String(50), nullable=False, server_default="running"),
        sa.Column("failures", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )

    # 7. Encounters
    op.create_table(
        "encounters",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("camera_id", sa.String(36), sa.ForeignKey("cameras.id", ondelete="CASCADE"), nullable=False),
        sa.Column("start_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("end_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("grouping_rule_version", sa.String(100), nullable=False),
        sa.Column("provenance", sa.String(50), nullable=False, server_default="inferred"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )

    # 8. Detections
    op.create_table(
        "detections",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("image_id", sa.String(36), sa.ForeignKey("image_frames.id", ondelete="CASCADE"), nullable=False),
        sa.Column("run_id", sa.String(36), sa.ForeignKey("prediction_runs.id", ondelete="CASCADE"), nullable=False),
        sa.Column("encounter_id", sa.String(36), sa.ForeignKey("encounters.id", ondelete="SET NULL"), nullable=True),
        sa.Column("bbox_x", sa.Float(), nullable=False),
        sa.Column("bbox_y", sa.Float(), nullable=False),
        sa.Column("bbox_w", sa.Float(), nullable=False),
        sa.Column("bbox_h", sa.Float(), nullable=False),
        sa.Column("raw_label", sa.String(100), nullable=False),
        sa.Column("taxon_id", sa.String(100), nullable=True),
        sa.Column("label", sa.String(100), nullable=False),
        sa.Column("score", sa.Float(), nullable=False),
        sa.Column("detection_score", sa.Float(), nullable=True),
        sa.Column("classification_score", sa.Float(), nullable=True),
        sa.Column("score_type", sa.String(50), nullable=True),
        sa.Column("calibration_status", sa.String(50), nullable=True),
        sa.Column("alternatives", sa.JSON(), nullable=False),
        sa.Column("model_version", sa.String(100), nullable=False),
        sa.Column("review_status", sa.String(50), nullable=False, server_default="pending"),
        sa.Column("provenance", sa.String(50), nullable=False, server_default="inferred"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )

    # 9. Encounter Members
    op.create_table(
        "encounter_members",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("encounter_id", sa.String(36), sa.ForeignKey("encounters.id", ondelete="CASCADE"), nullable=False),
        sa.Column("detection_id", sa.String(36), sa.ForeignKey("detections.id", ondelete="CASCADE"), nullable=False),
        sa.Column("image_id", sa.String(36), sa.ForeignKey("image_frames.id", ondelete="CASCADE"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )

    # 10. Review Events (F20)
    op.create_table(
        "review_events",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("detection_id", sa.String(36), sa.ForeignKey("detections.id", ondelete="CASCADE"), nullable=False),
        sa.Column("decision", sa.String(50), nullable=False),
        sa.Column("corrected_taxon_id", sa.String(100), nullable=True),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("reviewer_id", sa.String(100), nullable=False),
        sa.Column("expected_revision", sa.Integer(), nullable=False),
        sa.Column("resulting_revision", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )

    # 11. Dataset Revision Tracker
    op.create_table(
        "dataset_revisions",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("current_revision", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("change_reason", sa.String(255), nullable=True),
    )

    # 12. Ground Truth Annotations (Evaluation-Only)
    op.create_table(
        "ground_truth_annotations",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("source_media_id", sa.String(36), sa.ForeignKey("media_assets.id", ondelete="CASCADE"), nullable=False),
        sa.Column("dataset_source", sa.String(100), nullable=False),
        sa.Column("bbox_x", sa.Float(), nullable=True),
        sa.Column("bbox_y", sa.Float(), nullable=True),
        sa.Column("bbox_w", sa.Float(), nullable=True),
        sa.Column("bbox_h", sa.Float(), nullable=True),
        sa.Column("taxon_id", sa.String(100), nullable=False),
        sa.Column("label", sa.String(100), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("ground_truth_annotations")
    op.drop_table("dataset_revisions")
    op.drop_table("review_events")
    op.drop_table("encounter_members")
    op.drop_table("detections")
    op.drop_table("encounters")
    op.drop_table("prediction_runs")
    op.drop_table("image_frames")
    op.drop_table("media_assets")
    op.drop_table("monitoring_actions")
    op.drop_table("camera_telemetry")
    op.drop_table("cameras")
