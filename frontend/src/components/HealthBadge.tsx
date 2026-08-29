import { useQuery } from '@tanstack/react-query'
import { getHealth } from '../api/client'
import { useTenantExperience } from '../experience/TenantExperienceContext'

export default function HealthBadge() {
  const { t } = useTenantExperience()
  const query = useQuery({
    queryKey: ['health'],
    queryFn: ({ signal }) => getHealth(signal),
    refetchInterval: 30_000,
  })

  if (query.isPending) return <span className="health health-pending">{t('health.checking')}</span>
  if (query.isError) return <span className="health health-error">{t('health.unavailable')}</span>
  return <span className="health health-ok">{t('health.ok', { version: query.data.version })}</span>
}
