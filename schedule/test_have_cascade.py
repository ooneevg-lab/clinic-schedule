"""Каскад «Есть расписание» + seen/ack-персистентность (T9, T10, T13)."""

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


class HaveCascadeTests(TestCase):
    def setUp(self):
        self.b1 = Branch.objects.create(code="F1", name="Филиал 1")
        self.doc = User.objects.create_user("doc", password="pw")
        self.profile = DoctorProfile.objects.create(
            user=self.doc, branch=self.b1, schedule_name="Врачева А.А.")
        self.client.login(username="doc", password="pw")
        self.today = timezone.localdate()
        self.vd = self.today + datetime.timedelta(days=2)
        upload_schedule(branch=self.b1, work_date=self.vd,
                        uploaded_file=SimpleUploadedFile("n.xlsx", make_file()),
                        uploaded_by=None)
        self.ver = ScheduleVersion.objects.get(branch=self.b1, work_date=self.vd)

    def test_cascade_structure_and_new_before_open(self):
        r = self.client.get(
            f"/schedule/?date={self.today.isoformat()}&branch_id={self.b1.id}")
        self.assertEqual(r.status_code, 200)
        cas = r.context["upcoming_cascade"]
        self.assertEqual(len(cas), 1)
        self.assertEqual(cas[0]["year"], self.vd.year)
        day = cas[0]["months"][0]["dates"][0]
        self.assertEqual(day["iso"], self.vd.isoformat())
        self.assertTrue(day["is_new"])
        self.assertContains(r, 'id="schedule-calendar"')
        self.assertContains(r, 'id="calendar-days"')
        self.assertContains(r, 'id="calendar-data"')

    def test_new_gone_after_open_and_relogin_quiet(self):
        self.client.get(f"/schedule/?date={self.vd.isoformat()}&branch_id={self.b1.id}")
        r = self.client.get(
            f"/schedule/?date={self.today.isoformat()}&branch_id={self.b1.id}")
        day = r.context["upcoming_cascade"][0]["months"][0]["dates"][0]
        self.assertFalse(day["is_new"])
        self.client.logout()
        self.client.login(username="doc", password="pw")
        r2 = self.client.get("/schedule/")
        self.assertNotContains(r2, 'id="news-banner"')
        day2 = r2.context["upcoming_cascade"][0]["months"][0]["dates"][0]
        self.assertFalse(day2["is_new"])

    def test_ack_dismisses_news(self):
        r = self.client.get("/schedule/")
        self.assertContains(r, 'id="news-banner"')
        self.client.get(f"/schedule/?ack_news={self.ver.id}")
        self.assertNotContains(self.client.get("/schedule/"), 'id="news-banner"')

    def test_empty_branch_stub(self):
        b2 = Branch.objects.create(code="F2", name="Филиал 2")
        self.profile.branches.add(b2)
        r = self.client.get(
            f"/schedule/?date={self.today.isoformat()}&branch_id={b2.id}")
        self.assertEqual(r.context["upcoming_cascade"], [])
        self.assertContains(r, "Расписание пока не опубликовано")

    def test_no_zalito_wording(self):
        r = self.client.get("/schedule/")
        content = r.content.decode()
        self.assertIn("опубликовано", content.lower())
        self.assertNotIn("залито", content)
        self.assertNotIn("Залито", content)


class NearestDateTests(TestCase):
    def setUp(self):
        self.b1 = Branch.objects.create(code="F1", name="Филиал 1")
        self.doc = User.objects.create_user("doc", password="pw")
        DoctorProfile.objects.create(
            user=self.doc, branch=self.b1, schedule_name="Врачева А.А.")
        self.client.login(username="doc", password="pw")
        self.today = timezone.localdate()
        for delta in (-5, 2, 10):
            upload_schedule(
                branch=self.b1, work_date=self.today + datetime.timedelta(days=delta),
                uploaded_file=SimpleUploadedFile(f"n{delta}.xlsx", make_file()),
                uploaded_by=None)

    def _nearest_iso(self, day):
        r = self.client.get(
            f"/schedule/?date={day.isoformat()}&branch_id={self.b1.id}")
        self.assertEqual(r.status_code, 200)
        return r.context["nearest_date"]["iso"], r.content.decode()

    def test_nearest_not_first(self):
        # Запрос +7 (пусто): +2 (5 назад) против +10 (3 вперёд) → +10, а не +2.
        iso, html = self._nearest_iso(self.today + datetime.timedelta(days=7))
        self.assertEqual(iso, (self.today + datetime.timedelta(days=10)).isoformat())
        self.assertIn(f"?date={iso}&branch_id={self.b1.id}", html)

    def test_nearest_looks_back(self):
        iso, _ = self._nearest_iso(self.today - datetime.timedelta(days=10))
        self.assertEqual(iso, (self.today - datetime.timedelta(days=5)).isoformat())

    def test_tie_prefers_future(self):
        # Запрос +6: +2 (4 назад) и +10 (4 вперёд) — ничья → будущее.
        iso, _ = self._nearest_iso(self.today + datetime.timedelta(days=6))
        self.assertEqual(iso, (self.today + datetime.timedelta(days=10)).isoformat())
