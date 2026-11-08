"""Local design preview with fictitious data; never connects to the project DB.

Run with a Python environment containing Django:
    python scripts/design_preview.py
Open http://127.0.0.1:18765/ . POST requests are deliberately disabled.
"""
from datetime import date, datetime, time, timedelta, timezone
from html import escape
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from types import SimpleNamespace as Obj
from urllib.parse import parse_qs, urlsplit

from django.conf import settings

ROOT = Path(__file__).resolve().parents[1]
settings.configure(
    SECRET_KEY="local-fictional-preview",
    STATIC_URL="/static/",
    USE_TZ=True,
    TIME_ZONE="Asia/Irkutsk",
    INSTALLED_APPS=[],
    TEMPLATES=[{"BACKEND": "django.template.backends.django.DjangoTemplates",
                "DIRS": [ROOT / "templates"]}],
)
import django
django.setup()
from django.template.loader import render_to_string


def context(query):
    today = date(2026, 9, 19)
    try:
        selected = date.fromisoformat(query.get("date", [today.isoformat()])[0])
    except ValueError:
        selected = today
    branches = [Obj(id=1, code="ЦЕНТР", name="Центральный филиал"),
                Obj(id=2, code="СЕВЕР", name="Северный филиал")]
    branch = branches[1] if query.get("branch_id") == ["2"] else branches[0]
    columns = [Obj(id=1, name="Иванова Анна Сергеевна"), Obj(id=2, name="Смирнов Павел Андреевич"),
               Obj(id=3, name="Константинопольская Александра Константиновна")]
    patients = [
        ("Соколова Мария Андреевна", "34 года", "Первичная консультация"),
        ("Морозов Алексей Викторович", "42 года", "Повторный приём"),
        ("Александрова-Константинопольская Екатерина Александровна", "61 год", "Комплексное обследование и консультация по результатам исследований"),
        ("Волков Дмитрий Ильич", "", "Приём специалиста"),
        ("Орлова Елена Павловна", "28 лет", ""),
        ("Кузнецов Андрей Николаевич", "55 лет", "Повторная консультация"),
    ]
    entries = [Obj(full_name=name, age=age, service_name=service,
                   appointment_time=time(9 + i // 2, (i % 2) * 30))
               for i, (name, age, service) in enumerate(patients)]
    mode = query.get("state", ["filled"])[0]
    label = selected.strftime("%d.%m.%Y")
    if selected.month == 9:
        weekday = ["понедельник", "вторник", "среда", "четверг", "пятница", "суббота", "воскресенье"][selected.weekday()]
        label = f"{selected.day} сентября, {weekday}"
    version = Obj(uploaded_at=datetime(2026, 9, 18, 9, 42, tzinfo=timezone.utc))
    news = [] if "ack_news" in query else [
        dict(id=2, label="21 сентября, понедельник", work_date_iso="2026-09-21",
             branch_id=branch.id, branch_code=branch.code, uploaded_label="сегодня в 08:30")]
    return dict(
        today=today, today_iso=today.isoformat(), work_date=selected,
        work_date_iso=selected.isoformat(), work_date_label=label,
        yesterday=(selected-timedelta(days=1)).isoformat(),
        tomorrow=(selected+timedelta(days=1)).isoformat(),
        branch=branch, branches=branches, display_name="Иванова Анна Сергеевна",
        is_staff=True, has_version=mode != "unpublished", has_column=mode != "unmatched",
        my_entries=entries if mode == "filled" else [], my_count=len(entries) if mode == "filled" else 0,
        my_columns=[columns[0].name], full_count=len(entries)*2, grid_columns=columns,
        grid_rows=[dict(time=e.appointment_time, cells=[[e], [e], []]) for e in entries],
        doctor_cards=[dict(column=columns[0], entries=entries),
                      dict(column=columns[1], entries=entries), dict(column=columns[2], entries=[])],
        version=version, news=news, nearest_date=dict(iso="2026-09-21", label="21.09"),
        calendar_dates=[dict(iso=f"2026-09-{d:02}", is_new=d == 21) for d in [17, 18, 19, 21, 22, 24, 28]],
        default_date=selected.isoformat(), selected_branch_ids=[],
        hist_month="2026-09", hist_months=[dict(key="2026-09", title="Сентябрь 2026", count=3)],
        versions=[Obj(work_date=today-timedelta(days=i), branch_id=branch.id, branch=branch,
                      services_count=3, entries_count=12, is_active=i != 2) for i in range(3)],
        csrf_token="preview-only", form=Obj(errors=False), exception="",
    )


class Preview(BaseHTTPRequestHandler):
    def do_GET(self):
        url = urlsplit(self.path)
        query = parse_qs(url.query)
        if url.path == "/":
            width = query.get("width", ["390"])[0]
            width = int(width) if width in {"360", "390", "768", "1440"} else 390
            page = query.get("page", ["schedule"])[0]
            routes = {"schedule": "/schedule/", "upload": "/schedule/upload/",
                      "login": "/login/", "error": "/403/",
                      "empty": "/schedule/?state=empty", "unmatched": "/schedule/?state=unmatched",
                      "unpublished": "/schedule/?state=unpublished"}
            page = page if page in routes else "schedule"
            links = " · ".join(f'<a href="/?width={width}&page={p}">{escape(label)}</a>' for p, label in
                               [("schedule", "Расписание"), ("upload", "Загрузка"), ("login", "Вход"),
                                ("error", "Нет доступа"), ("empty", "Нет записей"),
                                ("unmatched", "Нет колонки"), ("unpublished", "Не опубликовано")])
            sizes = " · ".join(f'<a href="/?width={w}&page={page}">{w}px</a>' for w in [360, 390, 768, 1440])
            body = f"""<!doctype html><html lang="ru"><meta charset="utf-8"><title>Предпросмотр дизайна</title>
                <style>body{{margin:24px;background:#e6eae7;color:#203431;font:14px system-ui}}
                a{{color:#236b5e}}nav{{margin:14px 0}}iframe{{display:block;border:1px solid #c4d1ca;background:white;border-radius:16px}}
                h1{{font-size:20px}}#checks{{font-size:12px}}</style>
                <h1>Предпросмотр · все данные вымышлены</h1><nav>{links}</nav><nav>{sizes}</nav>
                <p id="checks">Проверка размеров…</p><iframe title="Макет" src="{routes[page]}" width="{width}" height="844"></iframe>
                <script>const frame=document.querySelector('iframe');frame.addEventListener('load',()=>{{
                const doc=frame.contentDocument, first=doc.querySelector('#mine .appointment');
                const top=first?Math.round(first.getBoundingClientRect().top):null;
                document.getElementById('checks').textContent='Ширина: '+frame.clientWidth+
                ' px · горизонтальное переполнение: '+(doc.documentElement.scrollWidth>frame.clientWidth?'есть':'нет')+
                (top===null?'':' · первая запись: '+top+' px от верха');}});</script></html>"""
            return self.reply(body.encode("utf-8"), "text/html; charset=utf-8")
        assets = {"/static/css/clinic.css": ("css/clinic.css", "text/css"),
                  "/static/js/schedule.js": ("js/schedule.js", "text/javascript"),
                  "/static/js/upload.js": ("js/upload.js", "text/javascript")}
        if url.path in assets:
            path, content_type = assets[url.path]
            return self.reply((ROOT / "static" / path).read_bytes(), content_type)
        pages = {"/schedule/": "schedule.html", "/schedule/upload/": "upload.html",
                 "/login/": "login.html", "/403/": "403.html"}
        if url.path not in pages:
            return self.send_error(404)
        self.reply(render_to_string(pages[url.path], context(query)).encode("utf-8"), "text/html; charset=utf-8")

    def do_POST(self):
        self.send_error(405, "Preview only. No changes are saved.")

    def reply(self, body, content_type):
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


if __name__ == "__main__":
    # On Windows, exclusive binding avoids sharing a port with another server.
    import socket
    class ExclusiveServer(ThreadingHTTPServer):
        allow_reuse_address = False

        def server_bind(self):
            if hasattr(socket, "SO_EXCLUSIVEADDRUSE"):
                self.socket.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
            super().server_bind()

    server = ExclusiveServer(("127.0.0.1", 18765), Preview)
    print("Fictitious-data preview: http://127.0.0.1:18765/", flush=True)
    server.serve_forever()
