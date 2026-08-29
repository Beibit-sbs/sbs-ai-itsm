# ADMIN-CONTROL-PLANE-002 Report

## Итог

Раздел администрирования переведён из преимущественно обзорного режима в рабочую
консоль управления доступом. Приоритет отдан операциям, без которых эксплуатация
production ITSM небезопасна: фактическому RBAC, защите глобальных ролей, отзыву
сессий и безопасному сбросу пароля.

## Реализовано

- просмотр фактических permission-связей каждой роли вместо UI-аппроксимации по имени роли;
- создание tenant-роли, изменение названия и описания;
- редактор permission matrix с группировкой по модулю и атомарной заменой набора прав;
- глобальные роли доступны администратору организации только для чтения;
- организация не может назначить глобальную `saas_root`-роль своему пользователю;
- зарезервирован tenant-код `saas_root`, нормализован и валидируется код новой роли;
- флаг `is_system` для tenant-роли не может быть установлен администратором организации;
- список реальных auth-сессий с владельцем, сроком refresh-токена и текущим статусом;
- отзыв отдельной сессии и всех сессий пользователя;
- деактивация учётной записи автоматически отзывает её сессии;
- административный сброс пароля с password-policy validation и опциональным отзывом сессий;
- пароли и API-токены не включаются в audit metadata;
- все новые административные операции записываются в tamper-evident audit log.

## Матрица полноты

| Контур | Состояние после этапа | Следующий production-этап |
|---|---|---|
| Пользователи | create/edit/status/roles/password/session revoke | приглашения, SCIM lifecycle, bulk import |
| Роли и права | реальные CRUD + permission matrix + scope protection | approval workflow и SoD policy |
| Security | login events, risk, реальные sessions/revoke | MFA/WebAuthn и conditional access |
| Audit | фильтры, detail, hash-chain integrity | WORM export и SIEM connector |
| AI providers | OpenAI/Gemini/Mock, keys, models, test | secret vault/KMS и usage budgets |
| Settings | tenant override, sensitive masking | typed schema, validation и change approval |
| Organization | read-only tenant overview | профиль, домены, branding, module entitlements |
| Identity | OIDC runtime + identity links | UI для SSO metadata, SCIM и break-glass workflow |
| Notifications | отдельный operational module | admin template editor и channel health |
| Integrations | отдельный operational module | centralized credential rotation dashboard |

## API

- `GET /api/v1/admin/roles/{role_id}/permissions`
- `PUT /api/v1/admin/roles/{role_id}/permissions`
- `POST /api/v1/admin/users/{user_id}/reset-password`
- `GET /api/v1/security/sessions`
- `POST /api/v1/security/sessions/{session_id}/revoke`
- `POST /api/v1/security/users/{user_id}/revoke-sessions`

## Проверка

- Ruff: новые backend routes, seed и security tests проходят.
- Backend focused suite: `27 passed`.
- Полный backend regression: `489 passed, 16 skipped` (`505` collected).
- TypeScript project build: проходит.
- Vite production build: проходит.
- Browser QA: роли, permission matrix, user security и реальные session metrics проверены
  на локальной demo-базе.
