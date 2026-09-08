import sqlite3
from datetime import date
from pathlib import Path

import click
from email_validator import EmailNotValidError, validate_email
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from .extensions import db
from .models import ROLES, RateRecord, RateRevision, User
from .services import audit
from .validation import validate_attachment


def email_value(value):
    try:
        return validate_email(value, check_deliverability=False).normalized.casefold()
    except EmailNotValidError as exc:
        raise click.ClickException("올바른 이메일을 입력하세요.") from exc


def password_prompt():
    password = click.prompt(
        "Password (12-128 characters)", hide_input=True, confirmation_prompt=True
    )
    if not 12 <= len(password) <= 128:
        raise click.ClickException("비밀번호는 12~128자여야 합니다.")
    return password


def register(app):
    @app.cli.command("create-user")
    @click.option("--email", required=True)
    @click.option("--name", required=True)
    @click.option("--role", type=click.Choice(ROLES), default="viewer")
    def create_user(email, name, role):
        """Create a named account without a default password."""
        email = email_value(email)
        if not 1 <= len(name.strip()) <= 80:
            raise click.ClickException("이름은 1~80자여야 합니다.")
        user = User(email=email, name=name.strip(), role=role)
        user.set_password(password_prompt())
        db.session.add(user)
        try:
            db.session.flush()
            audit(user, "user.provisioned", f"CLI 계정 생성 / {role}")
            db.session.commit()
        except IntegrityError as exc:
            db.session.rollback()
            raise click.ClickException("이미 존재하는 이메일입니다.") from exc
        click.echo(f"Created {user.email} ({user.role})")

    @app.cli.command("reset-password")
    @click.option("--email", required=True)
    def reset_password(email):
        """Reset a password and invalidate existing sessions."""
        user = db.session.scalar(select(User).where(User.email == email_value(email)))
        if not user:
            raise click.ClickException("계정을 찾을 수 없습니다.")
        user.set_password(password_prompt())
        audit(user, "user.password_reset_cli", "운영자 CLI 비밀번호 재설정")
        db.session.commit()
        click.echo("Password reset; existing sessions invalidated.")

    @app.cli.command("import-legacy")
    @click.option(
        "--database", type=click.Path(exists=True, dir_okay=False, path_type=Path), required=True
    )
    @click.option(
        "--uploads", type=click.Path(exists=True, file_okay=False, path_type=Path), required=True
    )
    @click.option("--owner", required=True)
    def import_legacy(database, uploads, owner):
        """Atomically import old rates as document drafts into the new schema."""
        user = db.session.scalar(select(User).where(User.email == email_value(owner)))
        if not user or not user.active or user.role not in ("admin", "editor"):
            raise click.ClickException("활성 관리자 또는 작성자 소유 계정이 필요합니다.")
        count = 0
        source = sqlite3.connect(database.resolve().as_uri() + "?mode=ro", uri=True)
        source.row_factory = sqlite3.Row
        base = uploads.resolve()
        try:
            for old in source.execute("SELECT * FROM rates ORDER BY id"):
                code = f"LEGACY-{old['id']}"
                if db.session.scalar(select(RateRecord.id).where(RateRecord.code == code)):
                    raise ValueError(f"{code}: 이미 이관되었거나 코드가 존재합니다.")
                path = (base / (old["filename"] or "")).resolve()
                if not path.is_relative_to(base) or not path.is_file():
                    raise ValueError(f"{code}: 첨부파일 누락 또는 안전하지 않은 경로입니다.")
                with path.open("rb") as stream:
                    blob = validate_attachment(
                        old["filename_orig"] or path.name, stream.read(10 * 1024 * 1024 + 1)
                    )
                db.session.add(blob)
                record = RateRecord(code=code, owner_id=user.id)
                db.session.add(record)
                db.session.flush()
                imported_date = str(old["upload_date"] or "")[:10]
                try:
                    effective = date.fromisoformat(imported_date)
                except ValueError:
                    raise ValueError(f"{code}: 원본 날짜 형식을 확인하세요.") from None
                reason = f"레거시 이관: 원본 user_id={old['user_id']}, upload_date={old['upload_date']}, priority={old['priority']}"
                revision = RateRevision(
                    record_id=record.id,
                    number=1,
                    title=old["title"] or code,
                    kind="other",
                    category=old["category"] or "레거시",
                    granted=old["granted"] or "",
                    source="기존 ratinglog SQLite 이관",
                    definition=old["definition"] or "원본 정의 없음",
                    comments=old["comments"] or "",
                    sql_note=old["sql"] or "",
                    priority=int(old["priority"])
                    if str(old["priority"]) in ("1", "2", "3", "4", "5")
                    else 3,
                    effective_from=effective,
                    effective_to=None,
                    data_type="document",
                    unit="probability",
                    rows=[],
                    warnings=[
                        "이관 날짜를 적용 시작일로 사용했습니다. 실제 적용일과 종류를 검토하세요."
                    ],
                    attachment=blob,
                    change_reason=reason,
                    created_by=user.id,
                )
                db.session.add(revision)
                db.session.flush()
                audit(user, "legacy.imported", reason, record, revision)
                count += 1
            db.session.commit()
        except (ValueError, sqlite3.Error, OSError, IntegrityError) as exc:
            db.session.rollback()
            raise click.ClickException(
                f"이관 전체 취소: {exc if isinstance(exc, ValueError) else '원본 DB·파일 또는 새 DB 제약을 확인하세요.'}"
            ) from exc
        finally:
            source.close()
        click.echo(f"Imported {count} records as private document drafts.")
