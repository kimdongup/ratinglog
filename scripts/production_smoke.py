"""Exercise production guards on isolated schemas and Redis key prefixes."""

import html
import os
import re
import secrets
import uuid

from flask_migrate import upgrade
from sqlalchemy import create_engine, text

from ratinglog import create_app
from ratinglog.extensions import db, limiter
from ratinglog.models import User


def run():
    database = os.environ["TEST_DATABASE_URL"]
    redis_url = os.environ["TEST_REDIS_URL"]
    schema = "production_smoke_" + uuid.uuid4().hex
    engine = create_engine(database)
    with engine.begin() as conn:
        conn.execute(text(f"CREATE SCHEMA {schema}"))
    app = None
    try:
        app = create_app(
            {
                "TESTING": True,
                "PRODUCTION": True,
                "SECRET_KEY": secrets.token_hex(32),
                "SQLALCHEMY_DATABASE_URI": database,
                "SQLALCHEMY_ENGINE_OPTIONS": {
                    "pool_pre_ping": True,
                    "connect_args": {"options": "-csearch_path=" + schema},
                },
                "TRUSTED_HOSTS": ["ratinglog.example"],
                "RATELIMIT_STORAGE_URI": redis_url,
                "RATELIMIT_KEY_PREFIX": schema,
                "RATELIMIT_ENABLED": True,
                "PROXY_HOPS": 1,
            }
        )
        password = secrets.token_urlsafe(24)
        with app.app_context():
            upgrade()
            user = User(email="smoke@example.com", name="Smoke", role="admin")
            user.set_password(password)
            db.session.add(user)
            db.session.commit()
        client = app.test_client()
        base = "https://ratinglog.example"
        assert client.get("/health/ready", base_url=base).status_code == 200
        assert client.get("/health/live", base_url="https://evil.example").status_code == 400
        response = client.get("/login", base_url=base)
        assert "Secure" in response.headers["Set-Cookie"]
        assert "max-age=31536000" == response.headers["Strict-Transport-Security"]
        token = html.unescape(
            re.search(r'name="csrf_token"[^>]*value="([^"]+)"', response.text).group(1)
        )
        headers = {"Referer": base + "/login"}
        response = client.post(
            "/login",
            base_url=base,
            headers=headers,
            data={"csrf_token": token, "email": "smoke@example.com", "password": password},
        )
        assert response.status_code == 302
        assert client.get("/api/v1/rates", base_url=base).status_code == 200
        anonymous = app.test_client()
        response = anonymous.get("/login", base_url=base)
        token = html.unescape(
            re.search(r'name="csrf_token"[^>]*value="([^"]+)"', response.text).group(1)
        )
        statuses = []
        for _ in range(11):
            response = anonymous.post(
                "/login",
                base_url=base,
                headers=headers,
                data={
                    "csrf_token": token,
                    "email": "nobody@example.com",
                    "password": "bad-password",
                },
            )
            statuses.append(response.status_code)
        assert statuses[-1] == 429 and 200 in statuses
        with app.app_context():
            original_check = limiter.storage.check
            try:
                limiter.storage.check = lambda: False
                assert client.get("/health/ready", base_url=base).status_code == 503
            finally:
                limiter.storage.check = original_check
        print(
            "Production PASS: PostgreSQL migration, Redis readiness and login limits, secure cookie, HSTS, trusted host, HTTPS login, dependency failure -> 503."
        )
    finally:
        if app:
            with app.app_context():
                db.session.remove()
                db.engine.dispose()
        with engine.begin() as conn:
            conn.execute(text(f"DROP SCHEMA {schema} CASCADE"))
        engine.dispose()


if __name__ == "__main__":
    run()
