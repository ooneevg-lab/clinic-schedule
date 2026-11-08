from django.contrib import admin

from .models import Branch, DoctorColumn, ScheduleEntry, ScheduleVersion


@admin.register(Branch)
class BranchAdmin(admin.ModelAdmin):
    list_display = ("code", "name", "is_active")


class DoctorColumnInline(admin.TabularInline):
    model = DoctorColumn
    extra = 0
    readonly_fields = ("name", "key", "source_column_index")
    can_delete = False


@admin.register(ScheduleVersion)
class ScheduleVersionAdmin(admin.ModelAdmin):
    list_display = ("work_date", "branch", "is_active", "services_count", "entries_count", "uploaded_at")
    list_filter = ("branch", "is_active", "work_date")
    inlines = [DoctorColumnInline]


@admin.register(ScheduleEntry)
class ScheduleEntryAdmin(admin.ModelAdmin):
    list_display = ("work_date", "branch_code", "column", "appointment_time", "full_name")
    list_filter = ("version__branch", "version__work_date")

    def work_date(self, obj):
        return obj.version.work_date

    def branch_code(self, obj):
        return obj.version.branch.code
