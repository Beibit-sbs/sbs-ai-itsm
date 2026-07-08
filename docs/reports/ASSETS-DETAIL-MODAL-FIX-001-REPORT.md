# ASSETS-DETAIL-MODAL-FIX-001 Report

## Причина бага
На странице Assets детали выбранного актива рендерились в закреплённой inline боковой панели рядом со списком. При прокрутке длинной таблицы активов UX выглядел как «приклеенный» блок, а не как отдельное окно деталей.

## Изменённые файлы
- `frontend/src/pages/AssetsPage.tsx`
- `frontend/src/styles.css`

## Что исправлено
1. Детали актива переведены с inline side panel на modal-overlay поверх страницы (UX-стандарт, аналогичный Tickets):
- открытие по кнопке "Детали";
- закрытие по кнопке "Закрыть";
- закрытие по клику на backdrop;
- закрытие по клавише Escape.

2. Старая боковая панель отключена из рендера, чтобы не было двойного интерфейса.

3. Добавлен мягкий fallback:
- при открытии детали сохраняются snapshot-данные строки таблицы;
- если API детали недоступен, модалка всё равно открывается с данными таблицы и предупреждением.

4. Карточка в модалке теперь показывает расширенный набор полей:
- asset_tag;
- inventory_number;
- name;
- type;
- manufacturer;
- model;
- serial_number;
- source;
- assigned_to_name;
- department;
- location;
- purchase_year;
- status;
- verification_status;
- health;
- warranty_until;
- imported_at;
- source_batch_id;
- связанные заявки.

5. UI-детали:
- `Location unknown` отображается как `Кабинет не указан`;
- для `verification_status = needs_location` добавлен понятный badge;
- длинные значения в заголовке и полях не ломают layout (перенос строк);
- блок связанных заявок читаемый, при отсутствии выводится `Связанных заявок пока нет.`

## Что не менялось
- Backend-контракты и API.
- Excel import workflow.
- Фильтры и таблица активов.

## Результаты проверок

### Frontend
- `npx tsc -b --pretty false` -> OK
- `npm run build` -> OK

### Backend
- `/home/sbs/sbs-ai-itsm-foundation-001/.venv/bin/python -m pytest -q` -> 97 passed

### Docker
- `docker compose config` -> OK

### Browser smoke-check
Проверено на `http://localhost:5173/assets`:
- кнопка "Детали" открывает modal-layer поверх интерфейса;
- модалка показывает карточку актива;
- закрытие по кнопке работает;
- закрытие по backdrop работает;
- закрытие по Escape работает.
