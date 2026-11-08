"""Статика без nginx: WhiteNoise отдаёт /static/ при DEBUG=False (T20)."""

from django.test import TestCase
from django.test.utils import override_settings


class StaticServingTests(TestCase):
    @override_settings(DEBUG=False)
    def test_css_served(self):
        r = self.client.get("/static/css/clinic.css")
        self.assertEqual(r.status_code, 200)
        self.assertIn("text/css", r["Content-Type"])

    @override_settings(DEBUG=False)
    def test_missing_static_404(self):
        self.assertEqual(self.client.get("/static/nope.css").status_code, 404)
