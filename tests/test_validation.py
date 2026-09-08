import io
import zipfile
from decimal import Decimal

import pytest

from ratinglog.validation import parse_table, table_csv, validate_attachment

HEADER = b"age,sex,smoking,duration,rate\n"


@pytest.mark.parametrize(
    "line",
    [
        b"30,F,all,0,NaN",
        b"30,F,all,0,Infinity",
        b"30,F,all,0,-1",
        b"121,F,all,0,0.1",
        b"30,X,all,0,0.1",
        b"30,F,yes,0,0.1",
        b"30,F,all,-1,0.1",
        b"30,F,all,0,1.0001",
        b"30,F,all,0,0.1234567890123",
        b"30,F,all,0,",
        b"30,F,all,0,0.1,extra",
        b"30,F,all,0",
    ],
)
def test_invalid_table(line):
    with pytest.raises(ValueError):
        parse_table(HEADER + line + b"\n", "probability")


@pytest.mark.parametrize(
    "unit,value,expected",
    [
        ("probability", "1", "1"),
        ("percent", "100", "1"),
        ("per_thousand", "1", "0.001"),
        ("percent", "0.000000000001", "0.00000000000001"),
    ],
)
def test_precise_units(unit, value, expected):
    rows, _ = parse_table(HEADER + f"30,F,all,0,{value}\n".encode(), unit)
    assert rows[0]["probability"] == expected
    assert Decimal(rows[0]["rate"]) == Decimal(value)
    roundtrip, _ = parse_table(table_csv(rows).encode(), unit)
    assert roundtrip == rows


def test_duplicates_gaps_encoding_and_limits():
    with pytest.raises(ValueError, match="중복"):
        parse_table(HEADER + b"30,F,all,0,0.1\n30,F,all,0,0.2\n", "probability")
    rows, warnings = parse_table(
        b"\xef\xbb\xbf" + HEADER + b"30,F,all,0,0.1\n32,F,all,0,0.2\n", "probability"
    )
    assert warnings and len(rows) == 2
    for data in [HEADER, b"wrong,headers\n", b"\xff\xfe", HEADER + b"\x00"]:
        with pytest.raises(ValueError):
            parse_table(data, "probability")
    with pytest.raises(ValueError):
        parse_table(b"a" * (10 * 1024 * 1024 + 1), "probability")


def zip_content(name, content=b"evidence", mode=zipfile.ZIP_STORED):
    stream = io.BytesIO()
    with zipfile.ZipFile(stream, "w", compression=mode) as archive:
        archive.writestr(name, content)
    return stream.getvalue()


@pytest.mark.parametrize("name", ["../../evil", "/absolute", "C:/absolute", "..\\evil"])
def test_zip_path_traversal(name):
    with pytest.raises(ValueError):
        validate_attachment("evil.zip", zip_content(name))


def test_zip_bomb_and_bad_signatures():
    with pytest.raises(ValueError):
        validate_attachment("bomb.zip", zip_content("bomb", b"0" * 1000000, zipfile.ZIP_DEFLATED))
    for name, data in [
        ("a.zip", b"not a zip"),
        ("a.pdf", b"<script>evil</script>"),
        ("a.csv", b"\xff"),
        ("a.html", b"<html>"),
    ]:
        with pytest.raises(ValueError):
            validate_attachment(name, data)
    valid = validate_attachment("../../자료.zip", zip_content("docs/evidence.txt"))
    assert valid.filename == "자료.zip"
    assert len(valid.sha256) == 64
    assert valid.size == len(valid.content)


def test_zip_symlink():
    stream = io.BytesIO()
    info = zipfile.ZipInfo("link")
    info.create_system = 3
    info.external_attr = 0o120777 << 16
    with zipfile.ZipFile(stream, "w") as archive:
        archive.writestr(info, "/etc/passwd")
    with pytest.raises(ValueError):
        validate_attachment("links.zip", stream.getvalue())
