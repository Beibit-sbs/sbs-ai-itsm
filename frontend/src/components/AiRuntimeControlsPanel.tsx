import { useEffect, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import {
  fetchAiRuntimeDashboard,
  resetAiProviderCircuit,
  updateAiDataPolicy,
  updateAiUsageBudget,
} from '../api/client'
import { useAuth } from '../auth/AuthContext'
import QueryFailureNotice from './QueryFailureNotice'
import LocalizedContent from '../experience/LocalizedContent'
import { useTenantExperience } from '../experience/TenantExperienceContext'

function errorText(error: unknown) {
  return error instanceof Error ? error.message : 'Неизвестная ошибка'
}

export default function AiRuntimeControlsPanel() {
  const { session } = useAuth()
  const { formatDateTime, translate } = useTenantExperience()
  const client = useQueryClient()
  const token = session?.access_token ?? ''
  const permissions = new Set(session?.user.permissions ?? [])
  const isRoot = session?.user.role === 'saas_root'
  const canRead = isRoot || permissions.has('ai.runtime.read')
  const canManage = isRoot || permissions.has('ai.runtime.manage')
  const [tenantId, setTenantId] = useState(session?.user.tenant_id ?? '')
  const scope = isRoot ? tenantId.trim() : session?.user.tenant_id
  const [externalEnabled, setExternalEnabled] = useState(false)
  const [openaiAllowed, setOpenaiAllowed] = useState(false)
  const [geminiAllowed, setGeminiAllowed] = useState(false)
  const [openaiRegion, setOpenaiRegion] = useState('global')
  const [geminiRegion, setGeminiRegion] = useState('global')
  const [maximumClass, setMaximumClass] = useState<'PUBLIC' | 'INTERNAL' | 'CONFIDENTIAL' | 'RESTRICTED'>('INTERNAL')
  const [monthlyRequests, setMonthlyRequests] = useState(10000)
  const [dailyRequests, setDailyRequests] = useState(1000)
  const [monthlyCost, setMonthlyCost] = useState(100)
  const [notice, setNotice] = useState('')

  const dashboard = useQuery({
    queryKey: ['ai-runtime-dashboard', token, scope],
    queryFn: () => fetchAiRuntimeDashboard(token, scope),
    enabled: Boolean(token && canRead && scope),
    refetchInterval: 30_000,
  })

  useEffect(() => {
    const data = dashboard.data
    if (!data) return
    setExternalEnabled(data.external_processing_enabled)
    setOpenaiAllowed(data.allowed_providers.includes('openai'))
    setGeminiAllowed(data.allowed_providers.includes('gemini'))
    setOpenaiRegion(data.provider_regions.openai ?? 'global')
    setGeminiRegion(data.provider_regions.gemini ?? 'global')
    setMaximumClass(data.maximum_external_classification)
    if (data.budget) {
      setMonthlyRequests(data.budget.monthly_request_limit)
      setDailyRequests(data.budget.daily_request_limit)
      setMonthlyCost(data.budget.monthly_cost_limit_usd)
    }
  }, [dashboard.data])

  const policyMutation = useMutation({
    mutationFn: () => {
      const allowedProviders: Array<'openai' | 'gemini'> = []
      const regions: Record<string, string> = {}
      if (openaiAllowed) {
        allowedProviders.push('openai')
        regions.openai = openaiRegion
      }
      if (geminiAllowed) {
        allowedProviders.push('gemini')
        regions.gemini = geminiRegion
      }
      return updateAiDataPolicy(token, {
        tenant_id: isRoot ? scope : undefined,
        expected_revision: dashboard.data?.data_policy?.revision ?? 0,
        external_processing_enabled: externalEnabled,
        allowed_providers: allowedProviders,
        provider_regions: regions,
        maximum_external_classification: maximumClass,
        pii_redaction_required: true,
        allow_reversible_redaction: true,
        retention_days: 180,
      })
    },
    onSuccess: async () => {
      setNotice('Data/residency policy сохранена и применяется до provider call.')
      await client.invalidateQueries({ queryKey: ['ai-runtime-dashboard'] })
    },
  })
  const budgetMutation = useMutation({
    mutationFn: () => updateAiUsageBudget(token, {
      tenant_id: isRoot ? scope : undefined,
      expected_revision: dashboard.data?.budget?.revision ?? 0,
      monthly_request_limit: monthlyRequests,
      monthly_cost_limit_usd: monthlyCost,
      daily_request_limit: dailyRequests,
      warning_percent: 80,
      hard_limit_enabled: true,
    }),
    onSuccess: async () => {
      setNotice('Hard budget сохранён.')
      await client.invalidateQueries({ queryKey: ['ai-runtime-dashboard'] })
    },
  })
  const resetMutation = useMutation({
    mutationFn: (provider: 'openai' | 'gemini') =>
      resetAiProviderCircuit(token, provider, 'Operator verified provider recovery', isRoot ? scope : undefined),
    onSuccess: async () => {
      setNotice('Circuit закрыт оператором; событие записано в audit.')
      await client.invalidateQueries({ queryKey: ['ai-runtime-dashboard'] })
    },
  })

  if (!canRead) return null
  const data = dashboard.data
  const requestUsage = data?.budget?.monthly_request_limit
    ? Math.min(100, Math.round((data.usage.monthly_requests / data.budget.monthly_request_limit) * 100))
    : 0
  const costUsage = data?.budget?.monthly_cost_limit_usd
    ? Math.min(100, Math.round((data.usage.monthly_cost_usd / data.budget.monthly_cost_limit_usd) * 100))
    : 0
  const error = policyMutation.error ?? budgetMutation.error ?? resetMutation.error

  return (
    <LocalizedContent>
    <section className="ai-runtime-controls">
      <QueryFailureNotice
        title="Данные AI Privacy & FinOps недоступны."
        sources={[
          { label: 'runtime dashboard', query: dashboard },
        ]}
      />
      <div className="rag-assistant-heading">
        <div>
          <p className="eyebrow">AI PRIVACY & FINOPS</p>
          <h2>Data residency, budgets и circuit breaker</h2>
          <p>Fail-closed policy выполняется до внешнего запроса. Запрещённые данные, provider, region, превышенный бюджет или открытый circuit автоматически переводят запрос на локальный безопасный fallback.</p>
        </div>
        <div className="rag-privacy-badges"><span>Fail closed</span><span>Hash-only ledger</span><span>Hard budget</span><span>Local fallback</span></div>
      </div>
      {isRoot ? <label className="inline-field"><span>Tenant ID</span><input value={tenantId} onChange={(event) => setTenantId(event.target.value)} placeholder="UUID организации" /></label> : null}
      <div className="ai-runtime-grid">
        <article className="copilot-panel">
          <p className="eyebrow">DATA & RESIDENCY POLICY</p>
          <label className="checkbox-row"><input type="checkbox" checked={externalEnabled} onChange={(event) => setExternalEnabled(event.target.checked)} /><span>Разрешить внешнюю обработку</span></label>
          <div className="provider-policy-row">
            <label className="checkbox-row"><input type="checkbox" checked={openaiAllowed} onChange={(event) => setOpenaiAllowed(event.target.checked)} /><span>OpenAI</span></label>
            <input value={openaiRegion} onChange={(event) => setOpenaiRegion(event.target.value)} placeholder="region / residency label" disabled={!openaiAllowed} />
          </div>
          <div className="provider-policy-row">
            <label className="checkbox-row"><input type="checkbox" checked={geminiAllowed} onChange={(event) => setGeminiAllowed(event.target.checked)} /><span>Gemini</span></label>
            <input value={geminiRegion} onChange={(event) => setGeminiRegion(event.target.value)} placeholder="region / residency label" disabled={!geminiAllowed} />
          </div>
          <label className="inline-field"><span>Максимальный класс для external provider</span><select value={maximumClass} onChange={(event) => setMaximumClass(event.target.value as typeof maximumClass)}><option value="PUBLIC">Public</option><option value="INTERNAL">Internal</option><option value="CONFIDENTIAL">Confidential (PII redacted)</option><option value="RESTRICTED">Restricted</option></select></label>
          <p className="rag-filter-note">PII redaction всегда включена. Без сохранённой policy внешние provider-вызовы запрещены.</p>
          {canManage ? <button type="button" onClick={() => policyMutation.mutate()} disabled={!scope || policyMutation.isPending}>Сохранить data policy</button> : null}
        </article>
        <article className="copilot-panel">
          <p className="eyebrow">TENANT BUDGET</p>
          <div className="form-grid">
            <label><span>Monthly requests</span><input type="number" min={0} value={monthlyRequests} onChange={(event) => setMonthlyRequests(Number(event.target.value))} /></label>
            <label><span>Daily requests</span><input type="number" min={0} value={dailyRequests} onChange={(event) => setDailyRequests(Number(event.target.value))} /></label>
            <label><span>Monthly USD</span><input type="number" min={0} step="0.01" value={monthlyCost} onChange={(event) => setMonthlyCost(Number(event.target.value))} /></label>
          </div>
          <div className="budget-meter"><div><span>Requests</span><strong>{data?.usage.monthly_requests ?? 0} / {data?.budget?.monthly_request_limit ?? '—'}</strong></div><progress max={100} value={requestUsage} /></div>
          <div className="budget-meter"><div><span>Estimated cost</span><strong>${(data?.usage.monthly_cost_usd ?? 0).toFixed(4)} / ${data?.budget?.monthly_cost_limit_usd ?? '—'}</strong></div><progress max={100} value={costUsage} /></div>
          {canManage ? <button type="button" onClick={() => budgetMutation.mutate()} disabled={!scope || budgetMutation.isPending}>Сохранить hard budget</button> : null}
        </article>
      </div>
      <div className="circuit-grid">
        {data?.circuits.length ? data.circuits.map((circuit) => (
          <article className="result-card" key={circuit.provider}>
            <span>{translate(circuit.provider)} {translate('circuit')}</span>
            <strong>{translate(circuit.state)} {translate('· failures')} {circuit.consecutive_failures}/{circuit.failure_threshold}</strong>
            <small>{circuit.last_failure_code ?? 'Ошибок нет'}{circuit.open_until ? ` ${translate('· retry')} ${formatDateTime(circuit.open_until)}` : ''}</small>
            {canManage && circuit.state !== 'CLOSED' ? <button type="button" className="ghost-button" onClick={() => resetMutation.mutate(circuit.provider as 'openai' | 'gemini')}>Проверено — reset</button> : null}
          </article>
        )) : <p className="empty-state">Circuit создаётся при первом внешнем provider-вызове.</p>}
      </div>
      {notice ? <p className="loading-state">{notice}</p> : null}
      {error ? <p className="error-message">{errorText(error)}</p> : null}
    </section>
    </LocalizedContent>
  )
}
