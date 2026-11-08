"""Доступ к филиалам: свой набор — можно, чужой — 403 (T15)."""

import datetime

from django.contrib.auth.models import User
from django.test import TestCase
from django.utils import timezone

from accounts.models import DoctorProfile
from schedule.models import Branch


class BranchAccessTests(TestCase):
    def setUp(self):
        self.b1 = Branch.objects.create(code="F1", name="Филиал 1")
        self.b2 = Branch.objects.create(code="F2", name="Филиал 2")
        self.doc = User.objects.create_user("doc", password="pw")
        DoctorProfile.objects.create(
            user=self.doc, branch=self.b1, schedule_name="Врачева А.А.")
        self.free = User.objects.create_user("free", password="pw")
        DoctorProfile.objects.create(
            user=self.free, branch=None, schedule_name="Свободная А.А.")
        self.staff = User.objects.create_user("adm", password="pw", is_staff=True)
        self.day = (timezone.localdate() + datetime.timedelta(days=1)).isoformat()

    def _get(self, username, branch):
        self.client.login(username=username, password="pw")
        r = self.client.get(f"/schedule/?date={self.day}&branch_id={branch.id}")
        self.client.logout()
        return r

    def test_own_branch_ok(self):
        self.assertEqual(self._get("doc", self.b1).status_code, 200)

    def test_foreign_branch_forbidden(self):
        r = self._get("doc", self.b2)
        self.assertEqual(r.status_code, 403)

    def test_staff_sees_all(self):
        self.assertEqual(self._get("adm", self.b2).status_code, 200)

    def test_doctor_without_set_denied(self):
        r = self._get("free", self.b2)
        self.assertEqual(r.status_code, 403)
        r = self._get("free", self.b1)
        self.assertEqual(r.status_code, 403)
