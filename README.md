# Clinic Schedule — расписание клиники с push-уведомлениями

Серверная часть управления расписанием врачей: администратор загружает Excel-график, система распознаёт его в структуру, раздаёт расписание по филиалам и рассылает push-уведомления в мобильное приложение врача (Cloud Firebase Messaging). Клиент на Android — «обёртка» над мобильным веб-интерфейсом + HTTP-пуши и «запасной» интерактив.

## Возможности

- **Загрузка Excel**: расписание разбирается из офисной таблицы (лист-загрузка, парсинг, проверка дублей и конфликтов, изоляция филиалов — `schedule/parsing.py`).
- **Преобразование в фоне**: Celery-воркеры (парсинг не висит в HTTP-запросе).
- **Push**: FCM через firebase-admin; секреты только на сервере (service account JSON вне репозитория и архива, путь через `.env`).
- **REST API с токен-авторизацией** (DRF Token), разграничение филиалов.
- **Django-админка** для операторов.
- **Тесты**: нагрузка `test_load100.py` (100 одновременных загрузок), каскадные проверки удаления (`test_have_cascade.py`), фаззи-тесты парсера (`test_fuzz.py`), изоляция филиалов, контракты API.

## Стек

Django + DRF, Celery + Redis, PostgreSQL/SQLite, firebase-admin (FCM), whitenoise; Android-клиент: Kotlin (WebView-обёртка + FCM-сервис PushService).

## Запуск (dev)

```bash
pip install -r requirements.txt
copy .env.example .env
python manage.py migrate
python manage.py runserver
```

Пуш можно отключить (`PUSH_ENABLED` из env, по умолчанию выключен).

## Android-клиент

Сборка описана в `android/README.md` (Gradle, `google-services.json` подаётся локально). Клиент кэширует авторизацию, получает FCM-события и лезет deep-link'ом в расписание.

## Деплой

`deploy/DEPLOY.md` (systemd-юниты `clinic-schedule.service` + `clinic-schedule-celery.service`, nginx, бэкапы); дизайн-доки в `docs/`.
