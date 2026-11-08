"""Нагрузка: 100 врачей, сотни записей — число запросов и замер (T18-C).

Время только печатается (информационно, без порога): на слабых машинах
жёсткий порог flaky. Число запросов — строгая граница против N+1.
"""

import datetime
import time

from django.contrib.auth.models import User
from django.db import connection
from django.test import TestCase
from django.test.utils import CaptureQueriesContext
from django.utils import timezone
from rest_framework.test import APIClient

from accounts.models import DoctorProfile
from schedule.models import Branch, ScheduleVersion
from schedule.services import _create_version

DOCTORS = 20
PER_DOCTOR = 100


class Load100Tests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.b1 = Branch.objects.create(code="F1", name="Филиал 1")
        for n in range(100):
            u = User.objects.create_user(f"doc{n:03d}", password="pw")
            DoctorProfile.objects.create(
                user=u, branch=cls.b1, schedule_name="Петров Петр Петрович")
        doc0 = User.objects.get(username="doc000")
        columns = [(i, f"Врач Тест Тестович {i}") for i in range(DOCTORS)]
        rows = []
        for i in range(DOCTORS):
            for j in range(PER_DOCTOR):
                rows.append((i, columns[i][1], {
                    "appointment_time": datetime.time(9 + (j % 9), j % 60),
                    "full_name": "Петров Петр Петрович",
                    "age": None, "service_name": "Осмотр"}))
        cls.day = timezone.localdate() + datetime.timedelta(days=2)
        version, _, _ = _create_version(
            branch=cls.b1, work_date=cls.day, columns=columns, rows=rows,
            source_name="load", uploaded_by=None)
        cls.version = version
        cls.doc0 = doc0

    def test_schedule_page_bounded_queries(self):
        self.client.login(username="doc000", password="pw")
        url = f"/schedule/?date={self.day.isoformat()}&branch_id={self.b1.id}"
        with CaptureQueriesContext(connection) as ctx:
            t0 = time.perf_counter()
            r = self.client.get(url)
            dt = time.perf_counter() - t0
        print(f"\n[load100] schedule_page: {dt:.2f}s, queries={len(ctx)}, "
              f"entries={self.version.entries_count}")
        self.assertLessEqual(len(ctx), 25)
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.context["full_count"], DOCTORS * PER_DOCTOR)

    def test_api_bounded_queries(self):
        api = APIClient()
        api.force_authenticate(user=self.doc0)
        url = f"/api/schedule/full/?date={self.day.isoformat()}&branch_id={self.b1.id}"
        with CaptureQueriesContext(connection) as ctx:
            t0 = time.perf_counter()
            r = api.get(url)
            dt = time.perf_counter() - t0
        print(f"\n[load100] api full: {dt:.2f}s, queries={len(ctx)}, count={r.data['count']}")
        self.assertLessEqual(len(ctx), 10)
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.data["count"], DOCTORS * PER_DOCTOR)
