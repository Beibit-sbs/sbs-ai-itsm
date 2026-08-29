# Software Asset Management — operational runbook

## Назначение

Раздел `/software-assets` управляет программными продуктами, правами на
использование и обнаруженными установками. Он не хранит plaintext license keys:
используется только безопасный номер закупки/лицензии и ссылка на договор.

## Права

| Permission | Назначение | Стандартные роли |
|---|---|---|
| `sam.read` | просмотр каталога, лицензий, установок и compliance | organization admin, IT manager, IT agent |
| `sam.catalog.manage` | продукты и политика запрещённого ПО | organization admin, IT manager |
| `sam.licenses.manage` | лицензии, договоры, сроки и стоимость | organization admin, IT manager |
| `sam.installations.manage` | установки и их authorization state | organization admin, IT manager |
| `sam.reconcile` | сверка лицензий и установок | organization admin, IT manager |

SaaS Root имеет все права, но обязан явно выбрать организацию. Requester к SAM
не допускается. Пользовательские роли настраиваются администратором явно и не
перезаписываются upgrade-backfill.

## Рабочий порядок

1. Откройте **Лицензии и ПО** в меню.
2. В **Каталоге ПО** создайте продукт: publisher, version и edition входят в
   уникальный tenant-scoped ключ.
3. Если ПО запрещено, включите политику и обязательно укажите причину.
4. В **Лицензиях** добавьте entitlement: тип, количество, supplier/contract,
   expiration, renewal, unit cost и currency.
5. В **Установках** выберите продукт и CMDB-актив. Источник должен отражать
   фактический канал (`INTUNE`, `SCCM`, `LANSWEEPER`, `IMPORT` или `MANUAL`).
6. Запустите **Сверку**. Она переводит истёкшие активные лицензии в `EXPIRED`,
   пересчитывает compliance и пишет событие `sam.reconciled` в audit trail.
7. Обработайте красные позиции и installation violations. Авторизация или
   снятие установки требуют отдельного действия и причины.

## Compliance rules

Приоритет состояний: `PROHIBITED`, `UNAUTHORIZED`, `EXPIRED`, `UNLICENSED`,
`OVER_DEPLOYED`, `UNDERUTILIZED`, `COMPLIANT`.

- `purchased_quantity` — сумма действующих entitlements;
- `detected_quantity` — активные installations;
- `assigned_quantity` — installations с назначенным пользователем;
- `shortfall_quantity = max(0, detected - purchased)`;
- cost at risk рассчитывается по среднему unit cost действующих лицензий в
  каждой валюте и не смешивает валюты.

## Инциденты и восстановление

- `409` при обновлении означает optimistic-lock conflict: обновите страницу и
  повторите действие на актуальной версии.
- `409` при создании продукта означает дубликат publisher/name/version/edition.
- `422` при установке означает, что product, asset или assigned user принадлежат
  другой организации либо отсутствуют.
- Запрещённый продукт никогда не регистрируется как `AUTHORIZED`: сервер
  автоматически переводит его в `UNAUTHORIZED`.
- Записи не удаляются API-функциями. Продукты и лицензии выводятся из
  эксплуатации статусом, установки — `REMOVED`; audit trail сохраняется.

## Release acceptance

Перед серверным выпуском выполнить:

```text
alembic current                         -> 20260814_0078 (head)
GET /api/v1/software-assets/dashboard  -> 200 для sam.read, 403 для requester
POST /api/v1/software-assets/reconcile -> audit event sam.reconciled
```

Дополнительно проверить реальный discovery source, уведомления о продлении и
bulk import preview/commit. До этого автоматический inventory feed имеет статус
`BLOCKED_EXTERNAL`, а не `SUCCESS`.
