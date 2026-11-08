"""Эндпоинт 1С: POST /api/integration/schedule/ (T16)."""

import datetime

from django.contrib.auth.models import User
from django.test import TestCase
from django.utils import timezone
from rest_framework.test import APIClient

from accounts.models import DoctorProfile
from schedule.models import Branch, ScheduleVersion


def payload(code="F1", day=None, doctors=None):
    return {
        "branch_code": code,
        "work_date": day or (timezone.localdate() + datetime.timedelta(days=2)).isoformat(),
        "doctors": doctors if doctors is not None else [
            {"name": "Врачева А.А.", "appointments": [
                {"time": "09:00", "patient": "Петров Петр Петрович", "service": "Осмотр"},
                {"time": None, "patient": "Сидоров Сидор Сидорович"},
            ]},
        ],
    }


class IntegrationTests(TestCase):
    def setUp(self):
        self.b1 = Branch.objects.create(code="F1", name="Филиал 1")
        self.staff = User.objects.create_user("adm1c", password="pw", is_staff=True)
        self.doc = User.objects.create_user("doc", password="pw")
        DoctorProfile.objects.create(
            user=self.doc, branch=self.b1, schedule_name="Врачева А.А.")
        self.api = APIClient()
        self.api.force_authenticate(user=self.staff)

    def test_ok_and_unmatched_empty(self):
        r = self.api.post("/api/integration/schedule/", payload(), format="json")
        self.assertEqual(r.status_code, 201)
        self.assertEqual(r.data["status"], "ok")
        self.assertEqual(r.data["branch"]["code"], "F1")
        self.assertEqual(r.data["services_loaded"], 1)
        self.assertEqual(r.data["patients_loaded"], 2)
        self.assertEqual(r.data["unmatched"], [])

    def test_unmatched_listed_not_failing(self):
        p = payload(doctors=[{"name": "Неизвестная А.А.", "appointments": [
            {"time": "10:00", "patient": "Петров Петр Петрович"}]}])
        r = self.api.post("/api/integration/schedule/", p, format="json")
        self.assertEqual(r.status_code, 201)
        self.assertEqual(r.data["unmatched"], ["Неизвестная А.А."])

    def test_unknown_branch_with_codes(self):
        r = self.api.post("/api/integration/schedule/",
                          payload(code="FX"), format="json")
        self.assertEqual(r.status_code, 400)
        self.assertIn("F1", r.data["branch_codes"])

    def test_bad_payload_indexed(self):
        p = payload()
        self.assertEqual(
            self.api.post("/api/integration/schedule/",
                          {**p, "work_date": "bogus"}, format="json").status_code, 400)
        self.assertEqual(
            self.api.post("/api/integration/schedule/",
                          {**p, "doctors": []}, format="json").status_code, 400)
        bad_time = payload(doctors=[{"name": "Врачева А.А.", "appointments": [
            {"time": "25:00", "patient": "Петров Петр Петрович"}]}])
        r = self.api.post("/api/integration/schedule/", bad_time, format="json")
        self.assertEqual(r.status_code, 400)
        self.assertIn("doctors[0].appointments[0]", r.data["detail"])
        no_patient = payload(doctors=[{"name": "Врачева А.А.", "appointments": [
            {"time": "09:00", "patient": "  "}]}])
        r = self.api.post("/api/integration/schedule/", no_patient, format="json")
        self.assertEqual(r.status_code, 400)
        self.assertIn("patient", r.data["detail"])

    def test_idempotent_repush(self):
        p = payload()
        self.api.post("/api/integration/schedule/", p, format="json")
        self.api.post("/api/integration/schedule/", p, format="json")
        active = ScheduleVersion.objects.filter(
            branch=self.b1, work_date=p["work_date"], is_active=True)
        self.assertEqual(active.count(), 1)

    def test_non_staff_forbidden(self):
        api = APIClient()
        api.force_authenticate(user=self.doc)
        self.assertEqual(
            api.post("/api/integration/schedule/", payload(), format="json").status_code,
            403)

    def test_deny_empty_set_api(self):
        naked = User.objects.create_user("naked", password="pw")
        DoctorProfile.objects.create(
            user=naked, branch=None, schedule_name="Голая А.А.")
        api = APIClient()
        api.force_authenticate(user=naked)
        self.assertEqual(
            api.get(f"/api/schedule/my/?branch_id={self.b1.id}").status_code, 403)
