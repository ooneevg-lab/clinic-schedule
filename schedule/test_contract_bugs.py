"""Охотники: поведение против заявленного, филиалы, логика (T18-A,B,E)."""

import datetime
import io

from django.contrib.auth.models import User
from django.core.exceptions import ValidationError
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase
from django.utils import timezone
from openpyxl import Workbook

from accounts.models import DoctorProfile
from schedule.models import Branch, ScheduleVersion
from schedule.services import upload_schedule


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


class ContractBugsTests(TestCase):
    def setUp(self):
        self.b1 = Branch.objects.create(code="F1", name="Филиал 1")
        self.b2 = Branch.objects.create(code="F2", name="Филиал 2")
        self.doc = User.objects.create_user("doc", password="pw")
        self.profile = DoctorProfile.objects.create(
            user=self.doc, branch=self.b1, schedule_name="Врачева А.А.")
        self.client.login(username="doc", password="pw")
        self.today = timezone.localdate()
        self.vd = self.today + datetime.timedelta(days=2)
        upload_schedule(branch=self.b1, work_date=self.vd,
                        uploaded_file=SimpleUploadedFile("n.xlsx", make_file()),
                        uploaded_by=None)
        upload_schedule(branch=self.b2, work_date=self.vd,
                        uploaded_file=SimpleUploadedFile("f.xlsx", make_file("Вторая А.А.")),
                        uploaded_by=None)
        self.v1 = ScheduleVersion.objects.get(branch=self.b1, work_date=self.vd)
        self.v2 = ScheduleVersion.objects.get(branch=self.b2, work_date=self.vd)

    def test_no_foreign_branch_anywhere(self):
        # Каскад, новости, чипы врача F1 не содержат F2.
        r = self.client.get("/schedule/")
        content = r.content.decode()
        dates = [d for y in r.context["upcoming_cascade"]
                 for m in y["months"] for d in m["dates"]]
        self.assertEqual(len(dates), 1)  # только дата своего филиала
        self.assertNotIn("F2", content)
        news_ids = {n["id"] for n in r.context["news"]}
        self.assertIn(self.v1.id, news_ids)
        self.assertNotIn(self.v2.id, news_ids)

    def test_foreign_ack_does_not_leak(self):
        # ack чужой версии не показывает чужие данные и не роняет.
        r = self.client.get(f"/schedule/?ack_news={self.v2.id}")
        self.assertEqual(r.status_code, 200)
        self.assertNotIn("F2", r.content.decode())

    def test_cascade_defaults_follow_viewed_day(self):
        r = self.client.get(
            f"/schedule/?date={self.vd.isoformat()}&branch_id={self.b1.id}")
        self.assertEqual(r.context["have_day"], self.vd.isoformat())
        self.assertEqual(r.context["have_year"], self.vd.year)

    def test_transfer_moves_news_and_access(self):
        # Перевод врача F1 -> F2: доступ и новости уже по F2, seen цел.
        self.profile.branch = self.b2
        self.profile.save()
        self.profile.branches.clear()
        branches = {n["branch_id"] for n in self.client.get("/schedule/").context["news"]}
        self.assertEqual(branches, {self.b2.id})
        r = self.client.get(
            f"/schedule/?date={self.vd.isoformat()}&branch_id={self.b2.id}")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(
            self.client.get(
                f"/schedule/?date={self.vd.isoformat()}&branch_id={self.b1.id}"
            ).status_code, 403)

    def test_inactive_primary_denied_not_stuck(self):
        # Единственный назначенный филиал неактивен: внятный 403, а не
        # залипание на пустом неактивном и не 500.
        self.b1.is_active = False
        self.b1.save()
        r = self.client.get("/schedule/")
        self.assertEqual(r.status_code, 403)
        # А если в наборе есть активный — дефолт уходит на него, 200.
        self.profile.branches.add(self.b2)
        r2 = self.client.get("/schedule/")
        self.assertEqual(r2.status_code, 200)
        self.assertEqual(r2.context["branch"].id, self.b2.id)

    def test_naked_profile_denied_with_hint(self):
        naked = User.objects.create_user("naked", password="pw")
        DoctorProfile.objects.create(
            user=naked, branch=None, schedule_name="Голая А.А.")
        self.client.login(username="naked", password="pw")
        r = self.client.get("/schedule/")
        self.assertEqual(r.status_code, 403)
        self.assertIn("администратор", r.content.decode().lower())

    def test_bare_profile_rejected_by_clean(self):
        naked = User.objects.create_user("naked2", password="pw")
        prof = DoctorProfile(user=naked, branch=None, schedule_name="Голая А.А.")
        with self.assertRaises(ValidationError):
            prof.full_clean()
