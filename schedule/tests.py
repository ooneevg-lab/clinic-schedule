from datetime import date
from pathlib import Path

from django.contrib.auth.models import User
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase
from rest_framework.authtoken.models import Token
from rest_framework.test import APIClient

from accounts.models import DoctorProfile
from schedule.models import Branch, ScheduleVersion
from schedule.parsing import normalize_doctor_key, parse_workbook
from schedule.services import upload_schedule

FIXTURE = Path(__file__).resolve().parent.parent.parent / "тест_расписания.xls"


class NormalizeTests(TestCase):
    def test_key_ignores_spaces_dots_case(self):
        self.assertEqual(normalize_doctor_key("Иванова А.А."), normalize_doctor_key("  иванова  А А "))
        self.assertEqual(normalize_doctor_key("Петрова-Иванова"), normalize_doctor_key("петрова иванова"))

    def test_yo(self):
        self.assertEqual(normalize_doctor_key("Фёдорова"), normalize_doctor_key("Федорова"))

    def test_key_survives_update_or_create(self):
        # Django 5 update_or_create сохраняет только поля из defaults —
        # вычисляемый ключ обязан попадать в БД и в этом случае.
        branch = Branch.objects.create(code="K", name="К")
        user = User.objects.create_user("keydoc", password="pw")
        DoctorProfile.objects.create(user=user, branch=branch, schedule_name="Ключева А.А.")
        DoctorProfile.objects.update_or_create(
            user=user, defaults={"branch": branch, "schedule_name": "Ключева А.А."}
        )
        profile = DoctorProfile.objects.get(user=user)
        self.assertEqual(profile.schedule_key, normalize_doctor_key("Ключева А.А."))
        self.assertTrue(profile.schedule_key)


class ParseTests(TestCase):
    def test_fixture_parses(self):
        if not FIXTURE.exists():
            self.skipTest("нет эталона тест_расписания.xls")
        with open(FIXTURE, "rb") as fh:
            uploaded = SimpleUploadedFile("тест_расписания.xls", fh.read())
        columns, rows = parse_workbook(uploaded)
        self.assertGreaterEqual(len(columns), 1)
        self.assertGreater(len(rows), 0)


class FlowTests(TestCase):
    def setUp(self):
        self.branch = Branch.objects.create(code="F1", name="Филиал 1")
        self.staff = User.objects.create_user("admin", password="pw", is_staff=True)
        self.doctor = User.objects.create_user("ivanova", password="pw")
        # Имя как в файле узнаем из парсинга, иначе fallback.
        name = "Иванова А.А."
        if FIXTURE.exists():
            with open(FIXTURE, "rb") as fh:
                uploaded = SimpleUploadedFile("t.xls", fh.read())
            columns, _ = parse_workbook(uploaded)
            if columns:
                name = columns[0][1]
        self.profile = DoctorProfile.objects.create(
            user=self.doctor, branch=self.branch, schedule_name=name
        )
        self.work_date = date(2026, 9, 15)
        if FIXTURE.exists():
            with open(FIXTURE, "rb") as fh:
                uploaded = SimpleUploadedFile("t.xls", fh.read())
            upload_schedule(branch=self.branch, work_date=self.work_date,
                            uploaded_file=uploaded, uploaded_by=self.staff)

    def test_my_only_mine(self):
        c = APIClient()
        r = c.post("/api/auth/login/", {"username": "ivanova", "password": "pw", "client": "app"})
        self.assertEqual(r.status_code, 200)
        token = Token.objects.get(user=self.doctor)
        self.assertEqual(r.data["token"], token.key)
        c.credentials(HTTP_AUTHORIZATION=f"Token {token.key}")
        my = c.get(f"/api/schedule/my/?date={self.work_date}&branch_id={self.branch.id}")
        full = c.get(f"/api/schedule/full/?date={self.work_date}&branch_id={self.branch.id}")
        self.assertEqual(my.status_code, 200)
        self.assertTrue(my.data["has_version"])
        self.assertTrue(my.data["has_column"])
        self.assertLessEqual(my.data["count"], full.data["count"])
        # Дата сегодня всегда в ответе.
        self.assertIn("today", my.data)

    def test_upload_requires_date(self):
        c = APIClient()
        c.force_authenticate(user=self.staff)
        r = c.post("/api/admin/upload/", {"branch_id": self.branch.id}, format="multipart")
        self.assertEqual(r.status_code, 400)

    def test_reupload_deactivates_old(self):
        if not FIXTURE.exists():
            self.skipTest("нет эталона")
        with open(FIXTURE, "rb") as fh:
            uploaded = SimpleUploadedFile("t.xls", fh.read())
        upload_schedule(branch=self.branch, work_date=self.work_date,
                        uploaded_file=uploaded, uploaded_by=self.staff)
        active = ScheduleVersion.objects.filter(
            branch=self.branch, work_date=self.work_date, is_active=True
        )
        self.assertEqual(active.count(), 1)

    def test_web_renders_pivot_grid(self):
        c = self.client
        c.login(username="ivanova", password="pw")
        r = c.get(f"/schedule/?date={self.work_date}&branch_id={self.branch.id}")
        self.assertEqual(r.status_code, 200)
        self.assertIn("grid_columns", r.context)
        self.assertIn("grid_rows", r.context)
        self.assertGreater(len(r.context["grid_rows"]), 0)
        # Мобильные карточки: те же врачи и то же число записей, что в сетке.
        cards = r.context["doctor_cards"]
        self.assertEqual(len(cards), len(r.context["grid_columns"]))
        self.assertEqual(sum(len(card["entries"]) for card in cards), r.context["full_count"])
        self.assertContains(r, "doctor-cards")

    def test_logout_requires_post(self):
        c = self.client
        c.login(username="ivanova", password="pw")
        self.assertEqual(c.get("/logout/").status_code, 405)
        self.assertEqual(c.post("/logout/").status_code, 302)
