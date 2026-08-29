import { useRef, useState } from 'react'
import { useMutation } from '@tanstack/react-query'
import { useNavigate } from 'react-router-dom'
import {
  createServiceRequest,
  validateCatalogForm,
  type CatalogFormVersion,
  type CatalogItem,
} from '../api/client'
import CatalogFormFields from './CatalogFormFields'
import LocalizedContent from '../experience/LocalizedContent'
import { useTenantExperience } from '../experience/TenantExperienceContext'

type Props = {
  accessToken: string
  item: CatalogItem
  form: CatalogFormVersion
}

export default function CatalogRequestForm({ accessToken, item, form }: Props) {
  const navigate = useNavigate()
  const { t } = useTenantExperience()
  const [values, setValues] = useState<Record<string, unknown>>({})
  const [files, setFiles] = useState<File[]>([])
  const [errors, setErrors] = useState<Record<string, string[]>>({})
  const idempotencyKey = useRef<string | null>(null)

  const submissionMutation = useMutation({
    mutationFn: async () => {
      const attachments = files.map((file) => ({
        name: file.name,
        size_bytes: file.size,
        content_type: file.type || undefined,
      }))
      const validation = await validateCatalogForm(accessToken, item.id, {
        values,
        attachments,
      })
      setErrors(validation.errors)
      if (!validation.valid) return null
      idempotencyKey.current ??= crypto.randomUUID()
      return createServiceRequest(accessToken, {
        catalog_item_id: item.id,
        form_version: validation.form_version,
        schema_hash: validation.schema_hash,
        values: validation.normalized_values,
        attachments,
        idempotency_key: idempotencyKey.current,
        title: item.name,
        description: item.short_description,
        approval_mode: 'SEQUENTIAL',
      })
    },
    onSuccess: (serviceRequest) => {
      if (!serviceRequest) return
      idempotencyKey.current = null
      navigate(`/requests?request_id=${encodeURIComponent(serviceRequest.id)}`)
    },
    onError: (error) => {
      setErrors({
        _form: [
          error instanceof Error
            ? error.message
            : t('catalog.form.validationFailed'),
        ],
      })
    },
  })

  return (
    <LocalizedContent>
    <section className="catalog-order-workflow">
      <CatalogFormFields
        schema={form.schema}
        attachmentRules={form.attachment_rules}
        values={values}
        errors={errors}
        disabled={submissionMutation.isPending}
        onChange={(key, value) => {
          setValues((current) => ({ ...current, [key]: value }))
          setErrors((current) => {
            const next = { ...current }
            delete next[key]
            return next
          })
        }}
        onAttachmentsChange={setFiles}
      />
      {errors._form?.map((message) => (
        <p key={message} className="catalog-runtime-error">{message}</p>
      ))}
      {form.attachment_rules.enabled ? (
        <p className="catalog-attachment-note">
          Сейчас проверяются имена, формат и размер. Сами файлы добавьте в карточке заявки
          после её создания — защищённое хранилище вложений будет подключено отдельным этапом.
        </p>
      ) : null}
      <button
        type="button"
        className="catalog-order-submit"
        disabled={submissionMutation.isPending}
        onClick={() => submissionMutation.mutate()}
      >
        {submissionMutation.isPending ? 'Создаём управляемый запрос…' : 'Отправить запрос на услугу'}
      </button>
      <small className="catalog-form-integrity">{t('catalog.form.integrity', {
        version: form.version,
        hash: form.schema_hash.slice(0, 12),
      })}</small>
    </section>
    </LocalizedContent>
  )
}
