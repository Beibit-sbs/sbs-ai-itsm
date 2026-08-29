import { useEffect, useMemo, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import {
  createCMDBImpactAssessment,
  fetchLatestCMDBImpactAssessment,
  previewCMDBImpact,
  type CMDBImpactAnalysis,
  type CMDBImpactDirection,
  type CMDBImpactEntityType,
} from '../api/client'
import LocalizedContent from '../experience/LocalizedContent'
import { useTenantExperience } from '../experience/TenantExperienceContext'


type CMDBImpactPanelProps = {
  accessToken: string
  tenantId?: string | null
  rootCiIds: string[]
  entityType?: CMDBImpactEntityType
  entityId?: string
  entityVersion?: number | null
  title?: string
  compact?: boolean
}

const severityLabels: Record<string, string> = {
  LOW: 'Низкое',
  MEDIUM: 'Среднее',
  HIGH: 'Высокое',
  CRITICAL: 'Критическое',
}

const reasonLabels: Record<string, string> = {
  business_service_impact: 'Затронут бизнес-сервис',
  critical_ci_impact: 'Затронут критичный CI',
  multiple_critical_cis: 'Несколько критичных CI',
  large_production_blast_radius: 'Большой production blast radius',
  change_window_collision: 'Конфликт окна изменений',
  limited_ci_scope: 'Ограниченная область влияния',
}

function formatDate(value: string | null | undefined, locale: string) {
  if (!value) return '—'
  return new Intl.DateTimeFormat(locale, {
    dateStyle: 'medium',
    timeStyle: 'short',
  }).format(new Date(value))
}

export default function CMDBImpactPanel({
  accessToken,
  tenantId,
  rootCiIds,
  entityType,
  entityId,
  entityVersion,
  title = 'Анализ влияния CMDB',
  compact = false,
}: CMDBImpactPanelProps) {
  const queryClient = useQueryClient()
  const { uiLocale: locale } = useTenantExperience()
  const [direction, setDirection] = useState<CMDBImpactDirection>('UPSTREAM')
  const [maxDepth, setMaxDepth] = useState(5)
  const [preview, setPreview] = useState<CMDBImpactAnalysis | null>(null)
  const latestQueryKey = ['cmdb-impact-latest', accessToken, entityType, entityId, entityVersion]
  const latestQuery = useQuery({
    queryKey: latestQueryKey,
    queryFn: () => fetchLatestCMDBImpactAssessment(
      accessToken,
      entityType ?? 'TICKET',
      entityId ?? '',
    ),
    enabled: Boolean(accessToken && entityType && entityId),
    retry: false,
  })
  const mutation = useMutation({
    mutationFn: async () => {
      if (entityType && entityId) {
        return createCMDBImpactAssessment(accessToken, entityType, entityId, {
          tenant_id: tenantId ?? undefined,
          root_ci_ids: rootCiIds,
          direction,
          max_depth: maxDepth,
          expected_entity_version: entityVersion ?? undefined,
        })
      }
      return previewCMDBImpact(accessToken, {
        tenant_id: tenantId ?? undefined,
        root_ci_ids: rootCiIds,
        direction,
        max_depth: maxDepth,
      })
    },
    onSuccess: async (result) => {
      if ('snapshot' in result) {
        setPreview(null)
        queryClient.setQueryData(latestQueryKey, result)
        await queryClient.invalidateQueries({ queryKey: latestQueryKey })
      } else {
        setPreview(result)
      }
    },
  })

  const assessment = latestQuery.data
  const result = preview ?? assessment?.snapshot ?? null
  const roots = useMemo(
    () => Array.from(new Set(rootCiIds.filter(Boolean))),
    [rootCiIds],
  )
  const rootKey = roots.join('|')
  const unavailable = roots.length === 0 && !(entityType && entityId)

  useEffect(() => {
    setPreview(null)
  }, [entityId, rootKey])

  return (
    <LocalizedContent>
    <section className={`cmdb-impact-panel ${compact ? 'compact' : ''}`}>
      <div className="cmdb-impact-head">
        <div>
          <p className="eyebrow">DEPENDENCY INTELLIGENCE</p>
          <h3>{title}</h3>
          <p className="section-subtitle">
            Расчёт затронутых сервисов, критичных CI и конфликтов изменений по графу зависимостей.
          </p>
        </div>
        {result ? (
          <span className={`impact-severity impact-${result.severity.toLowerCase()}`}>
            {severityLabels[result.severity] ?? result.severity}
          </span>
        ) : null}
      </div>

      {assessment?.is_stale ? (
        <div className="impact-warning">
          Оценка устарела:
          {assessment.graph_is_stale ? ' граф CMDB изменился.' : ''}
          {assessment.entity_is_stale ? ' Карточка процесса была обновлена.' : ''}
          {!assessment.integrity_valid ? ' Нарушена целостность снимка.' : ''}
        </div>
      ) : null}

      <div className="cmdb-impact-controls">
        <label>
          Направление
          <select value={direction} onChange={(event) => setDirection(event.target.value as CMDBImpactDirection)}>
            <option value="UPSTREAM">К потребителям / сервисам</option>
            <option value="DOWNSTREAM">К зависимостям</option>
            <option value="BOTH">Оба направления</option>
          </select>
        </label>
        <label>
          Глубина
          <select value={maxDepth} onChange={(event) => setMaxDepth(Number(event.target.value))}>
            {[2, 3, 4, 5, 7, 10, 12].map((depth) => <option value={depth} key={depth}>{depth}</option>)}
          </select>
        </label>
        <button
          type="button"
          disabled={unavailable || mutation.isPending}
          onClick={() => mutation.mutate()}
        >
          {mutation.isPending
            ? 'Расчёт…'
            : entityType
              ? assessment
                ? 'Пересчитать и сохранить'
                : 'Рассчитать и сохранить'
              : 'Рассчитать blast radius'}
        </button>
      </div>

      {unavailable ? (
        <p className="impact-empty">Сначала привяжите к карточке хотя бы один CI.</p>
      ) : null}
      {latestQuery.isPending && !result ? <p className="loading-state">Проверяем последнюю оценку…</p> : null}
      {latestQuery.isError ? <p className="error-message">Не удалось загрузить сохранённую оценку.</p> : null}
      {mutation.isError ? (
        <p className="error-message">
          {mutation.error instanceof Error ? mutation.error.message : 'Не удалось выполнить анализ влияния.'}
        </p>
      ) : null}

      {result ? (
        <>
          <div className="impact-metrics">
            <div><span>CI в радиусе</span><strong>{result.impacted_ci_count}</strong></div>
            <div><span>Сервисы</span><strong>{result.impacted_service_count}</strong></div>
            <div><span>Критичные CI</span><strong>{result.critical_ci_count}</strong></div>
            <div><span>Production CI</span><strong>{result.production_ci_count}</strong></div>
            <div><span>Конфликты RFC</span><strong>{result.collision_count}</strong></div>
          </div>
          <div className="impact-reasons">
            {result.customer_impact ? <span className="impact-chip customer">Возможное влияние на пользователей</span> : null}
            {result.severity_reasons.map((reason) => (
              <span className="impact-chip" key={reason}>{reasonLabels[reason] ?? reason}</span>
            ))}
            {result.truncated ? <span className="impact-chip warning">Результат ограничен лимитом</span> : null}
          </div>

          <div className="impact-columns">
            <div>
              <h4>Затронутые сервисы</h4>
              {!result.services.length ? <p className="muted">Сервисы в выбранном направлении не найдены.</p> : null}
              {result.services.map((node) => (
                <article className="impact-node" key={node.id}>
                  <div><strong>{node.name}</strong><span>{node.asset_tag} · глубина {node.depth}</span></div>
                  <span className={`impact-criticality criticality-${node.criticality.toLowerCase()}`}>{node.criticality}</span>
                </article>
              ))}
            </div>
            <div>
              <h4>Критичные CI</h4>
              {!result.critical_cis.length ? <p className="muted">Критичные CI не обнаружены.</p> : null}
              {result.critical_cis.map((node) => (
                <article className="impact-node" key={node.id}>
                  <div><strong>{node.name}</strong><span>{node.asset_tag} · {node.ci_class_name ?? 'CI'}</span></div>
                  <span>{node.environment}</span>
                </article>
              ))}
            </div>
          </div>

          {result.collisions.length ? (
            <div className="impact-collisions">
              <h4>Конфликты изменений</h4>
              {result.collisions.map((collision) => (
                <article key={collision.change_id}>
                  <div>
                    <strong>{collision.change_number} · {collision.title}</strong>
                    <span>
                      {collision.window_overlap ? 'Пересечение окна' : 'Общая область влияния'}
                      {' · '}{collision.shared_asset_tags.join(', ')}
                    </span>
                  </div>
                  <span>{collision.risk_level}</span>
                </article>
              ))}
            </div>
          ) : null}

          <footer className="impact-meta">
            <span>Граф: {result.graph_hash.slice(0, 12)}</span>
            <span>Рассчитано: {formatDate(result.computed_at, locale)}</span>
            {assessment ? <span>Снимок: {assessment.snapshot_hash.slice(0, 12)} · {assessment.integrity_valid ? 'целостность подтверждена' : 'ошибка целостности'}</span> : null}
          </footer>
        </>
      ) : (
        !unavailable && !latestQuery.isPending
          ? <p className="impact-empty">Оценка ещё не выполнялась.</p>
          : null
      )}
    </section>
    </LocalizedContent>
  )
}
