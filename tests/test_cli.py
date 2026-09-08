import io
import sqlite3
import zipfile
from contextlib import closing

from flask_migrate import downgrade, upgrade
from sqlalchemy import inspect, select

from ratinglog.extensions import db
from ratinglog.models import Attachment, AuditEvent, RateRecord, RateRevision, User

from .conftest import PASSWORD


def legacy_fixture(tmp_path, missing=False):
    database = tmp_path / "legacy.sqlite"
    uploads = tmp_path / "uploads"
    uploads.mkdir()
    stream = io.BytesIO()
    with zipfile.ZipFile(stream, "w") as archive:
        archive.writestr("evidence.txt", b"old evidence")
    (uploads / "old.zip").write_bytes(stream.getvalue())
    with closing(sqlite3.connect(database)) as conn, conn:
        conn.execute(
            "CREATE TABLE rates (id INTEGER PRIMARY KEY, user_id INTEGER, priority TEXT, title TEXT, granted TEXT, category TEXT, definition TEXT, comments TEXT, sql TEXT, filename_orig TEXT, filename TEXT, filesize INTEGER, upload_date TEXT)"
        )
        conn.execute(
            "INSERT INTO rates VALUES (1, 9, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                "1",
                "이관할 위험률",
                "A1",
                "보험",
                "원본 정의",
                "원본 설명",
                "SELECT * FROM private;",
                "근거.zip",
                "old.zip",
                len(stream.getvalue()),
                "2014-10-28 12:00:00",
            ),
        )
        if missing:
            conn.execute(
                'INSERT INTO rates SELECT 2, user_id, priority, title, granted, category, definition, comments, sql, filename_orig, "missing.zip", filesize, upload_date FROM rates WHERE id=1'
            )
    return database, uploads


def test_cli_create_reset_and_validation(app):
    runner = app.test_cli_runner()
    args = ["create-user", "--email", "new@example.com", "--name", "New", "--role", "editor"]
    response = runner.invoke(args=args, input=PASSWORD + "\n" + PASSWORD + "\n")
    assert response.exit_code == 0, response.output
    response = runner.invoke(args=args, input=PASSWORD + "\n" + PASSWORD + "\n")
    assert response.exit_code == 1 and "이미 존재" in response.output
    response = runner.invoke(
        args=["reset-password", "--email", "new@example.com"],
        input="another-password-123\nanother-password-123\n",
    )
    assert response.exit_code == 0
    with app.app_context():
        user = db.session.scalar(select(User).where(User.email == "new@example.com"))
        assert user.check_password("another-password-123")
        assert user.session_version == 2
    assert runner.invoke(args=["create-user", "--email", "not-email", "--name", "x"]).exit_code == 1
    assert runner.invoke(args=["reset-password", "--email", "unknown@example.com"]).exit_code == 1
    assert (
        runner.invoke(
            args=["create-user", "--email", "short@example.com", "--name", "x"],
            input="short\nshort\n",
        ).exit_code
        == 1
    )


def test_legacy_import_preserves_data_and_rejects_duplicate(app, tmp_path):
    database, uploads = legacy_fixture(tmp_path)
    args = [
        "import-legacy",
        "--database",
        str(database),
        "--uploads",
        str(uploads),
        "--owner",
        "admin@example.com",
    ]
    response = app.test_cli_runner().invoke(args=args)
    assert response.exit_code == 0, response.output
    with app.app_context():
        r = db.session.scalar(select(RateRevision))
        assert r.title == "이관할 위험률" and r.state == "draft"
        assert r.record.code == "LEGACY-1" and r.data_type == "document"
        assert r.sql_note == "SELECT * FROM private;"
        assert "user_id=9" in r.change_reason
        assert r.attachment.content == (uploads / "old.zip").read_bytes()
        assert db.session.scalar(select(db.func.count()).select_from(User)) == 5
    response = app.test_cli_runner().invoke(args=args)
    assert response.exit_code == 1
    with app.app_context():
        assert db.session.scalar(select(db.func.count()).select_from(RateRecord)) == 1


def test_legacy_import_is_atomic(app, tmp_path):
    database, uploads = legacy_fixture(tmp_path, missing=True)
    response = app.test_cli_runner().invoke(
        args=[
            "import-legacy",
            "--database",
            str(database),
            "--uploads",
            str(uploads),
            "--owner",
            "admin@example.com",
        ]
    )
    assert response.exit_code == 1 and "전체 취소" in response.output
    with app.app_context():
        for model in (RateRecord, RateRevision, Attachment, AuditEvent):
            assert db.session.scalar(select(db.func.count()).select_from(model)) == 0


def test_migration_roundtrip(app):
    with app.app_context():
        downgrade(revision="base")
        assert "rate_records" not in inspect(db.engine).get_table_names()
        upgrade()
        assert {"users", "rate_records", "rate_revisions", "attachments", "audit_events"} <= set(
            inspect(db.engine).get_table_names()
        )
