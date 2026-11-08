"""Web-загрузка: мультифилиалы + история по месяцам (T11, T12)."""

import datetime
import io

from django.contrib.auth.models import User
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase
from django.utils import timezone
from openpyxl import Workbook

from accounts.models import DoctorProfile
from schedule.models import Branch, ScheduleVersion
from schedule.services import upload_schedule


def make_file(doc="Врачева А.А."):
    wb = Workbook()
    ws = wb.active
    ws.cell(1, 1, "Hour")
    ws.cell(1, 2, "Min")
    ws.cell(1, 4, doc)
    ws.cell(2, 1, "09")
    ws.cell(2, 2, "00")
    ws.cell(2, 4, "Петров Петр Петрович\nОсмотр")
    buf = io.BytesIO()
    wb.save(buf)
    buf.seek(0)
    return buf.read()


class MultiUploadTests(TestCase):
    def setUp(self):
        self.b1 = Branch.objects.create(code="F1", name="Филиал 1")
        self.b2 = Branch.objects.create(code="F2", name="Филиал 2")
        self.staff = User.objects.create_user("adm", password="pw", is_staff=True)
        self.client.login(username="adm", password="pw")
        self.day = (timezone.localdate() + datetime.timedelta(days=2)).isoformat()

    def test_multi_two_branches(self):
        r = self.client.post("/schedule/upload/", {
            "branch_ids": [str(self.b1.id), str(self.b2.id)],
            "work_date": self.day,
            "file": SimpleUploadedFile("m.xlsx", make_file()),
        })
        self.assertEqual(r.status_code, 302)
        self.assertIn(f"branch_id={self.b1.id}", r.url)
        v1 = ScheduleVersion.objects.get(branch=self.b1, work_date=self.day, is_active=True)
        v2 = ScheduleVersion.objects.get(branch=self.b2, work_date=self.day, is_active=True)
        self.assertEqual(v1.entries_count, v2.entries_count)
        self.assertGreater(v1.entries_count, 0)

    def test_legacy_single_branch_id(self):
        r = self.client.post("/schedule/upload/", {
            "branch_id": str(self.b1.id),
            "work_date": self.day,
            "file": SimpleUploadedFile("s.xlsx", make_file()),
        })
        self.assertEqual(r.status_code, 302)
        self.assertTrue(ScheduleVersion.objects.filter(
            branch=self.b1, work_date=self.day, is_active=True).exists())

    def test_no_branches_error_without_versions(self):
        n = ScheduleVersion.objects.count()
        r = self.client.post("/schedule/upload/", {
            "work_date": self.day,
            "file": SimpleUploadedFile("e.xlsx", make_file()),
        })
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, "Укажите филиал")
        self.assertEqual(ScheduleVersion.objects.count(), n)

    def test_bad_branch_ids(self):
        n = ScheduleVersion.objects.count()
        r = self.client.post("/schedule/upload/", {
            "branch_ids": ["99999"],
            "work_date": self.day,
            "file": SimpleUploadedFile("e.xlsx", make_file()),
        })
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, "Некорректные филиалы")
        self.assertEqual(ScheduleVersion.objects.count(), n)


class HistoryMonthTests(TestCase):
    def setUp(self):
        self.b1 = Branch.objects.create(code="F1", name="Филиал 1")
        self.staff = User.objects.create_user("adm", password="pw", is_staff=True)
        self.client.login(username="adm", password="pw")
        today = timezone.localdate()
        self.d_new = today + datetime.timedelta(days=2)
        self.d_old = today - datetime.timedelta(days=45)
        upload_schedule(branch=self.b1, work_date=self.d_new,
                        uploaded_file=SimpleUploadedFile("n.xlsx", make_file()),
                        uploaded_by=None)
        upload_schedule(branch=self.b1, work_date=self.d_old,
                        uploaded_file=SimpleUploadedFile("o.xlsx", make_file()),
                        uploaded_by=None)
        self.key_new = f"{self.d_new.year}-{self.d_new.month:02d}"
        self.key_old = f"{self.d_old.year}-{self.d_old.month:02d}"

    def test_months_with_counts_default_freshest(self):
        r = self.client.get("/schedule/upload/")
        self.assertEqual(r.status_code, 200)
        months = {m["key"]: m["count"] for m in r.context["hist_months"]}
        self.assertEqual(months.get(self.key_new), 1)
        self.assertEqual(months.get(self.key_old), 1)
        self.assertEqual(r.context["hist_month"], self.key_new)
        self.assertContains(r, self.d_new.isoformat())
        self.assertNotContains(r, self.d_old.isoformat())

    def test_filter_old_month_and_bad_param(self):
        r = self.client.get(f"/schedule/upload/?hist_month={self.key_old}")
        self.assertContains(r, self.d_old.isoformat())
        self.assertNotContains(r, self.d_new.isoformat())
        r2 = self.client.get("/schedule/upload/?hist_month=bogus")
        self.assertEqual(r2.context["hist_month"], self.key_new)

    def test_date_links_to_schedule(self):
        r = self.client.get("/schedule/upload/")
        self.assertContains(
            r, f"/schedule/?date={self.d_new.isoformat()}&branch_id={self.b1.id}")
