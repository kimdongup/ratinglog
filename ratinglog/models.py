from datetime import UTC, date, datetime

from flask_login import UserMixin
from sqlalchemy import (
    JSON,
    CheckConstraint,
    ForeignKey,
    LargeBinary,
    String,
    Text,
    UniqueConstraint,
    event,
    inspect,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship
from werkzeug.security import check_password_hash, generate_password_hash

from .extensions import db

ROLES = ("admin", "editor", "reviewer", "viewer")
STATES = ("draft", "submitted", "approved", "rejected")
KINDS = ("mortality", "morbidity", "disability", "lapse", "other")
UNITS = ("probability", "percent", "per_thousand")


def now():
    return datetime.now(UTC)


class User(UserMixin, db.Model):
    __tablename__ = "users"
    id: Mapped[int] = mapped_column(primary_key=True)
    email: Mapped[str] = mapped_column(String(254), unique=True)
    name: Mapped[str] = mapped_column(String(80))
    password_hash: Mapped[str] = mapped_column(String(512))
    role: Mapped[str] = mapped_column(String(16), default="viewer")
    active: Mapped[bool] = mapped_column(default=True)
    session_version: Mapped[int] = mapped_column(default=1)
    created_at: Mapped[datetime] = mapped_column(default=now)
    __table_args__ = (
        CheckConstraint("role IN ('admin','editor','reviewer','viewer')", name="user_role"),
    )

    @property
    def is_active(self):
        return self.active

    def get_id(self):
        return f"{self.id}:{self.session_version}"

    def set_password(self, password):
        if not 12 <= len(password) <= 128:
            raise ValueError("비밀번호는 12~128자여야 합니다.")
        self.password_hash = generate_password_hash(password, method="scrypt")
        self.session_version = (self.session_version or 0) + 1

    def check_password(self, password):
        return check_password_hash(self.password_hash, password)


class Attachment(db.Model):
    __tablename__ = "attachments"
    id: Mapped[int] = mapped_column(primary_key=True)
    filename: Mapped[str] = mapped_column(String(200))
    mimetype: Mapped[str] = mapped_column(String(100))
    sha256: Mapped[str] = mapped_column(String(64))
    size: Mapped[int]
    content: Mapped[bytes] = mapped_column(LargeBinary, deferred=True)
    created_at: Mapped[datetime] = mapped_column(default=now)


class RateRecord(db.Model):
    __tablename__ = "rate_records"
    id: Mapped[int] = mapped_column(primary_key=True)
    code: Mapped[str] = mapped_column(String(64), unique=True)
    owner_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    owner: Mapped[User] = relationship()
    archived: Mapped[bool] = mapped_column(default=False, index=True)
    lock_version: Mapped[int] = mapped_column(default=1)
    created_at: Mapped[datetime] = mapped_column(default=now)
    updated_at: Mapped[datetime] = mapped_column(default=now)
    revisions: Mapped[list["RateRevision"]] = relationship(
        back_populates="record", order_by="RateRevision.number"
    )
    __mapper_args__ = {"version_id_col": lock_version}


class RateRevision(db.Model):
    __tablename__ = "rate_revisions"
    id: Mapped[int] = mapped_column(primary_key=True)
    record_id: Mapped[int] = mapped_column(ForeignKey("rate_records.id"), index=True)
    number: Mapped[int]
    title: Mapped[str] = mapped_column(String(200))
    kind: Mapped[str] = mapped_column(String(20))
    category: Mapped[str] = mapped_column(String(80))
    priority: Mapped[int] = mapped_column(default=3)
    granted: Mapped[str] = mapped_column(String(120), default="")
    source: Mapped[str] = mapped_column(String(500))
    definition: Mapped[str] = mapped_column(Text)
    comments: Mapped[str] = mapped_column(Text, default="")
    sql_note: Mapped[str] = mapped_column(Text, default="")
    effective_from: Mapped[date]
    effective_to: Mapped[date | None]
    data_type: Mapped[str] = mapped_column(String(16))
    unit: Mapped[str] = mapped_column(String(20), default="probability")
    rows: Mapped[list] = mapped_column(JSON, default=list)
    warnings: Mapped[list] = mapped_column(JSON, default=list)
    attachment_id: Mapped[int | None] = mapped_column(ForeignKey("attachments.id"))
    attachment: Mapped[Attachment | None] = relationship()
    change_reason: Mapped[str] = mapped_column(String(1000))
    state: Mapped[str] = mapped_column(String(16), default="draft", index=True)
    created_by: Mapped[int] = mapped_column(ForeignKey("users.id"))
    author: Mapped[User] = relationship(foreign_keys=[created_by])
    reviewed_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    review_note: Mapped[str] = mapped_column(String(1000), default="")
    created_at: Mapped[datetime] = mapped_column(default=now)
    reviewed_at: Mapped[datetime | None]
    record: Mapped[RateRecord] = relationship(back_populates="revisions")
    __table_args__ = (
        UniqueConstraint("record_id", "number", name="revision_number"),
        CheckConstraint(
            "state IN ('draft','submitted','approved','rejected')", name="revision_state"
        ),
        CheckConstraint("data_type IN ('table','document')", name="revision_type"),
        CheckConstraint("unit IN ('probability','percent','per_thousand')", name="revision_unit"),
        CheckConstraint("priority BETWEEN 1 AND 5", name="revision_priority"),
        CheckConstraint(
            "effective_to IS NULL OR effective_to >= effective_from", name="revision_dates"
        ),
    )


class AuditEvent(db.Model):
    __tablename__ = "audit_events"
    id: Mapped[int] = mapped_column(primary_key=True)
    record_id: Mapped[int | None] = mapped_column(ForeignKey("rate_records.id"), index=True)
    revision_id: Mapped[int | None] = mapped_column(ForeignKey("rate_revisions.id"))
    actor_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    actor: Mapped[User] = relationship()
    action: Mapped[str] = mapped_column(String(40))
    detail: Mapped[str] = mapped_column(String(2000))
    created_at: Mapped[datetime] = mapped_column(default=now, index=True)


# Service code never mutates published content. These ORM guards also protect
# maintenance code from accidentally rewriting history (not a DB-admin boundary).


@event.listens_for(RateRevision, "before_update")
def immutable_revision_content(mapper, connection, target):
    allowed = {"state", "reviewed_by", "review_note", "reviewed_at"}
    for attribute in inspect(target).mapper.column_attrs:
        if (
            attribute.key not in allowed
            and inspect(target).attrs[attribute.key].history.has_changes()
        ):
            raise ValueError("버전 내용은 수정할 수 없습니다. 새 버전을 만드세요.")


def reject_history_mutation(mapper, connection, target):
    raise ValueError("보존된 이력과 첨부자료는 변경하거나 삭제할 수 없습니다.")


for model in (AuditEvent, Attachment):
    event.listen(model, "before_update", reject_history_mutation)
    event.listen(model, "before_delete", reject_history_mutation)
event.listen(RateRevision, "before_delete", reject_history_mutation)
