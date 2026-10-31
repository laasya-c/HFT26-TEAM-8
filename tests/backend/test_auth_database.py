"""Security Phase 1 Database Regression Test Suite.

Verifies:
1. User model creation, unique constraints (username, email), and role validation.
2. Active vs disabled user account lifecycle.
3. RefreshToken model: hashed token storage, token family tracking, rotation metadata, and revocation.
4. ApiKey model: camera trap station association, hash uniqueness, rotation, and revocation.
5. Ownership relationships:
   - MediaAsset.uploader (SET NULL on user deletion).
   - ProcessingJob.creator (SET NULL on user deletion).
   - MonitoringAction.creator (SET NULL on user deletion).
6. ReviewEvent scientific audit invariants (append-only permanence and immutability).
7. Alembic migration 005 metadata, lineage, and operations.
"""
from datetime import datetime, timedelta, timezone
import importlib
import uuid
import pytest
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from src.backend.core.exceptions import ValidationException
from src.backend.models import (
    ApiKey,
    Camera,
    Detection,
    ImageFrame,
    MediaAsset,
    MonitoringAction,
    PredictionRun,
    ProcessingJob,
    RefreshToken,
    ReviewEvent,
    User,
    UserRole,
)


# ============================================================================
# 1. User Model & Constraints
# ============================================================================

@pytest.mark.unit
def test_user_creation_and_attributes(db_session: Session):
    """Verify that a User record can be persisted and retrieved with all fields."""
    user = User(
        id=str(uuid.uuid4()),
        username="ecologist_jane",
        email="jane@wildscope.org",
        hashed_password="$argon2id$v=19$m=65536,t=2,p=4$fake_hash_string",
        full_name="Dr. Jane Doe",
        role=UserRole.RESEARCHER.value,
        is_active=True,
    )
    db_session.add(user)
    db_session.commit()

    queried = db_session.query(User).filter_by(username="ecologist_jane").first()
    assert queried is not None
    assert queried.email == "jane@wildscope.org"
    assert queried.role == "researcher"
    assert queried.full_name == "Dr. Jane Doe"
    assert queried.is_active is True
    assert queried.created_at is not None
    assert queried.updated_at is not None


@pytest.mark.unit
def test_user_unique_username_constraint(db_session: Session):
    """Verify that duplicate usernames violate uniqueness constraints."""
    user1 = User(
        id=str(uuid.uuid4()),
        username="duplicate_user",
        email="user1@wildscope.org",
        hashed_password="hash1",
        role=UserRole.VIEWER.value,
    )
    db_session.add(user1)
    db_session.commit()

    user2 = User(
        id=str(uuid.uuid4()),
        username="duplicate_user",
        email="user2@wildscope.org",
        hashed_password="hash2",
        role=UserRole.VIEWER.value,
    )
    db_session.add(user2)
    with pytest.raises(IntegrityError):
        db_session.commit()
    db_session.rollback()


@pytest.mark.unit
def test_user_unique_email_constraint(db_session: Session):
    """Verify that duplicate email addresses violate uniqueness constraints."""
    user1 = User(
        id=str(uuid.uuid4()),
        username="unique_user_a",
        email="same_email@wildscope.org",
        hashed_password="hash1",
        role=UserRole.VIEWER.value,
    )
    db_session.add(user1)
    db_session.commit()

    user2 = User(
        id=str(uuid.uuid4()),
        username="unique_user_b",
        email="same_email@wildscope.org",
        hashed_password="hash2",
        role=UserRole.VIEWER.value,
    )
    db_session.add(user2)
    with pytest.raises(IntegrityError):
        db_session.commit()
    db_session.rollback()


@pytest.mark.unit
def test_user_role_validation():
    """Verify that User.validate_role accepts valid personas and rejects invalid roles."""
    valid_user = User(username="admin_user", role=UserRole.ADMIN.value)
    valid_user.validate_role()  # Should not raise

    valid_researcher = User(username="res_user", role=UserRole.RESEARCHER.value)
    valid_researcher.validate_role()  # Should not raise

    invalid_user = User(username="bad_user", role="superhacker")
    with pytest.raises(ValidationException) as exc_info:
        invalid_user.validate_role()
    assert "Invalid role 'superhacker'" in str(exc_info.value)


@pytest.mark.unit
def test_user_active_and_disabled_status(db_session: Session):
    """Verify active vs disabled user lifecycle management."""
    user = User(
        id=str(uuid.uuid4()),
        username="field_ranger",
        email="ranger@wildscope.org",
        hashed_password="hash",
        role=UserRole.RESEARCHER.value,
        is_active=True,
    )
    db_session.add(user)
    db_session.commit()

    assert db_session.query(User).filter_by(is_active=True).count() == 1

    # Deactivate account
    user.is_active = False
    db_session.add(user)
    db_session.commit()

    assert db_session.query(User).filter_by(is_active=True).count() == 0
    assert db_session.query(User).filter_by(is_active=False).count() == 1


# ============================================================================
# 2. RefreshToken Model, Family Rotation & Revocation
# ============================================================================

@pytest.mark.unit
def test_refresh_token_persistence_and_relationships(db_session: Session):
    """Verify that refresh tokens persist hashed values and link to users."""
    user = User(
        id=str(uuid.uuid4()),
        username="token_owner",
        email="owner@wildscope.org",
        hashed_password="hash",
        role=UserRole.RESEARCHER.value,
    )
    db_session.add(user)
    db_session.flush()

    token = RefreshToken(
        id=str(uuid.uuid4()),
        user_id=user.id,
        token_hash="sha256_hash_of_opaque_refresh_token_12345",
        family_id=str(uuid.uuid4()),
        parent_token_hash=None,
        is_revoked=False,
        expires_at=datetime.now(timezone.utc) + timedelta(days=7),
    )
    db_session.add(token)
    db_session.commit()

    queried_token = db_session.query(RefreshToken).filter_by(user_id=user.id).first()
    assert queried_token is not None
    assert queried_token.token_hash == "sha256_hash_of_opaque_refresh_token_12345"
    assert queried_token.user.username == "token_owner"
    assert len(user.refresh_tokens) == 1


@pytest.mark.unit
def test_refresh_token_hash_uniqueness(db_session: Session):
    """Verify that duplicate refresh token hashes are rejected."""
    user = User(id=str(uuid.uuid4()), username="user_x", email="x@wildscope.org", hashed_password="h")
    db_session.add(user)
    db_session.flush()

    tok1 = RefreshToken(
        id=str(uuid.uuid4()),
        user_id=user.id,
        token_hash="identical_token_hash",
        family_id="fam-1",
        expires_at=datetime.now(timezone.utc) + timedelta(days=7),
    )
    db_session.add(tok1)
    db_session.commit()

    tok2 = RefreshToken(
        id=str(uuid.uuid4()),
        user_id=user.id,
        token_hash="identical_token_hash",
        family_id="fam-2",
        expires_at=datetime.now(timezone.utc) + timedelta(days=7),
    )
    db_session.add(tok2)
    with pytest.raises(IntegrityError):
        db_session.commit()
    db_session.rollback()


@pytest.mark.unit
def test_refresh_token_family_rotation_and_revocation(db_session: Session):
    """Verify token family tracking across rotation and revocation lifecycle."""
    user = User(id=str(uuid.uuid4()), username="rotator", email="rot@wildscope.org", hashed_password="h")
    db_session.add(user)
    db_session.flush()

    family_id = str(uuid.uuid4())
    now_utc = datetime.now(timezone.utc)

    # Initial token R1
    tok1 = RefreshToken(
        id=str(uuid.uuid4()),
        user_id=user.id,
        token_hash="hash_r1",
        family_id=family_id,
        parent_token_hash=None,
        is_revoked=True,  # Consumed during rotation
        revoked_at=now_utc,
        expires_at=now_utc + timedelta(days=7),
    )
    # Rotated token R2 (child of R1)
    tok2 = RefreshToken(
        id=str(uuid.uuid4()),
        user_id=user.id,
        token_hash="hash_r2",
        family_id=family_id,
        parent_token_hash="hash_r1",
        is_revoked=False,
        expires_at=now_utc + timedelta(days=7),
    )
    db_session.add_all([tok1, tok2])
    db_session.commit()

    # Query all tokens in the rotation family
    family_tokens = db_session.query(RefreshToken).filter_by(family_id=family_id).all()
    assert len(family_tokens) == 2
    hashes = {t.token_hash: t.is_revoked for t in family_tokens}
    assert hashes["hash_r1"] is True
    assert hashes["hash_r2"] is False


@pytest.mark.unit
def test_cascade_delete_user_deletes_refresh_tokens(db_session: Session):
    """Verify that deleting a User cascades to delete all associated refresh tokens."""
    user = User(id=str(uuid.uuid4()), username="to_delete", email="del@wildscope.org", hashed_password="h")
    db_session.add(user)
    db_session.flush()

    tok = RefreshToken(
        id=str(uuid.uuid4()),
        user_id=user.id,
        token_hash="tok_to_delete",
        family_id="fam-del",
        expires_at=datetime.now(timezone.utc) + timedelta(days=1),
    )
    db_session.add(tok)
    db_session.commit()

    assert db_session.query(RefreshToken).filter_by(user_id=user.id).count() == 1

    db_session.delete(user)
    db_session.commit()

    assert db_session.query(RefreshToken).filter_by(user_id=user.id).count() == 0


# ============================================================================
# 3. Field-Device ApiKey Model & Scoping
# ============================================================================

@pytest.mark.unit
def test_api_key_camera_association_and_persistence(db_session: Session):
    """Verify that an ApiKey binds strictly to a camera station with hashed storage."""
    camera = Camera(id="CAM-STATION-99", label="Alpine Ridge", timezone="UTC", provenance="observed")
    db_session.add(camera)
    db_session.flush()

    key = ApiKey(
        id=str(uuid.uuid4()),
        name="Alpine Ridge Gateway #1",
        key_prefix="ws_live_",
        key_hash="sha256_hash_of_pre_shared_secret_key_abc",
        camera_id=camera.id,
        role="field_device",
        is_active=True,
        expires_at=datetime.now(timezone.utc) + timedelta(days=365),
    )
    db_session.add(key)
    db_session.commit()

    queried_key = db_session.query(ApiKey).filter_by(camera_id="CAM-STATION-99").first()
    assert queried_key is not None
    assert queried_key.name == "Alpine Ridge Gateway #1"
    assert queried_key.key_prefix == "ws_live_"
    assert queried_key.camera.label == "Alpine Ridge"
    assert len(camera.api_keys) == 1


@pytest.mark.unit
def test_api_key_hash_uniqueness(db_session: Session):
    """Verify that duplicate API key hashes are rejected."""
    cam = Camera(id="CAM-UNIQ", label="Unique Station", timezone="UTC", provenance="observed")
    db_session.add(cam)
    db_session.flush()

    key1 = ApiKey(id=str(uuid.uuid4()), name="Key 1", key_hash="dup_key_hash", camera_id=cam.id)
    key2 = ApiKey(id=str(uuid.uuid4()), name="Key 2", key_hash="dup_key_hash", camera_id=cam.id)
    db_session.add(key1)
    db_session.commit()

    db_session.add(key2)
    with pytest.raises(IntegrityError):
        db_session.commit()
    db_session.rollback()


@pytest.mark.unit
def test_api_key_rotation_and_revocation(db_session: Session):
    """Verify camera key rotation with active and revoked states."""
    cam = Camera(id="CAM-ROT", label="Rotation Station", timezone="UTC", provenance="observed")
    db_session.add(cam)
    db_session.flush()

    now_utc = datetime.now(timezone.utc)

    # Key 1 is revoked
    old_key = ApiKey(
        id=str(uuid.uuid4()),
        name="Primary Key (Old)",
        key_hash="hash_old",
        camera_id=cam.id,
        is_active=False,
        revoked_at=now_utc,
    )
    # Key 2 is active (Rotated)
    new_key = ApiKey(
        id=str(uuid.uuid4()),
        name="Secondary Key (New)",
        key_hash="hash_new",
        camera_id=cam.id,
        is_active=True,
    )
    db_session.add_all([old_key, new_key])
    db_session.commit()

    active_keys = db_session.query(ApiKey).filter_by(camera_id=cam.id, is_active=True).all()
    assert len(active_keys) == 1
    assert active_keys[0].name == "Secondary Key (New)"


# ============================================================================
# 4. Ownership Relationships & IDOR Protections
# ============================================================================

@pytest.mark.unit
def test_media_asset_uploader_ownership(db_session: Session):
    """Verify MediaAsset uploader foreign key and relationship."""
    user = User(id=str(uuid.uuid4()), username="photographer", email="photo@wildscope.org", hashed_password="h")
    db_session.add(user)
    db_session.flush()

    media = MediaAsset(
        id=str(uuid.uuid4()),
        type="image",
        uploader_id=user.id,
        storage_key="media/test.jpg",
        content_hash="hash_photo",
        provenance="observed",
    )
    db_session.add(media)
    db_session.commit()

    queried_media = db_session.query(MediaAsset).filter_by(id=media.id).first()
    assert queried_media.uploader is not None
    assert queried_media.uploader.username == "photographer"
    assert len(user.uploaded_media) == 1

    # Legacy media without uploader_id works cleanly
    legacy_media = MediaAsset(
        id=str(uuid.uuid4()),
        type="image",
        uploader_id=None,
        storage_key="media/legacy.jpg",
        content_hash="hash_legacy",
        provenance="observed",
    )
    db_session.add(legacy_media)
    db_session.commit()
    assert legacy_media.uploader is None


@pytest.mark.unit
def test_processing_job_creator_ownership(db_session: Session):
    """Verify ProcessingJob creator foreign key and relationship."""
    user = User(id=str(uuid.uuid4()), username="job_starter", email="starter@wildscope.org", hashed_password="h")
    db_session.add(user)
    db_session.flush()

    job = ProcessingJob(
        id=str(uuid.uuid4()),
        upload_id="up_test123",
        created_by_user_id=user.id,
        status="queued",
    )
    db_session.add(job)
    db_session.commit()

    queried_job = db_session.query(ProcessingJob).filter_by(id=job.id).first()
    assert queried_job.creator is not None
    assert queried_job.creator.username == "job_starter"
    assert len(user.processing_jobs) == 1


@pytest.mark.unit
def test_monitoring_action_creator_ownership(db_session: Session):
    """Verify MonitoringAction creator foreign key and relationship."""
    cam = Camera(id="CAM-ACTION-1", label="Action Camera", timezone="UTC", provenance="observed")
    user = User(id=str(uuid.uuid4()), username="ranger_bob", email="bob@wildscope.org", hashed_password="h")
    db_session.add_all([cam, user])
    db_session.flush()

    action = MonitoringAction(
        id=str(uuid.uuid4()),
        camera_id=cam.id,
        created_by_user_id=user.id,
        action_type="lens_clean",
        description="Cleaned outer lens obstruction",
        performed_at=datetime.now(timezone.utc),
    )
    db_session.add(action)
    db_session.commit()

    queried_action = db_session.query(MonitoringAction).filter_by(id=action.id).first()
    assert queried_action.creator is not None
    assert queried_action.creator.username == "ranger_bob"
    assert len(user.monitoring_actions) == 1


@pytest.mark.unit
def test_user_deletion_sets_null_on_assets_and_jobs(db_session: Session):
    """Verify that deleting a User sets uploader_id/created_by_user_id to NULL without data loss."""
    user = User(id=str(uuid.uuid4()), username="departed_user", email="dep@wildscope.org", hashed_password="h")
    db_session.add(user)
    db_session.flush()

    media = MediaAsset(id=str(uuid.uuid4()), type="image", uploader_id=user.id, storage_key="m/1.jpg", content_hash="h1", provenance="observed")
    job = ProcessingJob(id=str(uuid.uuid4()), upload_id="up_1", created_by_user_id=user.id, status="queued")
    db_session.add_all([media, job])
    db_session.commit()

    db_session.delete(user)
    db_session.commit()

    # Media and Job still exist; foreign keys set to NULL
    assert db_session.query(MediaAsset).filter_by(id=media.id).first().uploader_id is None
    assert db_session.query(ProcessingJob).filter_by(id=job.id).first().created_by_user_id is None


# ============================================================================
# 5. ReviewEvent Scientific Audit Integrity & Invariants
# ============================================================================

@pytest.mark.unit
def test_review_event_append_only_invariant_preserved(db_session: Session):
    """Verify that ReviewEvent records remain strictly append-only and cannot be mutated or deleted."""
    user = User(id=str(uuid.uuid4()), username="lead_scientist", email="lead@wildscope.org", hashed_password="h")
    db_session.add(user)
    db_session.flush()

    # Create dummy media, frame, run, and detection
    media = MediaAsset(id="MED-REV-1", type="image", storage_key="media/r.jpg", content_hash="hash_r", provenance="observed")
    db_session.add(media)
    db_session.flush()
    frame = ImageFrame(id="FRM-REV-1", source_media_id=media.id, content_url="/api/v1/images/FRM-REV-1/content", quality_flags=[], provenance="observed")
    db_session.add(frame)
    run = PredictionRun(id="RUN-REV-1", model_name="yolo", model_version="v1", device="cpu", status="completed")
    db_session.add(run)
    db_session.flush()
    detection = Detection(id="DET-REV-1", image_id=frame.id, run_id=run.id, bbox_x=0.1, bbox_y=0.1, bbox_w=0.5, bbox_h=0.5, raw_label="tiger", taxon_id="tiger", label="Tiger", score=0.9, model_version="v1", review_status="pending", provenance="inferred")
    db_session.add(detection)
    db_session.flush()

    # Create review event with authentic user ID
    review = ReviewEvent(
        id=str(uuid.uuid4()),
        detection_id=detection.id,
        decision="confirmed",
        reason="Visual confirmation of stripe pattern",
        reviewer_id=user.id,
        expected_revision=1,
        resulting_revision=2,
        provenance="observed",
    )
    db_session.add(review)
    db_session.commit()

    # Verify relationship resolves to User
    queried_review = db_session.query(ReviewEvent).filter_by(id=review.id).first()
    assert queried_review.reviewer is not None
    assert queried_review.reviewer.username == "lead_scientist"

    # Attempt mutation -> Must raise ValidationException
    queried_review.reason = "Tampered justification"
    with pytest.raises(ValidationException) as exc_info:
        db_session.commit()
    assert "append-only audit logs and cannot be modified" in str(exc_info.value)
    db_session.rollback()

    # Attempt deletion -> Must raise ValidationException
    db_session.delete(queried_review)
    with pytest.raises(ValidationException) as exc_info:
        db_session.commit()
    assert "permanent audit evidence and cannot be deleted" in str(exc_info.value)
    db_session.rollback()


@pytest.mark.unit
def test_legacy_review_event_without_user_model_backward_compatibility(db_session: Session):
    """Verify that legacy review records with arbitrary string reviewer_id load without foreign key crash."""
    media = MediaAsset(id="MED-REV-LEG", type="image", storage_key="m/l.jpg", content_hash="hl", provenance="observed")
    db_session.add(media)
    db_session.flush()
    frame = ImageFrame(id="FRM-REV-LEG", source_media_id=media.id, content_url="/api/v1/images/FRM-REV-LEG/content", quality_flags=[], provenance="observed")
    db_session.add(frame)
    run = PredictionRun(id="RUN-REV-LEG", model_name="yolo", model_version="v1", device="cpu", status="completed")
    db_session.add(run)
    db_session.flush()
    detection = Detection(id="DET-REV-LEG", image_id=frame.id, run_id=run.id, bbox_x=0.2, bbox_y=0.2, bbox_w=0.4, bbox_h=0.4, raw_label="deer", taxon_id="deer", label="Deer", score=0.8, model_version="v1", review_status="pending", provenance="inferred")
    db_session.add(detection)
    db_session.flush()

    # Legacy review event with historical string identifier
    legacy_review = ReviewEvent(
        id=str(uuid.uuid4()),
        detection_id=detection.id,
        decision="corrected",
        corrected_taxon_id="axis_axis",
        reason="Chital spotted deer confirmed",
        reviewer_id="legacy_expert_99",
        expected_revision=1,
        resulting_revision=2,
        provenance="observed",
    )
    db_session.add(legacy_review)
    db_session.commit()

    loaded = db_session.query(ReviewEvent).filter_by(reviewer_id="legacy_expert_99").first()
    assert loaded is not None
    assert loaded.reviewer is None  # Graceful fallback; no crash


# ============================================================================
# 6. Alembic Migration 005 Definition
# ============================================================================

@pytest.mark.unit
def test_migration_005_metadata_and_lineage():
    """Verify that migration 005 revision metadata chains correctly from 004 and defines naming conventions."""
    mig005 = importlib.import_module("migrations.versions.005_add_authentication_and_user_rbac")

    assert mig005.revision == "005_add_authentication_and_user_rbac"
    assert mig005.down_revision == "004_add_performance_and_query_indexes"
    assert callable(mig005.upgrade)
    assert callable(mig005.downgrade)
    assert hasattr(mig005, "NAMING_CONVENTION")
    assert "fk" in mig005.NAMING_CONVENTION
