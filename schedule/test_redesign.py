"""Behavioral coverage for the unified calendar and redesigned forms."""
from datetime import timedelta

from django.contrib.auth.models import User
from django.test import TestCase
from django.utils import timezone

from accounts.models import DoctorProfile
from schedule.models import Branch, DoctorColumn, ScheduleVersion


class RedesignTests(TestCase):
    def setUp(self):
        self.branch = Branch.objects.create(code="DESIGN", name="Тестовый филиал")
        self.user = User.objects.create_user("design-doctor")
        DoctorProfile.objects.create(
            user=self.user, branch=self.branch, schedule_name="Тестова А.А.")
        self.client.force_login(self.user)
        self.today = timezone.localdate()

    def version(self, day, **kwargs):
        return ScheduleVersion.objects.create(
            branch=self.branch, work_date=day, file_name="test.xlsx", **kwargs)

    def test_calendar_includes_history_and_excludes_other_branch_and_archives(self):
        past = self.today - timedelta(days=100)
        self.version(past)
        self.version(self.today + timedelta(days=4), is_active=False)
        foreign = Branch.objects.create(code="FOREIGN", name="Другой")
        ScheduleVersion.objects.create(
            branch=foreign, work_date=self.today, file_name="foreign.xlsx")
        response = self.client.get("/schedule/")
        self.assertEqual([d["iso"] for d in response.context["calendar_dates"]],
                         [past.isoformat()])
        self.assertNotContains(response, "FOREIGN")

    def test_calendar_marks_read_after_open_and_ack(self):
        tomorrow = self.today + timedelta(days=1)
        version = self.version(tomorrow)
        first = self.client.get("/schedule/")
        self.assertTrue(first.context["calendar_dates"][0]["is_new"])
        opened = self.client.get("/schedule/", {"date": tomorrow.isoformat()})
        self.assertFalse(opened.context["calendar_dates"][0]["is_new"])
        self.assertNotContains(opened, 'id="news-banner"')
        next_version = self.version(self.today + timedelta(days=2))
        acknowledged = self.client.get("/schedule/", {"ack_news": next_version.id})
        self.assertTrue(all(not d["is_new"] for d in acknowledged.context["calendar_dates"]))
        self.assertNotContains(acknowledged, 'id="news-banner"')

    def test_missing_publication_column_and_empty_column_are_distinct(self):
        self.assertContains(self.client.get("/schedule/"), "Расписание пока не опубликовано")
        version = self.version(self.today)
        self.assertContains(self.client.get("/schedule/"), "Ваша колонка не найдена")
        DoctorColumn.objects.create(version=version, name="Тестова А.А.", source_column_index=4)
        self.assertContains(self.client.get("/schedule/"), "На этот день записей нет")

    def test_day_navigation_is_relative_and_preserves_branch(self):
        day = self.today + timedelta(days=50)
        response = self.client.get("/schedule/", {"date": day.isoformat(), "branch_id": self.branch.id})
        self.assertContains(response, f'?date={(day - timedelta(days=1)).isoformat()}&branch_id={self.branch.id}')
        self.assertContains(response, f'?date={(day + timedelta(days=1)).isoformat()}&branch_id={self.branch.id}')

    def test_failed_upload_retains_date_and_selected_branches(self):
        self.user.is_staff = True
        self.user.save()
        selected = (self.today + timedelta(days=40)).isoformat()
        response = self.client.post("/schedule/upload/", {
            "work_date": selected, "branch_ids": [str(self.branch.id)]})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["default_date"], selected)
        self.assertEqual(response.context["selected_branch_ids"], [str(self.branch.id)])
        self.assertContains(response, "Приложите Excel-файл")
        self.assertContains(response, 'checked')
