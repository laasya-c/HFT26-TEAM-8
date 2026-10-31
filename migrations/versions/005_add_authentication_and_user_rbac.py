"""005 Add authentication, user RBAC, refresh tokens, and device credentials.

Revision ID: 005_add_authentication_and_user_rbac
Revises: 004_add_performance_and_query_indexes
Create Date: 2026-10-31

Adds:
1. `users` table:
   - Primary key UUID, unique username, unique email.
   - Argon2id password hash storage.
   - User role (admin, researcher, viewer), active status, timestamps.
2. `refresh_tokens` table:
   - SHA-256 token hash storage with family rotation tracking (RTR).
   - Foreign key to users.id (ON DELETE CASCADE) named `fk_refresh_tokens_user_id_users`.
   - Expiration and revocation timestamps.
3. `api_keys` table:
   - SHA-256 key hash scoped to specific camera trap stations.
   - Foreign key to cameras.id (ON DELETE CASCADE) named `fk_api_keys_camera_id_cameras`.
   - Expiration, revocation, and last-used timestamps.
4. Ownership foreign keys on existing models:
   - `media_assets.uploader_id` -> users.id (SET NULL) named `fk_media_assets_uploader_id_users`
   - `processing_jobs.created_by_user_id` -> users.id (SET NULL) named `fk_processing_jobs_created_by_user_id_users`
   - `monitoring_actions.created_by_user_id` -> users.id (SET NULL) named `fk_monitoring_actions_created_by_user_id_users`
"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa

revision: str = "005_add_authentication_and_user_rbac"
down_revision: Union[str, None] = "004_add_performance_and_query_indexes"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# Explicit naming convention ensuring SQLite batch mode never encounters unnamed constraints
NAMING_CONVENTION = {
    "ix": "ix_%(column_0_label)s",
    "uq": "uq_%(table_name)s_%(column_0_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    existing_tables = set(inspector.get_table_names())

    def index_names(table: str) -> set:
        try:
            return {ix["name"] for ix in inspector.get_indexes(table)}
        except Exception:
            return set()

    def column_names(table: str) -> set:
        try:
            return {col["name"] for col in inspector.get_columns(table)}
        except Exception:
            return set()

    # 1. Create users table (idempotent check)
    if "users" not in existing_tables:
        op.create_table(
            "users",
            sa.Column("id", sa.String(36), primary_key=True),
            sa.Column("username", sa.String(50), nullable=False),
            sa.Column("email", sa.String(255), nullable=False),
            sa.Column("hashed_password", sa.String(255), nullable=False),
            sa.Column("full_name", sa.String(100), nullable=True),
            sa.Column("role", sa.String(20), nullable=False, server_default="viewer"),
            sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        )

    users_indexes = index_names("users")
    if "ix_users_username" not in users_indexes:
        op.create_index("ix_users_username", "users", ["username"], unique=True)
    if "ix_users_email" not in users_indexes:
        op.create_index("ix_users_email", "users", ["email"], unique=True)
    if "ix_users_role" not in users_indexes:
        op.create_index("ix_users_role", "users", ["role"], unique=False)

    # 2. Create refresh_tokens table (idempotent check)
    if "refresh_tokens" not in existing_tables:
        op.create_table(
            "refresh_tokens",
            sa.Column("id", sa.String(36), primary_key=True),
            sa.Column(
                "user_id",
                sa.String(36),
                sa.ForeignKey("users.id", name="fk_refresh_tokens_user_id_users", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.Column("token_hash", sa.String(64), nullable=False),
            sa.Column("family_id", sa.String(36), nullable=False),
            sa.Column("parent_token_hash", sa.String(64), nullable=True),
            sa.Column("is_revoked", sa.Boolean(), nullable=False, server_default=sa.false()),
            sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        )

    rt_indexes = index_names("refresh_tokens")
    if "ix_refresh_tokens_token_hash" not in rt_indexes:
        op.create_index("ix_refresh_tokens_token_hash", "refresh_tokens", ["token_hash"], unique=True)
    if "ix_refresh_tokens_user_id" not in rt_indexes:
        op.create_index("ix_refresh_tokens_user_id", "refresh_tokens", ["user_id"], unique=False)
    if "ix_refresh_tokens_family_id" not in rt_indexes:
        op.create_index("ix_refresh_tokens_family_id", "refresh_tokens", ["family_id"], unique=False)

    # 3. Create api_keys table (idempotent check)
    if "api_keys" not in existing_tables:
        op.create_table(
            "api_keys",
            sa.Column("id", sa.String(36), primary_key=True),
            sa.Column("name", sa.String(100), nullable=False),
            sa.Column("key_prefix", sa.String(16), nullable=False, server_default="ws_live_"),
            sa.Column("key_hash", sa.String(64), nullable=False),
            sa.Column(
                "camera_id",
                sa.String(36),
                sa.ForeignKey("cameras.id", name="fk_api_keys_camera_id_cameras", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.Column("role", sa.String(20), nullable=False, server_default="field_device"),
            sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("last_used_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        )

    ak_indexes = index_names("api_keys")
    if "ix_api_keys_key_hash" not in ak_indexes:
        op.create_index("ix_api_keys_key_hash", "api_keys", ["key_hash"], unique=True)
    if "ix_api_keys_camera_id" not in ak_indexes:
        op.create_index("ix_api_keys_camera_id", "api_keys", ["camera_id"], unique=False)
    if "ix_api_keys_is_active" not in ak_indexes:
        op.create_index("ix_api_keys_is_active", "api_keys", ["is_active"], unique=False)

    # 4. Alter existing tables to add ownership foreign key columns (idempotent check)
    media_cols = column_names("media_assets")
    media_indexes = index_names("media_assets")
    if "uploader_id" not in media_cols:
        with op.batch_alter_table("media_assets", naming_convention=NAMING_CONVENTION) as batch_op:
            batch_op.add_column(
                sa.Column(
                    "uploader_id",
                    sa.String(36),
                    sa.ForeignKey("users.id", name="fk_media_assets_uploader_id_users", ondelete="SET NULL"),
                    nullable=True,
                )
            )
            if "ix_media_assets_uploader_id" not in media_indexes:
                batch_op.create_index("ix_media_assets_uploader_id", ["uploader_id"])
    elif "ix_media_assets_uploader_id" not in media_indexes:
        with op.batch_alter_table("media_assets", naming_convention=NAMING_CONVENTION) as batch_op:
            batch_op.create_index("ix_media_assets_uploader_id", ["uploader_id"])

    jobs_cols = column_names("processing_jobs")
    jobs_indexes = index_names("processing_jobs")
    if "created_by_user_id" not in jobs_cols:
        with op.batch_alter_table("processing_jobs", naming_convention=NAMING_CONVENTION) as batch_op:
            batch_op.add_column(
                sa.Column(
                    "created_by_user_id",
                    sa.String(36),
                    sa.ForeignKey("users.id", name="fk_processing_jobs_created_by_user_id_users", ondelete="SET NULL"),
                    nullable=True,
                )
            )
            if "ix_processing_jobs_created_by_user_id" not in jobs_indexes:
                batch_op.create_index("ix_processing_jobs_created_by_user_id", ["created_by_user_id"])
    elif "ix_processing_jobs_created_by_user_id" not in jobs_indexes:
        with op.batch_alter_table("processing_jobs", naming_convention=NAMING_CONVENTION) as batch_op:
            batch_op.create_index("ix_processing_jobs_created_by_user_id", ["created_by_user_id"])

    actions_cols = column_names("monitoring_actions")
    actions_indexes = index_names("monitoring_actions")
    if "created_by_user_id" not in actions_cols:
        with op.batch_alter_table("monitoring_actions", naming_convention=NAMING_CONVENTION) as batch_op:
            batch_op.add_column(
                sa.Column(
                    "created_by_user_id",
                    sa.String(36),
                    sa.ForeignKey("users.id", name="fk_monitoring_actions_created_by_user_id_users", ondelete="SET NULL"),
                    nullable=True,
                )
            )
            if "ix_monitoring_actions_created_by_user_id" not in actions_indexes:
                batch_op.create_index("ix_monitoring_actions_created_by_user_id", ["created_by_user_id"])
    elif "ix_monitoring_actions_created_by_user_id" not in actions_indexes:
        with op.batch_alter_table("monitoring_actions", naming_convention=NAMING_CONVENTION) as batch_op:
            batch_op.create_index("ix_monitoring_actions_created_by_user_id", ["created_by_user_id"])


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    existing_tables = set(inspector.get_table_names())

    def index_names(table: str) -> set:
        try:
            return {ix["name"] for ix in inspector.get_indexes(table)}
        except Exception:
            return set()

    def column_names(table: str) -> set:
        try:
            return {col["name"] for col in inspector.get_columns(table)}
        except Exception:
            return set()

    # 1. Drop added ownership columns from existing tables (idempotent check)
    if "monitoring_actions" in existing_tables:
        actions_cols = column_names("monitoring_actions")
        actions_indexes = index_names("monitoring_actions")
        if "created_by_user_id" in actions_cols:
            with op.batch_alter_table("monitoring_actions", naming_convention=NAMING_CONVENTION) as batch_op:
                if "ix_monitoring_actions_created_by_user_id" in actions_indexes:
                    batch_op.drop_index("ix_monitoring_actions_created_by_user_id")
                batch_op.drop_column("created_by_user_id")

    if "processing_jobs" in existing_tables:
        jobs_cols = column_names("processing_jobs")
        jobs_indexes = index_names("processing_jobs")
        if "created_by_user_id" in jobs_cols:
            with op.batch_alter_table("processing_jobs", naming_convention=NAMING_CONVENTION) as batch_op:
                if "ix_processing_jobs_created_by_user_id" in jobs_indexes:
                    batch_op.drop_index("ix_processing_jobs_created_by_user_id")
                batch_op.drop_column("created_by_user_id")

    if "media_assets" in existing_tables:
        media_cols = column_names("media_assets")
        media_indexes = index_names("media_assets")
        if "uploader_id" in media_cols:
            with op.batch_alter_table("media_assets", naming_convention=NAMING_CONVENTION) as batch_op:
                if "ix_media_assets_uploader_id" in media_indexes:
                    batch_op.drop_index("ix_media_assets_uploader_id")
                batch_op.drop_column("uploader_id")

    # 2. Drop authentication tables in reverse dependency order (idempotent check)
    if "api_keys" in existing_tables:
        op.drop_table("api_keys")
    if "refresh_tokens" in existing_tables:
        op.drop_table("refresh_tokens")
    if "users" in existing_tables:
        op.drop_table("users")
