# Развёртывание на другом компьютере

Ниже описан самый практичный сценарий переноса проекта на другой компьютер вместе с данными из базы.

## Что переносим

Нужно перенести:

- исходный код проекта
- файл `backend/.env`
- дамп базы данных PostgreSQL

Не рекомендуется переносить:

- папку `backend/.venv`
- docker volume `pgdata` как есть

Проще и надёжнее заново установить зависимости по `requirements.txt` и восстановить БД из дампа.

## Что должно быть на новом компьютере

Установить:

- Python `3.13`
- Docker Desktop
- Git

## Шаг 1. Скопировать проект

Скопировать папку проекта, например в:

```text
C:\market_risk_project
```

## Шаг 2. Поднять PostgreSQL в Docker

В корне проекта:

```powershell
cd C:\market_risk_project
docker compose up -d
```

Проверить, что контейнер поднялся:

```powershell
docker compose ps
```

## Шаг 3. Создать виртуальное окружение и установить зависимости

```powershell
cd C:\market_risk_project\backend
py -3.13 -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

## Шаг 4. Подготовить `.env`

Если файл `backend/.env` уже перенесён, ничего делать не нужно.

Если нет, создать его на основе:

```text
backend/.env.example
```

Текущие стандартные параметры проекта:

```env
DB_NAME=market_risk
DB_USER=market_risk
DB_PASSWORD=market_risk
DB_HOST=localhost
DB_PORT=5433
```

## Шаг 5. Применить миграции

```powershell
cd C:\market_risk_project\backend
.\.venv\Scripts\Activate.ps1
python manage.py migrate
```

## Шаг 6. Восстановить базу из дампа

Если у тебя уже есть дамп, восстановить его можно так:

```powershell
cd C:\market_risk_project
.\scripts\restore_db.ps1 -DumpPath C:\market_risk_project\backups\market_risk.dump
```

Если дампа ещё нет, сначала сделай его на старом компьютере:

```powershell
cd C:\market_risk_project
.\scripts\backup_db.ps1
```

По умолчанию дамп будет создан в:

```text
C:\market_risk_project\backups\market_risk.dump
```

## Шаг 7. Запустить Django

```powershell
cd C:\market_risk_project\backend
.\.venv\Scripts\Activate.ps1
python manage.py runserver
```

Сайт будет доступен по адресу:

```text
http://127.0.0.1:8000/
```

## Шаг 8. Проверка после переноса

Проверить:

- открывается главная страница
- работает вход в систему
- видны портфели и инструменты
- открываются результаты моделирования
- на месте сделки, сценарии и метрики

## Рекомендуемая последовательность переноса

1. На старом компьютере сделать дамп БД
2. Скопировать проект
3. На новом компьютере поднять Docker
4. Создать venv и установить зависимости
5. Применить миграции
6. Восстановить дамп
7. Запустить сервер

## Почему лучше переносить именно дамп, а не volume

Дамп БД:

- переносимее
- стабильнее
- проще восстановить
- не привязан к внутреннему состоянию Docker volume

Это самый безопасный вариант для дипломного проекта.
