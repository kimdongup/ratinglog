import html
import io
import os
import re
import uuid

import pytest
from flask_migrate import upgrade
from sqlalchemy import create_engine, text

from ratinglog import create_app
from ratinglog.extensions import db
from ratinglog.models import User

PASSWORD = "correct-horse-battery-123"
TABLE = b"age,sex,smoking,duration,rate\n30,F,non_smoker,0,0.0005\n31,F,non_smoker,0,0.0006\n"


@pytest.fixture()
def app(tmp_path):
    test_url = os.getenv("TEST_DATABASE_URL")
    admin_engine, schema = None, None
    engine_options = {"pool_pre_ping": True}
    if test_url:
        if not test_url.startswith("postgresql+psycopg://"):
            raise ValueError("TEST_DATABASE_URL must be a dedicated PostgreSQL test database.")
        schema = "test_" + uuid.uuid4().hex
        admin_engine = create_engine(test_url)
        with admin_engine.begin() as connection:
            connection.execute(text(f"CREATE SCHEMA {schema}"))
        engine_options["connect_args"] = {"options": "-csearch_path=" + schema}
    app = create_app(
        {
            "TESTING": True,
            "SECRET_KEY": "test-only-secret-32-characters-long",
            "SQLALCHEMY_DATABASE_URI": test_url or "sqlite:///" + str(tmp_path / "test.sqlite"),
            "SQLALCHEMY_ENGINE_OPTIONS": engine_options,
            "RATELIMIT_ENABLED": False,
            "TRUSTED_HOSTS": ["localhost"],
            "PRODUCTION": False,
            "SESSION_COOKIE_SECURE": False,
        }
    )
    with app.app_context():
        upgrade()
        for role, email in [
            ("admin", "admin@example.com"),
            ("editor", "editor@example.com"),
            ("editor", "other@example.com"),
            ("reviewer", "reviewer@example.com"),
            ("viewer", "viewer@example.com"),
        ]:
            user = User(email=email, name=email.split("@")[0], role=role)
            user.set_password(PASSWORD)
            db.session.add(user)
        db.session.commit()
    yield app
    with app.app_context():
        db.session.remove()
        db.engine.dispose()
    if admin_engine:
        with admin_engine.begin() as connection:
            connection.execute(text(f"DROP SCHEMA {schema} CASCADE"))
        admin_engine.dispose()


@pytest.fixture()
def client(app):
    return app.test_client()


def csrf(client, path="/login"):
    response = client.get(path)
    assert response.status_code == 200, response.data.decode()
    match = re.search(r'name="csrf_token"[^>]*value="([^"]+)"', response.data.decode())
    assert match, response.data.decode()
    return html.unescape(match.group(1))


def login(client, who="editor"):
    token = csrf(client)
    response = client.post(
        "/login", data={"csrf_token": token, "email": who + "@example.com", "password": PASSWORD}
    )
    assert response.status_code == 302, response.data.decode()
    return response


def logout(client):
    return client.post("/logout", data={"csrf_token": csrf(client, "/")})


def create_rate(client, code="MORT-001", table=TABLE, **overrides):
    data = {
        "csrf_token": csrf(client, "/rates/new"),
        "code": code,
        "title": "검증용 사망률",
        "kind": "mortality",
        "category": "생명보험",
        "priority": "3",
        "granted": "APP-001",
        "source": "합성 예제",
        "definition": "테스트용 정의",
        "comments": "",
        "sql_note": "",
        "effective_from": "2025-01-01",
        "effective_to": "",
        "data_type": "table",
        "unit": "probability",
        "change_reason": "최초 등록",
        "version": "0",
    }
    if table is not None:
        data["table_file"] = (io.BytesIO(table), "table.csv")
    data.update(overrides)
    return client.post("/rates/new", data=data, content_type="multipart/form-data")


def lock(app, record_id=1):
    from ratinglog.models import RateRecord

    with app.app_context():
        return db.session.get(RateRecord, record_id).lock_version


def action(client, app, name, record_id=1, version=None):
    return client.post(
        f"/rates/{record_id}/actions/{name}",
        data={
            "csrf_token": csrf(client, f"/rates/{record_id}"),
            "version": lock(app, record_id) if version is None else version,
            "reason": "검토 및 처리 사유",
        },
    )


def edit_rate(client, app, record_id=1, **overrides):
    from ratinglog.models import RateRevision
    from ratinglog.services import FIELDS

    with app.app_context():
        revision = db.session.scalar(
            db.select(RateRevision)
            .where(RateRevision.record_id == record_id)
            .order_by(RateRevision.number.desc())
        )
        data = {key: str(getattr(revision, key) or "") for key in FIELDS}
        data["code"] = revision.record.code
        data["version"] = str(revision.record.lock_version)
    data["csrf_token"] = csrf(client, f"/rates/{record_id}/edit")
    data["change_reason"] = "내용 개정"
    data.update(overrides)
    return client.post(f"/rates/{record_id}/edit", data=data, content_type="multipart/form-data")


def publish(client, app):
    login(client)
    assert create_rate(client).status_code == 302
    assert action(client, app, "submit").status_code == 302
    logout(client)
    login(client, "reviewer")
    assert action(client, app, "approve").status_code == 302
    logout(client)
