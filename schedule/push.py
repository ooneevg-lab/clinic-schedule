"""Получатели пушей и отправка через FCM.

Получатели — только врачи, которые реально есть в загруженной версии.
Сверка по уже существующему schedule_key (normalize_doctor_key).
В пуше нет медицинских данных: только факт готовности и целевой URL.
"""

from django.conf import settings


def recipients_for_version(version):
    """Вернуть {user_id: [registration, ...]} по активным устройствам.

    Берем ключи колонок версии, находим профили с такими ключами,
    для каждого врача берем только активные адреса.
    """
    from accounts.models import DoctorProfile, PushDevice
    from schedule.models import DoctorColumn

    keys = set(
        DoctorColumn.objects.filter(version=version).values_list("key", flat=True)
    )
    keys = {k for k in keys if k}
    if not keys:
        return {}
    profiles = (
        DoctorProfile.objects.filter(schedule_key__in=keys)
        .select_related("user")
        .values("user_id", "schedule_key")
    )
    user_ids = {p["user_id"] for p in profiles}
    if not user_ids:
        return {}
    devices = PushDevice.objects.filter(user_id__in=user_ids, active=True).values(
        "user_id", "registration"
    )
    result = {}
    for d in devices:
        result.setdefault(d["user_id"], []).append(d["registration"])
    return result


def target_url_for_version(version):
    return f"/schedule/?date={version.work_date.isoformat()}&branch_id={version.branch_id}"


def build_message(version):
    day = version.work_date.strftime("%d.%m.%Y")
    return {
        "title": "Расписание опубликовано",
        "body": f"Расписание на {day} доступно.",
        "data": {
            "type": "schedule_ready",
            "work_date": version.work_date.isoformat(),
            "branch_id": str(version.branch_id),
            "url": target_url_for_version(version),
        },
    }


def _firebase_app():
    from django.conf import settings as dj_settings

    import firebase_admin
    from firebase_admin import credentials

    if firebase_admin._apps:
        return firebase_admin.get_app()
    cred_file = getattr(dj_settings, "FIREBASE_CREDENTIALS_FILE", "")
    project_id = getattr(dj_settings, "FIREBASE_PROJECT_ID", "") or None
    if not cred_file:
        raise RuntimeError("Не задан FIREBASE_CREDENTIALS_FILE.")
    cred = credentials.Certificate(cred_file)
    options = {"projectId": project_id} if project_id else None
    if options:
        return firebase_admin.initialize_app(cred, options)
    return firebase_admin.initialize_app(cred)


def send_to_registrations(registrations, message):
    """Низкоуровневая отправка. Возвращает (sent, failed, invalid)."""
    if not registrations:
        return 0, 0, []
    if not getattr(settings, "PUSH_ENABLED", False):
        return 0, 0, []
    from firebase_admin import messaging

    _firebase_app()
    # FCM multicast ограничен пачкой в 500 адресов.
    sent = 0
    failed = 0
    invalid = []
    for i in range(0, len(registrations), 500):
        chunk = registrations[i : i + 500]
        msg = messaging.MulticastMessage(
            notification=messaging.Notification(
                title=message["title"], body=message["body"]
            ),
            data={k: str(v) for k, v in message.get("data", {}).items()},
            tokens=chunk,
        )
        resp = messaging.send_each_for_multicast(msg)
        sent += resp.success_count
        failed += resp.failure_count
        for idx, r in enumerate(resp.responses):
            if not r.success and _is_invalid_token_error(r.exception):
                invalid.append(chunk[idx])
    if invalid:
        _deactivate_invalid(invalid)
    return sent, failed, invalid


def _is_invalid_token_error(exc):
    code = getattr(exc, "code", "")
    text = str(exc or "").lower()
    return code in {"registration-token-not-registered", "invalid-argument"} or (
        "not registered" in text or "invalid registration" in text
    )


def _deactivate_invalid(registrations):
    from accounts.models import PushDevice

    PushDevice.objects.filter(registration__in=registrations).update(active=False)


def send_schedule_push(version_id):
    """Разослать пуш по готовой версии. Возвращает статистику для логов."""
    from schedule.models import ScheduleVersion

    try:
        version = ScheduleVersion.objects.select_related("branch").get(pk=version_id)
    except ScheduleVersion.DoesNotExist:
        return {"status": "no-version", "sent": 0, "failed": 0}
    recipients = recipients_for_version(version)
    registrations = sorted({r for regs in recipients.values() for r in regs})
    if not registrations:
        return {"status": "no-recipients", "sent": 0, "failed": 0}
    message = build_message(version)
    sent, failed, invalid = send_to_registrations(registrations, message)
    return {
        "status": "ok",
        "users": len(recipients),
        "devices": len(registrations),
        "sent": sent,
        "failed": failed,
        "invalid_deactivated": len(invalid),
    }
