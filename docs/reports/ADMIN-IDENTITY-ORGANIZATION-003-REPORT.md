# ADMIN-IDENTITY-ORGANIZATION-003 Report

## Итог

Административный контур организации и корпоративной идентификации переведён из
демонстрационного состояния в рабочий production-oriented control plane. Данные
организации теперь приходят из tenant-scoped API, а SSO-консоль показывает
фактическую готовность OIDC без передачи секретов в браузер.

## Организация

- добавлен отдельный `GET /api/v1/tenants/current`, который возвращает только tenant
  текущего пользователя;
- глобальный `GET /api/v1/tenants` оставлен исключительно для SaaS root;
- Organization Admin может изменять название и описание своей организации через
  `PATCH /api/v1/tenants/current`;
- tenant ID и slug доступны только для чтения;
- изменение профиля фиксируется событием `tenant_profile_updated`;
- добавлены отдельные permissions `tenant.profile.read` и
  `tenant.profile.manage`;
- удалены UI fallback-значения и вымышленные module entitlements.

## Identity & SSO

- создан отдельный административный раздел `Identity & SSO`;
- отображаются enabled/readiness status, issuer, redirect URI, client-auth method,
  scopes, signing algorithms, разрешённые домены, provisioning policy и статистика
  входов за 24 часа;
- client ID и client secret показываются только как `configured / not configured`;
- API никогда не возвращает значение client secret;
- readiness checklist перечисляет недостающие runtime-параметры;
- OIDC discovery можно проверить из консоли; в ответ возвращаются только issuer и
  hostname доверенных endpoints;
- каждая проверка записывается как `identity_provider_tested`;
- в карточку пользователя добавлены просмотр, pre-link и unlink корпоративной
  identity по immutable `sub`;
- linked users/identities и login counters ограничены текущим tenant scope.

## Production security decisions

- SSO secrets не редактируются в браузере и должны поступать из environment/Secret
  Manager;
- используется существующий Authorization Code + PKCE (`S256`) runtime;
- email linking и auto-provisioning остаются отдельными, выключенными по умолчанию
  политиками;
- SaaS root без выбранного tenant получает явный `null` current tenant и работает
  через fleet view;
- все новые mutation/test операции включены в tamper-evident audit trail.

## API

- `GET /api/v1/tenants/current`
- `PATCH /api/v1/tenants/current`
- `GET /api/v1/admin/identity-provider`
- `POST /api/v1/admin/identity-provider/test`
- `GET /api/v1/admin/users/{user_id}/external-identities`
- `POST /api/v1/admin/users/{user_id}/external-identities`
- `DELETE /api/v1/admin/users/{user_id}/external-identities/{identity_id}`

## Проверка

- Ruff: изменённые backend routes, seed и tests проходят.
- Focused admin/auth regression: `45 passed`.
- Полный backend regression: `493 passed, 16 skipped` (`509` collected).
- TypeScript project build: проходит.
- Vite production build: проходит.
- Browser QA: Organization Admin видит фактический tenant profile, readiness
  checklist SSO и состояние corporate identity в карточке пользователя.

## Следующие production-этапы

- MFA/WebAuthn и step-up authentication для privileged actions;
- SCIM 2.0 provisioning/deprovisioning;
- break-glass approval workflow и регулярная проверка аварийной учётной записи;
- verified-domain lifecycle и approval для смены tenant profile;
- SIEM/WORM export identity и administrative audit events.
