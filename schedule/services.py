"""Загрузка расписания: файл + обязательные дата и филиал."""

from django.db import transaction

from .models import DoctorColumn, ScheduleEntry, ScheduleVersion
from .parsing import parse_workbook


def _create_version(*, branch, work_date, columns, rows, source_name, uploaded_by=None):
    """Общее ядро: columns=[(index, name)], rows=[(index, name, data)]."""
    if not columns:
        raise ValueError("Не найдены колонки врачей.")
    if not rows:
        raise ValueError("Не найдены записи пациентов.")
    with transaction.atomic():
        ScheduleVersion.objects.filter(
            branch=branch, work_date=work_date, is_active=True
        ).update(is_active=False)
        version = ScheduleVersion.objects.create(
            branch=branch,
            work_date=work_date,
            file_name=source_name,
            uploaded_by=uploaded_by,
            is_active=True,
            services_count=len(columns),
            entries_count=len(rows),
        )
        col_map = {}
        for index, name in columns:
            col = DoctorColumn.objects.create(
                version=version, name=name, source_column_index=index
            )
            col_map[index] = col
        entries = [
            ScheduleEntry(
                version=version,
                column=col_map[column_index],
                appointment_time=data["appointment_time"],
                full_name=data["full_name"],
                age=data.get("age"),
                service_name=data.get("service_name"),
            )
            for column_index, _, data in rows
        ]
        ScheduleEntry.objects.bulk_create(entries)
    return version, len(columns), len(rows)


def upload_schedule(*, branch, work_date, uploaded_file, uploaded_by=None):
    columns, rows = parse_workbook(uploaded_file)
    if not columns:
        raise ValueError("В файле не найдены колонки врачей.")
    if not rows:
        raise ValueError("В файле не найдены записи пациентов.")
    return _create_version(
        branch=branch, work_date=work_date, columns=columns, rows=rows,
        source_name=getattr(uploaded_file, "name", ""), uploaded_by=uploaded_by,
    )


def _parse_json_time(value, where):
    import re
    from datetime import time as dt_time

    text = "" if value is None else str(value).strip()
    if not text:
        return None
    m = re.fullmatch(r"(\d{1,2}):(\d{2})", text)
    if not m or int(m.group(1)) > 23 or int(m.group(2)) > 59:
        raise ValueError(f"{where}: время «{text}», нужно HH:MM.")
    return dt_time(int(m.group(1)), int(m.group(2)))


def _opt_str(value, where):
    if value is None:
        return None
    if not isinstance(value, str):
        raise ValueError(f"{where}: должна быть строка.")
    text = value.strip()
    return text or None


def upload_schedule_data(*, branch, work_date, doctors, uploaded_by=None):
    """Приём от 1С: doctors=[{name, appointments:[{time,patient,age,service}]}].
    Ошибки — ValueError с индексами. Приём не роняют колонки без карточки."""
    if not isinstance(doctors, list) or not doctors:
        raise ValueError("Поле doctors: нужен непустой список врачей.")
    columns, rows = [], []
    for i, doc in enumerate(doctors):
        where = f"doctors[{i}]"
        if not isinstance(doc, dict):
            raise ValueError(f"{where}: нужен объект с name и appointments.")
        name = _opt_str(doc.get("name"), f"{where}.name")
        if not name:
            raise ValueError(f"{where}.name: нужно ФИО врача.")
        appts = doc.get("appointments", [])
        if not isinstance(appts, list):
            raise ValueError(f"{where}.appointments: нужен список.")
        columns.append((i, name))
        for j, ap in enumerate(appts):
            awhere = f"{where}.appointments[{j}]"
            if not isinstance(ap, dict):
                raise ValueError(f"{awhere}: нужен объект.")
            patient = _opt_str(ap.get("patient"), f"{awhere}.patient")
            if not patient:
                raise ValueError(f"{awhere}.patient: нужно ФИО пациента.")
            rows.append((i, name, {
                "appointment_time": _parse_json_time(ap.get("time"), awhere),
                "full_name": patient,
                "age": _opt_str(ap.get("age"), f"{awhere}.age"),
                "service_name": _opt_str(ap.get("service"), f"{awhere}.service"),
            }))
    return _create_version(
        branch=branch, work_date=work_date, columns=columns, rows=rows,
        source_name="1c-json", uploaded_by=uploaded_by,
    )
