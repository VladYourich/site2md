# site2md

Микросервис для преобразования веб-сайтов в чистый структурированный Markdown, оптимизированный для RAG/LLM-систем.

Двойной интерфейс: **REST API** (для программных клиентов) и **MCP Server** (для AI-агентов).

## Возможности

- Полный обход сайта с ограничением глубины и количества страниц
- Селективный JS-рендеринг через Playwright для SPA/JS-heavy страниц
- 6-стадийный пайплайн очистки контента: PreClean → Extract → PostProcess → Dedup → Convert → Assemble
- Удаление рекламы, навигации, cookie-уведомлений, скрытых элементов
- Cross-page дедупликация boilerplate (SimHash)
- Выходной Markdown с оглавлением, метаданными и чанк-маркерами (`\n><\n`)
- MCP Server — нативный доступ для AI-агентов (Claude, GPT)
- SSRF protection, resource limits, RFC 7807 ошибки
- SSE-прогресс, Prometheus метрики, JSON-логирование
- Docker Compose для разработки и деплоя

## Быстрый старт

### Docker Compose (рекомендуется)

```bash
git clone https://github.com/VladYourich/site2md.git
cd site2md
cp .env.example .env
docker compose up -d
```

Сервис будет доступен по адресу `http://localhost:8088`.

### Ручной запуск (разработка)

```bash
git clone https://github.com/VladYourich/site2md.git
cd site2md
python -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
cp .env.example .env
```

Запуск API:
```bash
uvicorn site2md.main:app --host 0.0.0.0 --port 8088 --workers 2
```

Запуск Worker (в отдельном терминале, требуется Redis):
```bash
arq site2md.worker.settings.WorkerSettings
```

Запуск MCP Server:
```bash
python -m site2md.mcp_server
```

### Запуск тестов

```bash
pytest
```

## API Endpoints

| Метод | Путь | Описание |
|-------|------|----------|
| POST | /api/v1/crawl | Создать задачу обхода |
| GET | /api/v1/crawl/{id}/status | Статус задачи |
| GET | /api/v1/crawl/{id}/result | Скачать done.md |
| DELETE | /api/v1/crawl/{id} | Отменить задачу |
| GET | /api/v1/crawl/{id}/events | SSE-прогресс |
| GET | /health | Liveness probe |
| GET | /ready | Readiness probe |
| GET | /metrics | Prometheus метрики |
| GET | /docs | Swagger UI |

## Пример использования

### REST API

```bash
# Создать задачу
curl -X POST http://localhost:8088/api/v1/crawl \
  -H "Content-Type: application/json" \
  -d '{"url": "https://example.com", "max_depth": 2}'

# Ответ: {"job_id": "...", "status": "pending", ...}

# Проверить статус
curl http://localhost:8088/api/v1/crawl/{job_id}/status

# Скачать результат
curl http://localhost:8088/api/v1/crawl/{job_id}/result > done.md
```

### MCP Server (AI-агенты)

Подключите в настройках MCP:

```json
{
  "mcpServers": {
    "site2md": {
      "command": "python",
      "args": ["-m", "site2md.mcp_server"]
    }
  }
}
```

Доступные tools:
- `scrape_website` — создать задачу обхода
- `get_scrape_status` — проверить статус
- `get_scrape_result` — получить Markdown

## Конфигурация

Переменные окружения (`.env`):

| Переменная | По умолчанию | Описание |
|-----------|-------------|----------|
| REDIS_URL | redis://localhost:6379/0 | URL Redis |
| MAX_PAGES | 200 | Максимум страниц |
| MAX_DEPTH | 5 | Максимальная глубина |
| JOB_TIMEOUT | 600 | Таймаут задачи (сек) |
| PLAYWRIGHT_MAX_CONTEXTS | 4 | Контекстов Playwright |
| RESULT_TTL_HOURS | 24 | Время жизни результата |
| LOG_LEVEL | INFO | Уровень логирования |

## Архитектура

```
site2md/
├── core/          # Логирование, Redis, health, метрики, безопасность
├── domain/        # Доменные модели, порты
├── models/        # Pydantic-схемы
├── api/           # REST API роуты
├── services/      # CrawlService, StorageService
├── pipeline/      # 6-стадийный пайплайн обработки контента
│   └── stages/    # PreClean, Extract, PostProcess, Dedup, Convert, Assemble
├── storage/       # Файловая система, TTL cleanup
├── worker/        # ARQ worker, задачи
├── mcp_server.py  # MCP Server для AI-агентов
├── main.py        # FastAPI приложение
└── config.py      # Pydantic Settings
```

## Лицензия

MIT
