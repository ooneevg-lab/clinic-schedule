"""Генерация демо-расписания + тестовые врачи. Запуск: manage.py shell < scripts/seed_demo.py"""

from datetime import timedelta

from django.contrib.auth.models import User
from django.core.files.uploadedfile import SimpleUploadedFile
from django.utils import timezone
from openpyxl import Workbook

from accounts.models import DoctorProfile
from schedule.models import Branch
from schedule.services import upload_schedule

branch, _ = Branch.objects.get_or_create(code="F1", defaults={"name": "Филиал 1"})

DOCTORS = [
    ("test_doc1", "test1234", "Тестова А.А."),
    ("test_doc2", "test1234", "Петров Б.Б."),
    ("test_doc3", "test1234", "Сидорова В.В."),
]

for username, password, fio in DOCTORS:
    user, _ = User.objects.get_or_create(username=username)
    user.set_password(password)
    user.save()
    DoctorProfile.objects.update_or_create(
        user=user, defaults={"branch": branch, "schedule_name": fio}
    )
    print(f"врач {username}/{password} -> {fio}")

wb = Workbook()
ws = wb.active
ws.cell(row=1, column=1, value="Час")
ws.cell(row=1, column=2, value="Мин")
ws.cell(row=1, column=4, value="Тестова А.А.")
ws.cell(row=1, column=5, value="Петров Б.Б.")
ws.cell(row=1, column=6, value="Сидорова В.В.")

slots = [
    ("09", "00", "Иванов Иван Иванович\nКонсультация", "Кузнецов Кузьма Кузьмич\nОсмотр", None),
    ("09", "30", "Смирнова Анна Петровна\nПовторный приём", None, "Козлова Мария Ивановна\nКонсультация"),
    ("10", "00", None, "Новиков Николай Николаевич\nУЗИ", "Морозова Елена Сергеевна\nОсмотр"),
    ("10", "30", "Павлов Павел Павлович\nКонсультация", "Соколов Сергей Викторович\nПовторный приём", None),
    ("11", "00", "Фролова Ольга Дмитриевна\nОсмотр", None, "Волков Андрей Олегович\nКонсультация"),
]

for i, (hour, minute, c1, c2, c3) in enumerate(slots, start=2):
    ws.cell(row=i, column=1, value=hour)
    ws.cell(row=i, column=2, value=minute)
    if c1:
        ws.cell(row=i, column=4, value=c1)
    if c2:
        ws.cell(row=i, column=5, value=c2)
    if c3:
        ws.cell(row=i, column=6, value=c3)

path = "demo_schedule.xlsx"
wb.save(path)
print(f"файл {path} записан")

work_date = timezone.localdate() + timedelta(days=1)
with open(path, "rb") as fh:
    uploaded = SimpleUploadedFile("demo_schedule.xlsx", fh.read())
admin = User.objects.filter(is_superuser=True).first()
version, ncols, nrows = upload_schedule(
    branch=branch, work_date=work_date, uploaded_file=uploaded, uploaded_by=admin
)
print(f"залито на {work_date}: колонок {ncols}, записей {nrows}")
