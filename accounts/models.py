from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models

from schedule.parsing import normalize_doctor_key


class DoctorProfile(models.Model):
    """Карточка врача. Создаёт суперпользователь в админке.

    schedule_name — ФИО как в таблице 1С. key считается сам и сравнивается
    с DoctorColumn.key внутри филиала врача.
    """

    user = models.OneToOneField(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="doctor_profile"
    )
    branch = models.ForeignKey(
        "schedule.Branch", on_delete=models.SET_NULL, null=True, blank=True,
        related_name="doctors", help_text="Основной филиал врача",
    )
    branches = models.ManyToManyField(
        "schedule.Branch", blank=True, related_name="assigned_doctors",
        help_text="Филиалы врача: выбор, новости и уведомления. Пусто — видны все.",
    )
    schedule_name = models.CharField(
        max_length=255, verbose_name="ФИО как в таблице",
        help_text="Точно как заголовок колонки в Excel, напр. Иванова А.А.",
    )
    schedule_key = models.CharField(max_length=255, editable=False)
    updated_at = models.DateTimeField(auto_now=True)
    # ID версий расписания, которые врач уже видел (новости/NEW не повторяются
    # после выхода: сессия при logout сносится, профиль — нет).
    seen_schedule_version_ids = models.JSONField(default=list, blank=True)

    class Meta:
        db_table = "sched_doctor_profiles"

    def save(self, *args, **kwargs):
        self.schedule_key = normalize_doctor_key(self.schedule_name)
        # update_or_create() сохраняет только поля из defaults — см. комментарий
        # в schedule.models.DoctorColumn.save. Дописываем ключ явно.
        if kwargs.get("update_fields") is not None:
            kwargs["update_fields"] = set(kwargs["update_fields"]) | {"schedule_key"}
        super().save(*args, **kwargs)

    def my_columns(self, version):
        from schedule.models import DoctorColumn

        return DoctorColumn.objects.filter(version=version, key=self.schedule_key)

    def clean(self):
        super().clean()
        has_primary = bool(self.branch_id)
        has_set = bool(self.pk and self.branches.exists())
        if not has_primary and not has_set:
            raise ValidationError(
                "Назначьте врачу филиал: основной или набор «Филиалы врача». "
                "Без набора доступ закрыт (default-deny)."
            )

    def allowed_branch_ids(self):
        """ID филиалов врача: основной + набор. Пусто — ограничение не задано."""
        ids = set(self.branches.values_list("id", flat=True))
        if self.branch_id:
            ids.add(self.branch_id)
        return ids

    def get_seen_version_ids(self):
        try:
            return {int(x) for x in (self.seen_schedule_version_ids or [])}
        except (TypeError, ValueError):
            return set()

    def add_seen_version_ids(self, ids):
        seen = self.get_seen_version_ids()
        new = {int(x) for x in ids} - seen
        if not new:
            return False
        seen |= new
        self.seen_schedule_version_ids = sorted(seen)[-200:]
        self.save(update_fields=["seen_schedule_version_ids", "updated_at"])
        return True

    def __str__(self):
        return f"{self.schedule_name} ({self.user.username})"


class LoginEvent(models.Model):
    """Журнал входов/выходов для аналитики пользования."""

    VIA_CHOICES = [("site", "Сайт"), ("app", "Приложение")]

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="login_events"
    )
    via = models.CharField(max_length=8, choices=VIA_CHOICES, default="site")
    ip = models.GenericIPAddressField(null=True, blank=True)
    user_agent = models.TextField(blank=True, null=True)
    login_at = models.DateTimeField(auto_now_add=True)
    logout_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "sched_login_events"
        indexes = [models.Index(fields=["user", "login_at"], name="idx_sched_login_user_time")]
        ordering = ["-login_at"]

    def __str__(self):
        return f"{self.user.username} {self.via} {self.login_at:%d.%m %H:%M}"


class PushDevice(models.Model):
    """Адрес установки приложения для пушей (FCM token / FID).

    Одна строка = одна установка приложения на одном телефоне.
    Владелец всегда один и текущий: кто последним вошел на этом телефоне,
    тот и получает пуши. Поле registration называем нейтрально, чтобы
    пережить переход Firebase с registration token на Installation ID.
    """

    PLATFORM_CHOICES = [("android", "Android")]

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="push_devices"
    )
    registration = models.CharField(
        max_length=255, unique=True,
        help_text="Адрес установки от Firebase (token / Installation ID).",
    )
    platform = models.CharField(max_length=16, choices=PLATFORM_CHOICES, default="android")
    active = models.BooleanField(
        default=True,
        help_text="Выключено после выхода из аккаунта или чистки недействительных адресов.",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    last_seen_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "sched_push_devices"
        indexes = [
            models.Index(fields=["user", "active"], name="idx_push_device_user_active"),
        ]

    def __str__(self):
        state = "активно" if self.active else "выключено"
        return f"{self.user.username} {self.platform} {state}"
