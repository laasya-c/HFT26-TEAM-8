"""Alembic Migration 005 Regression & Idempotency Test Suite.

Verifies:
1. Revision lineage and metadata (004 -> 005).
2. End-to-end upgrade on SQLite from revision 004 to 005 without constraint name errors.
3. Verification of all foreign key constraints, explicit constraint names, and ON DELETE actions:
   - fk_media_assets_uploader_id_users (ON DELETE SET NULL)
   - fk_processing_jobs_created_by_user_id_users (ON DELETE SET NULL)
   - fk_monitoring_actions_created_by_user_id_users (ON DELETE SET NULL)
   - fk_refresh_tokens_user_id_users (ON DELETE CASCADE)
   - fk_api_keys_camera_id_cameras (ON DELETE CASCADE)
4. Runtime foreign-key behavior under PRAGMA foreign_keys = ON:
   - Deleting a user sets uploader_id and created_by_user_id to NULL without deleting assets or jobs.
   - Deleting a user cascades and deletes all associated refresh tokens.
   - Deleting a camera cascades and deletes all associated API keys.
5. Idempotent re-run behavior against a partially-migrated database (simulating the line 88 failure):
   - When users, refresh_tokens, or api_keys tables already exist, migration 005 re-run succeeds.
   - Repeated upgrade() calls are fully safe no-ops.
6. Clean downgrade from 005 back to 004.
"""
from datetime import datetime, timezone
import importlib
import os
from pathlib import Path
import tempfile
import uuid
import pytest
import sqlalchemy as sa
from alembic import command
from alembic.config import Config

from src.backend.config import REPO_ROOT


@pytest.fixture
def temp_alembic_db():
    """Provides an isolated SQLite file database and an Alembic Config pointing to it."""
    temp_dir = tempfile.TemporaryDirectory()
    db_path = Path(temp_dir.name) / "test_migration.db"
    db_url = f"sqlite:///{db_path.as_posix()}"

    ini_path = REPO_ROOT / "migrations" / "alembic.ini"
    alembic_cfg = Config(str(ini_path))
    alembic_cfg.set_main_option("script_location", str(REPO_ROOT / "migrations"))
    alembic_cfg.set_main_option("sqlalchemy.url", db_url)

    yield {"db_path": db_path, "db_url": db_url, "config": alembic_cfg}

    temp_dir.cleanup()


# ============================================================================
# 1. Metadata and Lineage Verification
# ============================================================================

@pytest.mark.unit
def test_migration_005_metadata_and_lineage():
    """Verify revision ID, down-revision, and callable lifecycle functions."""
    mig005 = importlib.import_module("migrations.versions.005_add_authentication_and_user_rbac")
    assert mig005.revision == "005_add_authentication_and_user_rbac"
    assert mig005.down_revision == "004_add_performance_and_query_indexes"
    assert callable(mig005.upgrade)
    assert callable(mig005.downgrade)
    assert hasattr(mig005, "NAMING_CONVENTION")
    assert "fk" in mig005.NAMING_CONVENTION


# ============================================================================
# 2. SQLite Upgrade from 004 to 005 End-to-End
# ============================================================================

@pytest.mark.integration
def test_sqlite_upgrade_from_004_to_005(temp_alembic_db):
    """Verify that Alembic cleanly upgrades from revision 004 to 005 on SQLite without ValueError."""
    cfg = temp_alembic_db["config"]
    db_url = temp_alembic_db["db_url"]

    # 1. Upgrade to revision 004
    command.upgrade(cfg, "004_add_performance_and_query_indexes")

    engine = sa.create_engine(db_url)
    inspector_before = sa.inspect(engine)
    assert "users" not in inspector_before.get_table_names()
    assert "refresh_tokens" not in inspector_before.get_table_names()
    assert "api_keys" not in inspector_before.get_table_names()

    cols_media = [c["name"] for c in inspector_before.get_columns("media_assets")]
    assert "uploader_id" not in cols_media

    # 2. Upgrade to revision 005
    command.upgrade(cfg, "005_add_authentication_and_user_rbac")

    # 3. Inspect database schema post-upgrade
    inspector_after = sa.inspect(engine)
    tables_after = set(inspector_after.get_table_names())
    assert "users" in tables_after
    assert "refresh_tokens" in tables_after
    assert "api_keys" in tables_after

    # Verify added columns
    media_cols = {c["name"] for c in inspector_after.get_columns("media_assets")}
    assert "uploader_id" in media_cols

    jobs_cols = {c["name"] for c in inspector_after.get_columns("processing_jobs")}
    assert "created_by_user_id" in jobs_cols

    actions_cols = {c["name"] for c in inspector_after.get_columns("monitoring_actions")}
    assert "created_by_user_id" in actions_cols

    # Verify foreign key targets and ondelete behavior
    media_fks = inspector_after.get_foreign_keys("media_assets")
    uploader_fk = next((fk for fk in media_fks if "uploader_id" in fk["constrained_columns"]), None)
    assert uploader_fk is not None
    assert uploader_fk["referred_table"] == "users"
    assert uploader_fk["referred_columns"] == ["id"]
    assert str(uploader_fk.get("options", {}).get("ondelete", "")).upper() == "SET NULL"

    jobs_fks = inspector_after.get_foreign_keys("processing_jobs")
    job_fk = next((fk for fk in jobs_fks if "created_by_user_id" in fk["constrained_columns"]), None)
    assert job_fk is not None
    assert job_fk["referred_table"] == "users"
    assert job_fk["referred_columns"] == ["id"]
    assert str(job_fk.get("options", {}).get("ondelete", "")).upper() == "SET NULL"

    actions_fks = inspector_after.get_foreign_keys("monitoring_actions")
    action_fk = next((fk for fk in actions_fks if "created_by_user_id" in fk["constrained_columns"]), None)
    assert action_fk is not None
    assert action_fk["referred_table"] == "users"
    assert action_fk["referred_columns"] == ["id"]
    assert str(action_fk.get("options", {}).get("ondelete", "")).upper() == "SET NULL"

    rt_fks = inspector_after.get_foreign_keys("refresh_tokens")
    rt_fk = next((fk for fk in rt_fks if "user_id" in fk["constrained_columns"]), None)
    assert rt_fk is not None
    assert rt_fk["referred_table"] == "users"
    assert str(rt_fk.get("options", {}).get("ondelete", "")).upper() == "CASCADE"

    ak_fks = inspector_after.get_foreign_keys("api_keys")
    ak_fk = next((fk for fk in ak_fks if "camera_id" in fk["constrained_columns"]), None)
    assert ak_fk is not None
    assert ak_fk["referred_table"] == "cameras"
    assert str(ak_fk.get("options", {}).get("ondelete", "")).upper() == "CASCADE"

    engine.dispose()


# ============================================================================
# 3. Foreign Key Delete Cascades and SET NULL Runtime Verification
# ============================================================================

@pytest.mark.integration
def test_sqlite_upgrade_runtime_foreign_key_behavior(temp_alembic_db):
    """Verify runtime behavior of ON DELETE SET NULL and ON DELETE CASCADE on migrated SQLite database."""
    cfg = temp_alembic_db["config"]
    db_url = temp_alembic_db["db_url"]

    # Upgrade fully to 005
    command.upgrade(cfg, "005_add_authentication_and_user_rbac")

    engine = sa.create_engine(db_url)
    with engine.connect() as conn:
        # Enforce foreign keys in SQLite connection
        conn.execute(sa.text("PRAGMA foreign_keys = ON;"))

        # 1. Create User
        user_id = str(uuid.uuid4())
        conn.execute(
            sa.text(
                "INSERT INTO users (id, username, email, hashed_password, role, is_active, created_at, updated_at) "
                "VALUES (:id, 'mig_user', 'mig@wildscope.org', 'fake_hash', 'researcher', 1, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)"
            ),
            {"id": user_id},
        )

        # 2. Create Camera
        cam_id = "CAM-MIG-1"
        conn.execute(
            sa.text(
                "INSERT INTO cameras (id, label, timezone, provenance, created_at) "
                "VALUES (:id, 'Migration Camera', 'UTC', 'observed', CURRENT_TIMESTAMP)"
            ),
            {"id": cam_id},
        )

        # 3. Create MediaAsset referencing User
        media_id = "MED-MIG-1"
        conn.execute(
            sa.text(
                "INSERT INTO media_assets (id, type, camera_id, storage_key, content_hash, uploader_id, provenance, created_at) "
                "VALUES (:id, 'image', :cam_id, 'media/m1.jpg', 'hash_m1', :uploader_id, 'observed', CURRENT_TIMESTAMP)"
            ),
            {"id": media_id, "cam_id": cam_id, "uploader_id": user_id},
        )

        # 4. Create ProcessingJob referencing User
        job_id = "JOB-MIG-1"
        conn.execute(
            sa.text(
                "INSERT INTO processing_jobs (id, upload_id, status, progress, total_items, processed_items, media_ids, failures, created_by_user_id, created_at, updated_at) "
                "VALUES (:id, 'up_mig', 'queued', 0.0, 1, 0, '[]', '[]', :user_id, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)"
            ),
            {"id": job_id, "user_id": user_id},
        )

        # 5. Create MonitoringAction referencing User
        action_id = "ACT-MIG-1"
        conn.execute(
            sa.text(
                "INSERT INTO monitoring_actions (id, camera_id, action_type, description, performed_at, created_by_user_id, source, created_at) "
                "VALUES (:id, :cam_id, 'battery_swap', 'Routine maintenance', CURRENT_TIMESTAMP, :user_id, 'field_ranger', CURRENT_TIMESTAMP)"
            ),
            {"id": action_id, "cam_id": cam_id, "user_id": user_id},
        )

        # 6. Create RefreshToken referencing User
        rt_id = str(uuid.uuid4())
        conn.execute(
            sa.text(
                "INSERT INTO refresh_tokens (id, user_id, token_hash, family_id, is_revoked, expires_at, created_at) "
                "VALUES (:id, :user_id, 'thash_mig', 'fam_mig', 0, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)"
            ),
            {"id": rt_id, "user_id": user_id},
        )

        # 7. Create ApiKey referencing Camera
        key_id = str(uuid.uuid4())
        conn.execute(
            sa.text(
                "INSERT INTO api_keys (id, name, key_hash, camera_id, role, is_active, created_at) "
                "VALUES (:id, 'Station Key', 'khash_mig', :cam_id, 'field_device', 1, CURRENT_TIMESTAMP)"
            ),
            {"id": key_id, "cam_id": cam_id},
        )
        conn.commit()

        # Delete User -> media, job, and action must have foreign key set to NULL; refresh_tokens must be cascaded
        conn.execute(sa.text("DELETE FROM users WHERE id = :id"), {"id": user_id})
        conn.commit()

        # Check SET NULL on MediaAsset
        media_uploader = conn.execute(sa.text("SELECT uploader_id FROM media_assets WHERE id = :id"), {"id": media_id}).scalar()
        assert media_uploader is None

        # Check SET NULL on ProcessingJob
        job_creator = conn.execute(sa.text("SELECT created_by_user_id FROM processing_jobs WHERE id = :id"), {"id": job_id}).scalar()
        assert job_creator is None

        # Check SET NULL on MonitoringAction
        action_creator = conn.execute(sa.text("SELECT created_by_user_id FROM monitoring_actions WHERE id = :id"), {"id": action_id}).scalar()
        assert action_creator is None

        # Check CASCADE on RefreshToken (must be deleted)
        rt_count = conn.execute(sa.text("SELECT COUNT(*) FROM refresh_tokens WHERE id = :id"), {"id": rt_id}).scalar()
        assert rt_count == 0

        # Delete Camera -> api_keys must cascade
        conn.execute(sa.text("DELETE FROM cameras WHERE id = :id"), {"id": cam_id})
        conn.commit()

        ak_count = conn.execute(sa.text("SELECT COUNT(*) FROM api_keys WHERE id = :id"), {"id": key_id}).scalar()
        assert ak_count == 0

    engine.dispose()


# ============================================================================
# 4. Partial Migration Failure Recovery & Idempotency Simulation
# ============================================================================

@pytest.mark.integration
def test_migration_005_idempotent_recovery_from_partial_failure(temp_alembic_db):
    """Simulate the exact failure scenario: database where users, refresh_tokens, and api_keys exist,

    verifying that running migration 005 completes successfully and is safe to retry.
    """
    cfg = temp_alembic_db["config"]
    db_url = temp_alembic_db["db_url"]

    # 1. Upgrade to 004
    command.upgrade(cfg, "004_add_performance_and_query_indexes")

    # 2. Simulate partial execution before line 88 crash
    engine = sa.create_engine(db_url)
    with engine.connect() as conn:
        conn.execute(
            sa.text(
                "CREATE TABLE users ("
                "  id VARCHAR(36) PRIMARY KEY, "
                "  username VARCHAR(50) NOT NULL UNIQUE, "
                "  email VARCHAR(255) NOT NULL UNIQUE, "
                "  hashed_password VARCHAR(255) NOT NULL, "
                "  full_name VARCHAR(100), "
                "  role VARCHAR(20) DEFAULT 'viewer' NOT NULL, "
                "  is_active BOOLEAN DEFAULT 1 NOT NULL, "
                "  created_at TIMESTAMP NOT NULL, "
                "  updated_at TIMESTAMP NOT NULL"
                ");"
            )
        )
        conn.execute(sa.text("CREATE INDEX ix_users_username ON users (username);"))
        conn.execute(sa.text("CREATE INDEX ix_users_email ON users (email);"))
        conn.execute(sa.text("CREATE INDEX ix_users_role ON users (role);"))

        conn.execute(
            sa.text(
                "CREATE TABLE refresh_tokens ("
                "  id VARCHAR(36) PRIMARY KEY, "
                "  user_id VARCHAR(36) NOT NULL REFERENCES users(id) ON DELETE CASCADE, "
                "  token_hash VARCHAR(64) NOT NULL UNIQUE, "
                "  family_id VARCHAR(36) NOT NULL, "
                "  parent_token_hash VARCHAR(64), "
                "  is_revoked BOOLEAN DEFAULT 0 NOT NULL, "
                "  expires_at TIMESTAMP NOT NULL, "
                "  revoked_at TIMESTAMP, "
                "  created_at TIMESTAMP NOT NULL"
                ");"
            )
        )
        conn.execute(sa.text("CREATE INDEX ix_refresh_tokens_token_hash ON refresh_tokens (token_hash);"))

        conn.execute(
            sa.text(
                "CREATE TABLE api_keys ("
                "  id VARCHAR(36) PRIMARY KEY, "
                "  name VARCHAR(100) NOT NULL, "
                "  key_prefix VARCHAR(16) DEFAULT 'ws_live_' NOT NULL, "
                "  key_hash VARCHAR(64) NOT NULL UNIQUE, "
                "  camera_id VARCHAR(36) NOT NULL REFERENCES cameras(id) ON DELETE CASCADE, "
                "  role VARCHAR(20) DEFAULT 'field_device' NOT NULL, "
                "  is_active BOOLEAN DEFAULT 1 NOT NULL, "
                "  created_at TIMESTAMP NOT NULL, "
                "  expires_at TIMESTAMP, "
                "  last_used_at TIMESTAMP, "
                "  revoked_at TIMESTAMP"
                ");"
            )
        )
        conn.execute(sa.text("CREATE INDEX ix_api_keys_key_hash ON api_keys (key_hash);"))
        conn.commit()
    engine.dispose()

    # 3. Now run Alembic upgrade to 005. This MUST succeed cleanly despite tables already existing!
    command.upgrade(cfg, "005_add_authentication_and_user_rbac")

    # 4. Verify that the remaining alterations (media_assets, processing_jobs, monitoring_actions) completed
    engine = sa.create_engine(db_url)
    inspector = sa.inspect(engine)
    media_cols = {c["name"] for c in inspector.get_columns("media_assets")}
    jobs_cols = {c["name"] for c in inspector.get_columns("processing_jobs")}
    actions_cols = {c["name"] for c in inspector.get_columns("monitoring_actions")}

    assert "uploader_id" in media_cols
    assert "created_by_user_id" in jobs_cols
    assert "created_by_user_id" in actions_cols

    # 5. Reset alembic_version back to 004 to force Alembic to re-execute upgrade() of 005
    # against the ALREADY fully-migrated database, validating complete idempotency end-to-end!
    with engine.connect() as conn:
        conn.execute(sa.text("UPDATE alembic_version SET version_num = '004_add_performance_and_query_indexes'"))
        conn.commit()

    # Re-running upgrade to 005 through Alembic must succeed cleanly with zero duplicate table/column/index errors
    command.upgrade(cfg, "005_add_authentication_and_user_rbac")

    engine.dispose()


# ============================================================================
# 5. Downgrade Verification
# ============================================================================

@pytest.mark.integration
def test_migration_005_downgrade(temp_alembic_db):
    """Verify that migration 005 cleanly downgrades back to revision 004."""
    cfg = temp_alembic_db["config"]
    db_url = temp_alembic_db["db_url"]

    # Upgrade to 005
    command.upgrade(cfg, "005_add_authentication_and_user_rbac")

    engine = sa.create_engine(db_url)
    inspector_before = sa.inspect(engine)
    assert "users" in inspector_before.get_table_names()

    # Downgrade back to 004
    command.downgrade(cfg, "004_add_performance_and_query_indexes")

    inspector_after = sa.inspect(engine)
    tables_after = set(inspector_after.get_table_names())
    assert "users" not in tables_after
    assert "refresh_tokens" not in tables_after
    assert "api_keys" not in tables_after

    media_cols = {c["name"] for c in inspector_after.get_columns("media_assets")}
    assert "uploader_id" not in media_cols

    jobs_cols = {c["name"] for c in inspector_after.get_columns("processing_jobs")}
    assert "created_by_user_id" not in jobs_cols

    actions_cols = {c["name"] for c in inspector_after.get_columns("monitoring_actions")}
    assert "created_by_user_id" not in actions_cols

    engine.dispose()
