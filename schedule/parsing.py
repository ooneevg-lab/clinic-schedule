"""Парсинг Excel-расписания из 1С + нормализация имён врачей.

Копия проверенной логики из clinic_queue/patients/schedule_upload.py
(parse_patient_cell / parse_workbook) + склеенный ключ для сопоставления
«ФИО из админки == заголовок колонки» без учёта пробелов/точек/знаков.
"""

import re
from datetime import time as dt_time
from io import BytesIO

import pandas as pd

CYRILLIC_WORD = r"[А-ЯЁа-яё][А-ЯЁа-яё\-]+"
FIO_RE = re.compile(rf"^{CYRILLIC_WORD}(?:\s+{CYRILLIC_WORD}){{1,}}(?:\s+[А-ЯЁа-яё]\.?[А-ЯЁа-яё]?\.?)?$")
PHONE_RE = re.compile(r"^\s*тел\.?\s*", re.IGNORECASE)
AGE_RE = re.compile(r"\b\d{4}\s*г\.?\s*р\.?\s*\([^)]*(?:год|лет|года)[^)]*\)", re.IGNORECASE)
RANGE_RE = re.compile(r"\bс\s*(\d{1,2}):(\d{2})\s*до\s*\d{1,2}:\d{2}", re.IGNORECASE)
TIME_ONLY_RE = re.compile(r"^\s*\d{1,2}:\d{2}\s*$")
SKIP_MARKERS = {"не записывать!", "не записывать", "мазок", "холтер", "спирография", "сбор биоматериала"}


def normalize_doctor_key(value):
    """Склеенный ключ: lower + ё→е + только буквы/цифры.

    «Иванова А.А.» и «  иванова  А А » → одно и то же «ивановааа».
    Применяется ОДИНАКОВО к schedule_name врача и к заголовку колонки.
    """
    text = (value or "").strip().casefold().replace("ё", "е")
    return re.sub(r"[^а-яa-z0-9]+", "", text)


def _is_service_marker(value):
    text = re.sub(r"\b\d{1,2}:\d{2}\b", " ", str(value or "").casefold())
    text = re.sub(r"[^а-яё]+", " ", text).strip()
    if not text:
        return False
    for marker in SKIP_MARKERS - {"не записывать!", "не записывать"}:
        normalized = re.sub(r"[^а-яё]+", " ", marker).strip()
        remainder = text
        while normalized and normalized in remainder:
            remainder = remainder.replace(normalized, " ", 1)
            remainder = re.sub(r"\s+", " ", remainder).strip()
        if not remainder:
            return True
    return False


def _text(value):
    if value is None or pd.isna(value):
        return ""
    return str(value).strip()


def _clock(hour_value, minute_value):
    hour_text, minute_text = _text(hour_value), _text(minute_value)
    joined = hour_text if ":" in hour_text else f"{hour_text}:{minute_text}"
    match = re.search(r"(\d{1,2}):(\d{1,2})", joined)
    if not match:
        return None
    hour, minute = int(match.group(1)), int(match.group(2))
    return dt_time(hour, minute) if hour < 24 and minute < 60 else None


def parse_patient_cell(value, fallback_time=None):
    raw = _text(value)
    if not raw or TIME_ONLY_RE.fullmatch(raw) or raw.casefold() in SKIP_MARKERS:
        return None
    lines = [line.strip() for line in raw.replace("\r", "\n").split("\n") if line.strip()]
    if any(line.casefold() in {"не записывать!", "не записывать"} for line in lines):
        return None

    full_name = None
    age = None
    cell_time = None
    remaining = []
    for line in lines:
        if _is_service_marker(line):
            continue
        if PHONE_RE.match(line):
            continue
        age_match = AGE_RE.search(line)
        if age_match:
            age = age_match.group(0).strip()
            continue
        range_match = RANGE_RE.search(line)
        if range_match:
            hour, minute = int(range_match.group(1)), int(range_match.group(2))
            if hour < 24 and minute < 60:
                cell_time = dt_time(hour, minute)
            continue
        if TIME_ONLY_RE.fullmatch(line):
            continue
        candidate = re.sub(r"\s+", " ", line).strip(" ,;")
        if full_name is None and FIO_RE.fullmatch(candidate):
            full_name = candidate
        else:
            remaining.append(candidate)
    if full_name is None:
        return None
    services = [line for line in remaining if line.casefold() not in SKIP_MARKERS]
    return {
        "full_name": full_name,
        "age": age,
        "appointment_time": cell_time or fallback_time,
        "service_name": " · ".join(services) or None,
    }


def parse_workbook(uploaded_file):
    """Возвращает (columns, rows).

    columns: [(source_column_index, name)], начиная с 3-й колонки строки 0.
    rows: [(column_index, column_name, parsed_cell)].
    """
    suffix = uploaded_file.name.lower().rsplit(".", 1)[-1] if "." in uploaded_file.name else ""
    if suffix not in {"xls", "xlsx"}:
        raise ValueError("Поддерживаются только файлы .xls и .xlsx.")
    engine = "xlrd" if suffix == "xls" else "openpyxl"
    content = uploaded_file.read()
    try:
        frame = pd.read_excel(BytesIO(content), header=None, dtype=object, engine=engine)
    except Exception as exc:
        raise ValueError(f"Не удалось прочитать Excel-файл: {exc}")
    if frame.empty or frame.shape[1] < 4:
        raise ValueError("В файле не найдены колонки сервисов.")
    columns = []
    for index in range(3, frame.shape[1]):
        name = _text(frame.iat[0, index])
        if name:
            columns.append((index, name))
    rows = []
    last_hour = None
    for row_index in range(1, frame.shape[0]):
        if _text(frame.iat[row_index, 0]):
            last_hour = frame.iat[row_index, 0]
        base_time = _clock(last_hour, frame.iat[row_index, 1])
        for column_index, name in columns:
            parsed = parse_patient_cell(frame.iat[row_index, column_index], base_time)
            if parsed:
                rows.append((column_index, name, parsed))
    return columns, rows
