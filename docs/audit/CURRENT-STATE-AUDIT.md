# SBS AI ITSM — фактический аудит текущего состояния

Дата среза: 2026-08-14 11:43 +05:00  
Версия: 0.1.0  
Ветка/revision: `main` / `0b04ada23744349f565b44d60d52182da7f6da38`  
Контур: локальный Windows development/UAT

## 1. Решение

- **Локальный development/UAT: GO.** Основной runtime отвечает, 25 доступных
  менеджеру экранов проходят browser smoke без alert-ошибок и console errors.
- **Публичный production: NO-GO / BLOCKED_EXTERNAL.** Изолированный
  production-like контур PostgreSQL/Redis/worker/frontend/monitoring прошёл
  совместную live acceptance, но публичный domain/TLS, реальные внешние
  credentials, MFA enrollment и полный server cutover ещё не выполнены.
- Внешние OpenAI/Gemini, Microsoft Graph, Teams, Entra/SCIM, SMTP, monitoring
  receivers и discovery-коннекторы имеют статус `BLOCKED_EXTERNAL`, пока нет
  реальных credentials и подтверждения провайдера. Mock не считается доставкой.

## 2. Методика и границы

Проверены код, модели, миграции, OpenAPI, frontend routes, тесты, production
Compose, локальная база, живой API и browser UI. Руководство DOCX использовано
только как перечень заявленных функций, но не как доказательство реализации.

До любых миграций создан online snapshot работающей SQLite-базы, выполнено
логическое восстановление в отдельный файл и `PRAGMA integrity_check`.
Исходная база не изменялась прямым SQL и не очищалась.

## 3. Исходные данные и сохранность

| Показатель | Факт |
|---|---:|
| Таблицы | 205 |
| Tenants | 2 |
| Users | 11 |
| Tickets | 13 |
| Ticket comments / history | 13 / 29 |
| Service requests / requested items | 1 / 1 |
| Assets | 3 |
| Knowledge articles | 20 |
| Audit events | 64 |
| Changes / problems / major incidents / releases | 0 / 0 / 0 / 0 |

Backup SHA-256:
`5722f0477e8c1ee3165a70bf11bc6a01da2283109c02de74263058d373eeead8`.
Backup, source и restore-копия имеют одинаковое логическое состояние; integrity
равен `ok`. Детали находятся в
`backups/baseline/20260814_1048/manifest.json`.

## 4. Архитектурный срез

- Backend: FastAPI 0.139, SQLAlchemy 2, Alembic, Pydantic Settings.
- Frontend: React 19, TypeScript 6, Vite 8, React Router, TanStack Query.
- Production data plane: PostgreSQL 17, Redis 8, отдельный worker, outbox,
  retry/scheduled retry/dead-letter и replay.
- Runtime topology: backend, migrate, worker, frontend/reverse proxy,
  PostgreSQL, Redis, Prometheus, Alertmanager, Grafana.
- Production containers используют non-root compatible hardening: read-only
  filesystem, tmpfs, `no-new-privileges`, dropped capabilities, resource limits,
  healthchecks, internal data network и Docker secrets.
- Локальный launcher намеренно использует постоянную SQLite-базу, inline jobs,
  local websocket transport, demo mode и startup DDL. Production validator
  запрещает эти значения при `APP_ENV=production`.

## 5. API, маршруты и миграции

| Проверка | Результат |
|---|---|
| Backend endpoints | 746 |
| Protected endpoints | 739 |
| Governed public endpoints | 7 |
| OpenAPI paths | 621 |
| Frontend application routes | 32 + fallback |
| Alembic heads | одна: `20260829_0081` |
| Local schema mode | `development_startup_ddl` |

Локальная SQLite-база не имеет Alembic stamp, потому что launcher использует
явный development `create_all` режим. Readiness исправлен: этот режим теперь
честно отображается как `development_startup_ddl` и допускается только вне
production на SQLite. При production либо при отключённом development-режиме
устаревшая/непроставленная миграция по-прежнему даёт HTTP 503.

## 6. Проверки качества

| Gate | Результат |
|---|---|
| Backend collection | 769 scenarios in 87 files |
| Backend regression | 723 passed, 16 skipped, 0 failed, 0 errors |
| Ruff | PASS |
| Python compileall | PASS |
| TypeScript | PASS |
| Vite production build | PASS, 142 modules |
| Accessibility static baseline | PASS, 77 files, 16 dialogs |
| Interactive controls | PASS, 673 buttons, 39 links |
| M1 local/static release gate | 27/27 PASS |
| Browser smoke (manager) | 25/25 routes, 0 alerts, 0 console errors |
| Observability contract | 8 SLO, 21 alerts, 20 panels |
| PRG-006 static contract | 3 load profiles, 31 security controls |

Machine-readable M1 evidence:
`docs/audit/evidence/M1-LOCAL-STATIC-2026-08-14.json`, SHA-256
`072a2aadec120cb29fc09fae0352f4629ea52d5372627e7ba9c98706020be14e`.

Local production-like runtime rehearsal now also passes: production preflight
`66 OK / 2 WARN / 0 FAIL`, PostgreSQL/Redis/backend/frontend healthy, Alembic
`20260729_0072`, migration exit `0`, authenticated metrics, Grafana,
Alertmanager and login/identity/logout. Fresh runtime error signatures: `0`.
See `docs/audit/PRODUCTION-REHEARSAL-2026-08-14.md` and its JSON evidence.
Runtime evidence SHA-256:
`6dbb04223dd363e9c5c0dd27a893ea8587912b536b5b8b80a289587ac4114c85`.

Current-revision security and supply-chain gate also passes locally: Python and
frontend dependency audits have `0` known vulnerabilities; Bandit has `0`
findings; Git history and dirty worktree secret scans have `0` leaks; both
final images have `0` High/Critical CVE; source/image SBOMs are present; OWASP
ZAP reports `0 FAIL`, `4 WARN` rule IDs and `63 PASS`. The Medium CSP warning is
explicitly accepted only for the local gate. Security evidence SHA-256:
`b6b01b57adfc4bec18a1ab5c41851dd17819545fc7f9d91a6c2aceeb057b4b42`.

## 7. Подтверждённые production foundations

- fail-fast production settings validator;
- запрет demo mode, SQLite и startup DDL в production;
- strict CORS/trusted hosts/forwarded proxy validation;
- secure session/refresh lifecycle, MFA foundation, OIDC and SCIM foundation;
- multi-role RBAC, route authentication contract и tenant-scoped services;
- tamper-evident audit chain;
- request body limits, login abuse limits и bounded operational settings;
- secret injection через files/Docker secrets и отказ от plaintext provider keys;
- outbox/idempotency/retry/dead-letter/replay foundations;
- honest `SUCCESS/FAILED/SIMULATED/BLOCKED_EXTERNAL` provider evidence;
- catalog, request fulfillment, change, problem, major incident, release,
  CMDB, SLA, knowledge/RAG, automation, integrations и administration modules;
- monitoring rules/dashboards и backup/restore tooling.

## 8. Существенные gaps

1. Совместный production-like Compose rehearsal подтверждён. Остаются
   queue/outbox/DLQ failure/replay, graceful restart и PostgreSQL cross-tenant
   concurrency/load acceptance текущего среза.
2. Полный `upgrade -> downgrade -> upgrade` на изолированном PostgreSQL и
   сравнение данных не выполнены в этом аудите.
3. Dependency audit, SAST, secret scan, image scan, passive DAST и четыре SBOM
   подтверждены текущими outputs. Остаются публичный TLS active scan,
   rate-limit stress и независимый penetration test.
4. Attachment storage/quarantine/Graph foundation присутствует; реальный
   ClamAV acceptance и fail-closed malware workflow не подтверждены.
5. WCAG static baseline не заменяет axe/browser/screen-reader/zoom acceptance;
   аудит также выявляет 18 non-semantic clickable divs для ручной проверки.
6. Полная RU/KK/EN parity всех specialist/admin экранов не доказана
   автоматическим key-parity gate и human linguistic review.
7. Service Desk enterprise depth частична: participants/watchers завершены;
   macros/canned responses, shifts/on-call,
   delegation, scheduled reports и controlled exports требуют отдельного
   подтверждения или реализации.
8. Software Asset Management реализован как отдельный модуль; остаются live
   discovery feed, bulk import и end-to-end renewal delivery.
9. SaaS commercial controls (plans, quotas, metering, lifecycle/deletion,
   white-label/custom domain) намеренно deferred до бизнес-решения.
10. Полный suite занимает около 10 минут даже в четырёх shards; CI требует
    стабильного sharding, per-test timing и timeout policy.
11. Starlette предупреждает о переходе с `httpx` на `httpx2`; migration-тесты
    SQLite дают ожидаемые SAWarning для отражённых foreign keys.
12. Рабочее дерево было грязным до аудита: 146 tracked changes и большой набор
    untracked delivery files. Они сохранены и не перезаписаны.

## 9. Исправлено в рамках среза

- удалены четыре неиспользуемых импорта из DOCX generator, из-за которых Ruff
  делал release gate красным;
- исправлена семантика local readiness для явного development startup-DDL
  режима;
- добавлен negative test: вне локального режима outdated migrations остаются
  fail-closed и возвращают HTTP 503;
- после перезагрузки подтверждено: health `ok`, readiness `ready`, frontend 200.

## 10. Итоговый статус

`PARTIAL` для полной цели Production Ready. Внутренний кодовый/static foundation
сильный и воспроизводимо зелёный, локальный UAT готов. Финальный статус сервера
остаётся `BLOCKED_EXTERNAL` до предоставления production topology, домена/TLS,
реальных secrets/providers и выполнения live acceptance gates.

## 11. Продолжение среза — 2026-08-14 17:00 +05:00

Этот раздел заменяет устаревшие численные границы выше, не переписывая
исторический baseline:

- OpenAPI: 734 operations / 617 paths; frontend: 33 route declarations
  including fallback.
- Alembic: одна head-revision `20260814_0080`; PostgreSQL rehearsal успешно
  обновлён с `0079` и все три backend-реплики healthy.
- Observability: отдельный leader-elected scheduler, 8 SLO, 21 alert rules,
  20 dashboard panels, 3/3 backend scrape targets и проверенная firing/resolved
  Alertmanager-аудит цепочка.
- Data governance `0077` и Software Asset Management `0078` реализованы после
  исходного среза.
- SAM включает products, licenses, installations, prohibited software,
  unauthorized installation, expiration/renewal, reconciliation, compliance и
  cost-at-risk. Backend focused acceptance: 10 passed; TypeScript и чистая
  production Docker-сборка прошли.
- Ticket participants/watchers `0079` включают tenant isolation, internal и
  external participants, self-watch, роли, event scopes, in-app/email channels,
  optimistic locking, soft removal, history/audit и RU/KK/EN UI. Центр
  уведомлений теперь recipient-scoped; tenant-wide view требует отдельного
  `notifications.manage`. Runtime requester smoke и 26 focused tests прошли.
- Audited on-behalf registration `0080` фиксирует фактического создателя,
  заявителя, контакт, канал и обязательное основание; отдельное право выдано
  только root/admin/manager/agent, requester impersonation и cross-tenant выбор
  блокируются. PostgreSQL/runtime, RU/KK/EN UI, история и tamper-evident audit
  подтверждены; 73 focused test executions прошли.
- Текущая коллекция содержит 769 tests. Предыдущий полный подтверждённый
  regression остаётся 723 passed / 16 skipped. Последний монолитный повтор был
  остановлен по 20-минутному process timeout без зафиксированного failure,
  поэтому он честно не записан как полный PASS; изменения после baseline закрыты
  сфокусированными контрактными и runtime-проверками.

## 12. Продолжение среза — 2026-08-29

- Ticket duplicate/merge/split governance `0081` реализован полностью локально:
  explainable score, tenant/RBAC visibility, false-positive dismissal,
  non-destructive merge и выделение дочерней заявки.
- Optimistic governance versions и стабильные idempotency keys защищают от
  stale/concurrent повторов; решения сохраняются в отдельной immutable evidence
  table, ticket history и tamper-evident audit.
- Merge не удаляет и не переносит исходную заявку, комментарии или историю;
  запись переводится в `CANCELLED` и получает ссылку на primary ticket.
- Новые controls локализованы RU/KK/EN. TypeScript, production Vite build,
  accessibility и interactive-controls audits прошли.
- Focused acceptance: новый suite 6/6, migration/on-behalf preflight 6/6,
  расширенная ticket regression 33/33, Ruff и compileall PASS.
- Текущая коллекция: 775 tests; последний полный baseline остаётся 723 passed /
  16 skipped и не подменяется focused acceptance.
- Auth contract: 746 endpoints / 739 protected / 7 governed public. OpenAPI:
  738 operations / 621 paths.
- PostgreSQL rehearsal: `20260829_0081 (head)`; 3/3 backend replicas и frontend
  healthy, worker/scheduler running, readiness HTTP 200 с PostgreSQL, Redis,
  migrations, runtime и websocket checks `ok/ready`.
