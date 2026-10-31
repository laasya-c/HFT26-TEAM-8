"""002 Add processing_jobs table.

Revision ID: 002_add_processing_jobs
Revises: 001_initial_schema
Create Date: 2026-10-31

Creates persistent table for background processing jobs.
"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa

revision: str = "002_add_processing_jobs"
down_revision: Union[str, None] = "001_initial_schema"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "processing_jobs",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("upload_id", sa.String(36), nullable=False, index=True),
        sa.Column("status", sa.String(50), nullable=False, server_default="queued"),
        sa.Column("progress", sa.Float(), nullable=False, server_default="0.0"),
        sa.Column("total_items", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("processed_items", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("media_ids", sa.JSON(), nullable=False),
        sa.Column("run_id", sa.String(36), sa.ForeignKey("prediction_runs.id", ondelete="SET NULL"), nullable=True),
        sa.Column("failures", sa.JSON(), nullable=False),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_table("processing_jobs")
