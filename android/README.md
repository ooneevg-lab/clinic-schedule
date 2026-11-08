# Android-обертка расписания (WebView + FCM)

Тонкое приложение: показывает Django-сайт, принимает пуши, открывает
целевую страницу по нажатию. Логики расписания здесь нет.

## Сборка

1. Открыть папку `android/` в Android Studio.
   Важно для Windows: путь к проекту должен содержать только латиницу.
   Если репозиторий лежит в папке с кириллицей (как `актуально/...`),
   скопируй `android/` отдельно, например в `C:\schedule-android\`,
   и открывай его. Иначе AGP упадет с `path contains non-ASCII characters`.
2. Проверить версию Gradle: нужна **8.7** (зафиксирована в
   `gradle/wrapper/gradle-wrapper.properties` под AGP 8.5.2).
   Gradle 9.x не подходит — ломается трансформ `core-proto`.
   В Studio: Settings → Build Tools → Gradle → Use Gradle from:
   `gradle-wrapper.properties`, Gradle JDK — встроенный JBR 17,
   не системный Java 11.
   Если до этого синк падал на Gradle 9.3.0 — удалить
   `C:\Users\<имя>\.gradle\caches\9.3.0\` и нажать Sync Now заново.
Если сборка падает с `Unsupported class file major version 69` — Gradle запущен
   на слишком новом Java (69 = Java 25, а Gradle 8.7 понимает максимум Java 22).
   Лечится так: Settings → Build Tools → Gradle → Gradle JDK → выбрать
   встроенный JBR 17 от самой Studio (не системный Java). Потом остановить
   демонов и нажать Sync Now заново.
3. Если скачивание Gradle 8.7 рвется с `SocketTimeoutException: Read timed out`:
   - сначала просто нажать Sync Now еще 1–2 раза (обрыв бывает разовый);
     таймаут сети уже поднят до 120 секунд в `gradle-wrapper.properties`;
   - если рвется стабильно — скачать `gradle-8.7-bin.zip` вручную через браузер
     (браузер докачивает с resume, в отличие от wrapper) со страницы
     `https://gradle.org/releases/` и в Studio выбрать
     Settings → Build Tools → Gradle → Use Gradle from: **Specified location**,
     указав распакованную папку. Либо распаковать и положить путь в переменную
     окружения, wrapper больше ничего качать не будет;
   - проверить, что антивирус/файрвол не режет долгие HTTPS-скачивания
     и что нет корпоративного прокси (если прокси есть — прописать его
     в `gradle.properties` через `systemProp.http(s).proxyHost/Port`).
2. Положить свой `app/google-services.json` из Firebase-консоли
   (в репозиторий не коммитить).
3. Поменять `BASE_URL` в `MainActivity`:
   - сейчас тест: `http://203.0.113.77:8001/`
   - позже прод: `https://ваш-домен/`
4. Собрать и поставить на 2 телефона для проверки общего кейса.

## Мост WebView

Страница просит у приложения адрес установки через
`AndroidBridge.getPushRegistration()`. Приложение отдает строку,
сеть дальше идет со страницы (с кукой сессии), поэтому Django
берет владельца из `request.user`.

## Пуши

`PushService` показывает уведомление и кладет в него целевой URL
из data (`url`). По нажатию `MainActivity` открывает этот URL
в том же WebView. Сам пуш медицинских данных не содержит.

## Разрешения

Android 13+: запросить `POST_NOTIFICATIONS`, иначе шторка молчит.
