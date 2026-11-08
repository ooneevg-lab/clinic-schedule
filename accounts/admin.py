from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin
from django.contrib.auth.models import User

from schedule.models import DoctorColumn, ScheduleVersion

from .models import DoctorProfile, LoginEvent, PushDevice


class DoctorProfileInline(admin.StackedInline):
    model = DoctorProfile
    can_delete = False
    extra = 0
    fields = ("branch", "branches", "schedule_name")
    filter_horizontal = ("branches",)
    verbose_name = "Карточка врача"
    verbose_name_plural = "Карточка врача"


class UserAdmin(BaseUserAdmin):
    inlines = [DoctorProfileInline]
    list_display = ("username", "get_schedule_name", "get_branch", "is_active", "is_staff")

    def get_schedule_name(self, obj):
        return getattr(getattr(obj, "doctor_profile", None), "schedule_name", "—")

    get_schedule_name.short_description = "ФИО как в таблице"

    def get_branch(self, obj):
        profile = getattr(obj, "doctor_profile", None)
        return profile.branch.code if profile and profile.branch else "—"

    get_branch.short_description = "Филиал"

    def save_model(self, request, obj, form, change):
        super().save_model(request, obj, form, change)

    def save_formset(self, request, form, formset, change):
        instances = formset.save(commit=False)
        for instance in instances:
            instance.save()
        formset.save_m2m()


admin.site.unregister(User)
admin.site.register(User, UserAdmin)


@admin.register(DoctorProfile)
class DoctorProfileAdmin(admin.ModelAdmin):
    list_display = ("schedule_name", "user", "branch", "schedule_key", "match_status")
    list_filter = ("branch", "branches")
    search_fields = ("schedule_name", "user__username")
    filter_horizontal = ("branches",)

    def match_status(self, obj):
        if not obj.branch:
            return "⚠️ нет филиала"
        version = (
            ScheduleVersion.objects.filter(branch=obj.branch, is_active=True)
            .order_by("-work_date")
            .first()
        )
        if version is None:
            return "— нет загрузок"
        n = DoctorColumn.objects.filter(version=version, key=obj.schedule_key).count()
        if n == 1:
            return f"✅ {version.work_date}"
        if n == 0:
            return f"⚠️ нет колонки на {version.work_date}"
        return f"⚠️ дубли: {n}"

    match_status.short_description = "Сопоставление"


@admin.register(LoginEvent)
class LoginEventAdmin(admin.ModelAdmin):
    list_display = ("user", "via", "ip", "login_at", "logout_at")
    list_filter = ("via", "login_at")
    search_fields = ("user__username",)
    date_hierarchy = "login_at"


@admin.register(PushDevice)
class PushDeviceAdmin(admin.ModelAdmin):
    list_display = ("user", "short_registration", "platform", "active", "updated_at")
    list_filter = ("platform", "active")
    search_fields = ("user__username", "registration")

    def short_registration(self, obj):
        reg = obj.registration or ""
        return reg[:12] + "…" if len(reg) > 13 else reg

    short_registration.short_description = "Адрес Firebase"
