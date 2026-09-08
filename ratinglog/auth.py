import hashlib
from urllib.parse import urlsplit

from flask import Blueprint, abort, flash, redirect, render_template, request, session, url_for
from flask_login import current_user, login_required, login_user, logout_user
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from werkzeug.security import check_password_hash, generate_password_hash

from .extensions import db, limiter
from .forms import LoginForm, PasswordForm, UserAccessForm, UserForm
from .models import User
from .services import audit

bp = Blueprint("auth", __name__)
DUMMY_HASH = generate_password_hash("not-a-real-user-password", method="scrypt")


def email_bucket():
    value = request.form.get("email", "").strip().casefold()[:254]
    return hashlib.sha256(value.encode()).hexdigest()


def safe_next(value):
    if (
        not value
        or not value.startswith("/")
        or value.startswith("//")
        or "\\" in value
        or any(ord(ch) < 32 for ch in value)
    ):
        return url_for("web.dashboard")
    parts = urlsplit(value)
    return value if not parts.scheme and not parts.netloc else url_for("web.dashboard")


@bp.route("/login", methods=["GET", "POST"])
@limiter.limit("10 per minute", methods=["POST"])
@limiter.limit("20 per hour", key_func=email_bucket, methods=["POST"])
def login():
    if current_user.is_authenticated:
        return redirect(url_for("web.dashboard"))
    form = LoginForm()
    if form.validate_on_submit():
        user = db.session.scalar(select(User).where(User.email == form.email.data.casefold()))
        valid = (
            user.check_password(form.password.data)
            if user
            else check_password_hash(DUMMY_HASH, form.password.data)
        )
        if user and user.active and valid:
            session.clear()
            login_user(user, remember=False, fresh=True)
            session.permanent = True
            audit(user, "session.login", "로그인")
            db.session.commit()
            return redirect(safe_next(request.args.get("next")))
        flash("이메일 또는 비밀번호를 확인하세요.", "error")
    return render_template("login.html", form=form)


@bp.post("/logout")
@login_required
def logout():
    current_user.session_version += 1
    audit(current_user, "session.logout", "로그아웃 및 전체 세션 무효화")
    db.session.commit()
    logout_user()
    session.clear()
    return redirect(url_for("auth.login"))


@bp.route("/account", methods=["GET", "POST"])
@login_required
@limiter.limit("10 per minute", methods=["POST"])
def account():
    form = PasswordForm()
    if form.validate_on_submit():
        if not current_user.check_password(form.current_password.data):
            flash("현재 비밀번호가 일치하지 않습니다.", "error")
        else:
            current_user.set_password(form.password.data)
            audit(current_user, "user.password_changed", "본인 비밀번호 변경")
            db.session.commit()
            logout_user()
            session.clear()
            flash("비밀번호를 변경했습니다. 다시 로그인하세요.", "success")
            return redirect(url_for("auth.login"))
    return render_template("account.html", form=form)


@bp.route("/admin/users", methods=["GET", "POST"])
@login_required
def users():
    if current_user.role != "admin":
        abort(403)
    form = UserForm()
    if form.validate_on_submit():
        user = User(email=form.email.data.casefold(), name=form.name.data, role=form.role.data)
        user.set_password(form.password.data)
        db.session.add(user)
        try:
            db.session.flush()
            audit(current_user, "user.created", f"계정 {user.id} / {user.role}")
            db.session.commit()
        except IntegrityError:
            db.session.rollback()
            flash("이미 등록된 이메일입니다.", "error")
        else:
            flash("계정을 만들었습니다.", "success")
            return redirect(url_for("auth.users"))
    page = db.paginate(select(User).order_by(User.id), per_page=30, error_out=False)
    return render_template("users.html", form=form, page=page)


@bp.route("/admin/users/<int:user_id>", methods=["GET", "POST"])
@login_required
def access(user_id):
    if current_user.role != "admin":
        abort(403)
    user = db.get_or_404(User, user_id)
    if user.role == "admin" or user.id == current_user.id:
        abort(403)
    form = UserAccessForm(obj=user)
    if request.method == "GET":
        form.version.data = str(user.session_version)
    if form.validate_on_submit():
        try:
            version = int(form.version.data)
        except ValueError:
            abort(400)
        # Conditional update prevents concurrent changes from silently overwriting access.
        result = db.session.execute(
            db.update(User)
            .where(User.id == user.id, User.session_version == version)
            .values(role=form.role.data, active=form.active.data, session_version=version + 1)
        )
        if result.rowcount != 1:
            db.session.rollback()
            abort(409)
        audit(
            current_user,
            "user.access_changed",
            f"계정 {user.id}: {form.role.data}, 활성={form.active.data}. {form.reason.data}",
        )
        db.session.commit()
        flash("접근 권한을 변경하고 기존 세션을 만료했습니다.", "success")
        return redirect(url_for("auth.users"))
    return render_template("access.html", form=form, user=user)
