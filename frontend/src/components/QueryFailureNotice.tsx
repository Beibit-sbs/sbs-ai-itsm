import { useTenantExperience } from '../experience/TenantExperienceContext'

type QueryLike = {
  isError: boolean
  refetch: () => unknown
}

export type QueryFailureSource = {
  label: string
  query: QueryLike
}

type QueryFailureNoticeProps = {
  sources: QueryFailureSource[]
  title?: string
}

export default function QueryFailureNotice({
  sources,
  title = 'Часть данных временно недоступна.',
}: QueryFailureNoticeProps) {
  const { t, translate } = useTenantExperience()
  const failed = sources.filter(({ query }) => query.isError)
  const areaMatch = title.match(/^Часть данных (.+) недоступна\.$/)
  const renderedTitle = title === 'Часть данных временно недоступна.'
    ? t('failure.defaultTitle')
    : areaMatch
      ? t('failure.partial', { area: areaMatch[1] })
      : translate(title)

  if (failed.length === 0) return null

  return (
    <div className="state-panel state-panel-error" role="alert">
      <strong>{renderedTitle}</strong>
      <p>
        {t('failure.detail', {
          sources: failed.map(({ label }) => translate(label)).join(', '),
        })}
      </p>
      <button
        type="button"
        className="ghost-button"
        onClick={() => failed.forEach(({ query }) => void query.refetch())}
      >
        {t('failure.retry')}
      </button>
    </div>
  )
}
