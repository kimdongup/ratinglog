"""Real Chromium workflow on an isolated, temporary database (no production writes)."""

import logging
import secrets
import tempfile
import threading
from pathlib import Path

from flask_migrate import upgrade
from playwright.sync_api import expect, sync_playwright
from werkzeug.serving import make_server

from ratinglog import create_app
from ratinglog.extensions import db
from ratinglog.models import User


def run():
    root = Path(__file__).resolve().parents[1]
    screenshots = root / "artifacts"
    screenshots.mkdir(exist_ok=True)
    logging.getLogger("werkzeug").setLevel(logging.ERROR)
    with tempfile.TemporaryDirectory(prefix="ratinglog-browser-") as directory:
        app = create_app(
            {
                "TESTING": True,
                "SECRET_KEY": secrets.token_hex(32),
                "SQLALCHEMY_DATABASE_URI": "sqlite:///" + str(Path(directory) / "browser.sqlite"),
                "PRODUCTION": False,
                "SESSION_COOKIE_SECURE": False,
                "TRUSTED_HOSTS": ["127.0.0.1"],
                "RATELIMIT_ENABLED": False,
            }
        )
        password = secrets.token_urlsafe(24)
        with app.app_context():
            upgrade(directory=str(root / "migrations"))
            for name, role in [("작성자", "editor"), ("검토자", "reviewer")]:
                user = User(email=f"{role}@example.com", name=name, role=role)
                user.set_password(password)
                db.session.add(user)
            db.session.commit()
        server = make_server("127.0.0.1", 0, app, threaded=True)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        base = f"http://127.0.0.1:{server.server_port}"
        errors = []
        try:
            with sync_playwright() as playwright:
                browser = playwright.chromium.launch()
                page = browser.new_page(
                    viewport={"width": 1440, "height": 1000}, device_scale_factor=1
                )
                page.on("pageerror", lambda error: errors.append(str(error)))
                page.on(
                    "console",
                    lambda message: (
                        errors.append(message.text) if message.type == "error" else None
                    ),
                )

                def login(role):
                    page.goto(base + "/login")
                    page.get_by_label("이메일", exact=True).fill(f"{role}@example.com")
                    page.get_by_label("비밀번호", exact=True).fill(password)
                    page.get_by_role("button", name="로그인 →").click()
                    page.wait_for_url(base + "/")

                login("editor")
                page.goto(base + "/rates/new")
                for key, value in {
                    "code": "MORT-2026-001",
                    "title": "2026 표준 사망률 · 비흡연자",
                    "category": "개인 생명보험",
                    "granted": "검토 예제 2026-01",
                    "source": "RatingLog 합성 데이터 · 실제 계약 적용 금지",
                    "definition": "도달연령별 연간 사망확률을 관리하는 합성 위험률 표입니다.",
                    "effective_from": "2026-01-01",
                }.items():
                    page.locator("#" + key).fill(value)
                page.locator("#table_file").set_input_files(root / "examples/mortality.csv")
                page.locator("#attachment").set_input_files(
                    {
                        "name": "근거자료.pdf",
                        "mimeType": "application/pdf",
                        "buffer": b"%PDF-1.7\nsynthetic browser test",
                    }
                )
                page.get_by_role("button", name="초안으로 저장 →").click()
                page.wait_for_url(base + "/rates/1")
                expect(
                    page.get_by_role("heading", name="2026 표준 사망률 · 비흡연자")
                ).to_be_visible()
                expect(page.locator("[data-chart-summary]")).to_contain_text("3개 값")
                page.get_by_role("link", name="새 버전 작성", exact=True).click()
                page.locator("#comments").fill("근거파일 유지와 버전 보존 확인")
                page.locator("#change_reason").fill("검토용 설명 보완")
                page.get_by_role("button", name="초안으로 저장 →").click()
                page.wait_for_url(base + "/rates/1/versions/2")
                expect(page.get_by_text("근거자료.pdf", exact=True)).to_be_visible()
                page.locator("#reason").fill("연령별 위험률 및 단위 검토 요청")
                page.get_by_role("button", name="검토 요청 →").click()
                page.wait_for_url(base + "/rates/1")
                page.get_by_role("button", name="로그아웃", exact=True).click()
                login("reviewer")
                page.goto(base + "/rates/1")
                page.locator("#reason").fill("출처, CSV 범위 및 단위 검토 완료")
                page.get_by_role("button", name="승인", exact=True).click()
                page.wait_for_url(base + "/rates/1")
                expect(page.locator(".page-heading .badge")).to_have_text("승인")
                with page.expect_download() as info:
                    page.get_by_role("link", name="CSV 다운로드 ↓").click()
                download = info.value
                assert "age,sex,smoking,duration,rate" in Path(download.path()).read_text(
                    encoding="utf-8-sig"
                )
                page.screenshot(path=str(screenshots / "detail-desktop.png"), full_page=True)
                page.goto(base + "/")
                page.screenshot(path=str(screenshots / "dashboard-desktop.png"), full_page=True)
                page.set_viewport_size({"width": 390, "height": 844})
                page.goto(base + "/rates/1")
                assert page.evaluate("document.documentElement.scrollWidth <= innerWidth"), (
                    "Mobile page overflows viewport"
                )
                page.screenshot(path=str(screenshots / "detail-mobile.png"), full_page=True)
                assert not errors, errors
                browser.close()
        finally:
            server.shutdown()
            thread.join(timeout=5)
            server.server_close()
            with app.app_context():
                db.session.remove()
                db.engine.dispose()
    print(
        "Browser PASS: login, CSV+PDF upload, retained attachment, revision, submit, independent approval, chart, export, mobile layout; no console errors."
    )
    print(f"Screenshots: {screenshots}")


if __name__ == "__main__":
    run()
