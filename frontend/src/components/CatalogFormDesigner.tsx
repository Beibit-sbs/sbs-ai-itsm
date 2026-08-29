import { useEffect, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import {
  fetchCatalogForm,
  fetchCatalogFormVersions,
  initializeCatalogFormDraft,
  publishCatalogForm,
  updateCatalogFormDraft,
  type CatalogAttachmentRules,
  type CatalogFormDefinition,
  type CatalogFormField,
  type CatalogFormFieldType,
} from '../api/client'
import CatalogFormFields from './CatalogFormFields'
import QueryFailureNotice from './QueryFailureNotice'
import LocalizedContent from '../experience/LocalizedContent'
import { useTenantExperience } from '../experience/TenantExperienceContext'

const fieldTypes: Array<{ value: CatalogFormFieldType; label: string }> = [
  { value: 'text', label: 'Короткий текст' },
  { value: 'textarea', label: 'Многострочный текст' },
  { value: 'number', label: 'Число' },
  { value: 'boolean', label: 'Да / нет' },
  { value: 'select', label: 'Один вариант' },
  { value: 'multiselect', label: 'Несколько вариантов' },
  { value: 'date', label: 'Дата' },
  { value: 'email', label: 'Email' },
]

type Props = {
  accessToken: string
  itemId: string
  canPublish: boolean
  onNotice: (message: string) => void
  onError: (message: string) => void
}

function copyDefinition(value: CatalogFormDefinition): CatalogFormDefinition {
  return JSON.parse(JSON.stringify(value)) as CatalogFormDefinition
}

function copyRules(value: CatalogAttachmentRules): CatalogAttachmentRules {
  return { ...value, allowed_extensions: [...value.allowed_extensions] }
}

function newField(
  definition: CatalogFormDefinition,
  sectionId: string,
  label: string,
): CatalogFormField {
  let index = definition.fields.length + 1
  let key = `field_${index}`
  while (definition.fields.some((field) => field.key === key)) {
    index += 1
    key = `field_${index}`
  }
  return {
    key,
    label,
    type: 'text',
    section_id: sectionId,
    required: false,
    help_text: '',
    placeholder: '',
    options: [],
    validations: {},
  }
}

function optionValue(label: string, index: number) {
  const normalized = label
    .trim()
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, '_')
    .replace(/^_+|_+$/g, '')
  return normalized || `option_${index + 1}`
}

export default function CatalogFormDesigner({
  accessToken,
  itemId,
  canPublish,
  onNotice,
  onError,
}: Props) {
  const { t, translate } = useTenantExperience()
  const queryClient = useQueryClient()
  const [definition, setDefinition] = useState<CatalogFormDefinition | null>(null)
  const [attachmentRules, setAttachmentRules] = useState<CatalogAttachmentRules | null>(null)
  const [previewValues, setPreviewValues] = useState<Record<string, unknown>>({})
  const [showPreview, setShowPreview] = useState(false)
  const [publishReason, setPublishReason] = useState('')

  const draftQuery = useQuery({
    queryKey: ['catalog-form', accessToken, itemId, 'draft'],
    queryFn: () => fetchCatalogForm(accessToken, itemId, 'draft'),
    enabled: Boolean(accessToken && itemId),
  })
  const versionsQuery = useQuery({
    queryKey: ['catalog-form-versions', accessToken, itemId],
    queryFn: () => fetchCatalogFormVersions(accessToken, itemId),
    enabled: Boolean(accessToken && itemId),
  })

  useEffect(() => {
    if (draftQuery.data) {
      setDefinition(copyDefinition(draftQuery.data.schema))
      setAttachmentRules(copyRules(draftQuery.data.attachment_rules))
    } else if (draftQuery.isSuccess) {
      setDefinition(null)
      setAttachmentRules(null)
    }
  }, [draftQuery.data, draftQuery.isSuccess])

  async function refreshForms() {
    await Promise.all([
      queryClient.invalidateQueries({ queryKey: ['catalog-form'] }),
      queryClient.invalidateQueries({ queryKey: ['catalog-form-versions'] }),
    ])
  }

  function mutationError(error: unknown) {
    onError(
      error instanceof Error
        ? error.message
        : t('catalog.form.operationFailed'),
    )
  }

  const initializeMutation = useMutation({
    mutationFn: () => initializeCatalogFormDraft(accessToken, itemId),
    onSuccess: async (form) => {
      onNotice(t('catalog.form.draftCreated', { version: form.version }))
      await refreshForms()
    },
    onError: mutationError,
  })
  const saveMutation = useMutation({
    mutationFn: () => {
      if (!draftQuery.data || !definition || !attachmentRules) {
        throw new Error(t('catalog.form.draftMissing'))
      }
      return updateCatalogFormDraft(accessToken, itemId, {
        expected_revision: draftQuery.data.revision,
        schema: definition,
        attachment_rules: attachmentRules,
      })
    },
    onSuccess: async (form) => {
      onNotice(t('catalog.form.saved', { version: form.version, revision: form.revision }))
      await refreshForms()
    },
    onError: mutationError,
  })
  const publishMutation = useMutation({
    mutationFn: async () => {
      if (!draftQuery.data || !definition || !attachmentRules) {
        throw new Error(t('catalog.form.draftMissing'))
      }
      const saved = await updateCatalogFormDraft(accessToken, itemId, {
        expected_revision: draftQuery.data.revision,
        schema: definition,
        attachment_rules: attachmentRules,
      })
      return publishCatalogForm(accessToken, itemId, {
        expected_revision: saved.revision,
        reason: publishReason.trim() || t('catalog.form.defaultPublishReason'),
      })
    },
    onSuccess: async (form) => {
      onNotice(t('catalog.form.published', { version: form.version }))
      setShowPreview(false)
      await refreshForms()
    },
    onError: mutationError,
  })

  function updateField(index: number, patch: Partial<CatalogFormField>) {
    setDefinition((current) => {
      if (!current) return current
      const fields = [...current.fields]
      fields[index] = { ...fields[index], ...patch }
      return { ...current, fields }
    })
  }

  function moveField(index: number, direction: -1 | 1) {
    setDefinition((current) => {
      if (!current) return current
      const target = index + direction
      if (target < 0 || target >= current.fields.length) return current
      const fields = [...current.fields]
      ;[fields[index], fields[target]] = [fields[target], fields[index]]
      return { ...current, fields }
    })
  }

  if (draftQuery.isPending || versionsQuery.isPending) {
    return <LocalizedContent><section className="catalog-form-designer"><p className="muted">Загрузка конструктора…</p></section></LocalizedContent>
  }

  const versions = versionsQuery.data ?? []
  const published = versions.find((form) => form.status === 'PUBLISHED')

  if (!draftQuery.data || !definition || !attachmentRules) {
    return (
      <LocalizedContent>
      <section className="catalog-form-designer">
        <QueryFailureNotice
          title="Данные конструктора формы недоступны."
          sources={[
            { label: 'draft формы', query: draftQuery },
            { label: 'версии формы', query: versionsQuery },
          ]}
        />
        <header className="catalog-designer-heading">
          <div>
            <p className="eyebrow">REQUEST FORM</p>
            <h3>Форма заказа услуги</h3>
            <p className="muted">
              {published
                ? t('catalog.form.publishedHelp', { version: published.version })
                : 'Создайте форму из секций и полей. Программирование не требуется.'}
            </p>
          </div>
          <button
            type="button"
            disabled={initializeMutation.isPending}
            onClick={() => initializeMutation.mutate()}
          >
            {published ? 'Новая редакция' : 'Создать форму'}
          </button>
        </header>
        {versions.length ? (
          <div className="catalog-form-version-strip">
            {versions.map((form) => (
              <span key={form.id} className={`status-${form.status.toLowerCase()}`}>
                v{form.version} · {form.status}
              </span>
            ))}
          </div>
        ) : null}
      </section>
      </LocalizedContent>
    )
  }

  const draft = draftQuery.data
  return (
    <LocalizedContent>
    <section className="catalog-form-designer">
      <QueryFailureNotice
        title="Часть данных конструктора формы недоступна."
        sources={[
          { label: 'draft формы', query: draftQuery },
          { label: 'версии формы', query: versionsQuery },
        ]}
      />
      <header className="catalog-designer-heading">
        <div>
          <p className="eyebrow">NO-CODE REQUEST FORM</p>
          <h3>Конструктор формы · v{draft.version}</h3>
          <p className="muted">
            {t('catalog.form.draftRevision', { revision: draft.revision })}
          </p>
        </div>
        <span className="catalog-designer-badge">DRAFT</span>
      </header>

      <div className="catalog-designer-basics">
        <label>
          <span>Заголовок формы</span>
          <input
            value={definition.title}
            onChange={(event) => setDefinition({ ...definition, title: event.target.value })}
          />
        </label>
        <label>
          <span>Инструкция пользователю</span>
          <textarea
            value={definition.introduction}
            onChange={(event) => setDefinition({ ...definition, introduction: event.target.value })}
          />
        </label>
      </div>

      <div className="catalog-designer-sections">
        <div className="catalog-designer-section-title">
          <div>
            <h4>Секции</h4>
            <p>Группируют поля в понятные смысловые блоки.</p>
          </div>
          <button
            type="button"
            className="ghost-button"
            onClick={() => {
              const next = definition.sections.length + 1
              setDefinition({
                ...definition,
                sections: [
                  ...definition.sections,
                  {
                    id: `section_${next}`,
                    title: t('catalog.form.newSection', { index: next }),
                    description: '',
                    order: next * 10,
                  },
                ],
              })
            }}
          >
            + Секция
          </button>
        </div>
        {definition.sections.map((section, index) => (
          <article key={section.id} className="catalog-designer-section-card">
            <label>
              <span>Название</span>
              <input
                value={section.title}
                onChange={(event) => {
                  const sections = [...definition.sections]
                  sections[index] = { ...section, title: event.target.value }
                  setDefinition({ ...definition, sections })
                }}
              />
            </label>
            <label>
              <span>Описание</span>
              <input
                value={section.description}
                onChange={(event) => {
                  const sections = [...definition.sections]
                  sections[index] = { ...section, description: event.target.value }
                  setDefinition({ ...definition, sections })
                }}
              />
            </label>
            <button
              type="button"
              className="ghost-button catalog-icon-button"
              disabled={
                definition.sections.length === 1
                || definition.fields.some((field) => field.section_id === section.id)
              }
              title="Секцию с полями удалить нельзя"
              onClick={() => setDefinition({
                ...definition,
                sections: definition.sections.filter((candidate) => candidate.id !== section.id),
              })}
            >
              Удалить
            </button>
          </article>
        ))}
      </div>

      <div className="catalog-designer-fields">
        <div className="catalog-designer-section-title">
          <div>
            <h4>Поля</h4>
            <p>Порядок ниже совпадает с порядком в пользовательской форме.</p>
          </div>
          <button
            type="button"
            onClick={() => {
              const sectionId = definition.sections[0]?.id
              if (!sectionId) return
              setDefinition({
                ...definition,
                fields: [
                  ...definition.fields,
                  newField(
                    definition,
                    sectionId,
                    t('catalog.form.newField', { index: definition.fields.length + 1 }),
                  ),
                ],
              })
            }}
          >
            + Добавить поле
          </button>
        </div>
        {!definition.fields.length ? (
          <div className="catalog-designer-empty">
            <strong>Поля ещё не добавлены</strong>
            <span>Можно опубликовать и пустую форму, но обычно услуге нужны входные данные.</span>
          </div>
        ) : null}
        {definition.fields.map((field, index) => {
          const controllers = definition.fields.slice(0, index)
          return (
            <article key={`${field.key}-${index}`} className="catalog-designer-field-card">
              <header>
                <strong>{index + 1}. {field.label || 'Поле без названия'}</strong>
                <div>
                  <button type="button" className="ghost-button" disabled={index === 0} onClick={() => moveField(index, -1)}>↑</button>
                  <button type="button" className="ghost-button" disabled={index === definition.fields.length - 1} onClick={() => moveField(index, 1)}>↓</button>
                  <button
                    type="button"
                    className="ghost-button"
                    onClick={() => setDefinition({
                      ...definition,
                      fields: definition.fields.filter((_, fieldIndex) => fieldIndex !== index),
                    })}
                  >
                    Удалить
                  </button>
                </div>
              </header>
              <div className="catalog-designer-field-grid">
                <label>
                  <span>Название поля</span>
                  <input value={field.label} onChange={(event) => updateField(index, { label: event.target.value })} />
                </label>
                <label>
                  <span>Системный ключ</span>
                  <input value={field.key} onChange={(event) => updateField(index, { key: event.target.value.toLowerCase().replace(/[^a-z0-9_]/g, '_') })} />
                </label>
                <label>
                  <span>Тип</span>
                  <select
                    value={field.type}
                    onChange={(event) => {
                      const type = event.target.value as CatalogFormFieldType
                      updateField(index, {
                        type,
                        options: type === 'select' || type === 'multiselect'
                          ? field.options.length ? field.options : [{ value: 'option_1', label: 'Вариант 1' }]
                          : [],
                      })
                    }}
                  >
                    {fieldTypes.map((type) => <option key={type.value} value={type.value}>{translate(type.label)}</option>)}
                  </select>
                </label>
                <label>
                  <span>Секция</span>
                  <select value={field.section_id} onChange={(event) => updateField(index, { section_id: event.target.value })}>
                    {definition.sections.map((section) => <option key={section.id} value={section.id}>{section.title}</option>)}
                  </select>
                </label>
                <label className="catalog-designer-wide">
                  <span>Подсказка</span>
                  <input value={field.help_text} onChange={(event) => updateField(index, { help_text: event.target.value })} placeholder="Что именно нужно указать" />
                </label>
                <label>
                  <span>Пример в поле</span>
                  <input value={field.placeholder} onChange={(event) => updateField(index, { placeholder: event.target.value })} />
                </label>
                <label className="catalog-checkbox">
                  <input type="checkbox" checked={field.required} onChange={(event) => updateField(index, { required: event.target.checked })} />
                  <span>Обязательное поле</span>
                </label>
                {field.type === 'select' || field.type === 'multiselect' ? (
                  <label className="catalog-designer-wide">
                    <span>Варианты через запятую</span>
                    <input
                      value={field.options.map((option) => option.label).join(', ')}
                      onChange={(event) => {
                        const labels = event.target.value.split(',').map((value) => value.trim()).filter(Boolean)
                        updateField(index, {
                          options: labels.map((label, optionIndex) => ({
                            value: optionValue(label, optionIndex),
                            label,
                          })),
                        })
                      }}
                    />
                  </label>
                ) : null}
                {field.type === 'text' || field.type === 'textarea' || field.type === 'email' ? (
                  <>
                    <label>
                      <span>Мин. символов</span>
                      <input type="number" min={0} value={field.validations.min_length ?? ''} onChange={(event) => updateField(index, { validations: { ...field.validations, min_length: event.target.value === '' ? undefined : Number(event.target.value) } })} />
                    </label>
                    <label>
                      <span>Макс. символов</span>
                      <input type="number" min={1} value={field.validations.max_length ?? ''} onChange={(event) => updateField(index, { validations: { ...field.validations, max_length: event.target.value === '' ? undefined : Number(event.target.value) } })} />
                    </label>
                  </>
                ) : null}
                {field.type === 'number' ? (
                  <>
                    <label>
                      <span>Минимум</span>
                      <input type="number" value={field.validations.min ?? ''} onChange={(event) => updateField(index, { validations: { ...field.validations, min: event.target.value === '' ? undefined : Number(event.target.value) } })} />
                    </label>
                    <label>
                      <span>Максимум</span>
                      <input type="number" value={field.validations.max ?? ''} onChange={(event) => updateField(index, { validations: { ...field.validations, max: event.target.value === '' ? undefined : Number(event.target.value) } })} />
                    </label>
                  </>
                ) : null}
                <label>
                  <span>Показывать условно</span>
                  <select
                    value={field.visibility?.field_key ?? ''}
                    onChange={(event) => updateField(index, {
                      visibility: event.target.value
                        ? {
                            field_key: event.target.value,
                            operator: 'eq',
                            value: '',
                          }
                        : undefined,
                    })}
                  >
                    <option value="">Всегда показывать</option>
                    {controllers.map((controller) => <option key={controller.key} value={controller.key}>{controller.label}</option>)}
                  </select>
                </label>
                {field.visibility ? (
                  <>
                    <label>
                      <span>Условие</span>
                      <select
                        value={field.visibility.operator}
                        onChange={(event) => updateField(index, {
                          visibility: {
                            ...field.visibility!,
                            operator: event.target.value as 'eq' | 'neq' | 'truthy' | 'falsy',
                          },
                        })}
                      >
                        <option value="eq">Равно</option>
                        <option value="neq">Не равно</option>
                        <option value="truthy">Заполнено / да</option>
                        <option value="falsy">Не заполнено / нет</option>
                      </select>
                    </label>
                    {field.visibility.operator === 'eq' || field.visibility.operator === 'neq' ? (
                      <label>
                        <span>Значение условия</span>
                        <input
                          value={String(field.visibility.value ?? '')}
                          onChange={(event) => updateField(index, {
                            visibility: { ...field.visibility!, value: event.target.value },
                          })}
                        />
                      </label>
                    ) : null}
                  </>
                ) : null}
              </div>
            </article>
          )
        })}
      </div>

      <section className="catalog-attachment-policy">
        <div>
          <h4>Политика вложений</h4>
          <p>Ограничения уже проверяются сервером. Передача файлов в защищённое хранилище — следующий продуктовый этап.</p>
        </div>
        <label className="catalog-checkbox">
          <input
            type="checkbox"
            checked={attachmentRules.enabled}
            onChange={(event) => setAttachmentRules({
              ...attachmentRules,
              enabled: event.target.checked,
              required: event.target.checked ? attachmentRules.required : false,
            })}
          />
          <span>Разрешить вложения</span>
        </label>
        {attachmentRules.enabled ? (
          <div className="catalog-attachment-grid">
            <label className="catalog-checkbox">
              <input type="checkbox" checked={attachmentRules.required} onChange={(event) => setAttachmentRules({ ...attachmentRules, required: event.target.checked })} />
              <span>Вложение обязательно</span>
            </label>
            <label><span>Макс. файлов</span><input type="number" min={1} max={20} value={attachmentRules.max_files} onChange={(event) => setAttachmentRules({ ...attachmentRules, max_files: Number(event.target.value) })} /></label>
            <label><span>Размер файла, МБ</span><input type="number" min={1} max={100} value={attachmentRules.max_size_mb} onChange={(event) => setAttachmentRules({ ...attachmentRules, max_size_mb: Number(event.target.value) })} /></label>
            <label><span>Расширения</span><input value={attachmentRules.allowed_extensions.join(', ')} onChange={(event) => setAttachmentRules({ ...attachmentRules, allowed_extensions: event.target.value.split(',').map((value) => value.trim().toLowerCase().replace(/^\./, '')).filter(Boolean) })} /></label>
          </div>
        ) : null}
      </section>

      <div className="catalog-designer-actions">
        <button type="button" className="ghost-button" onClick={() => setShowPreview((current) => !current)}>
          {showPreview ? 'Скрыть предпросмотр' : 'Предпросмотр'}
        </button>
        <button type="button" disabled={saveMutation.isPending || publishMutation.isPending} onClick={() => saveMutation.mutate()}>
          {saveMutation.isPending ? 'Сохраняем…' : 'Сохранить черновик'}
        </button>
        {canPublish ? (
          <>
            <input
              aria-label="Причина публикации"
              value={publishReason}
              placeholder={t('catalog.form.defaultPublishReason')}
              onChange={(event) => setPublishReason(event.target.value)}
            />
            <button type="button" className="catalog-publish-button" disabled={publishMutation.isPending} onClick={() => publishMutation.mutate()}>
              {publishMutation.isPending ? 'Публикуем…' : 'Сохранить и опубликовать'}
            </button>
          </>
        ) : null}
      </div>

      {showPreview ? (
        <div className="catalog-designer-preview">
          <p className="eyebrow">USER PREVIEW</p>
          <CatalogFormFields
            schema={definition}
            attachmentRules={attachmentRules}
            values={previewValues}
            onChange={(key, value) => setPreviewValues((current) => ({ ...current, [key]: value }))}
          />
        </div>
      ) : null}

      {versions.length ? (
        <div className="catalog-form-version-strip">
          {versions.map((form) => (
            <span key={form.id} className={`status-${form.status.toLowerCase()}`}>
              v{form.version} · {form.status}
            </span>
          ))}
        </div>
      ) : null}
    </section>
    </LocalizedContent>
  )
}
