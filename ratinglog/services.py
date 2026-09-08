from datetime import date

from flask import abort
from sqlalchemy import func, or_, select
from werkzeug.datastructures import FileStorage

from .extensions import db
from .models import AuditEvent, RateRecord, RateRevision, now
from .validation import parse_table, row_key, table_csv, validate_attachment

FIELDS = (
    "title",
    "kind",
    "category",
    "priority",
    "granted",
    "source",
    "definition",
    "comments",
    "sql_note",
    "effective_from",
    "effective_to",
    "data_type",
    "unit",
    "change_reason",
)


def audit(user, action, detail, record=None, revision=None):
    event = AuditEvent(
        actor_id=user.id,
        action=action,
        detail=detail,
        record_id=record.id if record else None,
        revision_id=revision.id if revision else None,
    )
    db.session.add(event)
    return event


def visibility(user):
    if user.role == "admin":
        return True
    conditions = [RateRevision.state == "approved"]
    if user.role == "editor":
        conditions.append(RateRecord.owner_id == user.id)
    if user.role == "reviewer":
        conditions.extend([RateRevision.state == "submitted", RateRevision.reviewed_by == user.id])
    return or_(*conditions)


def visible_revisions(user, record_id):
    return select(RateRevision).join(RateRecord).where(RateRecord.id == record_id, visibility(user))


def visible_latest(user, archived=False):
    sub = (
        select(RateRevision.record_id, func.max(RateRevision.number).label("number"))
        .join(RateRecord)
        .where(visibility(user))
        .group_by(RateRevision.record_id)
        .subquery()
    )
    stmt = (
        select(RateRevision)
        .join(RateRecord)
        .join(
            sub, (RateRevision.record_id == sub.c.record_id) & (RateRevision.number == sub.c.number)
        )
    )
    if archived:
        if user.role != "admin":
            abort(403)
        return stmt.where(RateRecord.archived.is_(True))
    return stmt.where(RateRecord.archived.is_(False))


def get_revision(user, record_id, number=None):
    stmt = visible_revisions(user, record_id)
    if number is not None:
        stmt = stmt.where(RateRevision.number == number)
    result = db.session.scalar(stmt.order_by(RateRevision.number.desc()).limit(1))
    if not result or (result.record.archived and user.role != "admin"):
        abort(404)
    return result


def can_edit(user, record):
    return not record.archived and (
        user.role == "admin" or (user.role == "editor" and record.owner_id == user.id)
    )


def check_lock(record, expected):
    try:
        if record.lock_version != int(expected):
            abort(409)
    except (ValueError, TypeError):
        abort(400)
    record.updated_at = now()


def latest(record):
    return db.session.scalar(
        select(RateRevision)
        .where(RateRevision.record_id == record.id)
        .order_by(RateRevision.number.desc())
        .limit(1)
    )


def save_revision(user, form, record=None):
    old = None
    if record:
        if not can_edit(user, record):
            abort(403)
        check_lock(record, form.version.data)
        old = latest(record)
        if old.state == "submitted":
            raise ValueError("검토 중인 버전은 수정할 수 없습니다. 검토 결과를 기다리세요.")
        if form.code.data != record.code:
            raise ValueError("원장 코드는 변경할 수 없습니다.")
    elif user.role not in ("admin", "editor"):
        abort(403)
    values = {field: getattr(form, field).data for field in FIELDS}
    values["priority"] = int(values["priority"])
    attachment = old.attachment if old else None
    upload = form.attachment.data
    if isinstance(upload, FileStorage) and upload.filename:
        attachment = validate_attachment(upload.filename, upload.read(10 * 1024 * 1024 + 1))
    rows, warnings = [], []
    table = form.table_file.data
    if values["data_type"] == "table":
        if isinstance(table, FileStorage) and table.filename:
            rows, warnings = parse_table(table.read(10 * 1024 * 1024 + 1), values["unit"])
        elif old and old.rows:
            if old.unit != values["unit"]:
                raise ValueError("단위 변경 시 해당 단위의 CSV를 다시 첨부하세요.")
            rows, warnings = old.rows, old.warnings
        else:
            raise ValueError("수치표 유형은 CSV를 첨부해야 합니다.")
    elif not attachment:
        raise ValueError("문서 유형은 근거 첨부파일이 필요합니다.")
    if record is None:
        record = RateRecord(code=form.code.data, owner_id=user.id)
        db.session.add(record)
        db.session.flush()
    if attachment and attachment.id is None:
        db.session.add(attachment)
        db.session.flush()
    revision = RateRevision(
        record_id=record.id,
        number=old.number + 1 if old else 1,
        created_by=user.id,
        attachment=attachment,
        rows=rows,
        warnings=warnings,
        **values,
    )
    db.session.add(revision)
    db.session.flush()
    audit(user, "revision.created", values["change_reason"], record, revision)
    return revision


def transition(user, record, action, expected, reason):
    check_lock(record, expected)
    rev = latest(record)
    if action == "restore":
        if user.role != "admin":
            abort(403)
        if not record.archived:
            abort(409)
        record.archived = False
    elif action == "archive":
        if not can_edit(user, record):
            abort(403)
        if rev.state == "submitted":
            raise ValueError("검토 중인 자료는 보관할 수 없습니다.")
        record.archived = True
    else:
        if record.archived:
            abort(409)
        if action == "submit":
            if not can_edit(user, record):
                abort(403)
            if rev.state != "draft":
                abort(409)
            rev.state = "submitted"
        elif action in ("approve", "reject"):
            if user.role not in ("reviewer", "admin") or user.id in (
                record.owner_id,
                rev.created_by,
            ):
                abort(403)
            if rev.state != "submitted":
                abort(409)
            rev.state = "approved" if action == "approve" else "rejected"
            rev.reviewed_by = user.id
            rev.reviewed_at = now()
            rev.review_note = reason
        else:
            abort(400)
    audit(user, action, reason, record, rev)
    db.session.flush()
    return rev


def approved_query(as_of=None):
    as_of = as_of or date.today()
    return (
        select(RateRevision)
        .join(RateRecord)
        .where(
            RateRecord.archived.is_(False),
            RateRevision.state == "approved",
            RateRevision.effective_from <= as_of,
            or_(RateRevision.effective_to.is_(None), RateRevision.effective_to >= as_of),
        )
    )


def serialize(revision, include_rows=True):
    result = {
        "code": revision.record.code,
        "version": revision.number,
        "title": revision.title,
        "kind": revision.kind,
        "category": revision.category,
        "source": revision.source,
        "granted": revision.granted,
        "state": revision.state,
        "data_type": revision.data_type,
        "unit": revision.unit,
        "effective_from": revision.effective_from.isoformat(),
        "effective_to": revision.effective_to.isoformat() if revision.effective_to else None,
        "row_count": len(revision.rows),
    }
    if include_rows:
        result["rows"] = revision.rows
    return result


def compare(before, after):
    metadata = [
        (field, getattr(before, field), getattr(after, field))
        for field in FIELDS
        if getattr(before, field) != getattr(after, field)
    ]
    a, b = {row_key(r): r for r in before.rows}, {row_key(r): r for r in after.rows}
    changes = []
    for key in sorted(a.keys() | b.keys()):
        if a.get(key) != b.get(key):
            changes.append({"key": key, "before": a.get(key), "after": b.get(key)})
    attachment_changed = (before.attachment.sha256 if before.attachment else None) != (
        after.attachment.sha256 if after.attachment else None
    )
    return metadata, changes, attachment_changed


def csv_response_content(revision):
    return table_csv(revision.rows)
