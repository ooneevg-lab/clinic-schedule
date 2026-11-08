"""Проверка «Моё» для тестовых врачей. Запуск из корня проекта:
set DJANGO_SETTINGS_MODULE=config.settings && venv/python -c "..." — см. ниже.
Используется вручную и в smoke-проверках.
"""

import datetime

import django
import os

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")
django.setup()

from django.utils import timezone  # noqa: E402
from rest_framework.test import APIClient  # noqa: E402

work_date = (timezone.localdate() + datetime.timedelta(days=1)).isoformat()
print("date", work_date)
ok = True
for username in ["test_doc1", "test_doc2", "test_doc3"]:
    client = APIClient()
    login = client.post(
        "/api/auth/login/",
        {"username": username, "password": "test1234", "client": "app"},
    )
    assert login.status_code == 200, (username, login.status_code, login.data)
    client.credentials(HTTP_AUTHORIZATION=f"Token {login.data['token']}")
    my = client.get(f"/api/schedule/my/?date={work_date}&branch_id=1")
    print(username, my.status_code, my.data.get("has_column"),
          my.data.get("my_columns"), my.data.get("count"))
    if not (my.status_code == 200 and my.data.get("has_column") and my.data.get("count") > 0):
        ok = False
print("MY-SCHEDULE-OK" if ok else "MY-SCHEDULE-FAIL")
