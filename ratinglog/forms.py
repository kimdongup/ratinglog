from flask_wtf import FlaskForm
from flask_wtf.file import FileField
from wtforms import (
    BooleanField,
    DateField,
    HiddenField,
    IntegerField,
    PasswordField,
    SelectField,
    StringField,
    TextAreaField,
)
from wtforms.validators import (
    DataRequired,
    Email,
    EqualTo,
    InputRequired,
    Length,
    NumberRange,
    Optional,
    Regexp,
    ValidationError,
)

from .models import KINDS, ROLES, UNITS


def stripped(value):
    return value.strip() if value else ""


class LoginForm(FlaskForm):
    email = StringField(
        "이메일", validators=[DataRequired(), Email(), Length(max=254)], filters=[stripped]
    )
    password = PasswordField("비밀번호", validators=[DataRequired(), Length(max=128)])


class PasswordForm(FlaskForm):
    current_password = PasswordField("현재 비밀번호", validators=[DataRequired(), Length(max=128)])
    password = PasswordField("새 비밀번호", validators=[DataRequired(), Length(min=12, max=128)])
    confirm = PasswordField(
        "새 비밀번호 확인",
        validators=[DataRequired(), EqualTo("password", message="비밀번호가 일치하지 않습니다.")],
    )


class UserForm(FlaskForm):
    email = StringField(
        "이메일", validators=[DataRequired(), Email(), Length(max=254)], filters=[stripped]
    )
    name = StringField("이름", validators=[DataRequired(), Length(max=80)], filters=[stripped])
    role = SelectField("역할", choices=[(r, r) for r in ROLES if r != "admin"])
    password = PasswordField("초기 비밀번호", validators=[DataRequired(), Length(min=12, max=128)])


class UserAccessForm(FlaskForm):
    role = SelectField("역할", choices=[(r, r) for r in ROLES if r != "admin"])
    active = BooleanField("활성 계정")
    reason = StringField(
        "변경 사유", validators=[DataRequired(), Length(max=1000)], filters=[stripped]
    )
    version = HiddenField(validators=[DataRequired()])


class RateForm(FlaskForm):
    code = StringField(
        "원장 코드",
        validators=[
            DataRequired(),
            Length(max=64),
            Regexp(r"^[A-Z0-9][A-Z0-9_-]*$", message="영문 대문자·숫자·밑줄·하이픈만 사용하세요."),
        ],
        filters=[stripped],
    )
    title = StringField(
        "위험률 제목", validators=[DataRequired(), Length(max=200)], filters=[stripped]
    )
    kind = SelectField(
        "위험률 종류",
        choices=[
            (k, label)
            for k, label in zip(
                KINDS, ("사망률", "질병률", "장해율", "해지율", "기타"), strict=True
            )
        ],
    )
    category = StringField(
        "범주 / 상품군", validators=[DataRequired(), Length(max=80)], filters=[stripped]
    )
    priority = SelectField(
        "우선순위",
        choices=[
            (str(i), f"{i} · " + ("높음" if i == 1 else "낮음" if i == 5 else "보통"))
            for i in range(1, 6)
        ],
        default="3",
    )
    granted = StringField("인가정보", validators=[Optional(), Length(max=120)], filters=[stripped])
    source = StringField(
        "출처 / 근거", validators=[DataRequired(), Length(max=500)], filters=[stripped]
    )
    definition = TextAreaField(
        "정의", validators=[DataRequired(), Length(max=10000)], filters=[stripped]
    )
    comments = TextAreaField(
        "설명 / 검토 참고", validators=[Optional(), Length(max=10000)], filters=[stripped]
    )
    sql_note = TextAreaField(
        "SQL 참고문구 (실행하지 않음)",
        validators=[Optional(), Length(max=10000)],
        filters=[stripped],
    )
    effective_from = DateField("적용 시작일", validators=[InputRequired()])
    effective_to = DateField("적용 종료일", validators=[Optional()])
    data_type = SelectField("자료 유형", choices=[("table", "수치표"), ("document", "문서")])
    unit = SelectField(
        "위험률 단위",
        choices=list(zip(UNITS, ("확률 (0~1)", "퍼센트 (0~100)", "천분율 (0~1000)"), strict=True)),
    )
    table_file = FileField("수치표 CSV")
    attachment = FileField("근거 첨부파일 (PDF / CSV / ZIP)")
    change_reason = TextAreaField(
        "변경 사유", validators=[DataRequired(), Length(max=1000)], filters=[stripped]
    )
    version = HiddenField(default="0", validators=[DataRequired()])

    def validate_effective_to(self, field):
        if field.data and self.effective_from.data and field.data < self.effective_from.data:
            raise ValidationError("종료일은 시작일 이후여야 합니다.")


class ActionForm(FlaskForm):
    version = IntegerField(validators=[InputRequired(), NumberRange(min=1)])
    reason = TextAreaField(
        "사유", validators=[DataRequired(), Length(max=1000)], filters=[stripped]
    )
