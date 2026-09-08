import io

from sqlalchemy import select

from ratinglog.extensions import db
from ratinglog.models import Attachment, AuditEvent, RateRecord, RateRevision

from .conftest import TABLE, action, create_rate, csrf, edit_rate, lock, login, logout, publish


def test_complete_workflow_and_private_revision(client, app):
    publish(client, app)
    login(client)
    response = edit_rate(
        client,
        app,
        title="비공개 새 초안",
        attachment=(io.BytesIO(b"%PDF-1.7\nnew evidence"), "evidence.pdf"),
    )
    assert response.status_code == 302
    with app.app_context():
        revisions = db.session.scalars(select(RateRevision).order_by(RateRevision.number)).all()
        assert [(r.number, r.state) for r in revisions] == [(1, "approved"), (2, "draft")]
        assert revisions[0].title == "검증용 사망률"
        assert revisions[0].attachment_id is None
    assert "비공개 새 초안" in client.get("/rates/1/compare").text
    logout(client)
    login(client, "viewer")
    for path in [
        "/",
        "/rates",
        "/rates/1",
        "/rates/1/compare",
        "/api/v1/rates",
        "/api/v1/rates/MORT-001",
    ]:
        response = client.get(path)
        assert response.status_code == 200, path
        assert "비공개 새 초안" not in response.text
    for path in [
        "/rates/1/versions/2",
        "/rates/1/versions/2/attachment",
        "/rates/1/versions/2/export/json",
        "/rates/1/compare?after=2",
    ]:
        assert client.get(path).status_code == 404
    assert client.get("/rates/1/versions/1/export/csv").status_code == 200
    lookup = client.get("/api/v1/rates/MORT-001/lookup?age=30&sex=F&smoking=non_smoker")
    assert lookup.json["result"]["probability"] == "0.0005"
    assert lookup.json["version"] == 1


def test_cross_user_access_and_roles(client, app):
    login(client)
    assert (
        create_rate(client, attachment=(io.BytesIO(b"%PDF-1.7\nsample"), "sample.pdf")).status_code
        == 302
    )
    logout(client)
    for user in ["other", "viewer", "reviewer"]:
        login(client, user)
        for path in [
            "/rates/1",
            "/rates/1/edit",
            "/rates/1/versions/1/attachment",
            "/rates/1/versions/1/export/csv",
        ]:
            assert client.get(path).status_code == 404
        token = csrf(client, "/")
        for act in ["archive", "approve", "submit"]:
            assert (
                client.post(
                    "/rates/1/actions/" + act,
                    data={"csrf_token": token, "version": "1", "reason": "unauthorized"},
                ).status_code
                == 404
            )
        assert client.get("/admin/users").status_code == 403
        assert client.get("/admin/audit").status_code == 403
        assert client.get("/api/v1/rates/MORT-001").status_code == 404
        logout(client)


def test_self_approval_and_illegal_transitions(client, app):
    login(client, "admin")
    assert create_rate(client).status_code == 302
    assert action(client, app, "submit").status_code == 302
    assert action(client, app, "approve").status_code == 403
    assert action(client, app, "submit").status_code == 409
    assert client.get("/rates/1/edit").status_code == 409
    logout(client)
    login(client, "reviewer")
    assert action(client, app, "reject").status_code == 302
    assert client.get("/rates/1").status_code == 200  # Reviewers retain their review history.
    logout(client)
    login(client, "admin")
    assert action(client, app, "submit").status_code == 409
    assert edit_rate(client, app).status_code == 302
    assert action(client, app, "submit").status_code == 302


def test_stale_edit_and_actions(client, app):
    login(client)
    create_rate(client)
    original_lock = lock(app)
    assert edit_rate(client, app).status_code == 302
    assert edit_rate(client, app, version=str(original_lock), title="stale").status_code == 409
    assert action(client, app, "submit", version=original_lock).status_code == 409
    with app.app_context():
        assert db.session.scalar(select(db.func.count()).select_from(RateRevision)) == 2


def test_attachments_retained_and_transactions_rolled_back(client, app):
    login(client)
    create_rate(client, attachment=(io.BytesIO(b"%PDF-1.7\nfirst"), "first.pdf"))
    assert edit_rate(client, app, comments="메타데이터만 수정").status_code == 302
    with app.app_context():
        revs = db.session.scalars(select(RateRevision)).all()
        assert revs[0].attachment_id == revs[1].attachment_id
        assert db.session.scalar(select(db.func.count()).select_from(Attachment)) == 1
    response = edit_rate(
        client,
        app,
        table_file=(io.BytesIO(b"bad csv"), "bad.csv"),
        attachment=(io.BytesIO(b"%PDF-1.7\nsecond"), "second.pdf"),
    )
    assert response.status_code == 200
    with app.app_context():
        assert db.session.scalar(select(db.func.count()).select_from(Attachment)) == 1
        assert db.session.scalar(select(db.func.count()).select_from(RateRevision)) == 2
    response = client.get("/rates/1/versions/1/attachment")
    assert response.data == b"%PDF-1.7\nfirst"
    assert response.headers["Content-Disposition"].startswith("attachment")
    assert "nosniff" in response.headers["X-Content-Type-Options"]


def test_archive_restore_and_audit(client, app):
    publish(client, app)
    login(client)
    assert action(client, app, "archive").status_code == 302
    assert client.get("/rates/1").status_code == 404
    assert client.get("/api/v1/rates/MORT-001").status_code == 404
    logout(client)
    login(client, "admin")
    assert "검증용 사망률" in client.get("/rates?archived=1").text
    assert action(client, app, "restore").status_code == 302
    assert client.get("/api/v1/rates/MORT-001").status_code == 200
    assert client.get("/admin/audit").status_code == 200
    with app.app_context():
        actions = db.session.scalars(select(AuditEvent.action)).all()
        assert {"revision.created", "submit", "approve", "archive", "restore"} <= set(actions)
        assert not db.session.get(RateRecord, 1).archived


def test_csv_unit_change_requires_new_table(client, app):
    login(client)
    create_rate(client)
    response = edit_rate(client, app, unit="percent")
    assert response.status_code == 200
    assert "CSV를 다시 첨부" in response.text
    response = edit_rate(
        client,
        app,
        unit="percent",
        table_file=(io.BytesIO(TABLE.replace(b"0.0005", b"0.05")), "new.csv"),
    )
    assert response.status_code == 302
    with app.app_context():
        row = db.session.scalar(select(RateRevision).where(RateRevision.number == 2)).rows[0]
        assert row["probability"] == "0.0005"


def test_effective_dates_and_lookup_validation(client, app):
    publish(client, app)
    login(client, "viewer")
    assert client.get("/api/v1/rates/MORT-001?as_of=2024-12-31").status_code == 404
    assert client.get("/api/v1/rates/MORT-001?as_of=2025-01-01").status_code == 200
    assert client.get("/api/v1/rates/MORT-001?as_of=invalid").status_code == 400
    assert client.get("/api/v1/rates/MORT-001/lookup?age=abc").status_code == 400
    assert client.get("/api/v1/rates/MORT-001/lookup?age=150").status_code == 400
    assert client.get("/api/v1/rates/MORT-001/lookup?age=30").status_code == 404
    assert client.get("/api/v1/rates").json["total"] == 1


def test_search_pagination_and_xss(client, app):
    login(client)
    create_rate(client, title="<script>alert(1)</script>")
    assert "&lt;script&gt;" in client.get("/rates/1").text
    assert "<script>alert(1)</script>" not in client.get("/rates/1").text
    assert "MORT-001" in client.get("/rates?q=MORT").text
    assert "MORT-001" not in client.get("/rates?q=%25").text
    for i in range(2, 22):
        assert create_rate(client, code=f"MORT-{i:03}").status_code == 302
    response = client.get("/rates?page=2&q=MORT")
    assert response.status_code == 200
    assert "page=1" in response.text and "q=MORT" in response.text
    logout(client)
    login(client, "other")
    assert "MORT-001" not in client.get("/rates").text
    assert "21" not in client.get("/api/v1/rates").text
