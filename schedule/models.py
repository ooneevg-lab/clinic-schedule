from django.conf import settings
from django.db import models

from .parsing import normalize_doctor_key


class Branch(models.Model):
    code = models.CharField(max_length=64, unique=True)
    name = models.TextField()
    is_active = models.BooleanField(default=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "sched_branches"

    def __str__(self):
        return f"{self.code} — {self.name}"


class ScheduleVersion(models.Model):
    """Одна загрузка = пара (дата + филиал). Новая загрузка деактивирует старую."""

    branch = models.ForeignKey(Branch, on_delete=models.CASCADE, related_name="versions")
    work_date = models.DateField(verbose_name="Дата расписания (обязательно)")
    file_name = models.CharField(max_length=255)
    uploaded_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True
    )
    uploaded_at = models.DateTimeField(auto_now_add=True)
    is_active = models.BooleanField(default=True)
    services_count = models.PositiveIntegerField(default=0)
    entries_count = models.PositiveIntegerField(default=0)

    class Meta:
        db_table = "sched_versions"
        constraints = [
            models.UniqueConstraint(
                fields=["branch", "work_date", "is_active"],
                condition=models.Q(is_active=True),
                name="uq_sched_versions_branch_date_active",
            ),
        ]
        indexes = [models.Index(fields=["branch", "work_date"], name="idx_sched_ver_br_date")]
        ordering = ["-work_date", "-uploaded_at"]

    def __str__(self):
        return f"{self.branch.code} {self.work_date} ({'активна' if self.is_active else 'архив'})"


class DoctorColumn(models.Model):
    version = models.ForeignKey(ScheduleVersion, on_delete=models.CASCADE, related_name="columns")
    name = models.TextField(verbose_name="Имя колонки как в Excel")
    key = models.TextField(editable=False)
    source_column_index = models.PositiveIntegerField(default=0)

    class Meta:
        db_table = "sched_columns"
        constraints = [
            models.UniqueConstraint(
                fields=["version", "source_column_index"],
                name="uq_sched_columns_version_index",
            ),
        ]
        indexes = [models.Index(fields=["version", "key"], name="idx_sched_col_ver_key")]

    def save(self, *args, **kwargs):
        self.key = normalize_doctor_key(self.name)
        # update_or_create() сохраняет только поля из defaults: ключ иначе
        # посчитается в памяти, но не попадёт в БД. Дописываем его явно.
        if kwargs.get("update_fields") is not None:
            kwargs["update_fields"] = set(kwargs["update_fields"]) | {"key"}
        super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.name} [{self.version}]"


class ScheduleEntry(models.Model):
    version = models.ForeignKey(ScheduleVersion, on_delete=models.CASCADE, related_name="entries")
    column = models.ForeignKey(DoctorColumn, on_delete=models.CASCADE, related_name="entries")
    appointment_time = models.TimeField(null=True, blank=True)
    full_name = models.TextField(verbose_name="ФИО пациента")
    age = models.TextField(null=True, blank=True)
    service_name = models.TextField(null=True, blank=True)

    class Meta:
        db_table = "sched_entries"
        indexes = [
            models.Index(fields=["version", "column"], name="idx_sched_entries_ver_col"),
            models.Index(fields=["column", "appointment_time"], name="idx_sched_entries_col_time"),
        ]
        ordering = ["appointment_time", "full_name"]

    def __str__(self):
        t = self.appointment_time.strftime("%H:%M") if self.appointment_time else "--:--"
        return f"{t} {self.full_name} ({self.column.name})"
