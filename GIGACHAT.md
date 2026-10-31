# Подключение GigaChat API к проекту

Инструкция для Python-проекта и Windows PowerShell. Сверена с официальной документацией 31 октября 2026 года.

Примеры используют REST API через `requests`. В проекте уже есть `req.txt` с зависимостями для YOLO; для запросов к GigaChat GPU и CUDA не требуются.

## 1. Получить ключ авторизации

1. [Зарегистрируйтесь в Studio и создайте проект GigaChat API](https://developers.sber.ru/docs/ru/gigachat/quickstart/ind-create-project).
2. В проекте откройте **Настройки API → Получить ключ**. Это действие доступно владельцу или администратору проекта.
3. Сохраните **Authorization Key**, **Client ID** и **Client Secret**. Ключ и секрет показываются один раз.

Authorization Key уже содержит закодированную в Base64 пару `Client ID:Client Secret`. Готовый ключ повторно кодировать не нужно. В примерах ниже используйте его значение без префикса `Basic`.

Проверьте доступность токенов выбранной модели в кабинете. Для новых клиентов с 1 сентября 2026 года изменились условия оплаты: подробности приведены в [быстром старте](https://developers.sber.ru/docs/ru/gigachat/individuals-quickstart). Эта инструкция описывает прямой GigaChat API с ключом из Studio; для подключения через cloud.ru используйте документацию этой платформы.

Источник: [получение ключа и начало работы с API](https://developers.sber.ru/docs/ru/gigachat/quickstart/ind-using-api).

## 2. Подготовить Python и сертификат

Выполните команды из корня проекта. Если уже используете виртуальное окружение, установите `requests` в него. Для отдельного окружения:

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install requests
```

При включении интеграции в общие зависимости добавьте `requests` отдельной строкой в `req.txt`.

Для проверки TLS нужен корневой сертификат НУЦ Минцифры. Скачайте PEM-сертификат по адресу из [официальной инструкции по сертификатам](https://developers.sber.ru/docs/ru/gigachat/certificates):

```powershell
New-Item -ItemType Directory -Force -Path .\certs | Out-Null
Invoke-WebRequest -Uri "https://gu-st.ru/content/lending/russian_trusted_root_ca_pem.crt" -OutFile .\certs\russian_trusted_root_ca_pem.crt
```

Примеры передают этот файл явно через `--cacert` или `verify`. Проверка TLS остается включенной; при ошибке сертификата проверьте файл и цепочку доверия по инструкции выше.

## 3. Задать параметры подключения

В той же сессии PowerShell выполните:

```powershell
$env:GIGACHAT_CREDENTIALS = Read-Host "Вставьте Authorization Key"
$env:GIGACHAT_SCOPE = "GIGACHAT_API_PERS"
$env:GIGACHAT_BASE_URL = "https://api.giga.chat/v1"
$env:GIGACHAT_CA_BUNDLE = (Resolve-Path .\certs\russian_trusted_root_ca_pem.crt).Path
$env:GIGACHAT_MODEL = "GigaChat"
```

Переменные действуют в текущей сессии и доступны запущенному из нее Python. В `GIGACHAT_MODEL` укажите идентификатор из списка моделей, полученного на шаге 5.

Выберите `scope`, соответствующий вашему ключу:

| Значение | Тип доступа |
| --- | --- |
| `GIGACHAT_API_PERS` | Физические лица |
| `GIGACHAT_API_B2B` | ИП и юридические лица, предоплаченные пакеты |
| `GIGACHAT_API_CORP` | ИП и юридические лица, оплата по факту использования |

С 17 июля 2026 года целевой адрес API — `https://api.giga.chat`. OAuth-запросы отправляются на отдельный адрес, указанный ниже. Источник: [авторизация и адреса API](https://developers.sber.ru/docs/ru/gigachat/api/reference/rest/gigachat-api).

## 4. Получить токен доступа вручную

В Windows используйте `curl.exe`, чтобы вызвать именно cURL. Символ обратного апострофа в конце строки продолжает команду PowerShell; после него не должно быть пробелов.

```powershell
$requestId = [guid]::NewGuid().ToString()
$tokenJson = curl.exe --fail --silent --show-error `
    --request POST "https://ngw.devices.sberbank.ru:9443/api/v2/oauth" `
    --cacert "$env:GIGACHAT_CA_BUNDLE" `
    --header "Content-Type: application/x-www-form-urlencoded" `
    --header "Accept: application/json" `
    --header "RqUID: $requestId" `
    --header "Authorization: Basic $env:GIGACHAT_CREDENTIALS" `
    --data-urlencode "scope=$env:GIGACHAT_SCOPE"

if ($LASTEXITCODE -ne 0) { throw "Не удалось получить токен доступа" }
$tokenData = ($tokenJson -join "`n") | ConvertFrom-Json
$env:GIGACHAT_ACCESS_TOKEN = $tokenData.access_token
```

Тело OAuth-запроса имеет формат `application/x-www-form-urlencoded`. Заголовок `RqUID` содержит новый UUID версии 4 для каждого запроса.

Ответ содержит `access_token` и `expires_at`. Токен действует **30 минут**. После истечения получите новый через тот же OAuth-запрос; отдельный `refresh_token` в этой схеме не используется. Не запрашивайте токен перед каждым сообщением в работающем приложении: сохраняйте его в памяти и обновляйте перед истечением срока.

Ключ авторизации передается как `Authorization: Basic ...` только при получении токена. Для запросов к моделям передается полученный токен как `Authorization: Bearer ...`.

Источник: [получение токена доступа](https://developers.sber.ru/docs/ru/gigachat/quickstart/ind-using-api#poluchenie-tokena-dostupa), [справка OAuth](https://developers.sber.ru/docs/ru/gigachat/api/reference/rest/post-token).

## 5. Проверить список моделей

```powershell
curl.exe --fail --silent --show-error `
    "$env:GIGACHAT_BASE_URL/models" `
    --cacert "$env:GIGACHAT_CA_BUNDLE" `
    --header "Accept: application/json" `
    --header "Authorization: Bearer $env:GIGACHAT_ACCESS_TOKEN"
```

В ответе найдите `data[].id` и используйте доступную вашему проекту модель в `GIGACHAT_MODEL`. Метод и пример ответа описаны в [разделе запросов к API](https://developers.sber.ru/docs/ru/gigachat/quickstart/ind-using-api#zaprosy-k-gigachat-api).

## 6. Выполнить первый запрос из Python

Сохраните следующий пример в `gigachat_example.py` в корне проекта. Он самостоятельно получает токен, поэтому ручные шаги 4–5 нужны только для проверки подключения. Перед запуском выполните настройку окружения из шагов 2–3.

```python
import os
import uuid

import requests


def main():
    api_url = os.environ["GIGACHAT_BASE_URL"].rstrip("/")

    with requests.Session() as session:
        session.verify = os.environ["GIGACHAT_CA_BUNDLE"]
        session.headers.update({
            "Accept": "application/json",
            "User-Agent": "sibcode26-gigachat-example/1.0",
        })

        token_response = session.post(
            "https://ngw.devices.sberbank.ru:9443/api/v2/oauth",
            headers={
                "Authorization": "Basic " + os.environ["GIGACHAT_CREDENTIALS"],
                "RqUID": str(uuid.uuid4()),
            },
            data={"scope": os.environ["GIGACHAT_SCOPE"]},
            timeout=(10, 30),
        )
        token_response.raise_for_status()
        access_token = token_response.json()["access_token"]

        chat_response = session.post(
            f"{api_url}/chat/completions",
            headers={"Authorization": f"Bearer {access_token}"},
            json={
                "model": os.environ["GIGACHAT_MODEL"],
                "messages": [
                    {
                        "role": "system",
                        "content": "Ты помощник проекта. Отвечай кратко на русском языке.",
                    },
                    {
                        "role": "user",
                        "content": "Объясни, какие задачи решает модель YOLO.",
                    },
                ],
                "stream": False,
            },
            timeout=(10, 120),
        )
        chat_response.raise_for_status()
        print(chat_response.json()["choices"][0]["message"]["content"])


if __name__ == "__main__":
    main()
```

Запуск в той же сессии PowerShell:

```powershell
.\.venv\Scripts\python.exe .\gigachat_example.py
```

Ожидаемый результат — текстовый ответ модели в консоли. `requests` кодирует `data` как форму для OAuth, а `json` — как JSON для генерации. `raise_for_status()` останавливает выполнение при HTTP-ошибке.

Формат сообщений и ответа: [начало работы с API](https://developers.sber.ru/docs/ru/gigachat/quickstart/ind-using-api), [метод генерации ответа](https://developers.sber.ru/docs/ru/gigachat/api/reference/rest/post-chat).

## 7. Использование в приложении

- Вызывайте API из Python-кода или серверной части приложения. Храните ключ и токен в переменных окружения или хранилище секретов; исключите их из Git и логов.
- Пример выше рассчитан на один запуск. Для длительной работы вынесите получение и обновление токена в общий клиент, который переиспользуется между запросами. Альтернатива — [официальный Python SDK `gigachat`](https://developers.sber.ru/docs/ru/gigachat/guides/using-sdks).
- Для продолжения диалога передавайте в `messages` предыдущие сообщения пользователя и ответы ассистента. Системное сообщение должно идти первым.
- Возможный сценарий для проекта: передавать текстовые результаты YOLO и просить модель составить пояснение. Для передачи самих изображений отдельно изучите [работу с файлами](https://developers.sber.ru/docs/ru/gigachat/guides/working-with-files).

## 8. Частые ошибки

| Ошибка | Что проверить |
| --- | --- |
| `CERTIFICATE_VERIFY_FAILED` | Путь к PEM-сертификату, его содержимое и цепочку доверия. |
| `400` при OAuth | Новый UUID v4 в `RqUID`, значение `scope` и отправку тела как формы. |
| `401` | На OAuth — ключ и соответствие `scope`; на остальных запросах — Bearer-токен и срок его действия. |
| `402` | Остаток токенов именно у выбранной модели в кабинете. |
| `403` на `api.giga.chat` | Наличие заголовка `User-Agent`; в Python-примере он задан явно. |
| `422` | Формат и порядок сообщений, поддерживаемые параметры и размер контекста. |
| `429` | Число одновременных запросов; уменьшите параллельность и повторите с задержкой. |

Подробности: [официальное описание ошибок](https://developers.sber.ru/docs/ru/gigachat/api/errors-description).
