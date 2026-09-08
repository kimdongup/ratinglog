import io
from datetime import UTC, date, datetime

from flask import (
    Blueprint,
    Response,
    abort,
    flash,
    jsonify,
    redirect,
    render_template,
    request,
    send_file,
    url_for,
)
from flask_login import current_user, login_required
from sqlalchemy import func, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm.exc import StaleDataError

from .extensions import db
from .forms import ActionForm, RateForm
from .models import AuditEvent, RateRecord, RateRevision
from .services import (
    approved_query,
    audit,
    can_edit,
    compare,
    csv_response_content,
    get_revision,
    latest,
    save_revision,
    serialize,
    transition,
    visible_latest,
    visible_revisions,
)

bp = Blueprint("web", __name__)


def filters(stmt):
    word = request.args.get("q", "").strip()[:200]
    if word:
        escaped = word.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
        pattern = "%" + escaped + "%"
        stmt = stmt.where(
            or_(
                RateRecord.code.ilike(pattern, escape="\\"),
                RateRevision.title.ilike(pattern, escape="\\"),
                RateRevision.category.ilike(pattern, escape="\\"),
                RateRevision.granted.ilike(pattern, escape="\\"),
            )
        )
    for key in ("kind", "state"):
        value = request.args.get(key, "")
        if value:
            stmt = stmt.where(getattr(RateRevision, key) == value)
    if request.args.get("mine") == "1":
        stmt = stmt.where(RateRecord.owner_id == current_user.id)
    return stmt


def commit():
    try:
        db.session.commit()
    except StaleDataError:
        db.session.rollback()
        abort(409)


@bp.get("/")
@login_required
def dashboard():
    accessible = visible_latest(current_user).subquery()
    counts = dict(
        db.session.execute(
            select(accessible.c.state, func.count()).group_by(accessible.c.state)
        ).all()
    )
    rows = db.session.scalars(
        visible_latest(current_user).order_by(RateRecord.updated_at.desc()).limit(6)
    ).all()
    today = datetime.now(UTC).date()
    expiring = db.session.scalar(
        select(func.count())
        .select_from(accessible)
        .where(
            accessible.c.effective_to.is_not(None),
            accessible.c.effective_to >= today,
            accessible.c.effective_to <= date.fromordinal(today.toordinal() + 30),
        )
    )
    return render_template(
        "dashboard.html", counts=counts, rows=rows, expiring=expiring, today=today
    )


@bp.get("/rates")
@login_required
def rates():
    archived = request.args.get("archived") == "1"
    stmt = filters(visible_latest(current_user, archived)).order_by(
        RateRecord.updated_at.desc(), RateRecord.id.desc()
    )
    page = db.paginate(stmt, per_page=20, error_out=False)
    return render_template("rates.html", page=page, archived=archived)


@bp.route("/rates/new", methods=["GET", "POST"])
@login_required
def create():
    if current_user.role not in ("admin", "editor"):
        abort(403)
    form = RateForm()
    if request.method == "GET":
        form.effective_from.data = datetime.now(UTC).date()
        form.change_reason.data = "신규 등록"
    if form.validate_on_submit():
        try:
            rev = save_revision(current_user, form)
            commit()
        except (ValueError, IntegrityError) as exc:
            db.session.rollback()
            flash(
                str(exc) if isinstance(exc, ValueError) else "이미 사용 중인 원장 코드입니다.",
                "error",
            )
        else:
            flash("새 원장의 첫 버전을 저장했습니다.", "success")
            return redirect(url_for("web.detail", record_id=rev.record_id))
    return render_template("rate_form.html", form=form, revision=None)


@bp.route("/rates/<int:record_id>/edit", methods=["GET", "POST"])
@login_required
def edit(record_id):
    rev = get_revision(current_user, record_id)
    if not can_edit(current_user, rev.record):
        abort(403)
    if latest(rev.record).state == "submitted":
        abort(409)
    form = RateForm(obj=rev)
    if request.method == "GET":
        form.code.data = rev.record.code
        form.priority.data = str(rev.priority)
        form.version.data = str(rev.record.lock_version)
        form.change_reason.data = ""
    if form.validate_on_submit():
        try:
            new_rev = save_revision(current_user, form, rev.record)
            commit()
        except ValueError as exc:
            db.session.rollback()
            flash(str(exc), "error")
        except (StaleDataError, IntegrityError):
            db.session.rollback()
            abort(409)
        else:
            flash("기존 내용을 보존하고 새 버전을 저장했습니다.", "success")
            return redirect(url_for("web.detail", record_id=record_id, number=new_rev.number))
    return render_template("rate_form.html", form=form, revision=rev)


@bp.get("/rates/<int:record_id>")
@bp.get("/rates/<int:record_id>/versions/<int:number>")
@login_required
def detail(record_id, number=None):
    rev = get_revision(current_user, record_id, number)
    history = db.session.scalars(
        visible_revisions(current_user, record_id).order_by(RateRevision.number.desc())
    ).all()
    events = db.session.scalars(
        select(AuditEvent)
        .where(
            AuditEvent.record_id == record_id, AuditEvent.revision_id.in_([r.id for r in history])
        )
        .order_by(AuditEvent.id.desc())
        .limit(100)
    ).all()
    current = latest(rev.record)
    action_form = ActionForm(version=rev.record.lock_version)
    return render_template(
        "detail.html",
        revision=rev,
        history=history,
        events=events,
        action_form=action_form,
        editable=can_edit(current_user, rev.record),
        is_latest=rev.id == current.id,
    )


@bp.post("/rates/<int:record_id>/actions/<action>")
@login_required
def action(record_id, action):
    rev = get_revision(current_user, record_id)
    form = ActionForm()
    if not form.validate_on_submit():
        flash("작업 사유를 1~1,000자로 입력하세요.", "error")
        return redirect(url_for("web.detail", record_id=record_id))
    try:
        transition(current_user, rev.record, action, form.version.data, form.reason.data)
        commit()
    except ValueError as exc:
        db.session.rollback()
        flash(str(exc), "error")
    except StaleDataError:
        db.session.rollback()
        abort(409)
    else:
        flash("처리 결과와 사유를 기록했습니다.", "success")
    return redirect(
        url_for("web.rates") if action == "archive" else url_for("web.detail", record_id=record_id)
    )


@bp.get("/rates/<int:record_id>/compare")
@login_required
def comparison(record_id):
    history = db.session.scalars(
        visible_revisions(current_user, record_id).order_by(RateRevision.number.desc())
    ).all()
    if not history:
        abort(404)
    try:
        after_number = int(request.args.get("after", history[0].number))
        before_number = int(
            request.args.get("before", history[1].number if len(history) > 1 else history[0].number)
        )
    except ValueError:
        abort(400)
    before = get_revision(current_user, record_id, before_number)
    after = get_revision(current_user, record_id, after_number)
    metadata, changes, attachment_changed = compare(before, after)
    return render_template(
        "compare.html",
        before=before,
        after=after,
        history=history,
        metadata=metadata,
        changes=changes,
        attachment_changed=attachment_changed,
    )


@bp.get("/rates/<int:record_id>/versions/<int:number>/attachment")
@login_required
def attachment(record_id, number):
    rev = get_revision(current_user, record_id, number)
    if not rev.attachment:
        abort(404)
    blob = rev.attachment
    audit(current_user, "attachment.downloaded", blob.sha256, rev.record, rev)
    commit()
    return send_file(
        io.BytesIO(blob.content),
        mimetype="application/octet-stream",
        as_attachment=True,
        download_name=blob.filename,
        etag=blob.sha256,
        max_age=0,
    )


@bp.get("/rates/<int:record_id>/versions/<int:number>/export/<fmt>")
@login_required
def export(record_id, number, fmt):
    rev = get_revision(current_user, record_id, number)
    if fmt not in ("csv", "json"):
        abort(404)
    if fmt == "csv" and not rev.rows:
        abort(422)
    audit(current_user, "revision.exported", fmt, rev.record, rev)
    commit()
    response = (
        jsonify(serialize(rev))
        if fmt == "json"
        else Response("\ufeff" + csv_response_content(rev), mimetype="text/csv; charset=utf-8")
    )
    response.headers["Content-Disposition"] = (
        f'attachment; filename="{rev.record.code}-v{rev.number}.{fmt}"'
    )
    return response


@bp.get("/admin/audit")
@login_required
def audit_log():
    if current_user.role != "admin":
        abort(403)
    page = db.paginate(
        select(AuditEvent).order_by(AuditEvent.id.desc()), per_page=50, error_out=False
    )
    return render_template("audit.html", page=page)


def as_of_date():
    value = request.args.get("as_of")
    if not value:
        return datetime.now(UTC).date()
    try:
        return date.fromisoformat(value)
    except ValueError:
        abort(400)


def api_revision(code):
    rev = db.session.scalar(
        approved_query(as_of_date())
        .where(RateRecord.code == code)
        .order_by(RateRevision.number.desc())
        .limit(1)
    )
    if not rev:
        abort(404)
    return rev


@bp.get("/api/v1/rates")
@login_required
def api_rates():
    base = approved_query(as_of_date()).subquery()
    newest = (
        select(base.c.record_id, func.max(base.c.number).label("number"))
        .group_by(base.c.record_id)
        .subquery()
    )
    stmt = (
        select(RateRevision)
        .join(RateRecord)
        .join(
            newest,
            (RateRevision.record_id == newest.c.record_id)
            & (RateRevision.number == newest.c.number),
        )
    )
    page = db.paginate(filters(stmt).order_by(RateRecord.code), per_page=50, error_out=False)
    return jsonify(
        items=[serialize(rev, False) for rev in page.items],
        page=page.page,
        pages=page.pages,
        total=page.total,
    )


@bp.get("/api/v1/rates/<code>")
@login_required
def api_rate(code):
    return jsonify(serialize(api_revision(code)))


@bp.get("/api/v1/rates/<code>/lookup")
@login_required
def lookup(code):
    rev = api_revision(code)
    if rev.data_type != "table":
        abort(422)
    try:
        age = int(request.args["age"])
        duration = int(request.args.get("duration", "0"))
    except (KeyError, ValueError):
        abort(400)
    sex = request.args.get("sex", "U")
    smoking = request.args.get("smoking", "all")
    if (
        not 0 <= age <= 120
        or not 0 <= duration <= 120
        or sex not in ("F", "M", "U")
        or smoking not in ("non_smoker", "smoker", "all")
    ):
        abort(400)
    match = next(
        (
            row
            for row in rev.rows
            if (row["age"], row["sex"], row["smoking"], row["duration"])
            == (age, sex, smoking, duration)
        ),
        None,
    )
    if not match:
        abort(404)
    return jsonify(**serialize(rev, False), result=match)
