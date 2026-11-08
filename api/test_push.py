"""Привязка адреса к врачу по сессии: только свой, перепривязка, выход (T21)."""

from django.contrib.auth.models import User
from django.test import TestCase
from rest_framework.test import APIClient

from accounts.models import PushDevice


class PushRegisterTests(TestCase):
    def setUp(self):
        self.ivanov = User.objects.create_user("ivanov", password="pw")
        self.petrov = User.objects.create_user("petrov", password="pw")

    def test_anonymous_rejected(self):
        api = APIClient()
        r = api.post("/api/push/register/", {"registration": "ABC"}, format="json")
        self.assertIn(r.status_code, (401, 403))

    def test_register_binds_to_session_user(self):
        api = APIClient()
        api.force_authenticate(user=self.ivanov)
        r = api.post("/api/push/register/", {"registration": "ABC123"}, format="json")
        self.assertEqual(r.status_code, 200)
        d = PushDevice.objects.get(registration="ABC123")
        self.assertEqual(d.user, self.ivanov)
        self.assertTrue(d.active)

    def test_no_user_id_from_client(self):
        # Клиент не может подсунуть чужого владельца: владелец только из сессии.
        api = APIClient()
        api.force_authenticate(user=self.petrov)
        r = api.post(
            "/api/push/register/",
            {"registration": "ABC123", "user_id": 9999, "username": "ivanov"},
            format="json",
        )
        self.assertEqual(r.status_code, 200)
        d = PushDevice.objects.get(registration="ABC123")
        self.assertEqual(d.user, self.petrov)

    def test_relogin_rebinds_shared_phone(self):
        PushDevice.objects.create(user=self.ivanov, registration="SHARED")
        api = APIClient()
        api.force_authenticate(user=self.petrov)
        r = api.post("/api/push/register/", {"registration": "SHARED"}, format="json")
        self.assertEqual(r.status_code, 200)
        d = PushDevice.objects.get(registration="SHARED")
        self.assertEqual(d.user, self.petrov)
        self.assertFalse(
            PushDevice.objects.filter(user=self.ivanov, active=True).exists()
        )

    def test_unregister_only_own(self):
        PushDevice.objects.create(user=self.ivanov, registration="ABC123")
        PushDevice.objects.create(user=self.petrov, registration="OTHER")
        api = APIClient()
        api.force_authenticate(user=self.ivanov)
        r = api.post("/api/push/unregister/", {"registration": "ABC123"}, format="json")
        self.assertEqual(r.status_code, 200)
        self.assertFalse(PushDevice.objects.get(registration="ABC123").active)
        # Чужую запись не погасили.
        self.assertTrue(PushDevice.objects.get(registration="OTHER").active)

    def test_empty_registration_rejected(self):
        api = APIClient()
        api.force_authenticate(user=self.ivanov)
        r = api.post("/api/push/register/", {"registration": "  "}, format="json")
        self.assertEqual(r.status_code, 400)
        self.assertFalse(PushDevice.objects.exists())
