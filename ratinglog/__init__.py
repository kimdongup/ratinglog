import os
from datetime import timedelta
from pathlib import Path

from flask import Flask, Response, jsonify, render_template, request
from redis.exceptions import RedisError
from sqlalchemy import event, text
from sqlalchemy.engine import Engine
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm.exc import StaleDataError
from werkzeug.exceptions import SecurityError
from werkzeug.middleware.proxy_fix import ProxyFix

from .extensions import csrf, db, limiter, login_manager, migrate


@event.listens_for(Engine, "connect")
def sqlite_foreign_keys(connection, _):
    if type(connection).__module__ == "sqlite3":
        cursor = connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()


def create_app(test_config=None):
    from dotenv import load_dotenv

    load_dotenv()
    app = Flask(__name__, instance_relative_config=True)
    Path(app.instance_path).mkdir(parents=True, exist_ok=True)
    production = os.getenv("APP_ENV", "development") == "production"
    app.config.from_mapping(
        SECRET_KEY=os.getenv("SECRET_KEY", ""),
        PRODUCTION=production,
        SQLALCHEMY_DATABASE_URI=os.getenv("DATABASE_URL", "sqlite:///ratinglog.sqlite"),
        SQLALCHEMY_TRACK_MODIFICATIONS=False,
        SQLALCHEMY_ENGINE_OPTIONS={"pool_pre_ping": True, "hide_parameters": True},
        RATELIMIT_STORAGE_URI=os.getenv("RATELIMIT_STORAGE_URI", "memory://"),
        RATELIMIT_HEADERS_ENABLED=True,
        SESSION_COOKIE_HTTPONLY=True,
        SESSION_COOKIE_SECURE=production,
        SESSION_COOKIE_SAMESITE="Lax",
        SESSION_COOKIE_NAME="ratinglog_session_v2",
        PERMANENT_SESSION_LIFETIME=timedelta(hours=1),
        SESSION_REFRESH_EACH_REQUEST=False,
        MAX_CONTENT_LENGTH=12 * 1024 * 1024,
        MAX_FORM_MEMORY_SIZE=2 * 1024 * 1024,
        MAX_FORM_PARTS=50,
        TRUSTED_HOSTS=[
            v.strip()
            for v in os.getenv("TRUSTED_HOSTS", "localhost,127.0.0.1").split(",")
            if v.strip()
        ],
        PROXY_HOPS=int(os.getenv("PROXY_HOPS", "0")),
    )
    if test_config:
        app.config.update(test_config)
    secret = app.config["SECRET_KEY"]
    if len(secret) < 32 or secret.startswith("replace-with"):
        raise RuntimeError("SECRET_KEY에 무작위 32자 이상의 비밀키를 설정하세요.")
    if app.config["PRODUCTION"]:
        app.config["SESSION_COOKIE_SECURE"] = True
        if app.debug or os.getenv("FLASK_DEBUG", "0").lower() in ("1", "true"):
            raise RuntimeError("운영에서는 디버그 모드를 사용할 수 없습니다.")
        if not app.config["SQLALCHEMY_DATABASE_URI"].startswith("postgresql+psycopg://"):
            raise RuntimeError("운영 DATABASE_URL은 postgresql+psycopg:// 형식이어야 합니다.")
        if not app.config["RATELIMIT_STORAGE_URI"].startswith(("redis://", "rediss://")):
            raise RuntimeError("운영 속도 제한은 Redis 저장소가 필요합니다.")
        if not app.config["TRUSTED_HOSTS"]:
            raise RuntimeError("TRUSTED_HOSTS를 설정하세요.")
    hops = app.config["PROXY_HOPS"]
    if not 0 <= hops <= 3:
        raise RuntimeError("PROXY_HOPS는 0~3이어야 합니다.")
    if hops:
        app.wsgi_app = ProxyFix(app.wsgi_app, x_for=hops, x_proto=hops, x_host=hops)
    db.init_app(app)
    migrate.init_app(app, db)
    csrf.init_app(app)
    login_manager.init_app(app)
    limiter.init_app(app)
    login_manager.login_view = "auth.login"
    login_manager.login_message = "로그인 후 이용하세요."
    login_manager.session_protection = "strong"

    from . import auth, cli, views
    from .models import User

    @login_manager.user_loader
    def load_user(token):
        try:
            user_id, version = map(int, token.split(":"))
        except (ValueError, AttributeError):
            return None
        user = db.session.get(User, user_id)
        return user if user and user.active and user.session_version == version else None

    @login_manager.unauthorized_handler
    def unauthorized():
        from flask import redirect, url_for

        if request.path.startswith("/api/"):
            return jsonify(error="authentication_required"), 401
        return redirect(url_for("auth.login", next=request.full_path))

    app.register_blueprint(auth.bp)
    app.register_blueprint(views.bp)
    cli.register(app)

    @app.after_request
    def security_headers(response):
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Referrer-Policy"] = "same-origin"
        response.headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=()"
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; object-src 'none'; frame-ancestors 'none'; base-uri 'self'; form-action 'self'"
        )
        if app.config["SESSION_COOKIE_SECURE"]:
            response.headers["Strict-Transport-Security"] = "max-age=31536000"
        if not request.path.startswith("/static/"):
            response.headers["Cache-Control"] = "no-store"
        return response

    def error_response(error):
        code = getattr(error, "code", 500)
        messages = {
            400: "입력값 또는 보안 토큰을 확인하고 다시 시도하세요.",
            403: "이 작업에 대한 권한이 없습니다.",
            404: "자료를 찾을 수 없습니다.",
            405: "지원하지 않는 요청입니다.",
            409: "다른 변경이 먼저 저장되었습니다. 새로고침 후 다시 시도하세요.",
            413: "요청 크기가 12 MiB를 초과했습니다.",
            422: "요청한 자료 형식을 처리할 수 없습니다.",
            429: "요청이 너무 많습니다. 잠시 후 다시 시도하세요.",
            500: "처리 중 오류가 발생했습니다.",
            503: "서비스 연결을 확인하고 있습니다.",
        }
        if code >= 500:
            db.session.rollback()
        message = messages.get(code, "요청을 처리할 수 없습니다.")
        if request.path.startswith("/api/"):
            return jsonify(error=message), code
        # A rejected Host has no URL adapter; DB failures must not invoke the
        # authenticated layout/user loader again while handling the exception.
        if isinstance(error, SecurityError) or code >= 500:
            return Response(message, status=code, mimetype="text/plain")
        return render_template("error.html", code=code, message=message), code

    @app.errorhandler(StaleDataError)
    def stale_data(error):
        from werkzeug.exceptions import Conflict

        db.session.rollback()
        return error_response(Conflict())

    for code in (400, 403, 404, 405, 409, 413, 422, 429, 500, 503):
        app.register_error_handler(code, error_response)

    @app.get("/health/live")
    @limiter.exempt
    def live():
        return jsonify(status="ok")

    @app.get("/health/ready")
    @limiter.exempt
    def ready():
        try:
            db.session.execute(text("SELECT id FROM users LIMIT 1"))
            if app.config["PRODUCTION"] and not limiter.storage.check():
                return jsonify(status="unavailable"), 503
        except (SQLAlchemyError, OSError, RedisError):
            db.session.rollback()
            return jsonify(status="unavailable"), 503
        return jsonify(status="ok")

    @app.context_processor
    def pagination_helpers():
        from flask import url_for

        def page_url(number):
            args = request.args.to_dict()
            args.update(request.view_args or {})
            args["page"] = number
            return url_for(request.endpoint, **args)

        return {"page_url": page_url}

    @app.context_processor
    def labels():
        return {
            "state_labels": {
                "draft": "초안",
                "submitted": "검토 대기",
                "approved": "승인",
                "rejected": "반려",
            },
            "kind_labels": {
                "mortality": "사망률",
                "morbidity": "질병률",
                "disability": "장해율",
                "lapse": "해지율",
                "other": "기타",
            },
            "role_labels": {
                "admin": "관리자",
                "editor": "작성자",
                "reviewer": "검토자",
                "viewer": "열람자",
            },
            "unit_labels": {
                "probability": "확률 (0~1)",
                "percent": "퍼센트 (%)",
                "per_thousand": "천분율 (‰)",
            },
        }

    return app
