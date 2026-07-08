# ASSET-MANAGEMENT-PRODUCTION-001 Report

## Scope

Доведение модуля активов до production-ready инвентаризации оборудования:

- расширенная карточка актива (локация, ответственные, финансовые/жизненные поля)
- lifecycle-операции (assign/move/verify/dispose/restore)
- история изменений по активу и глобальная история
- сохранение Excel import workflow (upload -> preview -> commit)
- сохранение pagination envelope и совместимости с tickets/admin/rbac

Ограничения соблюдены:

- БД не пересоздавалась
- `docker compose down -v` не использовался
- `.env.production` не коммитился
- секреты не печатались

## Backend Changes

### Models

- `backend/app/models/asset.py`
  - добавлены поля inventory-учета: `building`, `floor`, `room`, `location_label`, `responsible_*`, `mol_*`, `initial_cost`, `residual_cost`, `writeoff_*`, `assigned_at`, `moved_at`, `disposed_at`, `last_inventory_at`, `last_verified_at`, `notes`
  - добавлена связь `histories`
- `backend/app/models/asset_history.py`
  - новая модель `AssetHistory` (`action`, `old_value`, `new_value`, `comment`, `created_at`, `actor_id`)
- `backend/app/models/__init__.py`
  - регистрация `AssetHistory`

### Migration

- `backend/migrations/versions/20261109_0003_asset_inventory_fields.py`
  - production-safe добавление новых колонок
  - создание таблицы `asset_history`
  - создание индексов для фильтрации/истории

### API

- `backend/app/api/v1/routes/assets.py`
  - расширен `GET /assets` фильтрами для реальной инвентаризации
  - сохранен pagination envelope: `{ items, total, page, page_size }`
  - `GET /assets/{id}` теперь возвращает:
    - `linked_tickets_summary`
    - `latest_history`
  - добавлены lifecycle endpoints:
    - `PATCH /assets/{id}`
    - `POST /assets/{id}/assign`
    - `POST /assets/{id}/move`
    - `POST /assets/{id}/verify`
    - `POST /assets/{id}/dispose`
    - `POST /assets/{id}/restore`
  - добавлены history endpoints:
    - `GET /assets/{id}/history`
    - `GET /assets/history`
  - import endpoints сохранены (`/import/upload`, `/import/preview`, `/import/{batch_id}/commit`, batches/rows)
  - фикс сериализации history payload:
    - рекурсивная нормализация `datetime`/`Decimal` в JSON-safe формат перед записью в `asset_history`

### RBAC / Seed

- `backend/app/services/seed.py`
  - добавлены права: `assets.move`, `assets.verify`, `assets.dispose`, `assets.restore`, `assets.history.read`
  - включение этих прав в роли manager/admin
  - добавлено `assets.verify` для `it_agent` (чтобы агент мог инвентаризировать)

### Import Compatibility

- `backend/app/services/asset_import.py`
  - runtime schema guard синхронизирован с новыми полями и `asset_history`
  - preview/commit workflow сохранен

## Frontend Changes

### API Client

- `frontend/src/api/client.ts`
  - расширены типы `Asset`/`AssetDetail`
  - добавлены типы `AssetHistory`, `AssetHistoryFeedItem`
  - добавлены методы:
    - `fetchAssetById`
    - `updateAsset`
    - `assignAsset`
    - `moveAsset`
    - `verifyAsset`
    - `disposeAsset`
    - `restoreAsset`
    - `fetchAssetHistory`
    - `fetchAssetHistoryFeed`
  - расширена сериализация query в `fetchAssetsPage`

### Assets UI

- `frontend/src/pages/AssetsPage.tsx`
  - реализованы вкладки:
    - Реестр активов
    - Импорт Excel
    - Инвентаризация
    - Кабинеты
    - Ответственные
    - Списание
    - История
  - registry: расширенные фильтры, таблица, pagination
  - detail modal tabs: Обзор / Учёт / Локация / Ответственные / Заявки / История
  - action-модалки: Переместить / Закрепить / Проверить / Списать / Восстановить
  - global history feed с фильтрами (action/actor/asset/date)
  - import flow сохранен (upload/preview/commit)

## Test Coverage

- `backend/tests/test_assets_inventory.py` добавлен:
  - pagination envelope
  - фильтры room/responsible/missing_location
  - manager update / requester forbidden
  - agent verify
  - assign/move/dispose/restore + history + audit
  - linked tickets summary в detail
  - проверка наличия migration `0003`

## Validation

### Backend

Команда:

- `/home/sbs/sbs-ai-itsm-foundation-001/.venv/bin/python -m pytest -q`

Результат:

- `127 passed, 2 warnings`

Что исправлялось по падениям:

- добавлено право `assets.verify` для агента
- исправлена JSON-сериализация history payload с `datetime`

### Frontend

Команды:

- `cd frontend && npx tsc -b --pretty false`
- `cd frontend && npm run build`

Результат:

- TypeScript: PASS
- Build: PASS

### Docker Compose

Команда:

- `docker compose config`

Результат:

- PASS

### Runtime Smoke-check

Перед проверкой UI выполнено:

- `docker compose up -d --build backend frontend`

Проверено на `http://localhost:5173/assets`:

- страница грузится без white screen
- видны все 7 вкладок
- переключение вкладок работает (`Инвентаризация`, `Кабинеты`, `Ответственные`, `Списание`, `История`)
- registry таблица и pagination работают
- detail modal открывается, табы карточки активны
- action modal `Переместить` открывается
- import workflow вкладка доступна

## Non-regression Notes

- Excel import workflow не сломан
- Pagination envelope не сломан
- Tickets workflow не сломан (проверено полным `pytest`)
- Admin Console не сломан (проверено косвенно полным `pytest` и UI маршрутизацией)
- RBAC не отключался

## Known Limitations

- Валидация выполнялась на demo-данных; для production rollout нужен отдельный прогон Alembic на целевой БД и post-deploy smoke-check на реальных ролях/тенантах.
