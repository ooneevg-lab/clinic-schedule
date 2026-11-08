from datetime import date as date_cls, timedelta

from django.contrib.auth import authenticate
from django.db import models
from django.utils import timezone
from rest_framework import status
from rest_framework.authtoken.models import Token
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import AllowAny, IsAdminUser, IsAuthenticated
from rest_framework.response import Response

from accounts.models import LoginEvent
from schedule.models import Branch, DoctorColumn, ScheduleEntry, ScheduleVersion
from schedule.services import upload_schedule


def _client_ip(request):
    xff = request.META.get("HTTP_X_FORWARDED_FOR", "")
    if xff:
        return xff.split(",")[0].strip()
    return request.META.get("REMOTE_ADDR")


def _parse_date(value):
    if not value:
        return timezone.localdate()
    return date_cls.fromisoformat(str(value))


def _resolve_branch(request, default_branch=None):
    branch_id = request.query_params.get("branch_id") or request.data.get("branch_id")
    if branch_id:
        try:
            branch_pk = int(branch_id)
        except (TypeError, ValueError):
            return None
        return Branch.objects.filter(pk=branch_pk).first()
    if default_branch:
        return default_branch
    return Branch.objects.filter(is_active=True).order_by("id").first()


def _default_branch(profile):
    """Основной активный филиал врача; иначе первый активный из набора."""
    if profile is None:
        return None
    if profile.branch_id:
        try:
            primary = profile.branch
        except Branch.DoesNotExist:
            primary = None
        if primary is not None and primary.is_active:
            return primary
    try:
        ids = profile.allowed_branch_ids()
    except Exception:
        return None
    if not ids:
        return None
    return Branch.objects.filter(pk__in=ids, is_active=True).order_by("id").first()


def _allowed_branch_ids(profile):
    if profile is None:
        return set()
    try:
        return set(profile.allowed_branch_ids())
    except Exception:
        return {profile.branch_id} if profile.branch_id else set()


def _invalid_branch_id(request):
    """True, если branch_id передан, но филиал по нему не найден/невалиден."""
    branch_id = request.query_params.get("branch_id") or request.data.get("branch_id")
    if not branch_id:
        return False
    try:
        branch_pk = int(branch_id)
    except (TypeError, ValueError):
        return True
    return not Branch.objects.filter(pk=branch_pk).exists()


def _entry_dict(entry):
    return {
        "time": entry.appointment_time.strftime("%H:%M") if entry.appointment_time else None,
        "patient": entry.full_name,
        "age": entry.age,
        "service": entry.service_name,
        "doctor": entry.column.name,
    }


def _version_payload(version):
    uploaded_at = version.uploaded_at
    return {
        "work_date": version.work_date.isoformat(),
        "branch": {"id": version.branch_id, "code": version.branch.code, "name": version.branch.name},
        "uploaded_at": uploaded_at.isoformat() if uploaded_at else None,
        "is_fresh": bool(uploaded_at and uploaded_at >= timezone.now() - timedelta(days=3)),
    }


@api_view(["POST"])
@permission_classes([AllowAny])
def login_view(request):
    username = (request.data.get("username") or "").strip()
    password = request.data.get("password") or ""
    user = authenticate(request, username=username, password=password)
    if user is None or not user.is_active:
        return Response({"detail": "Неверный логин или пароль."}, status=status.HTTP_400_BAD_REQUEST)
    token, _ = Token.objects.get_or_create(user=user)
    via = "app" if "Token" in (request.META.get("HTTP_AUTHORIZATION") or "") else "site"
    # Приложение всегда шлёт логин без токена → помечаем как app по флагу клиента.
    if str(request.data.get("client") or "").lower() in {"app", "android"}:
        via = "app"
    LoginEvent.objects.create(
        user=user, via=via, ip=_client_ip(request),
        user_agent=request.META.get("HTTP_USER_AGENT", "")[:500],
    )
    profile = getattr(user, "doctor_profile", None)
    branch_ids = sorted(_allowed_branch_ids(profile))
    if profile is not None and profile.branch_id and profile.branch_id in branch_ids:
        branch_ids = [profile.branch_id] + [i for i in branch_ids if i != profile.branch_id]
    return Response({
        "token": token.key,
        "username": user.username,
        "is_staff": user.is_staff,
        "display_name": profile.schedule_name if profile else user.get_full_name() or user.username,
        "branch_id": profile.branch_id if profile else None,
        "branch_ids": branch_ids,
    })


@api_view(["POST"])
@permission_classes([IsAuthenticated])
def logout_view(request):
    # Гасим только текущий токен: остальные устройства живут.
    token = request.auth
    if token is not None:
        token.delete()
    else:
        Token.objects.filter(user=request.user).delete()
    # API-выход закрывает только app-события (web — свои, via=site).
    LoginEvent.objects.filter(
        user=request.user, via="app", logout_at__isnull=True
    ).update(logout_at=timezone.now())
    return Response({"status": "ok"})


@api_view(["POST"])
@permission_classes([IsAuthenticated])
def push_register(request):
    """Привязка адреса установки к текущему врачу.

    Принимаем только сам адрес. Владелец всегда берется из сессии
    (request.user), никаких user_id от клиента. Повторная отправка того же
    адреса с новой кукой перепривязывает телефон к новому врачу.
    """
    from accounts.models import PushDevice

    data = request.data if isinstance(request.data, dict) else {}
    registration = str(data.get("registration") or "").strip()
    platform = str(data.get("platform") or "android").strip().lower() or "android"
    if not registration:
        return Response({"detail": "Укажите адрес установки (registration)."}, status=400)
    if len(registration) > 255:
        return Response({"detail": "Слишком длинный адрес установки."}, status=400)
    if platform not in {"android"}:
        return Response({"detail": "Поддерживается только platform=android."}, status=400)
    device, _ = PushDevice.objects.update_or_create(
        registration=registration,
        defaults={"user": request.user, "platform": platform, "active": True},
    )
    return Response({"status": "ok", "registration": device.registration, "active": True})


@api_view(["POST"])
@permission_classes([IsAuthenticated])
def push_unregister(request):
    """Отвязка адреса при выходе. Гасим только свою запись, чужие не трогаем."""
    from accounts.models import PushDevice

    data = request.data if isinstance(request.data, dict) else {}
    registration = str(data.get("registration") or "").strip()
    if not registration:
        return Response({"detail": "Укажите адрес установки (registration)."}, status=400)
    PushDevice.objects.filter(
        registration=registration, user=request.user
    ).update(active=False)
    return Response({"status": "ok"})


def _branch_allowed_api(user, profile, branch):
    """Зеркало schedule.views._branch_allowed для API (default-deny)."""
    if user.is_staff or branch is None or profile is None:
        return True
    return branch.id in _allowed_branch_ids(profile)


def _schedule_response(request, only_mine):
    try:
        work_date = _parse_date(request.query_params.get("date"))
    except ValueError:
        return Response({"detail": "Некорректная дата, формат YYYY-MM-DD."}, status=400)
    if _invalid_branch_id(request):
        return Response({"detail": "Некорректный филиал."}, status=400)
    profile = getattr(request.user, "doctor_profile", None)
    default_branch = _default_branch(profile)
    branch = _resolve_branch(request, default_branch)
    if branch is None:
        return Response({"detail": "Нет активных филиалов."}, status=400)
    if not _branch_allowed_api(request.user, profile, branch):
        return Response({"detail": "Нет доступа к этому филиалу."}, status=403)
    version = ScheduleVersion.objects.filter(
        branch=branch, work_date=work_date, is_active=True
    ).select_related("branch").first()
    today = timezone.localdate().isoformat()
    if version is None:
        return Response({
            "today": today, "work_date": work_date.isoformat(),
            "branch": {"id": branch.id, "code": branch.code, "name": branch.name},
            "has_version": False, "has_column": False,
            "my_columns": [], "count": 0, "entries": [],
        })
    entries = ScheduleEntry.objects.filter(version=version).select_related("column")
    my_columns, has_column = [], False
    if only_mine:
        if profile is None:
            return Response({"detail": "Нет карточки врача."}, status=403)
        cols = list(
            DoctorColumn.objects.filter(version=version, key=profile.schedule_key)
            .values("id", "name")
        )
        my_columns = [c["name"] for c in cols]
        has_column = bool(cols)
        ids = {c["id"] for c in cols}
        entries = [e for e in entries if e.column_id in ids]
    payload_entries = [_entry_dict(e) for e in entries]
    return Response({
        "today": today,
        **_version_payload(version),
        "has_version": True,
        "has_column": has_column if only_mine else True,
        "my_columns": my_columns if only_mine else [],
        "count": len(payload_entries),
        "entries": payload_entries,
    })


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def my_schedule(request):
    return _schedule_response(request, only_mine=True)


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def full_schedule(request):
    return _schedule_response(request, only_mine=False)


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def columns_list(request):
    try:
        work_date = _parse_date(request.query_params.get("date"))
    except ValueError:
        return Response({"detail": "Некорректная дата."}, status=400)
    if _invalid_branch_id(request):
        return Response({"detail": "Некорректный филиал."}, status=400)
    profile = getattr(request.user, "doctor_profile", None)
    branch = _resolve_branch(request, _default_branch(profile))
    if branch is None:
        return Response({"detail": "Нет активных филиалов."}, status=400)
    if not _branch_allowed_api(request.user, profile, branch):
        return Response({"detail": "Нет доступа к этому филиалу."}, status=403)
    version = ScheduleVersion.objects.filter(
        branch=branch, work_date=work_date, is_active=True
    ).first()
    if version is None:
        return Response({"today": timezone.localdate().isoformat(),
                         "work_date": work_date.isoformat(), "columns": []})
    cols = DoctorColumn.objects.filter(version=version).order_by(
        "source_column_index"
    ).annotate(entries_count=models.Count("entries"))
    data = [
        {"name": c.name, "entries": c.entries_count} for c in cols
    ]
    return Response({"today": timezone.localdate().isoformat(),
                     "work_date": work_date.isoformat(), "columns": data})


@api_view(["POST"])
@permission_classes([IsAdminUser])
def admin_upload(request):
    branch_ids = request.data.getlist("branch_ids") if hasattr(request.data, "getlist") else []
    if not branch_ids and request.data.get("branch_id"):
        branch_ids = [request.data.get("branch_id")]
    # JSON-клиенты шлют список одной строкой/числом: нормализуем.
    if isinstance(branch_ids, str) or not isinstance(branch_ids, list):
        branch_ids = [branch_ids]
    flat = []
    for item in branch_ids:
        if isinstance(item, str) and "," in item:
            flat.extend(p.strip() for p in item.split(",") if p.strip())
        else:
            flat.append(item)
    branch_ids = [b for b in flat if b not in (None, "")]
    work_date_raw = request.data.get("work_date")
    uploaded = request.FILES.get("file")
    if not branch_ids:
        return Response({"detail": "Укажите филиал (branch_id). Можно несколько (branch_ids)."}, status=400)
    if not work_date_raw:
        return Response({"detail": "Укажите дату расписания (work_date)."}, status=400)
    if uploaded is None:
        return Response({"detail": "Передайте Excel-файл в поле file."}, status=400)
    try:
        work_date = date_cls.fromisoformat(str(work_date_raw))
    except ValueError:
        return Response({"detail": "Некорректная дата, формат YYYY-MM-DD."}, status=400)
    branches, bad = [], []
    for raw_id in branch_ids:
        try:
            branches.append(Branch.objects.get(pk=int(raw_id)))
        except (ValueError, TypeError, Branch.DoesNotExist):
            bad.append(str(raw_id))
    if bad:
        return Response({"detail": f"Некорректные филиалы: {', '.join(bad)}."}, status=400)
    try:
        content = uploaded.read()
        file_name = getattr(uploaded, "name", "schedule.xlsx")
    except OSError as exc:
        return Response({"detail": str(exc)}, status=400)
    from django.core.files.uploadedfile import SimpleUploadedFile
    from django.db import transaction

    done, failed = [], []
    version_ids = []
    for branch in branches:
        try:
            version, sc, ec = upload_schedule(
                branch=branch, work_date=work_date,
                uploaded_file=SimpleUploadedFile(file_name, content),
                uploaded_by=request.user,
            )
        except (ValueError, OSError) as exc:
            failed.append({"branch_id": branch.id, "detail": str(exc)})
        else:
            version_ids.append(version.id)
            done.append({"branch": {"id": branch.id, "code": branch.code},
                         "services_loaded": sc, "patients_loaded": ec})
    if not done:
        return Response({"status": "error", "work_date": work_date.isoformat(),
                         "failed": failed}, status=400)
    from schedule.tasks import queue_schedule_push

    transaction.on_commit(lambda: [queue_schedule_push(v_id) for v_id in version_ids])
    payload = {"status": "ok" if not failed else "partial",
               "work_date": work_date.isoformat(),
               "branches": done, "failed": failed}
    if len(done) == 1 and not failed:
        payload.update({"branch": done[0]["branch"],
                        "services_loaded": done[0]["services_loaded"],
                        "patients_loaded": done[0]["patients_loaded"]})
    return Response(payload, status=status.HTTP_201_CREATED)


@api_view(["POST"])
@permission_classes([IsAdminUser])
def integration_schedule(request):
    """Приём расписания от 1С (JSON). Доступ: отдельный staff-пользователь
    1С + токен. Схема: {branch_code, work_date YYYY-MM-DD,
    doctors: [{name, appointments: [{time HH:MM|null, patient, age?, service?}]}]}.
    Семантика как Excel: повтор деактивирует старую версию; колонки без
    карточки врача приём не роняют, а уходят в unmatched."""
    from schedule.services import upload_schedule_data

    data = request.data if isinstance(request.data, dict) else {}
    branch_code = str(data.get("branch_code") or "").strip()
    work_date_raw = data.get("work_date")
    if not branch_code:
        return Response({"detail": "Укажите филиал (branch_code)."}, status=400)
    branch = Branch.objects.filter(code=branch_code, is_active=True).first()
    if branch is None:
        codes = list(Branch.objects.filter(is_active=True)
                     .order_by("code").values_list("code", flat=True))
        return Response({"detail": f"Неизвестный филиал: {branch_code}.",
                         "branch_codes": codes}, status=400)
    if not work_date_raw:
        return Response({"detail": "Укажите дату расписания (work_date)."}, status=400)
    try:
        work_date = date_cls.fromisoformat(str(work_date_raw))
    except ValueError:
        return Response({"detail": "Некорректная дата, формат YYYY-MM-DD."}, status=400)
    try:
        version, sc, ec = upload_schedule_data(
            branch=branch, work_date=work_date, doctors=data.get("doctors"),
            uploaded_by=request.user,
        )
    except (ValueError, TypeError) as exc:
        return Response({"detail": str(exc)}, status=400)
    from accounts.models import DoctorProfile
    from schedule.parsing import normalize_doctor_key

    keys = set(
        DoctorProfile.objects
        .filter(models.Q(branch=branch) | models.Q(branches=branch))
        .values_list("schedule_key", flat=True)
    )
    names = [c.name for c in version.columns.all()]
    unmatched = sorted({n for n in names if normalize_doctor_key(n) not in keys})
    from django.db import transaction

    from schedule.tasks import queue_schedule_push

    transaction.on_commit(lambda: queue_schedule_push(version.id))
    return Response({
        "status": "ok",
        "work_date": version.work_date.isoformat(),
        "branch": {"id": branch.id, "code": branch.code},
        "services_loaded": sc, "patients_loaded": ec,
        "unmatched": unmatched,
    }, status=status.HTTP_201_CREATED)


@api_view(["GET"])
@permission_classes([IsAdminUser])
def admin_versions(request):
    versions = ScheduleVersion.objects.select_related("branch").order_by("-work_date")[:30]
    return Response([{
        "id": v.id, "work_date": v.work_date.isoformat(),
        "branch": {"id": v.branch_id, "code": v.branch.code},
        "is_active": v.is_active, "services_count": v.services_count,
        "entries_count": v.entries_count,
        "uploaded_at": v.uploaded_at.isoformat() if v.uploaded_at else None,
    } for v in versions])


@api_view(["GET"])
@permission_classes([IsAdminUser])
def admin_analytics(request):
    events = LoginEvent.objects.select_related("user").order_by("-login_at")[:100]
    return Response([{
        "username": e.user.username, "via": e.via, "ip": e.ip,
        "login_at": e.login_at.isoformat() if e.login_at else None,
        "logout_at": e.logout_at.isoformat() if e.logout_at else None,
    } for e in events])
