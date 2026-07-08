import { useQuery } from '@tanstack/react-query'
import { getHealth } from '../api/client'

export default function HealthBadge() {
  const query = useQuery({
    queryKey: ['health'],
    queryFn: ({ signal }) => getHealth(signal),
    refetchInterval: 30_000,
  })

  if (query.isPending) return <span className="health health-pending">Проверка API…</span>
  if (query.isError) return <span className="health health-error">Backend недоступен</span>
  return <span className="health health-ok">API работает · v{query.data.version}</span>
}
