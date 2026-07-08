export const API_BASE_URL =
  import.meta.env.VITE_API_BASE_URL ?? 'http://localhost:8000/api/v1'

export type HealthResponse = {
  status: 'ok'
  service: string
  version: string
  environment: string
  timestamp: string
}

export type AuthUser = {
  id: string
  email: string
  full_name: string
  tenant_id: string | null
  role: string
  permissions: string[]
}

export type AuthSession = {
  access_token: string
  refresh_token: string
  token_type: string
  user: AuthUser
}

export type Tenant = {
  id: string
  name: string
  slug: string
  status: string
  description: string | null
}

export type TicketComment = {
  id: string
  author_name: string
  author_role: string
  body: string
  created_at: string
}

export type TicketHistory = {
  id: string
  actor_name: string
  event_type: string
  field_name: string | null
  old_value: string | null
  new_value: string | null
  message: string
  created_at: string
}

export type Ticket = {
  id: string
  ticket_number: string | null
  title: string
  description: string | null
  requester_name: string
  requester_email: string
  department: string
  location: string
  category: string
  category_label: string
  category_color: string
  priority: string
  priority_label: string
  priority_color: string
  status: string
  status_label: string
  status_color: string
  assignee_name: string | null
  asset_id: string | null
  asset_tag: string | null
  asset_name: string | null
  asset_type: string | null
  sla_due_at: string | null
  sla_policy_id: string | null
  response_due_at: string | null
  resolution_due_at: string | null
  sla_status: string | null
  resolved_at: string | null
  created_at: string
  updated_at: string
  response_minutes: number | null
}

export type TicketDetail = Ticket & {
  comments: TicketComment[]
  history_count: number
}

export type PaginatedResponse<T> = {
  items: T[]
  total: number
  page: number
  page_size: number
}

export type TicketQueryParams = {
  q?: string
  status?: string
  priority?: string
  category?: string
  assignee_name?: string
  sort_by?: string
  sort_dir?: 'asc' | 'desc'
  page?: number
  page_size?: number
}

export type CreateTicketRequest = {
  title: string
  description?: string | null
  requester_name: string
  requester_email: string
  department: string
  location: string
  category: string
  priority: string
  assignee_name?: string | null
  asset_id?: string | null
}

export type UpdateTicketRequest = Partial<CreateTicketRequest> & {
  status?: string
  sla_due_at?: string | null
}

export type CreateCommentRequest = {
  body: string
}

export type Asset = {
  id: string
  asset_tag: string
  name: string
  type: string | null
  asset_type: string
  original_type: string | null
  serial_number: string | null
  inventory_number: string | null
  source: string | null
  source_batch_id: string | null
  manufacturer: string | null
  model: string | null
  status: string
  owner_name: string
  assigned_to_name: string | null
  assigned_to_email: string | null
  department: string | null
  location: string
  purchase_date: string | null
  accepted_at: string | null
  purchase_cost: number | null
  current_cost: number | null
  depreciation_amount: number | null
  residual_value: number | null
  purchase_year: number | null
  verification_status: string | null
  imported_at: string | null
  warranty_until: string | null
  condition: string
  description: string | null
  tenant_id: string | null
  tenant_name: string | null
  health: string
}

export type AssetQueryParams = {
  q?: string
  source?: string
  verification_status?: string
  without_location?: boolean
  disposed?: boolean
  assigned_to_name?: string
  purchase_year?: number
  type?: string
  sort_by?: string
  sort_dir?: 'asc' | 'desc'
  page?: number
  page_size?: number
}

export type SlaPolicy = {
  id: string
  name: string
  priority: string
  target_response_minutes: number
  target_resolution_minutes: number
  response_minutes: number | null
  resolution_minutes: number | null
  is_active: boolean | null
  status: string
  breach_count: number
  description: string | null
  tenant_id: string | null
  tenant_name: string | null
}

export type AssetTicket = {
  id: string
  ticket_number: string | null
  title: string
  priority: string
  status: string
  assignee_name: string | null
  sla_status: string | null
  created_at: string
  updated_at: string
}

export type AssetImportBatch = {
  id: string
  tenant_id: string | null
  file_name: string
  original_file_name: string
  status: string
  total_rows: number
  valid_rows: number
  imported_rows: number
  skipped_rows: number
  error_rows: number
  created_by: string | null
  created_at: string
  completed_at: string | null
  summary: Record<string, unknown>
}

export type AssetImportRow = {
  id: string
  row_number: number
  raw: Record<string, unknown>
  normalized: Record<string, unknown>
  status: string
  error_message: string | null
  asset_id: string | null
  created_at: string
}

export type AssetImportSummary = {
  total_batches: number
  preview_ready_batches: number
  committed_batches: number
  total_rows: number
  total_imported_rows: number
  total_error_rows: number
}

export type AssetImportPreviewResult = {
  batch_id: string
  dry_run: boolean
  total_rows: number
  valid_rows: number
  error_rows: number
  duplicate_rows: number
  disposed_rows: number
  in_stock_rows: number
  missing_location_rows: number
  imported_rows?: number
  skipped_rows?: number
}

export type SlaOverview = {
  total_tickets: number
  breached_tickets: number
  warning_tickets: number
  problematic_assets: number
  warranty_expiring: number
}

export type SlaBreach = {
  ticket_id: string
  ticket_number: string | null
  title: string
  priority: string
  status: string
  sla_status: string | null
  response_due_at: string | null
  resolution_due_at: string | null
  tenant_name: string | null
}

export type KnowledgeCategory = {
  id: string
  code: string
  name: string
  description: string | null
  created_at: string
  updated_at: string
}

export type KnowledgeArticle = {
  id: string
  article_number: string
  title: string
  summary: string
  content: string
  category_id: string
  category_name: string | null
  ticket_category: string | null
  asset_type: string | null
  tags: string[]
  status: string
  visibility: string
  author_name: string
  helpful_count: number
  not_helpful_count: number
  created_at: string
  updated_at: string
  published_at: string | null
}

export type CreateKnowledgeArticleRequest = {
  title: string
  summary: string
  content: string
  category_id: string
  ticket_category?: string | null
  asset_type?: string | null
  tags?: string[]
  status?: string
  visibility?: string
}

export type UpdateKnowledgeArticleRequest = Partial<CreateKnowledgeArticleRequest> & {
  published_at?: string | null
}

export type KnowledgeFeedbackRequest = {
  is_helpful: boolean
  comment?: string | null
}

export type KnowledgeFeedback = {
  id: string
  article_id: string
  user_name: string
  is_helpful: boolean
  comment: string | null
  created_at: string
}

export type AiRelatedArticle = {
  id: string
  article_number: string
  title: string
  summary: string
}

export type AiSimilarTicket = {
  id: string
  ticket_number: string | null
  title: string
  status: string
}

export type AiSuggestion = {
  id: string
  ticket_id: string | null
  input_text: string
  recommended_category: string
  recommended_priority: string
  recommended_asset_type: string | null
  recommended_article_id: string | null
  summary: string
  possible_cause: string
  suggested_solution: string
  recommended_assignee: string
  confidence: string
  related_articles: AiRelatedArticle[]
  similar_tickets: AiSimilarTicket[]
  next_actions: string[]
  created_at: string
}

export type AiAnalyzeRequest = {
  input_text: string
  ticket_id?: string | null
}

export type Notification = {
  id: string
  type: string
  title: string
  message: string
  recipient_name: string
  recipient_email: string
  channel: string
  status: string
  related_ticket_id: string | null
  created_at: string
  read_at: string | null
}

export type NotificationTemplate = {
  id: string
  code: string
  name: string
  subject_template: string
  body_template: string
  channel: string
  is_active: boolean
  created_at: string
  updated_at: string
}

export type EmailMessageLog = {
  id: string
  provider: string
  to_email: string
  subject: string
  body: string
  status: string
  error_message: string | null
  related_ticket_id: string | null
  created_at: string
  sent_at: string | null
}

export type TestEmailRequest = {
  to_email: string
  subject: string
  body: string
  related_ticket_id?: string | null
}

export type AdminUser = {
  id: string
  tenant_id: string | null
  email: string
  full_name: string
  position: string | null
  department: string | null
  phone: string | null
  is_active: boolean
  is_superuser: boolean
  last_login_at: string | null
  created_at: string
  updated_at: string
}

export type AdminRole = {
  id: string
  tenant_id: string | null
  code: string
  name: string
  description: string | null
  is_system: boolean
  created_at: string
  updated_at: string
}

export type AdminPermission = {
  id: string
  code: string
  name: string
  description: string | null
  module: string
}

export type AdminAuditLog = {
  id: string
  tenant_id: string | null
  actor_user_id: string | null
  actor_email: string
  action: string
  entity_type: string
  entity_id: string | null
  ip_address: string | null
  user_agent: string | null
  metadata: Record<string, unknown>
  created_at: string
}

export type SystemSetting = {
  id: string
  tenant_id: string | null
  key: string
  value: string | null
  description: string | null
  is_sensitive: boolean
  updated_at: string
}

export type SecurityLoginEvent = {
  id: string
  actor_email: string
  action: string
  ip_address: string | null
  user_agent: string | null
  metadata: Record<string, unknown>
  created_at: string
}

export type SecuritySessionOverview = {
  active_users: number
  logged_in_last_24h: number
  inactive_users: number
  session_timeout_minutes: number
}

export type SecurityRiskSummary = {
  failed_logins_24h: number
  success_logins_24h: number
  active_users: number
  risk_level: string
  recent_security_events: Array<Record<string, unknown>>
}

export type AnalyticsCountItem = {
  count: number
  name?: string
  status?: string
  priority?: string
  category?: string
  type?: string
  topic?: string
}

export type TicketAnalytics = {
  total_tickets: number
  open_tickets: number
  closed_tickets: number
  tickets_today: number
  by_status: AnalyticsCountItem[]
  by_priority: AnalyticsCountItem[]
  by_category: AnalyticsCountItem[]
  average_response_minutes: number | null
  average_resolution_minutes: number | null
  top_requesters: AnalyticsCountItem[]
  top_assignees: AnalyticsCountItem[]
  open_critical_tickets: number
}

export type SlaAnalytics = {
  sla_compliance_percent: number
  response_breaches: number
  resolution_breaches: number
  tickets_at_risk: number
  critical_sla_breaches: number
  violations_by_priority: Array<{ priority: string; count: number }>
}

export type AssetAnalytics = {
  total_assets: number
  assets_by_type: Array<{ type: string; count: number }>
  assets_by_status: Array<{ status: string; count: number }>
  problem_assets: Array<{ asset_tag: string; name: string; status: string }>
  problem_assets_count: number
  top_assets_by_ticket_count: Array<{ asset_tag: string; name: string; count: number }>
  warranty_expiring_soon: Array<{ asset_tag: string; name: string; warranty_until: string | null }>
  unassigned_assets: Array<{ asset_tag: string; name: string }>
  unassigned_assets_count: number
  imported_assets_count: number
  assets_missing_location_count: number
  disposed_assets_count: number
  assets_by_source: Array<{ source: string; count: number }>
  assets_by_purchase_year: Array<{ year: string; count: number }>
  top_responsible_persons: Array<{ name: string; count: number }>
  duplicate_inventory_numbers: Array<{ inventory_number: string; count: number }>
}

export type AiAnalytics = {
  total_ai_analyses: number
  average_confidence_percent: number
  recommendations_by_category: Array<{ category: string; count: number }>
  recommendations_by_priority: Array<{ priority: string; count: number }>
  ai_suggestions_applied_demo: number
  frequent_request_topics: Array<{ topic: string; count: number }>
}

export type KnowledgeAnalytics = {
  total_articles: number
  published_articles: number
  top_helpful_articles: Array<{ article_number: string; title: string; helpful_count: number }>
  articles_with_negative_feedback: Array<{ article_number: string; title: string; not_helpful_count: number }>
  categories_without_articles: Array<{ code: string; name: string }>
  tickets_resolved_via_knowledge_demo: number
}

export type NotificationAnalytics = {
  total_notifications: number
  unread_notifications: number
  email_log_count: number
  mock_email_success: number
  mock_email_failed: number
  events_by_type: Array<{ type: string; count: number }>
}

export type SecurityAnalytics = {
  login_success: number
  login_failed: number
  audit_events_count: number
  admin_changes_today: number
  risk_summary: SecurityRiskSummary
  sensitive_settings_count: number
}

export type IntegrationAnalytics = {
  total_systems: number
  enabled_systems: number
  systems_by_status: Array<{ status: string; count: number }>
  systems_with_errors: number
  last_health_check: string | null
  active_import_jobs: number
  integration_events_count: number
  failed_integration_events: number
  import_success_rate: number
  integrations_health_score: number
  recent_integration_events: Array<{ id: string; event_type: string; status: string; correlation_id: string | null; created_at: string }>
}

export type AutomationRule = {
  id: string
  tenant_id: string | null
  code: string
  name: string
  description: string | null
  trigger_type: string
  conditions_json: Record<string, unknown> | Array<unknown>
  actions_json: Array<Record<string, unknown>>
  is_active: boolean
  priority: number
  created_at: string
  updated_at: string
}

export type AutomationRun = {
  id: string
  tenant_id: string | null
  rule_id: string
  trigger_type: string
  trigger_entity_type: string | null
  trigger_entity_id: string | null
  status: string
  started_at: string | null
  finished_at: string | null
  result_summary: Record<string, unknown>
  error_message: string | null
  created_at: string
}

export type AutomationActionLog = {
  id: string
  tenant_id: string | null
  automation_run_id: string
  action_type: string
  status: string
  input_json: Record<string, unknown>
  output_json: Record<string, unknown>
  error_message: string | null
  created_at: string
}

export type Runbook = {
  id: string
  tenant_id: string | null
  code: string
  title: string
  description: string | null
  category: string
  severity: string
  steps_json: Array<Record<string, unknown>>
  estimated_minutes: number
  is_active: boolean
  created_at: string
  updated_at: string
}

export type RunbookExecution = {
  id: string
  tenant_id: string | null
  runbook_id: string
  ticket_id: string | null
  status: string
  current_step: number
  started_by: string | null
  started_at: string | null
  completed_at: string | null
  result_summary: string | null
  created_at: string
}

export type ApprovalRequest = {
  id: string
  tenant_id: string | null
  title: string
  description: string | null
  entity_type: string
  entity_id: string | null
  requested_by: string
  approver_name: string | null
  status: string
  decision_comment: string | null
  created_at: string
  decided_at: string | null
}

export type TicketAutomationSuggestion = {
  ticket_id: string
  suggested_runbooks: Array<{ id: string; code: string; title: string; category: string; severity: string; estimated_minutes: number }>
  matched_rules: Array<{ rule_id: string; rule_code: string; rule_name: string; trigger_type: string; matched: boolean; planned_actions: Array<Record<string, unknown>>; mode: string }>
}

export type AutomationOverview = {
  active_rules: number
  runs_today: number
  failed_runs: number
  pending_approvals: number
  runbooks_available: number
  automation_success_rate: number
  automation_runs_count: number
  runbook_execution_count: number
  last_actions: Array<{ id: string; action_type: string; status: string; created_at: string; error_message: string | null }>
  top_triggered_rules: Array<{ rule_id: string; rule_name: string; count: number }>
  triggers: Array<{ trigger_type: string; count: number }>
}

export type ExecutiveSummary = {
  health_score: number
  it_workload_score: number
  sla_risk_score: number
  asset_risk_score: number
  security_risk_score: number
  ai_maturity_score: number
  integrations_health_score: number
  workflow_automation_score: number
  top_5_problems: Array<{ title: string; value: number }>
  top_5_recommendations: string[]
}

export type AnalyticsOverview = {
  tickets: TicketAnalytics
  sla: SlaAnalytics
  assets: AssetAnalytics
  ai: AiAnalytics
  knowledge: KnowledgeAnalytics
  notifications: NotificationAnalytics
  security: SecurityAnalytics
  integrations: IntegrationAnalytics
  automation: AutomationOverview
  executive_summary: ExecutiveSummary
}

export type IntegrationSystem = {
  id: string
  tenant_id: string | null
  code: string
  name: string
  system_type: string
  base_url: string | null
  status: string
  is_enabled: boolean
  last_health_status: string | null
  last_health_checked_at: string | null
  description: string | null
  created_at: string
  updated_at: string
  capabilities: string[]
}

export type IntegrationProvider = {
  code: string
  name: string
  status: string
  capabilities: string[]
}

export type IntegrationEvent = {
  id: string
  tenant_id: string | null
  external_system_id: string | null
  direction: string
  event_type: string
  status: string
  request_summary: Record<string, unknown>
  response_summary: Record<string, unknown>
  error_message: string | null
  correlation_id: string | null
  created_at: string
}

export type IntegrationImportJob = {
  id: string
  tenant_id: string | null
  external_system_id: string | null
  job_type: string
  status: string
  records_total: number
  records_success: number
  records_failed: number
  started_at: string | null
  finished_at: string | null
  error_message: string | null
  created_at: string
}

export type IntegrationWebhook = {
  id: string
  tenant_id: string | null
  name: string
  path: string
  target_system: string
  is_active: boolean
  secret_ref: string | null
  created_at: string
  updated_at: string
}

export type IntegrationMapping = {
  id: string
  tenant_id: string | null
  external_system_id: string | null
  source_entity: string
  target_entity: string
  mapping_json: Record<string, unknown>
  is_active: boolean
  created_at: string
  updated_at: string
}

export type SavedReport = {
  id: string
  tenant_id: string | null
  name: string
  report_type: string
  filters_json: Record<string, unknown>
  created_by: string
  created_at: string
  updated_at: string
}

export type ReportSnapshot = {
  id: string
  tenant_id: string | null
  report_type: string
  period_from: string | null
  period_to: string | null
  payload_json: Record<string, unknown>
  created_at: string
  created_by: string
}

export type DemoExport = {
  report_type: string
  format: string
  generated_at: string
  headers: string[]
  rows: Array<Record<string, unknown>>
  payload: Record<string, unknown>
}

type LoginRequest = {
  email: string
  password: string
}

type RefreshRequest = {
  refresh_token: string
}

export async function getHealth(signal?: AbortSignal): Promise<HealthResponse> {
  const response = await fetch(`${API_BASE_URL}/health`, { signal })
  if (!response.ok) throw new Error(`Backend returned ${response.status}`)
  return response.json() as Promise<HealthResponse>
}

async function readJsonResponse<T>(response: Response): Promise<T> {
  if (!response.ok) {
    const errorPayload = (await response.json().catch(() => null)) as { error?: { message?: string } } | null
    throw new Error(errorPayload?.error?.message ?? `Backend returned ${response.status}`)
  }

  return response.json() as Promise<T>
}

export async function loginWithPassword(request: LoginRequest): Promise<AuthSession> {
  const response = await fetch(`${API_BASE_URL}/auth/login`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(request),
  })

  return readJsonResponse<AuthSession>(response)
}

export async function refreshAuthSession(request: RefreshRequest): Promise<AuthSession> {
  const response = await fetch(`${API_BASE_URL}/auth/refresh`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(request),
  })

  return readJsonResponse<AuthSession>(response)
}

export async function fetchCurrentUser(accessToken: string): Promise<AuthUser> {
  const response = await fetch(`${API_BASE_URL}/auth/me`, {
    headers: { Authorization: `Bearer ${accessToken}` },
  })

  return readJsonResponse<AuthUser>(response)
}

export async function fetchTenants(accessToken: string): Promise<Tenant[]> {
  const response = await fetch(`${API_BASE_URL}/tenants`, {
    headers: { Authorization: `Bearer ${accessToken}` },
  })

  return readJsonResponse<Tenant[]>(response)
}

export async function fetchCurrentTenant(accessToken: string): Promise<Tenant | null> {
  const tenants = await fetchTenants(accessToken)
  return tenants[0] ?? null
}

export async function fetchTicketsPage(accessToken: string, params?: TicketQueryParams): Promise<PaginatedResponse<Ticket>> {
  const search = new URLSearchParams()
  if (params?.q) search.set('q', params.q)
  if (params?.status && params.status !== 'ALL') search.set('status', params.status)
  if (params?.priority && params.priority !== 'ALL') search.set('priority', params.priority)
  if (params?.category && params.category !== 'ALL') search.set('category', params.category)
  if (params?.assignee_name && params.assignee_name !== 'ALL') search.set('assignee_name', params.assignee_name)
  if (params?.sort_by) search.set('sort_by', params.sort_by)
  if (params?.sort_dir) search.set('sort_dir', params.sort_dir)
  if (typeof params?.page === 'number') search.set('page', String(params.page))
  if (typeof params?.page_size === 'number') search.set('page_size', String(params.page_size))

  const query = search.toString()
  const response = await fetch(`${API_BASE_URL}/tickets${query ? `?${query}` : ''}`, {
    headers: { Authorization: `Bearer ${accessToken}` },
  })

  return readJsonResponse<PaginatedResponse<Ticket>>(response)
}

export async function fetchTickets(accessToken: string): Promise<Ticket[]> {
  const page = await fetchTicketsPage(accessToken, { page: 1, page_size: 500 })
  return page.items
}

export async function fetchTicket(accessToken: string, ticketId: string): Promise<TicketDetail> {
  const response = await fetch(`${API_BASE_URL}/tickets/${ticketId}`, {
    headers: { Authorization: `Bearer ${accessToken}` },
  })

  return readJsonResponse<TicketDetail>(response)
}

export async function createTicket(accessToken: string, request: CreateTicketRequest): Promise<TicketDetail> {
  const response = await fetch(`${API_BASE_URL}/tickets`, {
    method: 'POST',
    headers: {
      Authorization: `Bearer ${accessToken}`,
      'Content-Type': 'application/json',
    },
    body: JSON.stringify(request),
  })

  return readJsonResponse<TicketDetail>(response)
}

export async function patchTicket(accessToken: string, ticketId: string, request: UpdateTicketRequest): Promise<TicketDetail> {
  const response = await fetch(`${API_BASE_URL}/tickets/${ticketId}`, {
    method: 'PATCH',
    headers: {
      Authorization: `Bearer ${accessToken}`,
      'Content-Type': 'application/json',
    },
    body: JSON.stringify(request),
  })

  return readJsonResponse<TicketDetail>(response)
}

export async function addTicketComment(accessToken: string, ticketId: string, request: CreateCommentRequest): Promise<TicketComment> {
  const response = await fetch(`${API_BASE_URL}/tickets/${ticketId}/comments`, {
    method: 'POST',
    headers: {
      Authorization: `Bearer ${accessToken}`,
      'Content-Type': 'application/json',
    },
    body: JSON.stringify(request),
  })

  return readJsonResponse<TicketComment>(response)
}

export async function fetchTicketHistory(accessToken: string, ticketId: string): Promise<TicketHistory[]> {
  const response = await fetch(`${API_BASE_URL}/tickets/${ticketId}/history`, {
    headers: { Authorization: `Bearer ${accessToken}` },
  })

  return readJsonResponse<TicketHistory[]>(response)
}

export async function fetchAssets(
  accessToken: string,
  params?: AssetQueryParams,
): Promise<Asset[]> {
  const page = await fetchAssetsPage(accessToken, {
    ...params,
    page: params?.page ?? 1,
    page_size: params?.page_size ?? 500,
  })
  return page.items
}

export async function fetchAssetsPage(accessToken: string, params?: AssetQueryParams): Promise<PaginatedResponse<Asset>> {
  const search = new URLSearchParams()
  if (params?.q) search.set('q', params.q)
  if (params?.source && params.source !== 'ALL') search.set('source', params.source)
  if (params?.verification_status && params.verification_status !== 'ALL') search.set('verification_status', params.verification_status)
  if (params?.without_location) search.set('without_location', 'true')
  if (params?.disposed) search.set('disposed', 'true')
  if (params?.assigned_to_name && params.assigned_to_name !== 'ALL') search.set('assigned_to_name', params.assigned_to_name)
  if (typeof params?.purchase_year === 'number') search.set('purchase_year', String(params.purchase_year))
  if (params?.type && params.type !== 'ALL') search.set('type', params.type)
  if (params?.sort_by) search.set('sort_by', params.sort_by)
  if (params?.sort_dir) search.set('sort_dir', params.sort_dir)
  if (typeof params?.page === 'number') search.set('page', String(params.page))
  if (typeof params?.page_size === 'number') search.set('page_size', String(params.page_size))
  const query = search.toString()

  const response = await fetch(`${API_BASE_URL}/assets${query ? `?${query}` : ''}`, {
    headers: { Authorization: `Bearer ${accessToken}` },
  })

  return readJsonResponse<PaginatedResponse<Asset>>(response)
}

export async function fetchAsset(accessToken: string, assetId: string): Promise<Asset> {
  const response = await fetch(`${API_BASE_URL}/assets/${assetId}`, {
    headers: { Authorization: `Bearer ${accessToken}` },
  })

  return readJsonResponse<Asset>(response)
}

export async function fetchAssetTickets(accessToken: string, assetId: string): Promise<AssetTicket[]> {
  const response = await fetch(`${API_BASE_URL}/assets/${assetId}/tickets`, {
    headers: { Authorization: `Bearer ${accessToken}` },
  })

  return readJsonResponse<AssetTicket[]>(response)
}

export async function uploadAssetImport(accessToken: string, file: File): Promise<AssetImportBatch> {
  const formData = new FormData()
  formData.append('file', file)
  const response = await fetch(`${API_BASE_URL}/assets/import/upload`, {
    method: 'POST',
    headers: { Authorization: `Bearer ${accessToken}` },
    body: formData,
  })
  return readJsonResponse<AssetImportBatch>(response)
}

export async function previewAssetImport(accessToken: string, payload: { batch_id: string; dry_run?: boolean }): Promise<AssetImportPreviewResult> {
  const response = await fetch(`${API_BASE_URL}/assets/import/preview`, {
    method: 'POST',
    headers: { Authorization: `Bearer ${accessToken}`, 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  })
  return readJsonResponse<AssetImportPreviewResult>(response)
}

export async function commitAssetImport(accessToken: string, batchId: string, payload?: { dry_run?: boolean }): Promise<AssetImportPreviewResult> {
  const response = await fetch(`${API_BASE_URL}/assets/import/${batchId}/commit`, {
    method: 'POST',
    headers: { Authorization: `Bearer ${accessToken}`, 'Content-Type': 'application/json' },
    body: JSON.stringify(payload ?? {}),
  })
  return readJsonResponse<AssetImportPreviewResult>(response)
}

export async function fetchAssetImportBatches(accessToken: string): Promise<AssetImportBatch[]> {
  const response = await fetch(`${API_BASE_URL}/assets/import/batches`, {
    headers: { Authorization: `Bearer ${accessToken}` },
  })
  return readJsonResponse<AssetImportBatch[]>(response)
}

export async function fetchAssetImportBatch(accessToken: string, batchId: string): Promise<AssetImportBatch> {
  const response = await fetch(`${API_BASE_URL}/assets/import/batches/${batchId}`, {
    headers: { Authorization: `Bearer ${accessToken}` },
  })
  return readJsonResponse<AssetImportBatch>(response)
}

export async function fetchAssetImportRows(accessToken: string, batchId: string): Promise<AssetImportRow[]> {
  const response = await fetch(`${API_BASE_URL}/assets/import/batches/${batchId}/rows`, {
    headers: { Authorization: `Bearer ${accessToken}` },
  })
  return readJsonResponse<AssetImportRow[]>(response)
}

export async function fetchAssetImportTemplate(accessToken: string): Promise<Record<string, unknown>> {
  const response = await fetch(`${API_BASE_URL}/assets/import/template`, {
    headers: { Authorization: `Bearer ${accessToken}` },
  })
  return readJsonResponse<Record<string, unknown>>(response)
}

export async function fetchAssetImportSummary(accessToken: string): Promise<AssetImportSummary> {
  const response = await fetch(`${API_BASE_URL}/assets/import/summary`, {
    headers: { Authorization: `Bearer ${accessToken}` },
  })
  return readJsonResponse<AssetImportSummary>(response)
}

export async function fetchSlaPolicies(accessToken: string): Promise<SlaPolicy[]> {
  const response = await fetch(`${API_BASE_URL}/sla/policies`, {
    headers: { Authorization: `Bearer ${accessToken}` },
  })

  return readJsonResponse<SlaPolicy[]>(response)
}

export async function fetchSlaOverview(accessToken: string): Promise<SlaOverview> {
  const response = await fetch(`${API_BASE_URL}/sla/overview`, {
    headers: { Authorization: `Bearer ${accessToken}` },
  })

  return readJsonResponse<SlaOverview>(response)
}

export async function fetchSlaBreaches(accessToken: string): Promise<SlaBreach[]> {
  const response = await fetch(`${API_BASE_URL}/sla/breaches`, {
    headers: { Authorization: `Bearer ${accessToken}` },
  })

  return readJsonResponse<SlaBreach[]>(response)
}

export async function fetchKnowledgeCategories(accessToken: string): Promise<KnowledgeCategory[]> {
  const response = await fetch(`${API_BASE_URL}/knowledge/categories`, {
    headers: { Authorization: `Bearer ${accessToken}` },
  })

  return readJsonResponse<KnowledgeCategory[]>(response)
}

export async function fetchKnowledgeArticles(accessToken: string): Promise<KnowledgeArticle[]> {
  const response = await fetch(`${API_BASE_URL}/knowledge/articles`, {
    headers: { Authorization: `Bearer ${accessToken}` },
  })

  return readJsonResponse<KnowledgeArticle[]>(response)
}

export async function fetchKnowledgeArticle(accessToken: string, articleId: string): Promise<KnowledgeArticle> {
  const response = await fetch(`${API_BASE_URL}/knowledge/articles/${articleId}`, {
    headers: { Authorization: `Bearer ${accessToken}` },
  })

  return readJsonResponse<KnowledgeArticle>(response)
}

export async function createKnowledgeArticle(accessToken: string, request: CreateKnowledgeArticleRequest): Promise<KnowledgeArticle> {
  const response = await fetch(`${API_BASE_URL}/knowledge/articles`, {
    method: 'POST',
    headers: {
      Authorization: `Bearer ${accessToken}`,
      'Content-Type': 'application/json',
    },
    body: JSON.stringify(request),
  })

  return readJsonResponse<KnowledgeArticle>(response)
}

export async function patchKnowledgeArticle(accessToken: string, articleId: string, request: UpdateKnowledgeArticleRequest): Promise<KnowledgeArticle> {
  const response = await fetch(`${API_BASE_URL}/knowledge/articles/${articleId}`, {
    method: 'PATCH',
    headers: {
      Authorization: `Bearer ${accessToken}`,
      'Content-Type': 'application/json',
    },
    body: JSON.stringify(request),
  })

  return readJsonResponse<KnowledgeArticle>(response)
}

export async function addKnowledgeFeedback(accessToken: string, articleId: string, request: KnowledgeFeedbackRequest): Promise<KnowledgeFeedback> {
  const response = await fetch(`${API_BASE_URL}/knowledge/articles/${articleId}/feedback`, {
    method: 'POST',
    headers: {
      Authorization: `Bearer ${accessToken}`,
      'Content-Type': 'application/json',
    },
    body: JSON.stringify(request),
  })

  return readJsonResponse<KnowledgeFeedback>(response)
}

export async function searchKnowledge(accessToken: string, query: string): Promise<KnowledgeArticle[]> {
  const response = await fetch(`${API_BASE_URL}/knowledge/search?q=${encodeURIComponent(query)}`, {
    headers: { Authorization: `Bearer ${accessToken}` },
  })

  return readJsonResponse<KnowledgeArticle[]>(response)
}

export async function analyzeTicketWithAi(accessToken: string, request: AiAnalyzeRequest): Promise<AiSuggestion> {
  const response = await fetch(`${API_BASE_URL}/ai/analyze-ticket`, {
    method: 'POST',
    headers: {
      Authorization: `Bearer ${accessToken}`,
      'Content-Type': 'application/json',
    },
    body: JSON.stringify(request),
  })

  return readJsonResponse<AiSuggestion>(response)
}

export async function fetchAiSuggestions(accessToken: string, ticketId: string): Promise<AiSuggestion[]> {
  const response = await fetch(`${API_BASE_URL}/ai/suggestions/${ticketId}`, {
    headers: { Authorization: `Bearer ${accessToken}` },
  })

  return readJsonResponse<AiSuggestion[]>(response)
}

export async function createArticleFromTicket(accessToken: string, ticketId: string): Promise<{ id: string; article_number: string; title: string; summary: string; status: string; visibility: string }> {
  const response = await fetch(`${API_BASE_URL}/ai/create-article-from-ticket/${ticketId}`, {
    method: 'POST',
    headers: { Authorization: `Bearer ${accessToken}` },
  })

  return readJsonResponse<{ id: string; article_number: string; title: string; summary: string; status: string; visibility: string }>(response)
}

export async function fetchNotifications(accessToken: string, params?: { status?: string; type?: string }): Promise<Notification[]> {
  const search = new URLSearchParams()
  if (params?.status && params.status !== 'ALL') search.set('status', params.status)
  if (params?.type && params.type !== 'ALL') search.set('type', params.type)
  const query = search.toString()
  const response = await fetch(`${API_BASE_URL}/notifications${query ? `?${query}` : ''}`, {
    headers: { Authorization: `Bearer ${accessToken}` },
  })
  return readJsonResponse<Notification[]>(response)
}

export async function fetchNotificationUnreadCount(accessToken: string): Promise<{ unread_count: number }> {
  const response = await fetch(`${API_BASE_URL}/notifications/unread-count`, {
    headers: { Authorization: `Bearer ${accessToken}` },
  })
  return readJsonResponse<{ unread_count: number }>(response)
}

export async function markNotificationAsRead(accessToken: string, notificationId: string): Promise<Notification> {
  const response = await fetch(`${API_BASE_URL}/notifications/${notificationId}/read`, {
    method: 'PATCH',
    headers: { Authorization: `Bearer ${accessToken}` },
  })
  return readJsonResponse<Notification>(response)
}

export async function markAllNotificationsAsRead(accessToken: string): Promise<{ updated: number }> {
  const response = await fetch(`${API_BASE_URL}/notifications/read-all`, {
    method: 'PATCH',
    headers: { Authorization: `Bearer ${accessToken}` },
  })
  return readJsonResponse<{ updated: number }>(response)
}

export async function fetchNotificationTemplates(accessToken: string): Promise<NotificationTemplate[]> {
  const response = await fetch(`${API_BASE_URL}/notifications/templates`, {
    headers: { Authorization: `Bearer ${accessToken}` },
  })
  return readJsonResponse<NotificationTemplate[]>(response)
}

export async function patchNotificationTemplate(
  accessToken: string,
  templateId: string,
  request: Partial<Pick<NotificationTemplate, 'name' | 'subject_template' | 'body_template' | 'channel' | 'is_active'>>,
): Promise<NotificationTemplate> {
  const response = await fetch(`${API_BASE_URL}/notifications/templates/${templateId}`, {
    method: 'PATCH',
    headers: {
      Authorization: `Bearer ${accessToken}`,
      'Content-Type': 'application/json',
    },
    body: JSON.stringify(request),
  })
  return readJsonResponse<NotificationTemplate>(response)
}

export async function fetchEmailLog(accessToken: string): Promise<EmailMessageLog[]> {
  const response = await fetch(`${API_BASE_URL}/notifications/email-log`, {
    headers: { Authorization: `Bearer ${accessToken}` },
  })
  return readJsonResponse<EmailMessageLog[]>(response)
}

export async function sendTestEmail(accessToken: string, request: TestEmailRequest): Promise<EmailMessageLog> {
  const response = await fetch(`${API_BASE_URL}/notifications/test-email`, {
    method: 'POST',
    headers: {
      Authorization: `Bearer ${accessToken}`,
      'Content-Type': 'application/json',
    },
    body: JSON.stringify(request),
  })
  return readJsonResponse<EmailMessageLog>(response)
}

export async function fetchAdminUsers(
  accessToken: string,
  params?: { role_id?: string; active?: boolean | 'ALL' },
): Promise<AdminUser[]> {
  const search = new URLSearchParams()
  if (params?.role_id && params.role_id !== 'ALL') search.set('role_id', params.role_id)
  if (typeof params?.active === 'boolean') search.set('active', String(params.active))
  const query = search.toString()
  const response = await fetch(`${API_BASE_URL}/admin/users${query ? `?${query}` : ''}`, {
    headers: { Authorization: `Bearer ${accessToken}` },
  })
  return readJsonResponse<AdminUser[]>(response)
}

export async function fetchAdminUser(accessToken: string, userId: string): Promise<AdminUser> {
  const response = await fetch(`${API_BASE_URL}/admin/users/${userId}`, {
    headers: { Authorization: `Bearer ${accessToken}` },
  })
  return readJsonResponse<AdminUser>(response)
}

export async function fetchAdminUserById(accessToken: string, userId: string): Promise<AdminUser> {
  return fetchAdminUser(accessToken, userId)
}

export async function createAdminUser(
  accessToken: string,
  request: {
    tenant_id?: string | null
    email: string
    full_name: string
    password: string
    position?: string | null
    department?: string | null
    phone?: string | null
    role_id?: string | null
  },
): Promise<AdminUser> {
  const response = await fetch(`${API_BASE_URL}/admin/users`, {
    method: 'POST',
    headers: { Authorization: `Bearer ${accessToken}`, 'Content-Type': 'application/json' },
    body: JSON.stringify(request),
  })
  return readJsonResponse<AdminUser>(response)
}

export async function patchAdminUser(accessToken: string, userId: string, request: Partial<Pick<AdminUser, 'full_name' | 'position' | 'department' | 'phone' | 'is_active'>>): Promise<AdminUser> {
  const response = await fetch(`${API_BASE_URL}/admin/users/${userId}`, {
    method: 'PATCH',
    headers: { Authorization: `Bearer ${accessToken}`, 'Content-Type': 'application/json' },
    body: JSON.stringify(request),
  })
  return readJsonResponse<AdminUser>(response)
}

export async function updateAdminUser(
  accessToken: string,
  userId: string,
  request: Partial<Pick<AdminUser, 'full_name' | 'position' | 'department' | 'phone' | 'is_active'>>,
): Promise<AdminUser> {
  return patchAdminUser(accessToken, userId, request)
}

export async function activateAdminUser(accessToken: string, userId: string): Promise<AdminUser> {
  const response = await fetch(`${API_BASE_URL}/admin/users/${userId}/activate`, {
    method: 'PATCH',
    headers: { Authorization: `Bearer ${accessToken}` },
  })
  return readJsonResponse<AdminUser>(response)
}

export async function deactivateAdminUser(accessToken: string, userId: string): Promise<AdminUser> {
  const response = await fetch(`${API_BASE_URL}/admin/users/${userId}/deactivate`, {
    method: 'PATCH',
    headers: { Authorization: `Bearer ${accessToken}` },
  })
  return readJsonResponse<AdminUser>(response)
}

export async function fetchUserRoles(accessToken: string, userId: string): Promise<AdminRole[]> {
  const response = await fetch(`${API_BASE_URL}/admin/users/${userId}/roles`, {
    headers: { Authorization: `Bearer ${accessToken}` },
  })
  return readJsonResponse<AdminRole[]>(response)
}

export async function assignUserRoles(accessToken: string, userId: string, roleIds: string[]): Promise<AdminRole[]> {
  const response = await fetch(`${API_BASE_URL}/admin/users/${userId}/roles`, {
    method: 'POST',
    headers: { Authorization: `Bearer ${accessToken}`, 'Content-Type': 'application/json' },
    body: JSON.stringify({ role_ids: roleIds }),
  })
  return readJsonResponse<AdminRole[]>(response)
}

export async function fetchAdminRoles(accessToken: string): Promise<AdminRole[]> {
  const response = await fetch(`${API_BASE_URL}/admin/roles`, {
    headers: { Authorization: `Bearer ${accessToken}` },
  })
  return readJsonResponse<AdminRole[]>(response)
}

export async function fetchAdminRoleById(accessToken: string, roleId: string): Promise<AdminRole> {
  const response = await fetch(`${API_BASE_URL}/admin/roles/${roleId}`, {
    headers: { Authorization: `Bearer ${accessToken}` },
  })
  return readJsonResponse<AdminRole>(response)
}

export async function createAdminRole(
  accessToken: string,
  request: { tenant_id?: string | null; code: string; name: string; description?: string | null; is_system?: boolean },
): Promise<AdminRole> {
  const response = await fetch(`${API_BASE_URL}/admin/roles`, {
    method: 'POST',
    headers: { Authorization: `Bearer ${accessToken}`, 'Content-Type': 'application/json' },
    body: JSON.stringify(request),
  })
  return readJsonResponse<AdminRole>(response)
}

export async function patchAdminRole(accessToken: string, roleId: string, request: Partial<Pick<AdminRole, 'name' | 'description' | 'is_system'>>): Promise<AdminRole> {
  const response = await fetch(`${API_BASE_URL}/admin/roles/${roleId}`, {
    method: 'PATCH',
    headers: { Authorization: `Bearer ${accessToken}`, 'Content-Type': 'application/json' },
    body: JSON.stringify(request),
  })
  return readJsonResponse<AdminRole>(response)
}

export async function fetchAdminPermissions(accessToken: string): Promise<AdminPermission[]> {
  const response = await fetch(`${API_BASE_URL}/admin/permissions`, {
    headers: { Authorization: `Bearer ${accessToken}` },
  })
  return readJsonResponse<AdminPermission[]>(response)
}

export async function fetchAdminAuditLogs(
  accessToken: string,
  params?: { action?: string; actor_email?: string; entity_type?: string },
): Promise<AdminAuditLog[]> {
  const search = new URLSearchParams()
  if (params?.action) search.set('action', params.action)
  if (params?.actor_email) search.set('actor_email', params.actor_email)
  if (params?.entity_type) search.set('entity_type', params.entity_type)
  const query = search.toString()
  const response = await fetch(`${API_BASE_URL}/admin/audit-logs${query ? `?${query}` : ''}`, {
    headers: { Authorization: `Bearer ${accessToken}` },
  })
  return readJsonResponse<AdminAuditLog[]>(response)
}

export async function fetchAuditLogs(
  accessToken: string,
  params?: { action?: string; actor_email?: string; entity_type?: string },
): Promise<AdminAuditLog[]> {
  return fetchAdminAuditLogs(accessToken, params)
}

export async function fetchAdminAuditLogById(accessToken: string, auditId: string): Promise<AdminAuditLog> {
  const response = await fetch(`${API_BASE_URL}/admin/audit-logs/${auditId}`, {
    headers: { Authorization: `Bearer ${accessToken}` },
  })
  return readJsonResponse<AdminAuditLog>(response)
}

export async function fetchAuditLogById(accessToken: string, auditId: string): Promise<AdminAuditLog> {
  return fetchAdminAuditLogById(accessToken, auditId)
}

export async function fetchAdminSettings(accessToken: string): Promise<SystemSetting[]> {
  const response = await fetch(`${API_BASE_URL}/admin/settings`, {
    headers: { Authorization: `Bearer ${accessToken}` },
  })
  return readJsonResponse<SystemSetting[]>(response)
}

export async function patchAdminSetting(accessToken: string, key: string, value: string): Promise<SystemSetting> {
  const response = await fetch(`${API_BASE_URL}/admin/settings/${encodeURIComponent(key)}`, {
    method: 'PATCH',
    headers: { Authorization: `Bearer ${accessToken}`, 'Content-Type': 'application/json' },
    body: JSON.stringify({ value }),
  })
  return readJsonResponse<SystemSetting>(response)
}

export async function updateAdminSetting(accessToken: string, key: string, value: string): Promise<SystemSetting> {
  return patchAdminSetting(accessToken, key, value)
}

export async function fetchSecurityLoginEvents(accessToken: string): Promise<SecurityLoginEvent[]> {
  const response = await fetch(`${API_BASE_URL}/security/login-events`, {
    headers: { Authorization: `Bearer ${accessToken}` },
  })
  return readJsonResponse<SecurityLoginEvent[]>(response)
}

export async function fetchLoginEvents(accessToken: string): Promise<SecurityLoginEvent[]> {
  return fetchSecurityLoginEvents(accessToken)
}

export async function fetchSecuritySessionOverview(accessToken: string): Promise<SecuritySessionOverview> {
  const response = await fetch(`${API_BASE_URL}/security/session-overview`, {
    headers: { Authorization: `Bearer ${accessToken}` },
  })
  return readJsonResponse<SecuritySessionOverview>(response)
}

export async function fetchSecurityOverview(accessToken: string): Promise<SecuritySessionOverview> {
  return fetchSecuritySessionOverview(accessToken)
}

export async function fetchSecurityRiskSummary(accessToken: string): Promise<SecurityRiskSummary> {
  const response = await fetch(`${API_BASE_URL}/security/risk-summary`, {
    headers: { Authorization: `Bearer ${accessToken}` },
  })
  return readJsonResponse<SecurityRiskSummary>(response)
}

export async function fetchRiskSummary(accessToken: string): Promise<SecurityRiskSummary> {
  return fetchSecurityRiskSummary(accessToken)
}

export async function fetchAnalyticsOverview(accessToken: string): Promise<AnalyticsOverview> {
  const response = await fetch(`${API_BASE_URL}/analytics/overview`, {
    headers: { Authorization: `Bearer ${accessToken}` },
  })
  return readJsonResponse<AnalyticsOverview>(response)
}

export async function fetchTicketAnalytics(accessToken: string): Promise<TicketAnalytics> {
  const response = await fetch(`${API_BASE_URL}/analytics/tickets`, {
    headers: { Authorization: `Bearer ${accessToken}` },
  })
  return readJsonResponse<TicketAnalytics>(response)
}

export async function fetchSlaAnalytics(accessToken: string): Promise<SlaAnalytics> {
  const response = await fetch(`${API_BASE_URL}/analytics/sla`, {
    headers: { Authorization: `Bearer ${accessToken}` },
  })
  return readJsonResponse<SlaAnalytics>(response)
}

export async function fetchAssetAnalytics(accessToken: string): Promise<AssetAnalytics> {
  const response = await fetch(`${API_BASE_URL}/analytics/assets`, {
    headers: { Authorization: `Bearer ${accessToken}` },
  })
  return readJsonResponse<AssetAnalytics>(response)
}

export async function fetchAiAnalytics(accessToken: string): Promise<AiAnalytics> {
  const response = await fetch(`${API_BASE_URL}/analytics/ai`, {
    headers: { Authorization: `Bearer ${accessToken}` },
  })
  return readJsonResponse<AiAnalytics>(response)
}

export async function fetchKnowledgeAnalytics(accessToken: string): Promise<KnowledgeAnalytics> {
  const response = await fetch(`${API_BASE_URL}/analytics/knowledge`, {
    headers: { Authorization: `Bearer ${accessToken}` },
  })
  return readJsonResponse<KnowledgeAnalytics>(response)
}

export async function fetchNotificationAnalytics(accessToken: string): Promise<NotificationAnalytics> {
  const response = await fetch(`${API_BASE_URL}/analytics/notifications`, {
    headers: { Authorization: `Bearer ${accessToken}` },
  })
  return readJsonResponse<NotificationAnalytics>(response)
}

export async function fetchSecurityAnalytics(accessToken: string): Promise<SecurityAnalytics> {
  const response = await fetch(`${API_BASE_URL}/analytics/security`, {
    headers: { Authorization: `Bearer ${accessToken}` },
  })
  return readJsonResponse<SecurityAnalytics>(response)
}

export async function fetchExecutiveSummary(accessToken: string): Promise<ExecutiveSummary> {
  const response = await fetch(`${API_BASE_URL}/analytics/executive-summary`, {
    headers: { Authorization: `Bearer ${accessToken}` },
  })
  return readJsonResponse<ExecutiveSummary>(response)
}

export async function fetchAutomationAnalytics(accessToken: string): Promise<AutomationOverview> {
  const response = await fetch(`${API_BASE_URL}/analytics/automation`, {
    headers: { Authorization: `Bearer ${accessToken}` },
  })
  return readJsonResponse<AutomationOverview>(response)
}

export async function fetchAutomationOverview(accessToken: string): Promise<AutomationOverview> {
  const response = await fetch(`${API_BASE_URL}/automation/overview`, {
    headers: { Authorization: `Bearer ${accessToken}` },
  })
  return readJsonResponse<AutomationOverview>(response)
}

export async function fetchAutomationRules(accessToken: string): Promise<AutomationRule[]> {
  const response = await fetch(`${API_BASE_URL}/automation/rules`, {
    headers: { Authorization: `Bearer ${accessToken}` },
  })
  return readJsonResponse<AutomationRule[]>(response)
}

export async function patchAutomationRule(accessToken: string, ruleId: string, request: Partial<Pick<AutomationRule, 'name' | 'description' | 'trigger_type' | 'is_active' | 'priority'>> & { conditions_json?: Record<string, unknown> | Array<unknown>; actions_json?: Array<Record<string, unknown>> }): Promise<AutomationRule> {
  const response = await fetch(`${API_BASE_URL}/automation/rules/${ruleId}`, {
    method: 'PATCH',
    headers: { Authorization: `Bearer ${accessToken}`, 'Content-Type': 'application/json' },
    body: JSON.stringify(request),
  })
  return readJsonResponse<AutomationRule>(response)
}

export async function dryRunAutomationRule(accessToken: string, ruleId: string, request: { trigger_type?: string; context?: Record<string, unknown> }): Promise<Record<string, unknown>> {
  const response = await fetch(`${API_BASE_URL}/automation/rules/${ruleId}/dry-run`, {
    method: 'POST',
    headers: { Authorization: `Bearer ${accessToken}`, 'Content-Type': 'application/json' },
    body: JSON.stringify(request),
  })
  return readJsonResponse<Record<string, unknown>>(response)
}

export async function manualRunAutomationRule(accessToken: string, ruleId: string, request: { trigger_type?: string; context?: Record<string, unknown> }): Promise<{ run: AutomationRun; summary: Record<string, unknown> }> {
  const response = await fetch(`${API_BASE_URL}/automation/rules/${ruleId}/manual-run`, {
    method: 'POST',
    headers: { Authorization: `Bearer ${accessToken}`, 'Content-Type': 'application/json' },
    body: JSON.stringify(request),
  })
  return readJsonResponse<{ run: AutomationRun; summary: Record<string, unknown> }>(response)
}

export async function fetchAutomationRuns(accessToken: string): Promise<AutomationRun[]> {
  const response = await fetch(`${API_BASE_URL}/automation/runs`, {
    headers: { Authorization: `Bearer ${accessToken}` },
  })
  return readJsonResponse<AutomationRun[]>(response)
}

export async function fetchAutomationRunLogs(accessToken: string, runId: string): Promise<AutomationActionLog[]> {
  const response = await fetch(`${API_BASE_URL}/automation/runs/${runId}/logs`, {
    headers: { Authorization: `Bearer ${accessToken}` },
  })
  return readJsonResponse<AutomationActionLog[]>(response)
}

export async function fetchRunbooks(accessToken: string): Promise<Runbook[]> {
  const response = await fetch(`${API_BASE_URL}/automation/runbooks`, {
    headers: { Authorization: `Bearer ${accessToken}` },
  })
  return readJsonResponse<Runbook[]>(response)
}

export async function fetchRunbookExecutions(accessToken: string): Promise<RunbookExecution[]> {
  const response = await fetch(`${API_BASE_URL}/automation/runbook-executions`, {
    headers: { Authorization: `Bearer ${accessToken}` },
  })
  return readJsonResponse<RunbookExecution[]>(response)
}

export async function startRunbookExecution(accessToken: string, runbookId: string, request: { ticket_id?: string | null }): Promise<RunbookExecution> {
  const response = await fetch(`${API_BASE_URL}/automation/runbooks/${runbookId}/executions`, {
    method: 'POST',
    headers: { Authorization: `Bearer ${accessToken}`, 'Content-Type': 'application/json' },
    body: JSON.stringify(request),
  })
  return readJsonResponse<RunbookExecution>(response)
}

export async function patchRunbookExecution(accessToken: string, executionId: string, request: { status?: string; current_step?: number; result_summary?: string }): Promise<RunbookExecution> {
  const response = await fetch(`${API_BASE_URL}/automation/runbook-executions/${executionId}`, {
    method: 'PATCH',
    headers: { Authorization: `Bearer ${accessToken}`, 'Content-Type': 'application/json' },
    body: JSON.stringify(request),
  })
  return readJsonResponse<RunbookExecution>(response)
}

export async function fetchApprovalRequests(accessToken: string): Promise<ApprovalRequest[]> {
  const response = await fetch(`${API_BASE_URL}/automation/approvals`, {
    headers: { Authorization: `Bearer ${accessToken}` },
  })
  return readJsonResponse<ApprovalRequest[]>(response)
}

export async function decideApprovalRequest(accessToken: string, approvalId: string, request: { decision: 'APPROVED' | 'REJECTED'; comment?: string }): Promise<ApprovalRequest> {
  const response = await fetch(`${API_BASE_URL}/automation/approvals/${approvalId}`, {
    method: 'PATCH',
    headers: { Authorization: `Bearer ${accessToken}`, 'Content-Type': 'application/json' },
    body: JSON.stringify(request),
  })
  return readJsonResponse<ApprovalRequest>(response)
}

export async function fetchTicketAutomationSuggestions(accessToken: string, ticketId: string): Promise<TicketAutomationSuggestion> {
  const response = await fetch(`${API_BASE_URL}/automation/tickets/${ticketId}/suggestions`, {
    headers: { Authorization: `Bearer ${accessToken}` },
  })
  return readJsonResponse<TicketAutomationSuggestion>(response)
}

export async function fetchSavedReports(accessToken: string): Promise<SavedReport[]> {
  const response = await fetch(`${API_BASE_URL}/reports/saved`, {
    headers: { Authorization: `Bearer ${accessToken}` },
  })
  return readJsonResponse<SavedReport[]>(response)
}

export async function createSavedReport(
  accessToken: string,
  request: { name: string; report_type: string; filters_json?: Record<string, unknown> },
): Promise<SavedReport> {
  const response = await fetch(`${API_BASE_URL}/reports/saved`, {
    method: 'POST',
    headers: { Authorization: `Bearer ${accessToken}`, 'Content-Type': 'application/json' },
    body: JSON.stringify(request),
  })
  return readJsonResponse<SavedReport>(response)
}

export async function fetchReportSnapshots(accessToken: string): Promise<ReportSnapshot[]> {
  const response = await fetch(`${API_BASE_URL}/reports/snapshots`, {
    headers: { Authorization: `Bearer ${accessToken}` },
  })
  return readJsonResponse<ReportSnapshot[]>(response)
}

export async function createReportSnapshot(
  accessToken: string,
  request: { report_type: string; period_from?: string | null; period_to?: string | null },
): Promise<ReportSnapshot> {
  const response = await fetch(`${API_BASE_URL}/reports/snapshots`, {
    method: 'POST',
    headers: { Authorization: `Bearer ${accessToken}`, 'Content-Type': 'application/json' },
    body: JSON.stringify(request),
  })
  return readJsonResponse<ReportSnapshot>(response)
}

export async function fetchDemoExport(accessToken: string, params?: { report_type?: string; format?: string }): Promise<DemoExport> {
  const search = new URLSearchParams()
  if (params?.report_type) search.set('report_type', params.report_type)
  if (params?.format) search.set('format', params.format)
  const query = search.toString()
  const response = await fetch(`${API_BASE_URL}/reports/export-demo${query ? `?${query}` : ''}`, {
    headers: { Authorization: `Bearer ${accessToken}` },
  })
  return readJsonResponse<DemoExport>(response)
}

export async function fetchIntegrationSystems(
  accessToken: string,
  params?: { system_type?: string; status?: string },
): Promise<IntegrationSystem[]> {
  const search = new URLSearchParams()
  if (params?.system_type && params.system_type !== 'ALL') search.set('system_type', params.system_type)
  if (params?.status && params.status !== 'ALL') search.set('status', params.status)
  const query = search.toString()
  const response = await fetch(`${API_BASE_URL}/integrations/systems${query ? `?${query}` : ''}`, {
    headers: { Authorization: `Bearer ${accessToken}` },
  })
  return readJsonResponse<IntegrationSystem[]>(response)
}

export async function runIntegrationHealthCheck(accessToken: string, systemId: string): Promise<{ status: string; message?: string }> {
  const response = await fetch(`${API_BASE_URL}/integrations/systems/${systemId}/health-check`, {
    method: 'POST',
    headers: { Authorization: `Bearer ${accessToken}` },
  })
  return readJsonResponse<{ status: string; message?: string }>(response)
}

export async function runIntegrationTestConnection(accessToken: string, systemId: string): Promise<{ status: string; message?: string }> {
  const response = await fetch(`${API_BASE_URL}/integrations/systems/${systemId}/test-connection`, {
    method: 'POST',
    headers: { Authorization: `Bearer ${accessToken}` },
  })
  return readJsonResponse<{ status: string; message?: string }>(response)
}

export async function fetchIntegrationProviders(accessToken: string): Promise<IntegrationProvider[]> {
  const response = await fetch(`${API_BASE_URL}/integrations/providers`, {
    headers: { Authorization: `Bearer ${accessToken}` },
  })
  return readJsonResponse<IntegrationProvider[]>(response)
}

export async function fetchIntegrationProviderCapabilities(accessToken: string, providerCode: string): Promise<IntegrationProvider> {
  const response = await fetch(`${API_BASE_URL}/integrations/providers/${providerCode}/capabilities`, {
    headers: { Authorization: `Bearer ${accessToken}` },
  })
  return readJsonResponse<IntegrationProvider>(response)
}

export async function fetchIntegrationEvents(accessToken: string): Promise<IntegrationEvent[]> {
  const response = await fetch(`${API_BASE_URL}/integrations/events`, {
    headers: { Authorization: `Bearer ${accessToken}` },
  })
  return readJsonResponse<IntegrationEvent[]>(response)
}

export async function fetchIntegrationImportJobs(accessToken: string): Promise<IntegrationImportJob[]> {
  const response = await fetch(`${API_BASE_URL}/integrations/import-jobs`, {
    headers: { Authorization: `Bearer ${accessToken}` },
  })
  return readJsonResponse<IntegrationImportJob[]>(response)
}

export async function createIntegrationImportJob(accessToken: string, request: { external_system_id: string; job_type: string }): Promise<IntegrationImportJob> {
  const response = await fetch(`${API_BASE_URL}/integrations/import-jobs`, {
    method: 'POST',
    headers: { Authorization: `Bearer ${accessToken}`, 'Content-Type': 'application/json' },
    body: JSON.stringify(request),
  })
  return readJsonResponse<IntegrationImportJob>(response)
}

export async function fetchIntegrationWebhooks(accessToken: string): Promise<IntegrationWebhook[]> {
  const response = await fetch(`${API_BASE_URL}/integrations/webhooks`, {
    headers: { Authorization: `Bearer ${accessToken}` },
  })
  return readJsonResponse<IntegrationWebhook[]>(response)
}

export async function simulateIntegrationWebhook(
  accessToken: string,
  webhookId: string,
  request: { payload?: Record<string, unknown>; create_demo_ticket?: boolean },
): Promise<Record<string, unknown>> {
  const response = await fetch(`${API_BASE_URL}/integrations/webhooks/${webhookId}/simulate`, {
    method: 'POST',
    headers: { Authorization: `Bearer ${accessToken}`, 'Content-Type': 'application/json' },
    body: JSON.stringify(request),
  })
  return readJsonResponse<Record<string, unknown>>(response)
}

export async function fetchIntegrationMappings(accessToken: string): Promise<IntegrationMapping[]> {
  const response = await fetch(`${API_BASE_URL}/integrations/mappings`, {
    headers: { Authorization: `Bearer ${accessToken}` },
  })
  return readJsonResponse<IntegrationMapping[]>(response)
}

export async function runMockLdapPullUsers(accessToken: string): Promise<Record<string, unknown>> {
  const response = await fetch(`${API_BASE_URL}/integrations/mock/ldap/pull-users`, {
    method: 'POST',
    headers: { Authorization: `Bearer ${accessToken}`, 'Content-Type': 'application/json' },
    body: JSON.stringify({}),
  })
  return readJsonResponse<Record<string, unknown>>(response)
}

export async function runMockZimbraPullMailboxes(accessToken: string, createDemoTicket = false): Promise<Record<string, unknown>> {
  const response = await fetch(`${API_BASE_URL}/integrations/mock/zimbra/pull-mailboxes`, {
    method: 'POST',
    headers: { Authorization: `Bearer ${accessToken}`, 'Content-Type': 'application/json' },
    body: JSON.stringify({ create_demo_ticket: createDemoTicket }),
  })
  return readJsonResponse<Record<string, unknown>>(response)
}

export async function runMockPlatonusPullUsers(accessToken: string): Promise<Record<string, unknown>> {
  const response = await fetch(`${API_BASE_URL}/integrations/mock/platonus/pull-users`, {
    method: 'POST',
    headers: { Authorization: `Bearer ${accessToken}`, 'Content-Type': 'application/json' },
    body: JSON.stringify({}),
  })
  return readJsonResponse<Record<string, unknown>>(response)
}

export async function runMockMoodlePullUsers(accessToken: string): Promise<Record<string, unknown>> {
  const response = await fetch(`${API_BASE_URL}/integrations/mock/moodle/pull-users`, {
    method: 'POST',
    headers: { Authorization: `Bearer ${accessToken}`, 'Content-Type': 'application/json' },
    body: JSON.stringify({}),
  })
  return readJsonResponse<Record<string, unknown>>(response)
}

export async function runMockWebhookReceive(accessToken: string, createDemoTicket = false): Promise<Record<string, unknown>> {
  const response = await fetch(`${API_BASE_URL}/integrations/mock/webhook/receive`, {
    method: 'POST',
    headers: { Authorization: `Bearer ${accessToken}`, 'Content-Type': 'application/json' },
    body: JSON.stringify({ payload: { source: 'ui-demo', severity: 'medium' }, create_demo_ticket: createDemoTicket }),
  })
  return readJsonResponse<Record<string, unknown>>(response)
}
