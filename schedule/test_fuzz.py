"""Фаззинг: мусор, XSS-пробы, границы — без 500 и без версий (T18-D)."""

import datetime
import io

from django.contrib.auth.models import User
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase
from django.utils import timezone
from openpyxl import Workbook
from rest_framework.test import APIClient

from accounts.models import DoctorProfile
from schedule.models import Branch, ScheduleVersion


def make_file(doc="Врачева А.А.", patient="Петров Петр Петрович"):
    wb = Workbook()
    ws = wb.active
    ws.cell(1, 1, "Hour")
    ws.cell(1, 2, "Min")
    ws.cell(1, 4, doc)
    ws.cell(2, 1, "09")
    ws.cell(2, 2, "00")
    ws.cell(2, 4, f"{patient}\nОсмотр")
    buf = io.BytesIO()
    wb.save(buf)
    buf.seek(0)
    return buf.read()


class FuzzTests(TestCase):
    def setUp(self):
        self.b1 = Branch.objects.create(code="F1", name="Филиал 1")
        self.staff = User.objects.create_user("adm", password="pw", is_staff=True)
        self.doc = User.objects.create_user("doc", password="pw")
        DoctorProfile.objects.create(
            user=self.doc, branch=self.b1, schedule_name="Врачева А.А.")
        self.client.login(username="doc", password="pw")
        self.api = APIClient()
        self.api.force_authenticate(user=self.doc)

    def test_evil_names_escaped_no_500(self):
        from schedule.services import upload_schedule
        day = timezone.localdate() + datetime.timedelta(days=2)
        evil_doc = "<script>alert(1)</script> Иваныч"
        evil_service = "Осмотр <img src=x onerror=1>"
        wb = Workbook()
        ws = wb.active
        ws.cell(1, 1, "Hour")
        ws.cell(1, 2, "Min")
        ws.cell(1, 4, evil_doc)
        ws.cell(2, 1, "09")
        ws.cell(2, 2, "00")
        ws.cell(2, 4, f"Петров Петр Петрович\n{evil_service}")
        buf = io.BytesIO()
        wb.save(buf)
        buf.seek(0)
        upload_schedule(branch=self.b1, work_date=day,
                        uploaded_file=SimpleUploadedFile("x.xlsx", buf.read()),
                        uploaded_by=None)
        r = self.client.get(f"/schedule/?date={day.isoformat()}&branch_id={self.b1.id}")
        self.assertEqual(r.status_code, 200)
        html = r.content.decode()
        self.assertNotIn("<script>alert(1)</script>", html)
        self.assertNotIn("<img src=x onerror=1>", html)
        self.assertIn("&lt;script&gt;", html)
        self.assertIn("&lt;img", html)

    def test_garbage_dates_branches(self):
        for bad_date in ["bogus", "32.13.0000", "", "2026-13-45", "None"]:
            r = self.client.get(f"/schedule/?date={bad_date}&branch_id={self.b1.id}")
            self.assertEqual(r.status_code, 200)
        for bad_branch in ["abc", "-1", "99999", ""]:
            r = self.client.get(
                f"/schedule/?date={timezone.localdate().isoformat()}&branch_id={bad_branch}")
            self.assertIn(r.status_code, (200, 403))
        self.assertEqual(ScheduleVersion.objects.count(), 0)

    def test_garbage_api(self):
        self.assertEqual(self.api.get("/api/schedule/my/?date=bogus").status_code, 400)
        self.assertEqual(self.api.get("/api/schedule/my/?branch_id=[]").status_code, 400)
        self.assertEqual(
            self.api.get("/api/schedule/full/?date=2026-02-30").status_code, 400)

    def test_garbage_files_no_versions(self):
        self.client.login(username="adm", password="pw")
        day = (timezone.localdate() + datetime.timedelta(days=2)).isoformat()
        bad_files = [
            ("t.txt", b"not excel at all"),
            ("e.xlsx", b""),
            ("cols.xlsx", make_file("", "")),
        ]
        for name, content in bad_files:
            n = ScheduleVersion.objects.count()
            r = self.client.post("/schedule/upload/", {
                "branch_ids": [str(self.b1.id)], "work_date": day,
                "file": SimpleUploadedFile(name, content)})
            self.assertEqual(r.status_code, 200)
            self.assertEqual(ScheduleVersion.objects.count(), n)

    def test_1c_garbage(self):
        admin = APIClient()
        admin.force_authenticate(user=self.staff)
        day = (timezone.localdate() + datetime.timedelta(days=2)).isoformat()
        for body in [
            {"branch_code": "F1", "work_date": day, "doctors": "notalist"},
            {"branch_code": "F1", "work_date": day,
             "doctors": [{"name": "", "appointments": []}]},
            {"branch_code": "F1", "work_date": day,
             "doctors": [{"name": "X", "appointments": [{"patient": ""}]}]},
            {"branch_code": "", "work_date": day, "doctors": []},
        ]:
            r = admin.post("/api/integration/schedule/", body, format="json")
            self.assertEqual(r.status_code, 400)
        self.assertEqual(ScheduleVersion.objects.count(), 0)
