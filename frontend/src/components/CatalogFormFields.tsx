import type {
  CatalogAttachmentRules,
  CatalogFormDefinition,
  CatalogFormField,
} from '../api/client'
import LocalizedContent from '../experience/LocalizedContent'
import { useTenantExperience } from '../experience/TenantExperienceContext'

type Props = {
  schema: CatalogFormDefinition
  attachmentRules?: CatalogAttachmentRules
  values: Record<string, unknown>
  errors?: Record<string, string[]>
  disabled?: boolean
  onChange: (key: string, value: unknown) => void
  onAttachmentsChange?: (files: File[]) => void
}

export function catalogFieldIsVisible(
  field: CatalogFormField,
  values: Record<string, unknown>,
) {
  if (!field.visibility) return true
  const current = values[field.visibility.field_key]
  const expected = field.visibility.value
  if (field.visibility.operator === 'eq') return current === expected
  if (field.visibility.operator === 'neq') return current !== expected
  if (field.visibility.operator === 'in') {
    return Array.isArray(expected) && expected.includes(current)
  }
  if (field.visibility.operator === 'truthy') return Boolean(current)
  return !current
}

function FieldControl({
  field,
  value,
  disabled,
  onChange,
}: {
  field: CatalogFormField
  value: unknown
  disabled: boolean
  onChange: (value: unknown) => void
}) {
  const common = {
    id: `catalog-field-${field.key}`,
    disabled,
    required: field.required,
  }
  if (field.type === 'textarea') {
    return (
      <textarea
        {...common}
        value={typeof value === 'string' ? value : ''}
        placeholder={field.placeholder}
        minLength={field.validations.min_length}
        maxLength={field.validations.max_length}
        onChange={(event) => onChange(event.target.value)}
      />
    )
  }
  if (field.type === 'select') {
    return (
      <select
        {...common}
        value={typeof value === 'string' ? value : ''}
        onChange={(event) => onChange(event.target.value)}
      >
        <option value="">Выберите значение</option>
        {field.options.map((option) => (
          <option key={option.value} value={option.value}>{option.label}</option>
        ))}
      </select>
    )
  }
  if (field.type === 'multiselect') {
    const selected = Array.isArray(value) ? value.map(String) : []
    return (
      <select
        {...common}
        multiple
        value={selected}
        onChange={(event) => onChange(
          Array.from(event.target.selectedOptions, (option) => option.value),
        )}
      >
        {field.options.map((option) => (
          <option key={option.value} value={option.value}>{option.label}</option>
        ))}
      </select>
    )
  }
  if (field.type === 'boolean') {
    return (
      <label className="catalog-runtime-checkbox">
        <input
          id={common.id}
          disabled={disabled}
          type="checkbox"
          checked={Boolean(value)}
          onChange={(event) => onChange(event.target.checked)}
        />
        <span>Да</span>
      </label>
    )
  }
  return (
    <input
      {...common}
      type={field.type === 'number' ? 'number' : field.type}
      value={
        typeof value === 'string' || typeof value === 'number'
          ? value
          : ''
      }
      placeholder={field.placeholder}
      min={field.validations.min}
      max={field.validations.max}
      minLength={field.validations.min_length}
      maxLength={field.validations.max_length}
      onChange={(event) => onChange(
        field.type === 'number'
          ? event.target.value === ''
            ? ''
            : Number(event.target.value)
          : event.target.value,
      )}
    />
  )
}

export default function CatalogFormFields({
  schema,
  attachmentRules,
  values,
  errors = {},
  disabled = false,
  onChange,
  onAttachmentsChange,
}: Props) {
  const { t } = useTenantExperience()
  const sections = [...schema.sections].sort((left, right) => left.order - right.order)
  return (
    <LocalizedContent>
    <div className="catalog-runtime-form">
      <header>
        <h3>{schema.title}</h3>
        {schema.introduction ? <p>{schema.introduction}</p> : null}
      </header>
      {sections.map((section) => {
        const fields = schema.fields.filter(
          (field) => field.section_id === section.id && catalogFieldIsVisible(field, values),
        )
        if (!fields.length) return null
        return (
          <section key={section.id} className="catalog-runtime-section">
            <div className="catalog-runtime-section-heading">
              <h4>{section.title}</h4>
              {section.description ? <p>{section.description}</p> : null}
            </div>
            <div className="catalog-runtime-grid">
              {fields.map((field) => (
                <label
                  key={field.key}
                  className={[
                    field.type === 'textarea' || field.type === 'multiselect'
                      ? 'catalog-runtime-wide'
                      : '',
                    errors[field.key]?.length ? 'catalog-runtime-invalid' : '',
                  ].join(' ')}
                  htmlFor={`catalog-field-${field.key}`}
                >
                  <span className="catalog-runtime-label">
                    {field.label}
                    {field.required ? <strong aria-label="обязательное поле">*</strong> : null}
                  </span>
                  <FieldControl
                    field={field}
                    value={values[field.key]}
                    disabled={disabled}
                    onChange={(value) => onChange(field.key, value)}
                  />
                  {field.help_text ? <small>{field.help_text}</small> : null}
                  {errors[field.key]?.map((message) => (
                    <em key={message}>{message}</em>
                  ))}
                </label>
              ))}
            </div>
          </section>
        )
      })}
      {attachmentRules?.enabled ? (
        <section className="catalog-runtime-attachments">
          <label>
            <span className="catalog-runtime-label">
              Подтверждающие файлы
              {attachmentRules.required ? <strong>*</strong> : null}
            </span>
            <input
              type="file"
              multiple={attachmentRules.max_files > 1}
              required={attachmentRules.required}
              disabled={disabled}
              accept={attachmentRules.allowed_extensions.map((value) => `.${value}`).join(',')}
              onChange={(event) => onAttachmentsChange?.(Array.from(event.target.files ?? []))}
            />
            <small>{t('catalog.form.attachmentsLimits', {
              files: attachmentRules.max_files,
              size: attachmentRules.max_size_mb,
              formats: attachmentRules.allowed_extensions.join(', '),
            })}</small>
            {errors._attachments?.map((message) => <em key={message}>{message}</em>)}
          </label>
        </section>
      ) : null}
    </div>
    </LocalizedContent>
  )
}
