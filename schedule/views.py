from datetime import date as date_cls, timedelta

from django.contrib import messages
from django.contrib.auth.decorators import login_required, user_passes_test
from django.core.exceptions import PermissionDenied
from django.core.files.uploadedfile import SimpleUploadedFile
from django.db import transaction
from django.shortcuts import redirect, render
from django.utils import timezone

from schedule.models import Branch, DoctorColumn, ScheduleEntry, ScheduleVersion
from schedule.services import upload_schedule


def _selected_date(request):
    raw = request.GET.get("date") or request.POST.get("date")
    if not raw:
        return timezone.localdate()
    try:
        return date_cls.fromisoformat(str(raw))
    except ValueError:
        return timezone.localdate()


def _selected_branch(request, profile):
    branch_id = request.GET.get("branch_id") or request.POST.get("branch_id")
    if branch_id:
        try:
            return Branch.objects.get(pk=int(branch_id))
        except (ValueError, Branch.DoesNotExist):
            pass
    if profile and profile.branch_id:
        try:
            primary = profile.branch
        except Branch.DoesNotExist:
            primary = None
        if primary is not None and primary.is_active:
            return primary
    if profile is not None:
        allowed = _allowed_ids(profile) or set()
        if allowed:
            first = Branch.objects.filter(
                id__in=allowed, is_active=True
            ).order_by("id").first()
            if first is not None:
                return first
    return Branch.objects.filter(is_active=True).order_by("id").first()


def _allowed_ids(profile):
    """Набор филиалов врача с кэшем на время запроса. None — не удалось
    выяснить (вызывающие трактуют как открыто, fail-open)."""
    if profile is None:
        return set()
    try:
        return profile._allowed_cache
    except AttributeError:
        pass
    try:
        cached = profile.allowed_branch_ids()
    except Exception:
        return None
    profile._allowed_cache = cached
    return cached


def _allowed_branches_for_selector(request, profile, branches_all):
    """Филиалы для селекта: staff — все; врач с набором — только свои
    (основной первым); без набора — все (совместимость)."""
    if request.user.is_staff or profile is None:
        return branches_all
    allowed = _allowed_ids(profile)
    if allowed is None:
        return branches_all
    if not allowed:
        return branches_all
    ordered = [b for b in branches_all if b.id in allowed]
    ordered.sort(key=lambda b: (0 if b.id == profile.branch_id else 1, b.id))
    return ordered or branches_all


def _branch_allowed(request, profile, branch):
    """Default-deny: врач без назначенных филиалов — запрет (админка раздаёт).
    Staff, пользователи без карточки и пустой выбор при отсутствии карточки —
    как раньше (открыто)."""
    if request.user.is_staff or branch is None or profile is None:
        return True
    allowed = _allowed_ids(profile)
    if allowed is None:
        return True
    return branch.id in allowed


def _news_branches(profile):
    """Филиалы для уведомлений: набор врача; без набора — основной (как раньше)."""
    if profile is None:
        return []
    allowed = _allowed_ids(profile)
    if allowed is None:
        allowed = set()
    if allowed:
        return list(
            Branch.objects.filter(id__in=allowed, is_active=True).order_by("id")
        )
    if profile.branch_id:
        try:
            primary = profile.branch
        except Branch.DoesNotExist:
            primary = None
        if primary is not None and primary.is_active:
            return [primary]
    return []


_RU_MONTHS = {
    1: "января", 2: "февраля", 3: "марта", 4: "апреля",
    5: "мая", 6: "июня", 7: "июля", 8: "августа",
    9: "сентября", 10: "октября", 11: "ноября", 12: "декабря",
}
_RU_WEEKDAYS = [
    "понедельник", "вторник", "среда", "четверг",
    "пятница", "суббота", "воскресенье",
]
_RU_WEEKDAYS_SHORT = ["пн", "вт", "ср", "чт", "пт", "сб", "вс"]

# Новым считается расписание, опубликованное за последние N дней.
FRESH_DAYS = 3

_RU_MONTHS_NOM = {
    1: "Январь", 2: "Февраль", 3: "Март", 4: "Апрель",
    5: "Май", 6: "Июнь", 7: "Июль", 8: "Август",
    9: "Сентябрь", 10: "Октябрь", 11: "Ноябрь", 12: "Декабрь",
}

# Сколько чипов дат видно сразу, остальные — за кнопкой «Показать ещё».
UPCOMING_VISIBLE = 7
# Сколько дат тянем для вкладки «Есть расписание» (хватает на месяцы вперёд).
UPCOMING_LIMIT = 60


def _ru_date_label(day):
    """16 сентября, вторник."""
    return f"{day.day} {_RU_MONTHS[day.month]}, {_RU_WEEKDAYS[day.weekday()]}"


def _uploaded_label(when, today):
    """Когда залили, словами: сегодня в 14:20 / вчера в 09:05 / 15.09 в 18:40."""
    local = timezone.localtime(when)
    hm = local.strftime("%H:%M")
    delta = (today - local.date()).days
    if delta <= 0:
        return f"сегодня в {hm}"
    if delta == 1:
        return f"вчера в {hm}"
    return f"{local.strftime('%d.%m')} в {hm}"


def _fresh_versions(branches, today):
    """Активные версии филиалов, опубликованные за последние FRESH_DAYS."""
    cutoff = timezone.now() - timedelta(days=FRESH_DAYS)
    return list(
        ScheduleVersion.objects.filter(
            branch__in=branches, is_active=True, uploaded_at__gte=cutoff
        ).select_related("branch").order_by("-uploaded_at")[:10]
    )


def _seen_version_ids(request):
    """ID версий, которые врач уже открывал (NEW для них гаснет)."""
    raw = request.session.get("seen_version_ids") or []
    try:
        return {int(x) for x in raw}
    except (TypeError, ValueError):
        return set()


def _get_seen_ids(request, profile):
    """Просмотренные версии: профиль (переживает выход) + сессия (staff/кэш)."""
    seen = _seen_version_ids(request)
    if profile is not None:
        try:
            seen |= profile.get_seen_version_ids()
        except Exception:
            pass
    return seen


def _persist_seen_ids(request, profile, ids):
    """Отметить версии просмотренными: профиль + сессия. Возвращает набор."""
    try:
        ids = {int(x) for x in ids}
    except (TypeError, ValueError):
        return _get_seen_ids(request, profile)
    if not ids:
        return _get_seen_ids(request, profile)
    if profile is not None:
        try:
            profile.add_seen_version_ids(ids)
        except Exception:
            pass
    seen = _seen_version_ids(request) | ids
    request.session["seen_version_ids"] = sorted(seen)[-50:]
    if profile is not None:
        try:
            seen |= profile.get_seen_version_ids()
        except Exception:
            pass
    return seen


def _nearest_date(branch, work_date):
    """Ближайшая активная версия филиала к дате (модуль разницы, ничья —
    будущее). None, если расписаний нет."""
    prev = (ScheduleVersion.objects.filter(
        branch=branch, is_active=True, work_date__lte=work_date
    ).order_by("-work_date").values_list("work_date", flat=True).first())
    nxt = (ScheduleVersion.objects.filter(
        branch=branch, is_active=True, work_date__gte=work_date
    ).order_by("work_date").values_list("work_date", flat=True).first())
    if prev is None:
        best = nxt
    elif nxt is None:
        best = prev
    else:
        best = nxt if (nxt - work_date) <= (work_date - prev) else prev
    if best is None:
        return None
    return {"iso": best.isoformat(), "label": best.strftime("%d.%m")}


def _parse_ack_ids(request):
    raw = request.GET.get("ack_news") or ""
    ids = set()
    for part in str(raw).replace(",", " ").split():
        try:
            ids.add(int(part))
        except (TypeError, ValueError):
            continue
    return ids


@login_required
def schedule_page(request):
    profile = getattr(request.user, "doctor_profile", None)
    today = timezone.localdate()
    work_date = _selected_date(request)
    branch = _selected_branch(request, profile)
    branches_all = list(Branch.objects.filter(is_active=True).order_by("id"))
    branches = _allowed_branches_for_selector(request, profile, branches_all)
    ctx = {
        "today": today, "work_date": work_date, "branch": branch,
        "branches": branches,
        "yesterday": (work_date - timedelta(days=1)).isoformat(),
        "tomorrow": (work_date + timedelta(days=1)).isoformat(),
        "work_date_iso": work_date.isoformat(),
        "today_iso": today.isoformat(),
        "work_date_label": _ru_date_label(work_date),
        "upcoming_dates": [], "calendar_dates": [],
        "nearest_date": None,
        "news": [],
        "my_entries": [], "full_entries": [], "my_columns": [],
        "grid_columns": [], "grid_rows": [], "doctor_cards": [],
        "my_count": 0, "full_count": 0,
        "has_version": False, "has_column": False, "version": None,
        "is_staff": request.user.is_staff,
        "display_name": profile.schedule_name if profile else request.user.username,
    }
    if branch is None:
        return render(request, "schedule.html", ctx)
    if not _branch_allowed(request, profile, branch):
        raise PermissionDenied("Нет доступа к этому филиалу. Если филиалы не назначены — обратитесь к администратору.")
    # Просмотры: подтверждение закрытия (ack_news) + открытая дата.
    # Источник правды — профиль (переживает выход), сессия — кэш/staff.
    fresh_cutoff = timezone.now() - timedelta(days=FRESH_DAYS)
    seen_ids = _get_seen_ids(request, profile)
    ack_ids = _parse_ack_ids(request)
    if ack_ids:
        seen_ids = _persist_seen_ids(request, profile, ack_ids)
    version = ScheduleVersion.objects.filter(
        branch=branch, work_date=work_date, is_active=True
    ).select_related("branch").first()
    if version is not None:
        seen_ids = _persist_seen_ids(request, profile, {version.id})
    # Calendar markers include past publications, scoped to the permitted branch.
    ctx["calendar_dates"] = [
        {"iso": v.work_date.isoformat(),
         "is_new": v.uploaded_at >= fresh_cutoff and v.id not in seen_ids}
        for v in ScheduleVersion.objects.filter(branch=branch, is_active=True)
        .only("id", "work_date", "uploaded_at").order_by("work_date")
    ]
    # Дни, на которые есть активное расписание (для чипов в календаре).
    # NEW гаснет после просмотра даты: id версии в seen.
    upcoming = list(
        ScheduleVersion.objects.filter(
            branch=branch, is_active=True, work_date__gte=today - timedelta(days=1)
        ).order_by("work_date")[:UPCOMING_LIMIT]
    )
    dated = [
        {
            "iso": v.work_date.isoformat(),
            "label": v.work_date.strftime("%d.%m"),
            "is_new": v.uploaded_at >= fresh_cutoff and v.id not in seen_ids,
            "month_key": v.work_date.strftime("%Y-%m"),
            "month_title": f"{_RU_MONTHS_NOM[v.work_date.month]} {v.work_date.year}",
        }
        for v in upcoming
    ]
    ctx["upcoming_dates"] = [
        {k: d[k] for k in ("iso", "label", "is_new")} for d in dated[:14]
    ]
    # Вкладка «Есть расписание»: те же даты группами по месяцам.
    # Видны ближайшие UPCOMING_VISIBLE, остальные — за кнопкой «Показать ещё».
    for i, d in enumerate(dated):
        d["hidden"] = i >= UPCOMING_VISIBLE and d["iso"] != work_date.isoformat()
    months = []
    for d in dated:
        if not months or months[-1]["key"] != d["month_key"]:
            months.append({"key": d["month_key"], "title": d["month_title"],
                           "dates": [], "hidden_count": 0})
        months[-1]["dates"].append(d)
        if d["hidden"]:
            months[-1]["hidden_count"] += 1
    ctx["upcoming_months"] = months
    ctx["upcoming_hidden_total"] = sum(1 for d in dated if d["hidden"])
    # Истинно ближайшее расписание к запрошенному дню (прошлое + будущее,
    # ничья — будущее). Отдельно от чипов: те смотрят только вперёд.
    ctx["nearest_date"] = _nearest_date(branch, work_date)
    # Каскад «Есть расписание»: год → месяцы → дни (компактно при годах работы).
    cascade, years_index = [], {}
    for v in upcoming:
        wd = _RU_WEEKDAYS_SHORT[v.work_date.weekday()]
        entry = {"iso": v.work_date.isoformat(),
                 "label": f"{v.work_date.day} {_RU_MONTHS[v.work_date.month]}, {wd}",
                 "is_new": v.uploaded_at >= fresh_cutoff and v.id not in seen_ids}
        y = v.work_date.year
        if y not in years_index:
            years_index[y] = {"year": y, "months": [], "mindex": {}}
            cascade.append(years_index[y])
        mkey = v.work_date.strftime("%Y-%m")
        mindex = years_index[y]["mindex"]
        if mkey not in mindex:
            mindex[mkey] = {"key": mkey,
                            "title": _RU_MONTHS_NOM[v.work_date.month],
                            "dates": []}
            years_index[y]["months"].append(mindex[mkey])
        mindex[mkey]["dates"].append(entry)
    for yb in cascade:
        del yb["mindex"]
    ctx["upcoming_cascade"] = cascade
    have_isos = {e["iso"] for yb in cascade for mb in yb["months"] for e in mb["dates"]}
    if work_date.isoformat() in have_isos:
        ctx["have_year"], ctx["have_month"] = work_date.year, work_date.strftime("%Y-%m")
        ctx["have_day"] = work_date.isoformat()
    elif cascade:
        ctx["have_year"] = cascade[0]["year"]
        ctx["have_month"] = cascade[0]["months"][0]["key"]
        ctx["have_day"] = cascade[0]["months"][0]["dates"][0]["iso"]
    else:
        ctx["have_year"] = ctx["have_month"] = ctx["have_day"] = ""
    # Уведомление «появилось новое расписание»: филиалы врача (набор;
    # без набора — основной), опубликованное за FRESH_DAYS, кроме виденных.
    # Показ сам по себе не гасит: гасят открытие даты и закрытие (ack_news).
    news_branches = _news_branches(profile)
    if news_branches:
        fresh = _fresh_versions(news_branches, today)
        news = [v for v in fresh if v.id not in seen_ids]
        if news:
            ctx["news"] = [
                {
                    "id": v.id,
                    "work_date_iso": v.work_date.isoformat(),
                    "label": _ru_date_label(v.work_date),
                    "branch_id": v.branch_id,
                    "branch_code": v.branch.code,
                    "uploaded_label": _uploaded_label(v.uploaded_at, today),
                }
                for v in news
            ]
    if version is None:
        return render(request, "schedule.html", ctx)
    ctx["version"] = version
    ctx["has_version"] = True
    columns = list(
        DoctorColumn.objects.filter(version=version).order_by("source_column_index")
    )
    ctx["grid_columns"] = columns
    full = list(
        ScheduleEntry.objects.filter(version=version)
        .select_related("column").order_by("appointment_time", "column__source_column_index")
    )
    ctx["full_entries"] = full
    ctx["full_count"] = len(full)
    # Сводная сетка «время × врачи» как в Excel: строки — время, столбцы — врачи.
    by_time = {}
    for entry in full:
        by_time.setdefault(entry.appointment_time, {}).setdefault(entry.column_id, []).append(entry)
    times = sorted([t for t in by_time if t is not None]) + ([None] if None in by_time else [])
    ctx["grid_rows"] = [
        {"time": t, "cells": [by_time[t].get(col.id, []) for col in columns]}
        for t in times
    ]
    # Карточки по врачам для мобильных: те же данные, вид «врач → его записи».
    by_column = {}
    for entry in full:
        by_column.setdefault(entry.column_id, []).append(entry)
    ctx["doctor_cards"] = [
        {"column": col, "entries": by_column.get(col.id, [])}
        for col in columns
    ]
    if profile:
        cols = list(DoctorColumn.objects.filter(version=version, key=profile.schedule_key))
        ctx["my_columns"] = [c.name for c in cols]
        ctx["has_column"] = bool(cols)
        ids = {c.id for c in cols}
        mine = [e for e in full if e.column_id in ids]
        ctx["my_entries"] = mine
        ctx["my_count"] = len(mine)
    elif request.user.is_staff:
        ctx["has_column"] = True
    return render(request, "schedule.html", ctx)


def _is_staff(user):
    return user.is_authenticated and user.is_staff


@login_required
@user_passes_test(_is_staff)
def upload_page(request):
    branches = list(Branch.objects.filter(is_active=True).order_by("id"))
    default_date = (timezone.localdate() + timedelta(days=1)).isoformat()
    selected_branch_ids = []
    result = None
    if request.method == "POST":
        branch_ids = request.POST.getlist("branch_ids")
        if not branch_ids and request.POST.get("branch_id"):
            branch_ids = [request.POST.get("branch_id")]
        selected_branch_ids = branch_ids
        work_date_raw = request.POST.get("work_date")
        if work_date_raw:
            default_date = work_date_raw
        uploaded = request.FILES.get("file")
        if not branch_ids:
            messages.error(request, "Укажите филиал — можно несколько.")
        elif not work_date_raw:
            messages.error(request, "Укажите дату расписания — это обязательное поле.")
        elif uploaded is None:
            messages.error(request, "Приложите Excel-файл (.xls/.xlsx).")
        else:
            try:
                work_date = date_cls.fromisoformat(str(work_date_raw))
            except ValueError:
                messages.error(request, "Некорректная дата.")
                return render(request, "upload.html", {
                    "branches": branches, "default_date": work_date_raw or default_date,
                    "selected_branch_ids": selected_branch_ids,
                    "result": None, **_history_context(request),
                })
            targets, bad = [], []
            for raw_id in branch_ids:
                try:
                    targets.append(Branch.objects.get(pk=int(raw_id)))
                except (ValueError, Branch.DoesNotExist):
                    bad.append(str(raw_id))
            if bad:
                messages.error(request, f"Некорректные филиалы: {', '.join(bad)}.")
            if not targets:
                if not bad:
                    messages.error(request, "Укажите филиал — можно несколько.")
            else:
                try:
                    content = uploaded.read()
                    file_name = getattr(uploaded, "name", "schedule.xlsx")
                except OSError as exc:
                    messages.error(request, f"Не загрузилось: {exc}")
                    targets = []
                ok, failed = [], []
                for branch in targets:
                    try:
                        copy = SimpleUploadedFile(file_name, content)
                        version, sc, ec = upload_schedule(
                            branch=branch, work_date=work_date,
                            uploaded_file=copy, uploaded_by=request.user,
                        )
                    except (ValueError, OSError) as exc:
                        failed.append(f"{branch.code}: {exc}")
                    else:
                        ok.append((branch, sc, ec, version.id))
                for f in failed:
                    messages.error(request, f"Не загрузилось ({f}).")
                if ok:
                    codes = ", ".join(b.code for b, _s, _e, _v in ok)
                    sc, ec = ok[0][1], ok[0][2]
                    result = {"work_date": work_date.isoformat(),
                              "branch": codes,
                              "services_loaded": sc,
                              "patients_loaded": ec,
                              "branches_count": len(ok)}
                    messages.success(
                        request,
                        f"Расписание на {work_date:%d.%m.%Y} опубликовано: "
                        f"филиалы {codes}. Врачей {sc}, пациентов {ec} в каждом.",
                    )
                    # Пуши — только после успешного сохранения, в фоне.
                    from schedule.tasks import queue_schedule_push

                    version_ids = [v_id for _b, _s, _e, v_id in ok]
                    transaction.on_commit(
                        lambda: [queue_schedule_push(v_id) for v_id in version_ids]
                    )
                    first = ok[0][0]
                    return redirect(f"/schedule/?date={work_date.isoformat()}&branch_id={first.id}")
    return render(request, "upload.html", {
        "branches": branches, "default_date": default_date,
        "selected_branch_ids": selected_branch_ids,
        "result": result, **_history_context(request),
    })


def _history_context(request):
    """Месяцы загрузок + версии выбранного месяца (?hist_month=YYYY-MM)."""
    from django.db.models import Count
    month_rows = list(
        ScheduleVersion.objects
        .values("work_date__year", "work_date__month")
        .annotate(n=Count("id"))
        .order_by("-work_date__year", "-work_date__month")
    )
    hist_months = [
        {"key": f"{r['work_date__year']}-{r['work_date__month']:02d}",
         "title": f"{_RU_MONTHS_NOM[r['work_date__month']]} {r['work_date__year']}",
         "count": r["n"]}
        for r in month_rows
    ]
    hist_month = request.GET.get("hist_month") or (hist_months[0]["key"] if hist_months else "")
    year = month = None
    try:
        y, m = hist_month.split("-")
        year, month = int(y), int(m)
        if not (1 <= month <= 12):
            raise ValueError
    except (ValueError, AttributeError):
        hist_month = hist_months[0]["key"] if hist_months else ""
        if hist_month:
            year, month = int(hist_month[:4]), int(hist_month[5:7])
    if year and month:
        versions = list(
            ScheduleVersion.objects.select_related("branch")
            .filter(work_date__year=year, work_date__month=month)
            .order_by("-work_date", "-uploaded_at")[:100]
        )
    else:
        versions = []
    return {"versions": versions, "hist_months": hist_months, "hist_month": hist_month}
