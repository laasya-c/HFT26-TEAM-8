"""Pytest Configuration and Test Fixtures.

Provides:
- In-memory SQLite test database engine with foreign key pragmas.
- FastAPI TestClient instance with overridden database session.
"""
from typing import Any, Generator
import uuid
import pytest
from starlette.testclient import TestClient

from src.backend.config import settings
from src.backend.core.security import create_access_token, hash_password, generate_api_key
from src.backend.main import app
from src.backend.models.auth import User, UserRole, ApiKey

try:
    from sqlalchemy import create_engine, event
    from sqlalchemy.engine import Engine
    from sqlalchemy.orm import sessionmaker, Session
    from sqlalchemy.pool import StaticPool
    from src.backend.db.base import Base
    from src.backend.db.session import get_db
    import src.backend.models
    HAS_DB = True
except ImportError:
    HAS_DB = False


if HAS_DB:
    # Use isolated in-memory SQLite with StaticPool for testing
    TEST_DATABASE_URL = "sqlite:///:memory:"

    test_engine = create_engine(
        TEST_DATABASE_URL,
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )

    @event.listens_for(Engine, "connect")
    def set_test_sqlite_pragmas(dbapi_connection: Any, connection_record: Any) -> None:
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON;")
        cursor.close()

    TestingSessionLocal = sessionmaker(
        autocommit=False,
        autoflush=False,
        bind=test_engine,
        expire_on_commit=False,
    )

    # Patch global sessionmaker and engine so background tasks and helpers connect to test_engine
    import src.backend.db.session as db_session_module
    db_session_module.SessionLocal = TestingSessionLocal
    db_session_module.engine = test_engine

    @pytest.fixture(scope="session", autouse=True)
    def setup_test_database():
        """Create tables in in-memory test database for the session."""
        Base.metadata.create_all(bind=test_engine)
        yield
        Base.metadata.drop_all(bind=test_engine)

    @pytest.fixture(autouse=True)
    def clean_database():
        """Ensure database tables are completely clean before each test, and cleaned after."""
        with test_engine.begin() as conn:
            for table in reversed(Base.metadata.sorted_tables):
                conn.execute(table.delete())
            # Initialize singleton dataset revision baseline (F20)
            from src.backend.models.review import DatasetRevision
            conn.execute(
                DatasetRevision.__table__.insert().values(
                    id=1,
                    current_revision=1,
                    change_reason="Initial test baseline revision",
                )
            )
        yield
        with test_engine.begin() as conn:
            for table in reversed(Base.metadata.sorted_tables):
                conn.execute(table.delete())

    @pytest.fixture
    def db_session() -> Generator[Session, None, None]:
        """Provides a clean database session for test execution."""
        session = TestingSessionLocal()
        try:
            yield session
        finally:
            session.rollback()
            session.close()

    @pytest.fixture
    def client(db_session: Session) -> Generator[TestClient, None, None]:
        """TestClient with overridden get_db dependency."""
        def override_get_db():
            yield db_session

        app.dependency_overrides[get_db] = override_get_db
        with TestClient(app) as test_client:
            yield test_client
        app.dependency_overrides.clear()

    # ========================================================================
    # Reusable RBAC & Authentication Fixtures for Security Compliance
    # ========================================================================

    TEST_USER_PASSWORD = "StrongTestPassword123!"

    def create_test_user(
        db_session: Session,
        role: str = "researcher",
        username: str = None,
        email: str = None,
        user_id: str = None,
        full_name: str = None,
    ) -> User:
        """Helper to create and persist a test user in the active database session."""
        uid = user_id or str(uuid.uuid4())
        uname = username or f"{role}_{uid[:8]}"
        uemail = email or f"{uname}@wildscope.org"
        user = User(
            id=uid,
            username=uname,
            email=uemail,
            hashed_password=hash_password(TEST_USER_PASSWORD),
            full_name=full_name or f"Test {role.capitalize()}",
            role=role,
            is_active=True,
        )
        db_session.add(user)
        db_session.commit()
        db_session.refresh(user)
        return user

    def get_user_auth_headers(user: User) -> dict:
        """Helper generating Bearer authorization headers for a given User."""
        token = create_access_token(
            user_id=user.id,
            role=user.role,
            username=user.username,
            email=user.email,
        )
        return {"Authorization": f"Bearer {token}"}

    @pytest.fixture
    def admin_user(db_session: Session) -> User:
        """Administrator persona fixture."""
        return create_test_user(
            db_session,
            role=UserRole.ADMIN.value,
            username="admin_fixture_user",
            email="admin_fixture@wildscope.org",
        )

    @pytest.fixture
    def researcher_user(db_session: Session) -> User:
        """Primary researcher persona fixture."""
        return create_test_user(
            db_session,
            role=UserRole.RESEARCHER.value,
            username="researcher_fixture_user",
            email="researcher_fixture@wildscope.org",
        )

    @pytest.fixture
    def viewer_user(db_session: Session) -> User:
        """Public viewer persona fixture."""
        return create_test_user(
            db_session,
            role=UserRole.VIEWER.value,
            username="viewer_fixture_user",
            email="viewer_fixture@wildscope.org",
        )

    @pytest.fixture
    def admin_headers(admin_user: User) -> dict:
        """Authorization headers for admin_user."""
        return get_user_auth_headers(admin_user)

    @pytest.fixture
    def researcher_headers(researcher_user: User) -> dict:
        """Authorization headers for researcher_user."""
        return get_user_auth_headers(researcher_user)

    @pytest.fixture
    def viewer_headers(viewer_user: User) -> dict:
        """Authorization headers for viewer_user."""
        return get_user_auth_headers(viewer_user)

    @pytest.fixture
    def admin_client(db_session: Session, admin_headers: dict) -> Generator[TestClient, None, None]:
        """TestClient pre-authenticated as Administrator."""
        def override_get_db():
            yield db_session

        app.dependency_overrides[get_db] = override_get_db
        with TestClient(app, headers=admin_headers) as test_client:
            yield test_client
        app.dependency_overrides.clear()

    @pytest.fixture
    def researcher_client(db_session: Session, researcher_headers: dict) -> Generator[TestClient, None, None]:
        """TestClient pre-authenticated as Researcher."""
        def override_get_db():
            yield db_session

        app.dependency_overrides[get_db] = override_get_db
        with TestClient(app, headers=researcher_headers) as test_client:
            yield test_client
        app.dependency_overrides.clear()

    @pytest.fixture
    def viewer_client(db_session: Session, viewer_headers: dict) -> Generator[TestClient, None, None]:
        """TestClient pre-authenticated as Viewer."""
        def override_get_db():
            yield db_session

        app.dependency_overrides[get_db] = override_get_db
        with TestClient(app, headers=viewer_headers) as test_client:
            yield test_client
        app.dependency_overrides.clear()

    @pytest.fixture
    def auth_client_factory(db_session: Session) -> Generator[Any, None, None]:
        """Factory fixture returning a TestClient authenticated as any provided User."""
        clients = []
        def _create(user: User) -> TestClient:
            headers = get_user_auth_headers(user)
            def override_get_db():
                yield db_session
            app.dependency_overrides[get_db] = override_get_db
            tc = TestClient(app, headers=headers)
            clients.append(tc)
            return tc

        yield _create
        for tc in clients:
            try:
                tc.close()
            except Exception:
                pass
        app.dependency_overrides.clear()

    @pytest.fixture
    def device_client_factory(db_session: Session) -> Generator[Any, None, None]:
        """Factory fixture creating TestClients authenticated with a camera-bound API key."""
        clients = []
        def _create(camera_id: str, name: str = "Field Device Key") -> tuple[TestClient, str, ApiKey]:
            raw_key, key_hash = generate_api_key()
            api_key = ApiKey(
                id=str(uuid.uuid4()),
                name=name,
                key_hash=key_hash,
                camera_id=camera_id,
                role="field_device",
                is_active=True,
            )
            db_session.add(api_key)
            db_session.commit()
            db_session.refresh(api_key)

            def override_get_db():
                yield db_session

            app.dependency_overrides[get_db] = override_get_db
            test_client = TestClient(app, headers={"X-API-Key": raw_key})
            clients.append(test_client)
            return test_client, raw_key, api_key

        yield _create
        for tc in clients:
            try:
                tc.close()
            except Exception:
                pass
        app.dependency_overrides.clear()

    @pytest.fixture
    def anyio_backend() -> str:
        """Configures AnyIO to use the asyncio backend for asynchronous tests."""
        return "asyncio"

else:
    @pytest.fixture
    def client() -> Generator[TestClient, None, None]:
        """Fallback TestClient when SQLAlchemy is not installed."""
        with TestClient(app) as test_client:
            yield test_client

    @pytest.fixture
    def anyio_backend() -> str:
        """Fallback AnyIO backend fixture when SQLAlchemy is not installed."""
        return "asyncio"
