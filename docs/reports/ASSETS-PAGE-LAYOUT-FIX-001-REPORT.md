# ASSETS-PAGE-LAYOUT-FIX-001 Report

## Причина проблемы
На странице Assets одновременно рендерились:
- preview-таблица импорта Excel;
- основная таблица реестра активов.

Это создавало визуальную конкуренцию двух таблиц и нестабильное восприятие интерфейса при фильтрации и скролле.

## Как разделили режимы registry/import
В `frontend/src/pages/AssetsPage.tsx` добавлен отдельный state режима:
- `activeAssetsMode = 'registry' | 'import'`
- значение по умолчанию: `registry`

Поведение:
- кнопка `Импорт из Excel` переводит страницу в `import`;
- кнопка `Назад к реестру активов` возвращает в `registry`.

## Как исправили проблему двух таблиц
1. В режиме `registry` отображаются только:
- KPI активов;
- фильтры реестра активов;
- основная таблица активов;
- кнопка `Импорт из Excel`.

2. В режиме `import` отображаются только:
- upload/preview/commit блок импорта;
- summary preview;
- preview filters;
- preview table.

3. Основная таблица активов не рендерится в режиме `import`.

4. Preview-таблица импорта не рендерится в режиме `registry`.

5. После commit добавлен post-commit блок:
- создано;
- обновлено;
- пропущено;
- ошибки;
- дубликаты.

6. Добавлены post-commit действия:
- `Показать импортированные активы`:
  - перевод в `registry`;
  - фильтр `source = excel_import`;
  - обновление списка активов.
- `Остаться в импорте`.

## Как исправили детали актива (modal)
Детали актива приведены к modal UX-стандарту:
- открытие по кнопке `Детали`;
- рендер поверх интерфейса в `modal-backdrop` + `modal-card`;
- закрытие по кнопке `Закрыть`;
- закрытие по клику на backdrop;
- закрытие по клавише Escape.

Старая закреплённая inline/side panel больше не рендерится.

## Детали карточки в модалке
В модалке выводятся:
- asset_tag;
- inventory_number;
- name;
- type;
- original_type;
- status;
- source;
- assigned_to_name;
- department / МОЛ;
- location;
- purchase_year;
- verification_status;
- health;
- manufacturer;
- model;
- serial_number;
- warranty_until;
- imported_at;
- source_batch_id;
- связанные заявки.

Дополнительно:
- `Location unknown` -> `Кабинет не указан`;
- `verification_status = needs_location` -> badge `Требует кабинета`;
- пустой список связанных заявок -> `Связанных заявок пока нет.`

## Изменённые файлы
- `frontend/src/pages/AssetsPage.tsx`
- `frontend/src/styles.css`

## Результаты проверок

### Frontend
- `npx tsc -b --pretty false` -> OK
- `npm run build` -> OK

### Backend
- `/home/sbs/sbs-ai-itsm-foundation-001/.venv/bin/python -m pytest -q` -> 97 passed

### Docker
- `docker compose config` -> OK

## Browser smoke-check (/assets)
Проверено:

### Registry mode
- видна только основная таблица активов;
- preview-таблица импорта не отображается;
- кнопка `Детали` открывает модалку;
- закрытие модалки работает по кнопке, backdrop и Escape.

### Import mode
- переход по кнопке `Импорт из Excel` работает;
- основной список активов скрыт;
- отображается preview-таблица импорта;
- preview filters применяются отдельно от фильтров реестра;
- confirm на commit появляется;
- post-commit summary отображается;
- кнопка `Показать импортированные активы` возвращает в `registry` и выставляет `source=excel_import`.

## Оставшиеся ограничения
- Для полного end-to-end UX на реальном пользовательском файле импорта по-прежнему требуется ручная проверка с конкретным Excel-файлом и правами роли с `assets.import.preview`/`assets.import.commit`.
