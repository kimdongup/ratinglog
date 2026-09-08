import csv
import hashlib
import io
import re
import stat
import zipfile
from collections import defaultdict
from decimal import Decimal, InvalidOperation
from pathlib import PurePosixPath

from .models import Attachment

HEADERS = ["age", "sex", "smoking", "duration", "rate"]
MAX_FILE = 10 * 1024 * 1024
DIVISORS = {"probability": Decimal(1), "percent": Decimal(100), "per_thousand": Decimal(1000)}


def decimal_text(value):
    return format(value.normalize(), "f")


def parse_table(content, unit):
    if unit not in DIVISORS:
        raise ValueError("올바른 위험률 단위를 선택하세요.")
    if len(content) > MAX_FILE:
        raise ValueError("CSV 파일은 10 MiB 이하만 가능합니다.")
    try:
        source = content.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise ValueError("CSV는 UTF-8 인코딩이어야 합니다.") from exc
    if "\x00" in source:
        raise ValueError("CSV에 NUL 문자가 포함되어 있습니다.")
    reader = csv.DictReader(io.StringIO(source, newline=""), strict=True)
    rows, seen = [], set()
    try:
        if reader.fieldnames != HEADERS:
            raise ValueError("CSV 헤더는 age,sex,smoking,duration,rate 순서여야 합니다.")
        for index, row in enumerate(reader, start=2):
            if len(rows) >= 10000:
                raise ValueError("CSV는 최대 10,000행입니다.")
            if None in row or any(value is None or not value.strip() for value in row.values()):
                raise ValueError(f"{index}행: 누락된 값 또는 열 개수 오류입니다.")
            row = {key: value.strip() for key, value in row.items()}
            for key in ("age", "duration"):
                if not re.fullmatch(r"\d{1,3}", row[key]) or not 0 <= int(row[key]) <= 120:
                    raise ValueError(f"{index}행: {key}는 0~120 정수여야 합니다.")
                row[key] = int(row[key])
            if row["sex"] not in ("F", "M", "U"):
                raise ValueError(f"{index}행: sex는 F, M, U 중 하나여야 합니다.")
            if row["smoking"] not in ("non_smoker", "smoker", "all"):
                raise ValueError(f"{index}행: smoking 값이 올바르지 않습니다.")
            if not re.fullmatch(r"\d{1,4}(?:\.\d{1,12})?", row["rate"]):
                raise ValueError(
                    f"{index}행: rate는 소수점 이하 12자리 이내의 비음수 십진수여야 합니다."
                )
            try:
                value = Decimal(row["rate"])
            except InvalidOperation as exc:
                raise ValueError(f"{index}행: 위험률 숫자를 확인하세요.") from exc
            if not value.is_finite() or not 0 <= value <= DIVISORS[unit]:
                raise ValueError(f"{index}행: rate가 선택한 단위의 범위를 벗어났습니다.")
            key = row_key(row)
            if key in seen:
                raise ValueError(f"{index}행: 연령·성별·흡연·경과기간 조합이 중복됩니다.")
            seen.add(key)
            row["rate"] = decimal_text(value)
            row["probability"] = decimal_text(value / DIVISORS[unit])
            rows.append(row)
    except csv.Error as exc:
        raise ValueError("CSV 구문 오류 또는 너무 긴 셀입니다.") from exc
    if not rows:
        raise ValueError("수치표에는 최소 1행이 필요합니다.")
    groups = defaultdict(list)
    for row in rows:
        groups[(row["sex"], row["smoking"], row["duration"])].append(row["age"])
    gaps = sum(
        any(b - a > 1 for a, b in zip(sorted(ages), sorted(ages)[1:], strict=False))
        for ages in groups.values()
    )
    warnings = (
        [f"{gaps}개 차원 그룹에서 연령 간격이 발견되었습니다. 보간 없이 원본을 보관합니다."]
        if gaps
        else []
    )
    return sorted(rows, key=row_key), warnings


def row_key(row):
    return row["age"], row["sex"], row["smoking"], row["duration"]


def table_csv(rows):
    output = io.StringIO(newline="")
    writer = csv.DictWriter(output, fieldnames=HEADERS, extrasaction="ignore")
    writer.writeheader()
    writer.writerows(rows)
    return output.getvalue()


def validate_attachment(filename, content):
    if not content or len(content) > MAX_FILE:
        raise ValueError("첨부파일은 비어 있지 않은 10 MiB 이하 파일이어야 합니다.")
    name = filename.replace("\\", "/").split("/")[-1]
    name = "".join(ch for ch in name if ch.isprintable()).strip()[:200]
    if not name or "." not in name:
        raise ValueError("첨부파일 이름과 확장자를 확인하세요.")
    suffix = name.rsplit(".", 1)[-1].lower()
    mimetype = {"pdf": "application/pdf", "csv": "text/csv", "zip": "application/zip"}.get(suffix)
    if not mimetype:
        raise ValueError("첨부파일은 PDF, CSV, ZIP만 가능합니다.")
    if suffix == "pdf" and not content.startswith(b"%PDF-"):
        raise ValueError("PDF 파일 내용이 올바르지 않습니다.")
    if suffix == "csv":
        try:
            value = content.decode("utf-8-sig")
            if "\x00" in value:
                raise ValueError("CSV에 NUL 문자가 포함되어 있습니다.")
        except UnicodeDecodeError as exc:
            raise ValueError("CSV 첨부파일은 UTF-8이어야 합니다.") from exc
    if suffix == "zip":
        try:
            with zipfile.ZipFile(io.BytesIO(content)) as archive:
                items = archive.infolist()
                if not items or len(items) > 1000:
                    raise ValueError("ZIP 항목 수는 1~1,000개여야 합니다.")
                total = 0
                for item in items:
                    path = PurePosixPath(item.filename.replace("\\", "/"))
                    if (
                        path.is_absolute()
                        or ".." in path.parts
                        or ":" in item.filename
                        or "\x00" in item.filename
                    ):
                        raise ValueError("ZIP에 허용하지 않는 파일 경로가 있습니다.")
                    if stat.S_ISLNK(item.external_attr >> 16) or item.flag_bits & 1:
                        raise ValueError("ZIP 심볼릭 링크 또는 암호화 항목은 허용하지 않습니다.")
                    total += item.file_size
                    if (
                        total > 50 * 1024 * 1024
                        or item.file_size > max(1, item.compress_size) * 100
                    ):
                        raise ValueError("ZIP의 압축 해제 크기 또는 압축률이 한도를 초과했습니다.")
                # Stream bounded contents for CRC validation; never extract to disk.
                count = 0
                for item in items:
                    if not item.is_dir():
                        with archive.open(item) as stream:
                            while block := stream.read(65536):
                                count += len(block)
                                if count > 50 * 1024 * 1024:
                                    raise ValueError("ZIP 해제 크기 한도를 초과했습니다.")
        except (zipfile.BadZipFile, NotImplementedError, RuntimeError, OSError) as exc:
            raise ValueError("ZIP 파일이 손상되었거나 지원하지 않는 형식입니다.") from exc
    return Attachment(
        filename=name,
        mimetype=mimetype,
        size=len(content),
        sha256=hashlib.sha256(content).hexdigest(),
        content=content,
    )
