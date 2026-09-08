import io
from datetime import timedelta

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session
from sqlalchemy.orm.exc import StaleDataError

from ratinglog.extensions import db
from ratinglog.models import AuditEvent, RateRecord, RateRevision, User, now
from ratinglog.validation import parse_table

from .conftest import PASSWORD, action, create_rate, csrf, edit_rate, login, logout, publish


def test_orm_guards_preserve_history(client, app):
    login(client)
    create_rate(client, attachment=(io.BytesIO(b"%PDF-1.7\ndata"), "test.pdf"))
    with app.app_context():
        revision = db.session.scalar(select(RateRevision))
        revision.title = "rewrite old history"
        with pytest.raises(ValueError):
            db.session.commit()
        db.session.rollback()
        event = db.session.scalar(select(AuditEvent).where(AuditEvent.action == "revision.created"))
        db.session.delete(event)
        with pytest.raises(ValueError):
            db.session.commit()
        db.session.rollback()
        assert db.session.scalar(select(RateRevision.title)) == "검증용 사망률"


def test_database_optimistic_lock(client, app):
    login(client)
    create_rate(client)
    with app.app_context(), Session(db.engine) as first, Session(db.engine) as second:
        a, b = first.get(RateRecord, 1), second.get(RateRecord, 1)
        a.updated_at = now() + timedelta(seconds=1)
        first.commit()
        b.updated_at = now() + timedelta(seconds=2)
        with pytest.raises(StaleDataError):
            second.commit()
        second.rollback()


def test_document_type_and_read_permissions(client, app):
    login(client)
    response = create_rate(client, table=None, data_type="document")
    assert response.status_code == 200 and "근거 첨부파일이 필요" in response.text
    assert (
        create_rate(
            client,
            table=None,
            data_type="document",
            attachment=(io.BytesIO(b"%PDF-1.7\nevidence"), "test.pdf"),
        ).status_code
        == 302
    )
    action(client, app, "submit")
    logout(client)
    login(client, "reviewer")
    assert client.get("/rates/1/versions/1/attachment").status_code == 200
    action(client, app, "approve")
    assert client.get("/api/v1/rates/MORT-001/lookup?age=30").status_code == 422
    assert client.get("/rates/1/versions/1/export/csv").status_code == 422
    assert client.get("/rates/1/versions/1/export/xml").status_code == 404


def test_last_applicable_approved_version_and_inclusive_dates(client, app):
    publish(client, app)
    login(client)
    edit_rate(client, app, effective_from="2026-01-01", effective_to="2026-12-31")
    action(client, app, "submit")
    logout(client)
    login(client, "reviewer")
    action(client, app, "approve")
    assert client.get("/api/v1/rates/MORT-001?as_of=2025-12-31").json["version"] == 1
    assert client.get("/api/v1/rates/MORT-001?as_of=2026-01-01").json["version"] == 2
    assert client.get("/api/v1/rates/MORT-001?as_of=2026-12-31").json["version"] == 2
    assert client.get("/api/v1/rates/MORT-001?as_of=2027-01-01").json["version"] == 1
    assert client.get("/api/v1/rates?as_of=2026-06-01").json["items"][0]["version"] == 2


def test_invalid_dates_and_duplicate_code(client, app):
    login(client)
    response = create_rate(client, effective_from="2026-02-01", effective_to="2026-01-01")
    assert response.status_code == 200 and "종료일은 시작일 이후" in response.text
    assert create_rate(client).status_code == 302
    assert create_rate(client).status_code == 200
    with app.app_context():
        assert db.session.scalar(select(db.func.count()).select_from(RateRecord)) == 1


def test_demoted_owner_cannot_read_drafts(client, app):
    login(client)
    create_rate(client)
    with app.app_context():
        user = db.session.get(User, 2)
        user.role = "viewer"
        db.session.commit()
    assert client.get("/rates/1").status_code == 404


def test_logout_invalidates_stolen_cookie(client, app):
    login(client)
    cookie = client.get_cookie("ratinglog_session_v2")
    stolen = app.test_client()
    stolen.set_cookie("ratinglog_session_v2", cookie.value)
    assert stolen.get("/api/v1/rates").status_code == 200
    logout(client)
    assert stolen.get("/api/v1/rates").status_code == 401


def test_web_user_creation_and_wrong_current_password(client, app):
    login(client, "admin")
    form = {
        "csrf_token": csrf(client, "/admin/users"),
        "email": "web@example.com",
        "name": "Web",
        "role": "editor",
        "password": PASSWORD,
    }
    assert client.post("/admin/users", data=form).status_code == 302
    form["csrf_token"] = csrf(client, "/admin/users")
    assert "이미 등록된 이메일" in client.post("/admin/users", data=form).text
    response = client.post(
        "/account",
        data={
            "csrf_token": csrf(client, "/account"),
            "current_password": "wrong",
            "password": PASSWORD,
            "confirm": PASSWORD,
        },
    )
    assert "현재 비밀번호가 일치하지 않습니다." in response.text


def test_large_requests_rejected(client):
    response = client.post(
        "/login",
        data=b"x" * (12 * 1024 * 1024 + 1),
        content_type="application/x-www-form-urlencoded",
    )
    assert response.status_code == 413


def test_row_limit():
    data = "age,sex,smoking,duration,rate\n" + "\n".join(
        f"{a},F,all,{d},0.01" for a in range(121) for d in range(121)
    )
    with pytest.raises(ValueError, match="10,000"):
        parse_table(data.encode(), "probability")
