"""API-контракты: auth, расписание, мультизагрузка (T10, T11)."""

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
from schedule.services import upload_schedule


def make_file():
    wb = Workbook()
    ws = wb.active
    ws.cell(1, 1, "Hour")
    ws.cell(1, 2, "Min")
    ws.cell(1, 4, "Врачева А.А.")
    ws.cell(2, 1, "09")
    ws.cell(2, 2, "00")
    ws.cell(2, 4, "Петров Петр Петрович\nОсмотр")
    buf = io.BytesIO()
    wb.save(buf)
    buf.seek(0)
    return buf.read()


class ApiContractTests(TestCase):
    def setUp(self):
        self.b1 = Branch.objects.create(code="F1", name="Филиал 1")
        self.b2 = Branch.objects.create(code="F2", name="Филиал 2")
        self.staff = User.objects.create_user("adm", password="pw", is_staff=True)
        self.doc = User.objects.create_user("doc", password="pw")
        DoctorProfile.objects.create(
            user=self.doc, branch=self.b1, schedule_name="Врачева А.А.")
        self.day = timezone.localdate() + datetime.timedelta(days=2)
        upload_schedule(branch=self.b1, work_date=self.day,
                        uploaded_file=SimpleUploadedFile("n.xlsx", make_file()),
                        uploaded_by=None)
        self.api = APIClient()
        self.api.force_authenticate(user=self.doc)
        self.admin = APIClient()
        self.admin.force_authenticate(user=self.staff)

    def test_login_branch_ids(self):
        r = APIClient().post("/api/auth/login/",
                             {"username": "doc", "password": "pw"})
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.data["branch_id"], self.b1.id)
        self.assertEqual(r.data["branch_ids"], [self.b1.id])

    def test_my_full_ok(self):
        my = self.api.get(f"/api/schedule/my/?date={self.day}&branch_id={self.b1.id}")
        full = self.api.get(f"/api/schedule/full/?date={self.day}&branch_id={self.b1.id}")
        self.assertEqual(my.status_code, 200)
        self.assertTrue(my.data["has_version"])
        self.assertLessEqual(my.data["count"], full.data["count"])
        self.assertIn("today", my.data)

    def test_bad_params_400(self):
        self.assertEqual(
            self.api.get("/api/schedule/my/?date=bogus").status_code, 400)
        self.assertEqual(
            self.api.get("/api/schedule/my/?branch_id=abc").status_code, 400)
        self.assertEqual(
            self.api.get("/api/schedule/my/?branch_id=99999").status_code, 400)

    def test_admin_upload_single_compat(self):
        day = (self.day + datetime.timedelta(days=5)).isoformat()
        r = self.admin.post("/api/admin/upload/", {
            "branch_id": self.b1.id, "work_date": day,
            "file": SimpleUploadedFile("s.xlsx", make_file())}, format="multipart")
        self.assertEqual(r.status_code, 201)
        self.assertEqual(r.data["branch"]["code"], "F1")
        self.assertIn("services_loaded", r.data)

    def test_admin_upload_multi(self):
        day = (self.day + datetime.timedelta(days=6)).isoformat()
        r = self.admin.post("/api/admin/upload/", {
            "branch_ids": [self.b1.id, self.b2.id], "work_date": day,
            "file": SimpleUploadedFile("m.xlsx", make_file())}, format="multipart")
        self.assertEqual(r.status_code, 201)
        self.assertEqual(len(r.data["branches"]), 2)
        self.assertTrue(ScheduleVersion.objects.filter(
            branch=self.b2, work_date=day, is_active=True).exists())

    def test_admin_upload_requires_branch(self):
        r = self.admin.post("/api/admin/upload/", {"work_date": str(self.day)},
                            format="multipart")
        self.assertEqual(r.status_code, 400)
