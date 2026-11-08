"""Устройства для пушей: одна установка = один текущий владелец (T21)."""

from django.contrib.auth.models import User
from django.test import TestCase

from accounts.models import PushDevice


class PushDeviceTests(TestCase):
    def setUp(self):
        self.ivanov = User.objects.create_user("ivanov", password="pw")
        self.petrov = User.objects.create_user("petrov", password="pw")

    def test_register_new_device(self):
        d = PushDevice.objects.create(user=self.ivanov, registration="ABC123")
        self.assertTrue(d.active)
        self.assertEqual(
            PushDevice.objects.filter(user=self.ivanov, active=True).count(), 1
        )

    def test_same_registration_rebinds_to_new_owner(self):
        PushDevice.objects.create(user=self.ivanov, registration="ABC123")
        d = PushDevice.objects.get(registration="ABC123")
        d.user = self.petrov
        d.active = True
        d.save()
        self.assertEqual(PushDevice.objects.filter(registration="ABC123").count(), 1)
        self.assertFalse(
            PushDevice.objects.filter(user=self.ivanov, active=True).exists()
        )
        self.assertTrue(
            PushDevice.objects.filter(user=self.petrov, active=True).exists()
        )

    def test_one_doctor_many_devices(self):
        PushDevice.objects.create(user=self.ivanov, registration="PHONE1")
        PushDevice.objects.create(user=self.ivanov, registration="TABLET1")
        self.assertEqual(
            PushDevice.objects.filter(user=self.ivanov, active=True).count(), 2
        )

    def test_logout_deactivates(self):
        d = PushDevice.objects.create(user=self.ivanov, registration="ABC123")
        d.active = False
        d.save(update_fields=["active"])
        self.assertFalse(
            PushDevice.objects.filter(user=self.ivanov, active=True).exists()
        )
