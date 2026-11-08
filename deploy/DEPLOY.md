# Деплой clinic_schedule на VPS Beget (тест по IP, рядом с clinic_queue)

Проект живёт отдельно: `/home/clinic/clinic_schedule`, свой venv, служба
`clinic-schedule` (gunicorn `:8001`), свой SQLite и `.env`. Очередь
(`:8000`, Postgres, Redis, nginx) не затрагивается. Проверка каждого шага —
сразу под командой.

## 0. Локальная подготовка (Windows PowerShell, корень проекта)

```powershell
.\scripts\build_deploy_archive.ps1
# через Bypass, если ругается политика:
powershell -ExecutionPolicy Bypass -File .\scripts\build_deploy_archive.ps1
Test-Path clinic_schedule_deploy.zip
```

В архив НЕ кладутся: `.env`, `db.sqlite3`, `venv/`, `static_root/`, кэши.
Перед сборкой: `manage.py check` чисто, `pytest -q` зелёный.

## 1. Подключение

```powershell
ssh root@203.0.113.77
```

```bash
free -h                # нужно ~200 МБ сверх очереди
python3 --version      # нужен 3.10+
systemctl status clinic-queue | head -3   # active (running) — было и осталось
ss -ltnp | grep 800    # слушает только :8000 — :8001 свободен
```

## 2. Заливка архива (WinSCP SFTP в /root/ либо scp)

```powershell
scp clinic_schedule_deploy.zip root@203.0.113.77:/root/
```

```bash
ls -lh /root/*.zip
cp /root/clinic_schedule_deploy.zip /tmp/clinic_schedule_deploy.zip && chmod 644 /tmp/clinic_schedule_deploy.zip
sudo -u clinic unzip -o /tmp/clinic_schedule_deploy.zip -d /home/clinic/clinic_schedule
rm -f /tmp/clinic_schedule_deploy.zip
ls /home/clinic/clinic_schedule   # manage.py, config/, deploy/ на месте
```

## 3. venv и зависимости

```bash
sudo -u clinic python3 -m venv /home/clinic/clinic_schedule/venv
sudo -u clinic /home/clinic/clinic_schedule/venv/bin/pip install -r /home/clinic/clinic_schedule/requirements.txt
sudo -u clinic /home/clinic/clinic_schedule/venv/bin/pip show gunicorn | grep -E "Name|Version"
sudo -u clinic /home/clinic/clinic_schedule/venv/bin/python -c "import django; print(django.get_version())"
```

## 4. `.env` (руками, секреты в архив не кладутся)

```bash
sudo -u clinic nano /home/clinic/clinic_schedule/.env
```

```
SECRET_KEY=<сгенерировать командой ниже>
DEBUG=0
ALLOWED_HOSTS=203.0.113.77,127.0.0.1
```

```bash
sudo -u clinic /home/clinic/clinic_schedule/venv/bin/python -c "from django.core.management.utils import get_random_secret_key; print(get_random_secret_key())"
```

Без своего `SECRET_KEY` при `DEBUG=0` старт упадёт (прод-guard, так задумано).

## 5. Django: check → migrate → collectstatic

```bash
cd /home/clinic/clinic_schedule
sudo -u clinic ./venv/bin/python manage.py check
sudo -u clinic ./venv/bin/python manage.py migrate --noinput
sudo -u clinic ./venv/bin/python manage.py collectstatic --noinput
```

Ожидаем: check чисто; миграции все, включая `accounts/0002`; статика
собрана в `static_root/` (статика раздаётся WhiteNoise, nginx не нужен).

## 6. Служба (без автозапуска — это тест)

```bash
cp /home/clinic/clinic_schedule/deploy/clinic-schedule.service /etc/systemd/system/
systemctl daemon-reload
systemctl start clinic-schedule && sleep 5
systemctl status clinic-schedule | head -5
```

Ожидаем `active (running)`, главный процесс gunicorn.

## 7. Проверки

```bash
curl -sI http://127.0.0.1:8001/login/ | head -3                                   # 200
curl -sI http://127.0.0.1:8001/static/css/clinic.css | head -5                    # 200 + gzip
systemctl status clinic-queue | head -3                                           # active, не задета
ss -ltnp | grep 800                                                               # :8000 daphne + :8001 gunicorn
```

## 8. Прямой доступ из браузера (тест, без домена)

```bash
ufw allow 8001/tcp
```

В `ExecStart` unit-файла `--bind 127.0.0.1:8001` → `--bind 0.0.0.0:8001`,
`systemctl daemon-reload && systemctl restart clinic-schedule`.
Chrome: `http://203.0.113.77:8001/login/`. Риски открытого HTTP
(перехват паролей, перебор) — держать окно теста коротким; в проде порт
закрыть и встать за nginx с HTTPS.

## 9. Данные и приёмка

```bash
cd /home/clinic/clinic_schedule && sudo -u clinic ./venv/bin/python manage.py createsuperuser
```

Пароль — только в менеджер паролей (в базе лишь хэш; сброс —
`changepassword`). В `/admin/`: филиалы → врач с карточкой (филиал
обязателен, иначе 403) → пробная заливка xlsx → модалка «опубликовано».
Глазами: каскад ②, шаги ①→④, история по месяцам, стили на месте.

## 10. Обновление уже стоящего (повторный деплой)

```bash
cp /root/clinic_schedule_deploy.zip /tmp/ && chmod 644 /tmp/clinic_schedule_deploy.zip
sudo -u clinic unzip -o /tmp/clinic_schedule_deploy.zip -d /home/clinic/clinic_schedule
rm -f /tmp/clinic_schedule_deploy.zip
cd /home/clinic/clinic_schedule
sudo -u clinic ./venv/bin/pip install -r requirements.txt
sudo -u clinic ./venv/bin/python manage.py migrate --noinput
sudo -u clinic ./venv/bin/python manage.py collectstatic --noinput
systemctl restart clinic-schedule && sleep 4
curl -sI http://127.0.0.1:8001/login/ | head -3
```

`.env` и `db.sqlite3` при этом не затираются (их нет в архиве).

## 10.5 Пуши: Firebase и свой Celery (очередь не трогаем)

```bash
# Ключ Firebase положить только на сервер, в архив он не входит:
sudo -u clinic nano /home/clinic/clinic_schedule/.firebase-service.json
sudo chmod 600 /home/clinic/clinic_schedule/.firebase-service.json
sudo -u clinic nano /home/clinic/clinic_schedule/.env
```

В `.env` добавить:

```
PUSH_ENABLED=1
FIREBASE_CREDENTIALS_FILE=/home/clinic/clinic_schedule/.firebase-service.json
FIREBASE_PROJECT_ID=your-firebase-project
CELERY_BROKER_URL=redis://127.0.0.1:6379/10
CELERY_RESULT_BACKEND=redis://127.0.0.1:6379/10
```

Свой Redis только для расписания должен слушать локально. Общий Redis
очереди не используем — отдельная база/инстанс.

```bash
cd /home/clinic/clinic_schedule
sudo -u clinic ./venv/bin/pip install -r requirements.txt
sudo -u clinic ./venv/bin/python manage.py migrate --noinput
cp /home/clinic/clinic_schedule/deploy/clinic-schedule-celery.service /etc/systemd/system/
systemctl daemon-reload
systemctl start clinic-schedule-celery && sleep 3
systemctl status clinic-schedule-celery | head -5
systemctl restart clinic-schedule && sleep 4
curl -sI http://127.0.0.1:8001/login/ | head -3
```

Проверка пушей: врач входит через приложение на двух телефонах,
админ заливает расписание с этим врачом в файле — пуш приходит
на оба. Общий телефон проверяется выходом одного и входом другого:
пуш идет только текущему.

Пока работаем по http с IP. После переезда на домен+https поменять
только базовый адрес в приложении и настройки сайта, логика пушей
не меняется.

## 11. Откат

```bash
systemctl stop clinic-schedule   # + disable, если включали
rm -rf /home/clinic/clinic_schedule
rm -f /etc/systemd/system/clinic-schedule.service
ufw delete allow 8001/tcp   # если открывали
```

БД внутри каталога (SQLite) — следов ноль, очередь не задета.

## Замечания

- `unzip` хранит иркутское время файлов, сервер в UTC — расхождение меток
  ~5 часов норма.
- Выход из `status`/`journalctl` — клавиша `q`.
- Куки обеих систем на одном IP дефолтные (`sessionid`) — при прыжках между
  проектами возможен разлогин; на разных поддоменах пройдёт само.
