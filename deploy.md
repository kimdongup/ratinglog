# 배포와 운영

## 환경

Python 3.13 이상, Flask WSGI 앱입니다. 로컬은 SQLite, 운영은 PostgreSQL과 Redis를 사용합니다. 운영 파일은 DB에 함께 저장하므로 별도 공유 업로드 볼륨이 필요 없습니다. 대용량 자료는 외부 객체 저장소와 별도 검사 파이프라인 도입을 검토하세요.

필수 환경변수는 `.env.example`에 설명되어 있습니다. `APP_ENV=production`에서는 충분히 긴 `SECRET_KEY`, PostgreSQL `DATABASE_URL`, Redis `RATELIMIT_STORAGE_URI`, `TRUSTED_HOSTS`를 검증합니다. HTTPS 쿠키가 강제되며 개발 서버나 디버그 모드는 운영에 사용하지 않습니다.

## 설치 및 실행

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
# .env 또는 프로세스 환경에 운영 설정 주입
flask --app ratinglog db upgrade
flask --app ratinglog create-user --email admin@example.com --name 관리자 --role admin
gunicorn 'ratinglog:create_app()' --bind 127.0.0.1:8000 --workers 2 --threads 4 --timeout 60 --access-logfile -
```

서버를 열기 전에 마이그레이션을 한 프로세스에서 실행합니다. 앱 시작 시 테이블 생성이나 데이터 변경은 하지 않습니다. Gunicorn 앞에서 Nginx/Caddy 등의 HTTPS 역방향 프록시를 운영하고 업로드 한도를 12 MiB에 맞추세요. `PROXY_HOPS=1`은 신뢰하는 프록시가 하나이고 직접 접근을 차단했을 때만 설정합니다. 기본은 0입니다. 프록시는 외부에서 받은 전달 헤더를 덮어써야 합니다.

`GET /health/live`는 프로세스 상태, `GET /health/ready`는 DB와 운영 Redis 연결을 검사합니다. 응답에 접속정보나 오류 상세를 노출하지 않습니다. 실행 계정은 최소 DB 권한을 사용하고 마이그레이션 권한은 가능하면 별도 관리하세요.

## 사용자 관리

```bash
flask --app ratinglog create-user --email writer@example.com --name 작성자 --role editor
flask --app ratinglog create-user --email reviewer@example.com --name 검토자 --role reviewer
flask --app ratinglog reset-password --email writer@example.com
```

비밀번호는 숨겨진 확인 프롬프트로 입력합니다. 임의의 기본 관리자나 공용 비밀번호를 생성하지 않습니다. 웹 사용자 관리에서는 관리자 계정 변경을 제한하고 일반 계정의 역할·활성 상태를 관리합니다.

## 백업과 복원

첨부파일·수치표·감사 기록·계정은 모두 DB에 있습니다. DB와 비밀키를 서로 다른 보호된 위치에 백업합니다. 감사 기록은 앱에서 수정/삭제할 수 없지만 DB 관리자에 대한 암호학적 위변조 방지를 제공하지는 않습니다.

SQLite는 앱을 중지하거나 SQLite 온라인 백업 API를 사용합니다.

```bash
python - <<'PYSQL'
import sqlite3
from contextlib import closing
with closing(sqlite3.connect('instance/ratinglog.sqlite')) as source:
    with closing(sqlite3.connect('backup.sqlite')) as target:
        source.backup(target)
PYSQL
```

PostgreSQL 예시(비밀번호는 `.pgpass`/비밀 저장소 사용):

```bash
pg_dump --format=custom --file=ratinglog.dump "$PG_DSN"
# 새 빈 DB에 복원 후 마이그레이션 버전 및 기능 확인
pg_restore --no-owner --dbname="$RESTORE_PG_DSN" ratinglog.dump
```

복원 연습에서는 원장 개수, 버전, 첨부 SHA-256, 역할별 접근, 승인표 조회를 확인합니다. Redis는 속도 제한용이며 원장 데이터의 원본이 아닙니다. 키 교체 시 모든 사용자에게 재로그인이 필요합니다.

## 기존 Python 2 앱 이관

기존 서버를 정지하고 SQLite 파일 및 업로드 폴더를 백업합니다. 새 DB에 스키마와 가져오기 담당 관리자 계정을 만든 후 실행합니다.

```bash
flask --app ratinglog import-legacy   --database /backup/ratinglog   --uploads /backup/upload   --owner admin@example.com
```

이관은 읽기 전용 SQLite 연결을 사용합니다. 옛 사용자별 자동 계정을 만들지 않고 지정한 소유자 아래 `LEGACY-<id>` 코드로 문서형 초안을 생성합니다. 원래 사용자 ID·시각·내용·SQL 문구를 버전 설명에 보존합니다. 비밀번호·Twitter 비밀키는 가져오지 않습니다. 첨부 경로 이탈이나 검사 실패·누락 파일은 전체 이관을 롤백하여 조용한 자료 손실을 방지합니다. 재실행 시 이미 존재하는 코드도 오류로 중단하므로 중복 적재하지 않습니다. ZIP 크기·안전성 문제는 백업 사본을 검토·정리한 후 재시도하세요. 이관 자료는 검토·승인 전까지 조직에 공개하지 않습니다.

## 배포 확인

```bash
pytest
ruff check .
ruff format --check .
pip-audit -r requirements.txt
flask --app ratinglog db current
```

HTTPS 로그인, CSRF 거절, 권한별 자료 접근, 제출·다른 계정 승인, CSV 오류, 다운로드, 보관/복원, 백업/복원을 스테이징에서 확인한 뒤 운영 트래픽을 연결합니다. 테스트 결과와 실제 운영환경 검증 여부는 README에 별도 기록합니다.

## 테스트 전용 운영 구성 검증

기존 운영 DB를 지정하지 마세요. 테스트 스크립트는 지정 DB에 임시 스키마를 만들고 끝나면 해당 스키마를 제거합니다. Redis는 고유 키 접두어와 만료 시간을 사용합니다.

```bash
export TEST_DATABASE_URL='postgresql+psycopg://test_user:test_password@127.0.0.1:5432/test_db'
export TEST_REDIS_URL='redis://127.0.0.1:6379/0'
pytest
PYTHONPATH=. python scripts/production_smoke.py
```

기본 `pytest`는 `TEST_DATABASE_URL`이 없으면 SQLite 임시 DB를 사용합니다. PostgreSQL 테스트 계정에는 테스트 DB 안의 스키마 생성 권한이 필요합니다. 각 테스트는 고유 스키마로 격리됩니다.

과거 Git 이력에 있던 Twitter 인증키는 새 코드에서 제거했으며 더 이상 사용하지 않습니다. 이미 공개된 키의 폐기는 제공자 콘솔에서 소유자가 처리해야 합니다. Git 이력 재작성은 하지 않습니다. CLI 감사 이벤트는 대상 계정과 CLI 수행 사실을 기록하며 실제 OS 운영자 식별은 서버의 접근·명령 감사 기록과 함께 확인해야 합니다.
