import os
import sys
import types

import pytest

pytestmark = pytest.mark.system


def _fake_redis_client():
    class _Client:
        def ping(self):
            return True

        def close(self):
            pass

    return _Client()


def test_health_and_version_endpoints(monkeypatch):
    fastapi = pytest.importorskip("fastapi")
    from fastapi.testclient import TestClient

    # Optional service deps; skip if not installed
    pytest.importorskip("sqlalchemy")
    pytest.importorskip("redis")
    pytest.importorskip("slowapi")

    # Skip DB migrations and stub connections
    os.environ["RUN_DB_MIGRATIONS"] = "0"

    # Create lightweight stubs to avoid loading real settings/.env and DB engine
    # Stub settings
    cfg_mod = types.ModuleType("services.shared.config")

    class _Obj:
        pass

    settings = _Obj()
    settings.DEBUG = False
    settings.ENVIRONMENT = "test"
    settings.SERVICE_VERSION = "test"
    settings.worker = _Obj()
    settings.worker.MAX_ANALYSIS_DURATION = 3600
    settings.api = _Obj()
    settings.api.MAX_REQUEST_SIZE = 50_000_000
    settings.api.RATE_LIMIT_PER_MINUTE = 60
    settings.api.RUNNING_JOB_STALE_SECONDS = 900
    settings.api.ALLOWED_HOSTS = ["*"]  # noqa
    settings.redis = _Obj()
    settings.redis.REDIS_URL = "redis://localhost:6379/0"
    cfg_mod.settings = settings
    sys.modules["services.shared.config"] = cfg_mod

    # Stub database module (avoid SQLAlchemy engine and env parsing)
    db_mod = types.ModuleType("services.shared.database")

    def _get_db():
        if False:
            yield None  # pragma: no cover

    db_mod.get_db = _get_db
    db_mod.check_db_connection = lambda: True
    sys.modules["services.shared.database"] = db_mod

    # Stub celery client
    celery_mod = types.ModuleType("services.shared.celery_client")

    class _Ctl:
        def ping(self, timeout=1.0):
            return [{"ok": True}]

    class _Celery:
        def __init__(self):
            self.control = _Ctl()

    celery_mod.celery_client = _Celery()
    sys.modules["services.shared.celery_client"] = celery_mod

    # Patch slowapi limiter to a no-op to avoid Redis storage initialization
    import slowapi as slowapi_mod

    class _DummyLimiter:
        def __init__(self, *args, **kwargs):
            pass

        def limit(self, *args, **kwargs):
            def _decorator(f):
                return f

            return _decorator

    monkeypatch.setattr(slowapi_mod, "Limiter", _DummyLimiter, raising=False)
    monkeypatch.setattr(slowapi_mod, "_rate_limit_exceeded_handler", lambda *a, **k: None, raising=False)

    # Patch Redis client
    import redis as redis_mod

    monkeypatch.setattr(redis_mod, "from_url", lambda *args, **kwargs: _fake_redis_client())

    # Import app after stubs/monkeypatches
    from services.api.app.main import app

    with TestClient(app) as client:
        r = client.get("/version")
        assert r.status_code == 200
        data = r.json()
        assert "api_version" in data
        assert "gardener_version" in data

        h = client.get("/health")
        assert h.status_code == 200
        health = h.json()
        assert "status" in health
        assert "database" in health and "redis" in health
