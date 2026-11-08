"""Получатели пушей: только врачи из версии, только активные адреса (T21)."""

import datetime

from django.contrib.auth.models import User
from django.test import TestCase
from django.utils import timezone

from accounts.models import DoctorProfile, PushDevice
from schedule.models import Branch, ScheduleVersion
from schedule.push import build_message, recipients_for_version, target_url_for_version
from schedule.services import _create_version


def make_version(branch, day, doctors=("Врачева А.А.",)):
    columns = [(i, name) for i, name in enumerate(doctors)]
    rows = [
        (0, doctors[0], {"appointment_time": None, "full_name": "Петров Петр Петрович",
                         "age": None, "service_name": "Осмотр"})
    ]
    version, _, _ = _create_version(
        branch=branch, work_date=day, columns=columns, rows=rows,
        source_name="test", uploaded_by=None,
    )
    return version


class PushRecipientsTests(TestCase):
    def setUp(self):
        self.branch = Branch.objects.create(code="F1", name="Филиал 1")
        self.day = timezone.localdate() + datetime.timedelta(days=1)
        self.ivanov = User.objects.create_user("ivanov", password="pw")
        DoctorProfile.objects.create(
            user=self.ivanov, branch=self.branch, schedule_name="Врачева А.А.")
        self.petrov = User.objects.create_user("petrov", password="pw")
        DoctorProfile.objects.create(
            user=self.petrov, branch=self.branch, schedule_name="Вторая Б.Б.")
        PushDevice.objects.create(user=self.ivanov, registration="IVAN-PHONE")
        PushDevice.objects.create(user=self.ivanov, registration="IVAN-TABLET")
        PushDevice.objects.create(
            user=self.ivanov, registration="IVAN-OLD", active=False)
        PushDevice.objects.create(user=self.petrov, registration="PETR-PHONE")

    def test_only_doctors_from_version(self):
        version = make_version(self.branch, self.day, ("Врачева А.А.",))
        recipients = recipients_for_version(version)
        self.assertIn(self.ivanov.id, recipients)
        self.assertNotIn(self.petrov.id, recipients)
        self.assertCountEqual(
            recipients[self.ivanov.id], ["IVAN-PHONE", "IVAN-TABLET"])

    def test_shared_phone_goes_to_current_owner(self):
        # Общий телефон перепривязан к Петрову — Иванову туда слать нельзя.
        PushDevice.objects.filter(registration="IVAN-PHONE").update(user=self.petrov)
        version = make_version(self.branch, self.day, ("Врачева А.А.",))
        recipients = recipients_for_version(version)
        self.assertCountEqual(recipients[self.ivanov.id], ["IVAN-TABLET"])

    def test_message_has_no_medical_data(self):
        version = make_version(self.branch, self.day, ("Врачева А.А.",))
        msg = build_message(version)
        self.assertIn("Расписание", msg["title"])
        self.assertNotIn("Петров", msg["title"] + msg["body"])
        self.assertEqual(msg["data"]["url"], target_url_for_version(version))
        self.assertIn(str(self.branch.id), msg["data"]["url"])

    def test_send_disabled_is_noop(self):
        from schedule.push import send_schedule_push

        version = make_version(self.branch, self.day, ("Врачева А.А.",))
        # PUSH_ENABLED=0 по умолчанию в тестах — отправки нет, но получатели есть.
        result = send_schedule_push(version.id)
        self.assertEqual(result["status"], "ok")
        self.assertEqual(result["users"], 1)
        self.assertEqual(result["devices"], 2)
        self.assertEqual(result["sent"], 0)

    def test_upload_queues_without_blocking(self):
        # Загрузка через Web не должна падать, даже если брокера нет.
        from django.core.files.uploadedfile import SimpleUploadedFile
        from openpyxl import Workbook
        import io

        staff = User.objects.create_user("adm", password="pw", is_staff=True)
        self.client.login(username="adm", password="pw")
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
        r = self.client.post("/schedule/upload/", {
            "branch_ids": [str(self.branch.id)],
            "work_date": self.day.isoformat(),
            "file": SimpleUploadedFile("m.xlsx", buf.read()),
        })
        self.assertEqual(r.status_code, 302)
        self.assertTrue(
            ScheduleVersion.objects.filter(
                branch=self.branch, work_date=self.day, is_active=True).exists()
        )
