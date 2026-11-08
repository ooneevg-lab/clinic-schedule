"""Фоновые задачи расписания: рассылка пушей после загрузки."""

import logging
import threading

from celery import shared_task

logger = logging.getLogger(__name__)


@shared_task(
    name="schedule.send_schedule_push",
    bind=True,
    autoretry_for=(Exception,),
    retry_kwargs={"max_retries": 3, "countdown": 30},
    rate_limit="10/s",
)
def send_schedule_push_task(self, version_id):
    from schedule.push import send_schedule_push

    return send_schedule_push(version_id)


def queue_schedule_push(version_id):
    """Поставить рассылку в фон, не блокируя загрузку.

    При недоступном брокере — не роняем загрузку: пробуем eager,
    в крайнем случае уходим в daemon-поток. Вызывать внутри
    transaction.on_commit, чтобы слать только после сохранения версии.
    """
    from django.conf import settings as dj_settings

    if getattr(dj_settings, "CELERY_TASK_ALWAYS_EAGER", False):
        from schedule.push import send_schedule_push

        return send_schedule_push(version_id)
    try:
        return send_schedule_push_task.delay(version_id)
    except Exception as exc:  # брокер лег — загрузка все равно успешна
        logger.warning("Celery недоступен, шлю в потоке: %s", exc)

        def _run():
            try:
                from schedule.push import send_schedule_push

                send_schedule_push(version_id)
            except Exception:  # noqa: BLE001 — фон, только лог
                logger.exception("Фоновая рассылка упала")

        threading.Thread(target=_run, daemon=True).start()
        return None
