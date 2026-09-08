# ratinglog

사망률(mortality)·질병률(morbidity) 등 **위험률 관련 정보와 첨부 자료를 관리하는 웹 앱**입니다. 사용자가 로그인한 뒤 위험률의 제목, 인가정보, 범주, 정의, 설명, SQL 문구를 ZIP 파일과 함께 저장하고 조회합니다. Python 2와 Flask로 작성된 2014년 코드입니다.

위험률을 직접 계산하거나 그래프로 분석하는 기능은 없습니다. SQL 입력값은 문자열로 보관하며 실행하지 않습니다. 수정 시 기존 기록을 덮어쓰므로 변경 이력을 버전별로 보존하는 기능도 없습니다.

## 주요 기능

- 회원가입, 아이디 중복 확인, 로그인·로그아웃, 개인정보 수정, 회원 탈퇴
- 로그인한 사용자의 위험률 목록 조회: 등록/수정 시각 내림차순, 기본 10개씩 표시
- 제목 또는 범주에 포함된 문자열로 검색
- 위험률 등록·수정·삭제 및 ZIP 첨부파일 업로드·다운로드
- OAuth를 통한 Twitter 연동 코드: 항목 제목과 전송 시각을 게시하며, 첨부파일을 전송하지 않음

현재 폼 검증상 모든 텍스트 항목과 ZIP 파일을 입력해야 하며, **수정할 때도 ZIP 파일을 다시 선택해야 합니다.**

| 필드 | 의미 | 입력 길이 |
| --- | --- | --- |
| `priority` | 우선순위 | 1자 |
| `title` | 제목 | 1~100자 |
| `granted` | 인가정보/인가번호 | 1~20자 |
| `category` | 범주 | 1~20자 |
| `definition` | 정의 | 1~400자 |
| `comments` | 내용/설명 | 1~400자 |
| `sql` | 관련 SQL 문구 | 1~400자 |
| `uploadfile` | ZIP 첨부파일 | 전체 HTTP 요청 크기 최대 10 MiB |

## 구성

| 경로 | 역할 |
| --- | --- |
| `runserver.py` | 앱 생성 및 개발 서버 실행 진입점 |
| `ratinglog/__init__.py` | Flask 앱 팩토리, 설정·로그·DB·세션 초기화 |
| `ratinglog/config.py` | 기본 설정 |
| `ratinglog/database.py` | SQLAlchemy 연결 및 테이블 자동 생성 |
| `ratinglog/model/user.py` | 사용자 모델 (`users`) |
| `ratinglog/model/rate.py` | 위험률 및 첨부파일 메타데이터 모델 (`rates`) |
| `ratinglog/controller/` | 인증, 사용자 관리, 위험률 CRUD, 검색, Twitter 연동 |
| `ratinglog/cache_session.py` | 서버 메모리 기반 세션, 선택 가능한 Redis 구현 |
| `ratinglog/templates/` | Jinja2 HTML 화면 |
| `ratinglog/static/` | Bootstrap, Font Awesome, JavaScript, CSS |
| `requirements.txt` | 버전이 고정되지 않은 원래 의존성 목록 |

기본 DB는 SQLite이므로 별도 DB 서버가 필요 없습니다. 세션은 `SimpleCache`를 사용하므로 Redis도 기본 실행에는 필요 없습니다. 별도 프런트엔드 빌드 과정은 없으며, 화면의 jQuery는 Google CDN에서 불러옵니다.

## 로컬 실행 방법

### 1. Python 2.7 환경 준비

`print` 문, `reload(sys)`, `sys.setdefaultencoding`, `unicode`, `xrange` 등 Python 2 전용 코드가 있어 Python 3에서 그대로 실행할 수 없습니다. `werkzeug.contrib.cache`와 구형 Flask 오류 처리 API도 사용합니다.

아래는 **Python 2.7과 pip가 준비된 macOS/Linux 환경에서 사용할 레거시 재현 절차**입니다. 현재 리뷰 환경에는 Python 2 실행기가 없어 실제 설치 및 서버 구동은 검증하지 못했습니다. 아래 버전 조합은 코드의 구형 API에 맞춘 재현용 예시이며, 검증된 잠금 파일은 아닙니다.

Python 2 및 오래된 의존성을 사용하는 앱이므로 격리된 로컬 환경에서 샘플 데이터로 확인하세요. 외부 서비스로 운영하려면 아래 리뷰 항목을 먼저 해결해야 합니다.

```bash
git clone https://github.com/kimdongup/ratinglog.git
cd ratinglog

python2.7 --version
python2.7 -m pip install 'virtualenv==16.7.12'
python2.7 -m virtualenv .venv
source .venv/bin/activate

python -m pip install 'pip==20.3.4' 'setuptools==44.1.1' 'wheel==0.37.1'
python -m pip install \
  'Flask==0.10.1' \
  'Werkzeug==0.16.1' \
  'Jinja2==2.11.3' \
  'MarkupSafe==1.1.1' \
  'itsdangerous==1.1.0' \
  'SQLAlchemy==1.3.24' \
  'WTForms==2.2.1' \
  'twython==3.8.2' \
  'requests==2.27.1' \
  'requests-oauthlib==1.3.1' \
  'oauthlib==3.1.0'
python -m pip check
```

`requirements.txt`에는 버전 제한과 잠금 파일이 없고 `PIL`도 포함되어 있습니다. 현재 앱 코드에는 PIL import나 이미지 처리 기능이 없어 위 설치 예시에서는 제외했습니다. 원본 목록을 최신 Python에서 그대로 설치하는 방식으로는 실행 환경을 재현할 수 없습니다. Twython은 Twitter 버튼을 사용하지 않아도 컨트롤러 로딩 시 import하므로 설치해야 합니다. [Flask 0.10.1 배포 정보](https://pypi.org/project/Flask/0.10.1/), [Twython의 Python 2 지원 안내](https://pypi.org/project/twython/)를 참고하세요.

### 2. 저장 폴더와 로컬 설정 준비

저장소 루트에서 실행합니다. 앱은 아래 폴더를 자동으로 만들지 않습니다.

```bash
mkdir -p ratinglog/resource/database ratinglog/resource/log \
  ratinglog/resource/upload ratinglog/resource/tmp
```

선택 설정 파일은 **`ratinglog/resource/config.cfg`**입니다. 프로젝트 루트의 `resource/config.cfg`가 아니라 Flask 패키지 폴더 기준으로 읽습니다. 파일이 없으면 기본 설정을 사용합니다. 로컬 확인용 예시는 다음과 같습니다.

```python
# ratinglog/resource/config.cfg
DB_LOG_FLAG = 'False'
TWIT_APP_KEY = ''
TWIT_APP_SECRET = ''
TWIT_CALLBACK_SERVER = 'http://127.0.0.1:5000'
```

`DB_LOG_FLAG`는 코드에서 `eval()`에 전달하므로 불리언 `False`가 아닌 문자열 `'False'`로 작성해야 합니다. `.env` 또는 설정용 환경변수를 자동으로 읽는 기능은 구현되어 있지 않습니다. 위 빈 Twitter 키는 기본값을 덮어쓰며 Twitter 인증에는 사용할 수 없습니다.

| 설정 | 기본값/동작 |
| --- | --- |
| `DB_URL` | `sqlite:///` |
| `DB_FILE_PATH` | `resource/database/ratinglog` |
| `LOG_FILE_PATH` | `resource/log/ratinglog.log` |
| `UPLOAD_FOLDER` | `resource/upload/` — 경로를 문자열로 연결하는 코드가 있어 끝의 `/` 유지 |
| `TMP_FOLDER` | `resource/tmp/` — 설정은 있지만 현재 업로드 흐름에서는 사용하지 않음 |
| `MAX_CONTENT_LENGTH` | `10 * 1024 * 1024` 바이트, 파일뿐 아니라 요청 전체에 적용 |
| `PER_PAGE` | `10` |
| `PERMANENT_SESSION_LIFETIME` | `3600`초, 서버 캐시의 세션 보존 시간 |
| `SESSION_COOKIE_NAME` | `ratinglog_session` |

DB·로그·업로드의 상대 경로는 모두 `ratinglog/` 패키지 폴더를 기준으로 해석합니다. 첫 앱 초기화 때 SQLite 파일과 `users`, `rates` 테이블을 자동 생성합니다. 초기 계정이나 샘플 데이터는 없습니다. 로컬 설정, DB, 업로드 파일, 로그, `.venv`는 Git에 커밋하지 마세요.

### 3. 서버 시작

로컬 루프백 주소에만 바인딩하고 디버그 모드를 끄려면 다음과 같이 실행합니다.

```bash
python -c "from runserver import application; application.run(host='127.0.0.1', port=5000, debug=False)"
```

브라우저에서 <http://127.0.0.1:5000>에 접속합니다. 원래 진입점인 `python runserver.py`도 있지만, 해당 명령은 **`0.0.0.0:5000`, `debug=True`**로 실행하므로 다른 기기에서 접근할 수 있습니다. 종료는 `Ctrl+C`입니다.

### 4. 사용 순서와 수동 확인

1. `/user/regist`에서 사용자명 중복 확인 후 회원가입합니다. 사용자명과 비밀번호는 각각 4~50자이며 이메일과 비밀번호 확인도 필요합니다.
2. `/user/login`에서 로그인하면 위험률 목록으로 이동합니다.
3. 상단 **위험률 정보등록**에서 모든 텍스트 항목과 작은 ZIP 파일을 입력해 저장합니다.
4. **위험률 목록보기**에서 항목을 확인하고 제목/범주로 검색합니다.
5. 목록의 행을 눌러 상세 내용을 확인하고 첨부파일을 내려받습니다. 수정 저장 시에는 ZIP 파일을 다시 선택합니다.
6. 샘플 항목 삭제와 로그아웃을 확인합니다.

Twitter 연동은 선택 기능이며 이번 리뷰에서는 인증·전송을 검증하지 않았습니다. 사용하려면 본인 앱의 키와 실제 콜백 서버 주소를 설정하고 `/sns/twitter/callback/<Rate_id>` 형태의 콜백 및 외부 API 호환성을 별도로 확인해야 합니다.

## 코드 리뷰에서 확인한 제약

아래는 현재 코드에서 확인한 사항이며, 이 README 작성 과정에서 앱 코드를 수정하지는 않았습니다.

| 우선순위 | 확인 사항 | 근거 및 영향 |
| --- | --- | --- |
| 높음 | 항목 소유권 검사 누락 | `item_register.py`, `item_show.py`, `twitter.py`의 ID 기반 접근은 로그인만 검사합니다. 다른 사용자의 ID로 조회·수정·삭제·다운로드·전송을 요청할 수 있어 `user_id` 검증이 필요합니다. |
| 높음 | 사용자 정보 수정 권한 검사 누락 | `register_user.py`의 `/user/<username>`은 현재 로그인 계정과 대상 계정이 같은지 확인하지 않아 다른 계정의 이메일·비밀번호를 바꿀 수 있습니다. |
| 높음 | 인증정보 노출 | `config.py`에 Twitter 인증정보가 하드코딩되어 있고 `print_settings()`는 모든 설정을 출력합니다. OAuth 콜백 값도 로그에 남깁니다. 기존 키 폐기·재발급, 비밀값 분리, 로그 마스킹이 필요합니다. |
| 높음 | CSRF 보호 부재 | 일반 WTForms `Form`을 사용하며 CSRF 토큰 검증이 없습니다. 삭제·탈퇴·트윗 전송은 GET 요청으로 수행됩니다. |
| 중간 | 로그인 후 이동 URL 검증 부재 | `login.py`가 폼의 `next_url`로 바로 리다이렉트하므로 외부 주소로 유도될 수 있습니다. |
| 중간 | 페이지 수 계산 오류 | `show_all()`은 전체 사용자의 항목 수로 페이지 수를 계산하지만 실제 목록에는 현재 사용자 항목만 표시합니다. |
| 중간 | 파일과 DB의 변경 불일치 가능성 | 수정은 DB 커밋 전에 기존 파일을 삭제하고, 삭제는 DB 커밋 후 파일을 삭제합니다. 중간 실패 시 DB와 파일 상태가 어긋날 수 있습니다. |
| 중간 | 세션의 프로세스 의존성 | 기본 `SimpleCache` 세션은 재시작하면 사라지고 여러 프로세스 사이에 공유되지 않습니다. |
| 중간 | 실행 환경 재현성 부족 | Python 2 전용 문법, 제거된 라이브러리 API, 버전 미고정 의존성 때문에 현대 환경으로 이식하거나 별도 레거시 환경을 준비해야 합니다. |

특히 목록이 사용자별로 필터링된다고 해서 개별 항목 접근까지 안전한 것은 아닙니다. 현재 상태로 여러 사용자의 실제 자료를 보관하는 공개 서비스로 운영하기에는 권한 및 인증 관련 보완이 필요합니다.

## 실행 중 문제 해결

| 증상 | 확인할 사항 |
| --- | --- |
| `SyntaxError` 또는 `reload`/`unicode`/`xrange` 오류 | Python 3로 실행 중인지 확인합니다. 현재 원본은 Python 2.7용입니다. |
| `No module named werkzeug.contrib` 또는 `TextField` import 오류 | 최신 Werkzeug/WTForms가 설치되었는지 확인합니다. 위 레거시 버전 예시를 참고하세요. |
| 로그 파일 관련 `No such file or directory` | `ratinglog/resource/log` 폴더를 먼저 만듭니다. |
| SQLite `unable to open database file` | `ratinglog/resource/database` 폴더와 쓰기 권한을 확인합니다. |
| 업로드/수정 시 `illegal file` | ZIP 확장자 파일을 선택했는지 확인합니다. 수정 시에도 파일을 다시 첨부해야 합니다. |
| HTTP 413 | ZIP과 폼 데이터를 합친 요청이 10 MiB를 넘는지 확인합니다. |
| 화면 버튼이나 중복 확인이 동작하지 않음 | Google CDN에서 jQuery를 불러올 수 있는지 브라우저 개발자 도구로 확인합니다. |
| 재시작 후 로그아웃됨 | 메모리 세션을 사용하므로 다시 로그인해야 합니다. |

검증 범위: GitHub 원본과 로컬 소스의 일치 여부 및 코드·템플릿·설정의 정적 리뷰. 자동화 테스트는 저장소에 없으며, 위 실행 절차와 수동 확인 항목은 실제 구동 검증이 남아 있습니다.
