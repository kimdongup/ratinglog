from sqlalchemy import select

from ratinglog import create_app
from ratinglog.extensions import db
from ratinglog.models import User

from .conftest import PASSWORD, csrf, login, logout


def test_csrf_and_methods(client):
    assert (
        client.post(
            "/login", data={"email": "editor@example.com", "password": PASSWORD}
        ).status_code
        == 400
    )
    assert client.get("/logout").status_code == 405
    assert client.get("/api/v1/rates").status_code == 401
    login(client)
    assert client.post("/rates/new", data={}).status_code == 400
    assert client.get("/rates/1/actions/archive").status_code == 405
    assert client.get("/health/live").json["status"] == "ok"
    assert client.get("/health/ready").status_code == 200


def test_safe_redirect(client):
    for bad in ["https://evil.example", "//evil.example", "/\\evil.example"]:
        token = csrf(client)
        response = client.post(
            "/login",
            query_string={"next": bad},
            data={"csrf_token": token, "email": "editor@example.com", "password": PASSWORD},
        )
        assert response.location == "/"
        logout(client)


def test_password_change_revokes_all_sessions(client, app):
    login(client)
    other = app.test_client()
    login(other)
    response = client.post(
        "/account",
        data={
            "csrf_token": csrf(client, "/account"),
            "current_password": PASSWORD,
            "password": "new-safe-password-1234",
            "confirm": "new-safe-password-1234",
        },
    )
    assert response.status_code == 302
    assert other.get("/api/v1/rates").status_code == 401
    with app.app_context():
        user = db.session.scalar(select(User).where(User.email == "editor@example.com"))
        assert user.check_password("new-safe-password-1234")
        assert user.password_hash != "new-safe-password-1234"


def test_admin_access_and_revocation(client, app):
    editor = app.test_client()
    login(editor)
    login(client, "admin")
    response = client.post(
        "/admin/users/2",
        data={
            "csrf_token": csrf(client, "/admin/users/2"),
            "version": "1",
            "role": "viewer",
            "reason": "변경",
        },
    )
    # Initial passwords increment the session version from 0 to 1.
    assert response.status_code == 302
    assert editor.get("/api/v1/rates").status_code == 401
    assert client.get("/admin/users/1").status_code == 403
    with app.app_context():
        user = db.session.get(User, 2)
        assert user.role == "viewer" and not user.active


def test_security_headers_and_unknown_users(client):
    response = client.get("/login")
    assert "default-src 'self'" in response.headers["Content-Security-Policy"]
    assert response.headers["X-Frame-Options"] == "DENY"
    assert "HttpOnly" in response.headers["Set-Cookie"]
    response = client.post(
        "/login",
        data={
            "csrf_token": csrf(client),
            "email": "missing@example.com",
            "password": "wrong-password",
        },
    )
    assert response.status_code == 200
    assert "이메일 또는 비밀번호를 확인하세요." in response.text


def test_production_configuration():
    import pytest

    with pytest.raises(RuntimeError):
        create_app({"SECRET_KEY": "short"})
    with pytest.raises(RuntimeError):
        create_app(
            {
                "PRODUCTION": True,
                "SECRET_KEY": "x" * 64,
                "SQLALCHEMY_DATABASE_URI": "sqlite:///:memory:",
            }
        )
    with pytest.raises(RuntimeError):
        create_app(
            {
                "PRODUCTION": True,
                "SECRET_KEY": "x" * 64,
                "SQLALCHEMY_DATABASE_URI": "postgresql+psycopg://localhost/db",
                "RATELIMIT_STORAGE_URI": "memory://",
            }
        )


def test_untrusted_host_is_rejected_without_template_error(client):
    response = client.get("/health/live", base_url="https://evil.example")
    assert response.status_code == 400
    assert "evil.example" not in response.text
