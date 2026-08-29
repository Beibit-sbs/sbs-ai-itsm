import { useEffect, useState } from 'react'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import {
  fetchEntityCustomFieldSets,
  saveEntityCustomFieldValues,
  type CustomFieldDefinition,
  type CustomFieldEntityType,
} from '../api/client'
import { useAuth } from '../auth/AuthContext'
import LocalizedContent from '../experience/LocalizedContent'

type Props = {
  entityType: CustomFieldEntityType
  entityId: string
  tenantId?: string | null
  compact?: boolean
}

function errorText(error: unknown) {
  return error instanceof Error ? error.message : 'Не удалось сохранить поля'
}

function isVisible(
  field: CustomFieldDefinition,
  values: Record<string, unknown>,
) {
  const rule = field.visibility
  if (!rule) return true
  const current = values[rule.field_key]
  if (rule.operator === 'eq') return current === rule.value
  if (rule.operator === 'neq') return current !== rule.value
  if (rule.operator === 'in') {
    return Array.isArray(rule.value) && rule.value.includes(current)
  }
  if (rule.operator === 'truthy') return Boolean(current)
  if (rule.operator === 'falsy') return !current
  return false
}

function normalizedInitialValues(values: Record<string, unknown>) {
  return Object.fromEntries(
    Object.entries(values).filter(([, value]) => value !== '••••••'),
  )
}

export default function EntityCustomFieldsPanel({
  entityType,
  entityId,
  tenantId,
  compact = false,
}: Props) {
  const { session } = useAuth()
  const queryClient = useQueryClient()
  const token = session?.access_token ?? ''
  const isRoot = session?.user.role === 'saas_root'
  const permissions = new Set(session?.user.permissions ?? [])
  const canRead =
    isRoot || permissions.has('custom_fields.values.read')
  const canWrite =
    isRoot || permissions.has('custom_fields.values.write')
  const [drafts, setDrafts] = useState<
    Record<string, Record<string, unknown>>
  >({})
  const [dirtySets, setDirtySets] = useState<Set<string>>(new Set())
  const [busyId, setBusyId] = useState('')
  const [notice, setNotice] = useState('')
  const [error, setError] = useState('')

  const query = useQuery({
    queryKey: [
      'entity-custom-fields-panel',
      token,
      tenantId,
      entityType,
      entityId,
    ],
    queryFn: () =>
      fetchEntityCustomFieldSets(token, entityType, entityId, tenantId),
    enabled: Boolean(token && entityId && canRead),
  })

  useEffect(() => {
    if (!query.data) return
    setDrafts((current) => {
      const next = { ...current }
      query.data.forEach((entry) => {
        if (dirtySets.has(entry.field_set.id)) return
        next[entry.field_set.id] = normalizedInitialValues(
          entry.value_record?.values ?? {},
        )
      })
      return next
    })
  }, [dirtySets, query.data])

  if (!canRead) return null
  if (query.isLoading) {
    return (
      <section className="entity-custom-fields">
        <p className="muted">Загружаем дополнительные поля…</p>
      </section>
    )
  }
  if (query.isError) {
    return (
      <section className="entity-custom-fields">
        <p className="error-message">{errorText(query.error)}</p>
      </section>
    )
  }
  if (!query.data?.length) return null

  const updateValue = (
    fieldSetId: string,
    key: string,
    value: unknown,
  ) => {
    setDrafts((current) => ({
      ...current,
      [fieldSetId]: {
        ...(current[fieldSetId] ?? {}),
        [key]: value,
      },
    }))
    setDirtySets((current) => new Set(current).add(fieldSetId))
    setNotice('')
    setError('')
  }

  const save = async (
    fieldSetId: string,
    expectedVersion: number | null,
  ) => {
    setBusyId(fieldSetId)
    setNotice('')
    setError('')
    try {
      await saveEntityCustomFieldValues(
        token,
        fieldSetId,
        entityId,
        drafts[fieldSetId] ?? {},
        expectedVersion,
      )
      setDirtySets((current) => {
        const next = new Set(current)
        next.delete(fieldSetId)
        return next
      })
      await Promise.all([
        queryClient.invalidateQueries({
          queryKey: ['entity-custom-fields-panel'],
        }),
        queryClient.invalidateQueries({
          queryKey: ['entity-custom-fields'],
        }),
      ])
      setNotice('Дополнительные поля сохранены')
    } catch (saveError) {
      setError(errorText(saveError))
    } finally {
      setBusyId('')
    }
  }

  return (
    <LocalizedContent>
    <section className={`entity-custom-fields${compact ? ' compact' : ''}`}>
      <header>
        <div>
          <span>Дополнительные поля</span>
          <h3>Настраиваемые данные</h3>
        </div>
        <small>{query.data.length} наборов</small>
      </header>
      {notice ? <p className="entity-custom-fields-notice">{notice}</p> : null}
      {error ? <p className="error-message">{error}</p> : null}
      {query.data.map((entry) => {
        const schema = entry.published_version.schema_definition
        if (!schema) return null
        const values = drafts[entry.field_set.id] ?? {}
        return (
          <article key={entry.field_set.id}>
            <header>
              <div>
                <strong>{entry.field_set.name}</strong>
                <small>
                  {entry.field_set.code} · schema v
                  {entry.published_version.version_number}
                </small>
              </div>
              {!entry.value_schema_current ? (
                <span className="badge badge-warning">обновится при сохранении</span>
              ) : null}
            </header>
            {schema.introduction ? <p>{schema.introduction}</p> : null}
            <div className="entity-custom-field-grid">
              {schema.fields
                .filter((field) => isVisible(field, values))
                .map((field) => {
                  const value = values[field.key]
                  const masked =
                    entry.value_record?.values[field.key] === '••••••'
                  const common = {
                    id: `${entry.field_set.id}-${field.key}`,
                    disabled: !canWrite,
                  }
                  return (
                    <label
                      key={field.key}
                      className={
                        field.type === 'textarea'
                          ? 'entity-custom-field-wide'
                          : ''
                      }
                    >
                      <span>
                        {field.label}
                        {field.required ? ' *' : ''}
                        {field.sensitive ? ' · protected' : ''}
                      </span>
                      {field.type === 'textarea' ? (
                        <textarea
                          {...common}
                          value={String(value ?? '')}
                          placeholder={
                            masked
                              ? 'Значение сохранено; оставьте пустым без изменения'
                              : field.placeholder
                          }
                          onChange={(event) =>
                            updateValue(
                              entry.field_set.id,
                              field.key,
                              event.target.value,
                            )
                          }
                        />
                      ) : field.type === 'boolean' ? (
                        <input
                          {...common}
                          type="checkbox"
                          checked={Boolean(value)}
                          onChange={(event) =>
                            updateValue(
                              entry.field_set.id,
                              field.key,
                              event.target.checked,
                            )
                          }
                        />
                      ) : field.type === 'select' ? (
                        <select
                          {...common}
                          value={String(value ?? '')}
                          onChange={(event) =>
                            updateValue(
                              entry.field_set.id,
                              field.key,
                              event.target.value,
                            )
                          }
                        >
                          <option value="">Не выбрано</option>
                          {field.options.map((option) => (
                            <option key={option.value} value={option.value}>
                              {option.label}
                            </option>
                          ))}
                        </select>
                      ) : field.type === 'multiselect' ? (
                        <select
                          {...common}
                          multiple
                          value={Array.isArray(value) ? value.map(String) : []}
                          onChange={(event) =>
                            updateValue(
                              entry.field_set.id,
                              field.key,
                              Array.from(
                                event.target.selectedOptions,
                                (option) => option.value,
                              ),
                            )
                          }
                        >
                          {field.options.map((option) => (
                            <option key={option.value} value={option.value}>
                              {option.label}
                            </option>
                          ))}
                        </select>
                      ) : (
                        <input
                          {...common}
                          type={
                            field.type === 'number'
                              ? 'number'
                              : field.type === 'date'
                                ? 'date'
                                : field.type === 'email'
                                  ? 'email'
                                  : 'text'
                          }
                          value={String(value ?? '')}
                          placeholder={
                            masked
                              ? 'Значение сохранено; оставьте пустым без изменения'
                              : field.placeholder
                          }
                          onChange={(event) =>
                            updateValue(
                              entry.field_set.id,
                              field.key,
                              field.type === 'number' &&
                                event.target.value !== ''
                                ? Number(event.target.value)
                                : event.target.value,
                            )
                          }
                        />
                      )}
                      {field.help_text ? <small>{field.help_text}</small> : null}
                    </label>
                  )
                })}
            </div>
            {canWrite ? (
              <footer>
                <button
                  type="button"
                  className="secondary-button"
                  disabled={
                    busyId !== '' || !dirtySets.has(entry.field_set.id)
                  }
                  onClick={() =>
                    void save(
                      entry.field_set.id,
                      entry.value_record?.version ?? null,
                    )
                  }
                >
                  {busyId === entry.field_set.id
                    ? 'Сохраняем…'
                    : 'Сохранить поля'}
                </button>
              </footer>
            ) : null}
          </article>
        )
      })}
    </section>
    </LocalizedContent>
  )
}
