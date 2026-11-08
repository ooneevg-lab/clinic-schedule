"""Токены и события входа/выхода по каналам site/app (T15)."""

from django.contrib.auth.models import User
from django.test import TestCase
from rest_framework.authtoken.models import Token
from rest_framework.test import APIClient

from accounts.models import DoctorProfile, LoginEvent
from schedule.models import Branch


class LogoutScopeTests(TestCase):
    def setUp(self):
        self.b1 = Branch.objects.create(code="F1", name="Филиал 1")
        self.b2 = Branch.objects.create(code="F2", name="Филиал 2")
        self.doc = User.objects.create_user("doc", password="pw")
        DoctorProfile.objects.create(
            user=self.doc, branch=self.b1, schedule_name="Врачева А.А.")

    def test_api_logout_kills_current_token(self):
        api = APIClient()
        r = api.post("/api/auth/login/", {"username": "doc", "password": "pw"})
        key = r.data["token"]
        api.credentials(HTTP_AUTHORIZATION=f"Token {key}")
        self.assertEqual(api.post("/api/auth/logout/").status_code, 200)
        self.assertFalse(Token.objects.filter(key=key).exists())
        api2 = APIClient()
        api2.credentials(HTTP_AUTHORIZATION=f"Token {key}")
        # DRF без валидного токена: IsAuthenticated → 403.
        self.assertEqual(api2.get("/api/schedule/my/").status_code, 403)

    def test_api_logout_closes_only_app_events(self):
        LoginEvent.objects.create(user=self.doc, via="site")
        LoginEvent.objects.create(user=self.doc, via="app")
        api = APIClient()
        api.force_authenticate(user=self.doc)
        api.post("/api/auth/logout/")
        site = LoginEvent.objects.filter(user=self.doc, via="site").first()
        app = LoginEvent.objects.filter(user=self.doc, via="app").first()
        self.assertIsNone(site.logout_at)
        self.assertIsNotNone(app.logout_at)

    def test_web_logout_closes_only_site_events(self):
        LoginEvent.objects.create(user=self.doc, via="site")
        LoginEvent.objects.create(user=self.doc, via="app")
        self.client.login(username="doc", password="pw")
        self.assertEqual(self.client.post("/logout/").status_code, 302)
        site = LoginEvent.objects.filter(user=self.doc, via="site").first()
        app = LoginEvent.objects.filter(user=self.doc, via="app").first()
        self.assertIsNotNone(site.logout_at)
        self.assertIsNone(app.logout_at)

    def test_api_foreign_branch_forbidden(self):
        api = APIClient()
        api.force_authenticate(user=self.doc)
        self.assertEqual(
            api.get(f"/api/schedule/full/?branch_id={self.b2.id}").status_code, 403)
        self.assertEqual(
            api.get(f"/api/schedule/my/?branch_id={self.b2.id}").status_code, 403)
        self.assertEqual(
            api.get(f"/api/columns/?branch_id={self.b2.id}").status_code,
            403)

    def test_api_own_branch_ok(self):
        api = APIClient()
        api.force_authenticate(user=self.doc)
        self.assertEqual(
            api.get(f"/api/schedule/full/?branch_id={self.b1.id}").status_code, 200)
