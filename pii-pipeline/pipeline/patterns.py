import re

from pipeline.tokenizer import TOKEN_HEX, TOKEN_PREFIX

TOKEN = re.compile(rf"^{TOKEN_PREFIX}[0-9a-f]{{{TOKEN_HEX}}}$")

# formats that must never show up in an exported cell
IDENTIFIERS = {
    "주민등록번호": re.compile(r"\d{6}-[1-4][\dX*]{6}"),
    "휴대전화 번호": re.compile(r"01[016789]-\d{3,4}-\d{4}"),
    "이메일": re.compile(r"[\w.+-]+@[\w-]+\.[\w.]+"),
}

GENERALIZED = {
    "sigungu": (re.compile(r"^[^\s\d]+ [^\s\d]+$"), "시군구"),
    "month": (re.compile(r"^\d{4}-(0[1-9]|1[0-2])$"), "월"),
    "year": (re.compile(r"^\d{4}$"), "연도"),
    "age_band": (re.compile(r"^(\d+~\d+세|90세 이상)$"), "5세 구간"),
}
