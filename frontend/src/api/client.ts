export const API_BASE_URL =
  import.meta.env.VITE_API_BASE_URL ?? 'http://localhost:8000/api/v1'

const API_MAX_PAGE_SIZE = 200

export type HealthResponse = {
  status: 'ok'
  service: string
  version: string
  environment: string
  timestamp: string
}

export type LivenessResponse = {
  status: 'alive'
  timestamp: string
}

export type ReadinessResponse = {
  status: 'ready' | 'not_ready'
  ready: boolean
  checks: {
    postgres: string
    redis: string
  }
  timestamp: string
}

export type DeepHealthResponse = {
  status: string
  service: string
  version: string
  environment: string
  demo_mode: boolean
  run_startup_ddl: boolean
  checks: {
    postgres: Record<string, unknown>
    redis: Record<string, unknown>
    alembic: Record<string, unknown>
  }
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
  author_id: string | null
  author_name: string
  author_role: string
  body: string
  is_internal: boolean
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
  requester_id: string | null
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
  assignee_id: string | null
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
  sla_badge: string | null
  response_remaining_minutes: number | null
  resolution_remaining_minutes: number | null
  is_response_breached: boolean
  is_resolution_breached: boolean
  resolved_at: string | null
  closed_at: string | null
  reopened_at: string | null
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
  queue?: 'all' | 'mine' | 'unassigned' | 'critical' | 'sla_breached' | 'due_today' | 'created_by_me' | 'closed'
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
  requester_id?: string | null
  requester_name: string
  requester_email: string
  requester_contact?: string | null
  department: string
  location?: string | null
  category: string
  priority: string
  assignee_id?: string | null
  assignee_name?: string | null
  asset_id?: string | null
}

export type UpdateTicketRequest = Partial<CreateTicketRequest> & {
  status?: string
  sla_due_at?: string | null
}

export type CreateCommentRequest = {
  body: string
  is_internal?: boolean
}

export type TicketTransitionRequest = {
  status: string
  comment?: string
  is_internal?: boolean
}

export type TicketAssignRequest = {
  assignee_id?: string | null
  comment?: string
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
  building: string | null
  floor: string | null
  room: string | null
  location_label: string | null
  location_verified_at: string | null
  responsible_person_name: string | null
  responsible_person_position: string | null
  responsible_department: string | null
  mol_name: string | null
  mol_department: string | null
  purchase_date: string | null
  accepted_at: string | null
  purchase_cost: number | null
  current_cost: number | null
  initial_cost: number | null
  depreciation_amount: number | null
  residual_cost: number | null
  residual_value: number | null
  purchase_year: number | null
  writeoff_date: string | null
  writeoff_reason: string | null
  verification_status: string | null
  imported_at: string | null
  assigned_at: string | null
  moved_at: string | null
  disposed_at: string | null
  last_inventory_at: string | null
  last_verified_at: string | null
  warranty_until: string | null
  condition: string
  description: string | null
  notes: string | null
  tenant_id: string | null
  tenant_name: string | null
  health: string
  created_at: string
  updated_at: string
}

export type AssetQueryParams = {
  q?: string
  asset_type?: string
  status?: string
  source?: string
  verification_status?: string
  room?: string
  building?: string
  responsible_person_name?: string
  mol_name?: string
  missing_location?: boolean
  needs_verification?: boolean
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

export type AssetHistory = {
  id: string
  asset_id: string
  actor_id: string | null
  action: string
  old_value: Record<string, unknown> | null
  new_value: Record<string, unknown> | null
  comment: string | null
  created_at: string
}

export type AssetHistoryFeedItem = AssetHistory & {
  asset_name: string | null
  inventory_number: string | null
  actor_email: string | null
}

export type AssetDetail = Asset & {
  linked_tickets_summary: Array<{
    id: string
    ticket_number: string | null
    title: string
    status: string
    priority: string
    updated_at: string
  }>
  latest_history: AssetHistory[]
}

export type AssetUpdateRequest = Partial<{
  name: string
  asset_type: string
  status: string
  source: string
  verification_status: string
  building: string | null
  floor: string | null
  room: string | null
  location_label: string | null
  responsible_person_name: string | null
  responsible_person_position: string | null
  responsible_department: string | null
  mol_name: string | null
  mol_department: string | null
  purchase_date: string | null
  purchase_year: number | null
  initial_cost: number | null
  depreciation_amount: number | null
  residual_cost: number | null
  writeoff_date: string | null
  writeoff_reason: string | null
  serial_number: string | null
  manufacturer: string | null
  model: string | null
  notes: string | null
  description: string | null
}>

export type AssetAssignRequest = {
  responsible_person_name: string
  responsible_department?: string | null
  mol_name?: string | null
  mol_department?: string | null
  comment?: string
}

export type AssetMoveRequest = {
  building?: string | null
  floor?: string | null
  room?: string | null
  location_label?: string | null
  comment?: string
}

export type AssetVerifyRequest = {
  verification_status: string
  comment?: string
}

export type AssetDisposeRequest = {
  writeoff_reason: string
  comment?: string
}

export type AssetRestoreRequest = {
  comment?: string
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
  slug?: string | null
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
  source_ticket_id?: string | null
  source_asset_id?: string | null
  created_by_id?: string | null
  updated_by_id?: string | null
  view_count?: number
  helpful_count: number
  not_helpful_count: number
  last_used_at?: string | null
  created_at: string
  updated_at: string
  published_at: string | null
  archived_at?: string | null
}

export type KnowledgeArticlePage = PaginatedResponse<KnowledgeArticle>

export type KnowledgeArticlesQueryParams = {
  q?: string
  category_id?: string
  status?: string
  visibility?: string
  sort_by?: 'updated_at' | 'created_at' | 'published_at' | 'title' | 'helpful_count' | 'view_count' | 'last_used_at'
  sort_dir?: 'asc' | 'desc'
  page?: number
  page_size?: number
}

export type CreateKnowledgeArticleRequest = {
  title: string
  slug?: string | null
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

export type KnowledgeArticleStatusResponse = {
  id: string
  status: string
  published_at: string | null
  archived_at: string | null
}

export type KnowledgeUsageRequest = {
  ticket_id?: string | null
  action?: string
  context?: Record<string, unknown> | null
}

export type KnowledgeUsage = {
  id: string
  article_id: string
  ticket_id: string | null
  user_id: string | null
  action: string
  context: Record<string, unknown> | null
  created_at: string
}

export type TicketKnowledgeLink = {
  id: string
  ticket_id: string
  article_id: string
  article_number: string
  article_title: string
  linked_by_id: string | null
  linked_by_name: string | null
  link_type: string
  confidence: number | null
  comment: string | null
  created_at: string
}

export type CreateTicketKnowledgeLinkRequest = {
  article_id: string
  link_type?: string
  confidence?: number | null
  comment?: string | null
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
  confidence_value?: number | null
  suggestion_type?: string
  rationale?: string | null
  status?: string
  accepted_by_id?: string | null
  accepted_at?: string | null
  rejected_by_id?: string | null
  rejected_at?: string | null
  related_articles: AiRelatedArticle[]
  similar_tickets: AiSimilarTicket[]
  next_actions: string[]
  created_at: string
}

export type AiSuggestionDecisionRequest = {
  rationale?: string | null
}

export type AiSuggestionDecisionResponse = {
  id: string
  status: string
  accepted_by_id: string | null
  accepted_at: string | null
  rejected_by_id: string | null
  rejected_at: string | null
  rationale: string | null
}

export type AiAnalyzeRequest = {
  input_text: string
  ticket_id?: string | null
}

export type Notification = {
  id: string
  type: string
  event_type?: string | null
  severity?: string | null
  title: string
  message: string
  recipient_name: string
  recipient_email: string
  channel: string
  status: string
  is_read?: boolean
  related_ticket_id: string | null
  entity_type?: string | null
  entity_id?: string | null
  action_url?: string | null
  metadata?: Record<string, unknown> | null
  created_at: string
  read_at: string | null
}

export type NotificationListResponse = {
  items: Notification[]
  total: number
  page: number
  page_size: number
  unread_count: number
}

export type NotificationTemplate = {
  id: string
  tenant_id?: string | null
  key?: string | null
  event_type?: string | null
  locale?: string
  code: string
  name: string
  subject_template: string
  body_template: string
  channel: string | null
  is_active: boolean
  created_at: string
  updated_at: string
}

export type EmailMessageLog = {
  id: string
  tenant_id?: string | null
  notification_id?: string | null
  event_type?: string | null
  provider: string
  provider_message_id?: string | null
  to_email: string
  to_name?: string | null
  subject: string
  body: string
  status: string
  attempt_count?: number
  max_attempts?: number
  next_retry_at?: string | null
  payload?: Record<string, unknown> | null
  metadata?: Record<string, unknown> | null
  error_message: string | null
  related_ticket_id: string | null
  created_at: string
  sent_at: string | null
}

export type EmailLogListResponse = {
  items: EmailMessageLog[]
  total: number
  page: number
  page_size: number
}

export type NotificationPreference = {
  id: string
  event_type: string
  channel_in_app: boolean
  channel_email: boolean
  is_muted: boolean
  updated_at: string
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
  runbook_id?: string | null
  trigger_type: string
  trigger_entity_type: string | null
  trigger_entity_id: string | null
  status: string
  input_payload_json?: Record<string, unknown> | null
  output_payload_json?: Record<string, unknown> | null
  started_at: string | null
  finished_at: string | null
  executed_by_id?: string | null
  approval_request_id?: string | null
  result_summary: Record<string, unknown>
  error_message: string | null
  created_at: string
}

export type AutomationActionLog = {
  id: string
  tenant_id: string | null
  automation_run_id: string
  execution_id?: string | null
  action_type: string
  action_payload_json?: Record<string, unknown>
  status: string
  result_payload_json?: Record<string, unknown>
  input_json: Record<string, unknown>
  output_json: Record<string, unknown>
  error_message: string | null
  created_at: string
}

export type Runbook = {
  id: string
  tenant_id: string | null
  name?: string | null
  code: string
  title: string
  description: string | null
  category: string
  severity: string
  steps_json: Array<Record<string, unknown>>
  estimated_minutes: number
  is_active: boolean
  requires_approval?: boolean
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
  requested_by_id?: string | null
  approver_id?: string | null
  requested_by: string
  approver_name: string | null
  status: string
  reason?: string | null
  decision_comment: string | null
  requested_at?: string
  metadata_json?: Record<string, unknown>
  created_at: string
  decided_at: string | null
}

export type AutomationExecutionDetail = {
  execution: AutomationRun
  action_logs: AutomationActionLog[]
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

export type IntegrationSystemV2 = {
  id: string
  tenant_id: string | null
  code: string
  name: string
  system_type: string
  base_url: string | null
  status: string
  health_status?: string | null
  is_mock?: boolean
  is_enabled: boolean
  last_health_check_at?: string | null
  last_success_at?: string | null
  last_error_at?: string | null
  last_error_message?: string | null
  config?: Record<string, unknown>
  created_by_id?: string | null
  description?: string | null
  created_at: string
  updated_at: string
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

type IntegrationEventV2 = {
  id: string
  external_system_id: string | null
  direction: string
  event_type: string
  entity_type?: string | null
  entity_id?: string | null
  status: string
  payload?: Record<string, unknown>
  response_payload?: Record<string, unknown>
  error_message: string | null
  attempt_count?: number
  next_retry_at?: string | null
  created_at: string
  processed_at?: string | null
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

type IntegrationImportJobV2 = {
  id: string
  external_system_id: string | null
  job_type: string
  status: string
  source_filename?: string | null
  total_rows?: number
  success_rows?: number
  failed_rows?: number
  records_total?: number
  records_success?: number
  records_failed?: number
  error_report?: Record<string, unknown>
  dry_run?: boolean
  created_by_id?: string | null
  started_at: string | null
  finished_at: string | null
  created_at: string
  error_message?: string | null
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

type IntegrationWebhookV2 = {
  id: string
  external_system_id: string | null
  name: string
  path: string
  event_type: string
  is_active: boolean
  secret_required?: boolean
  last_received_at?: string | null
  success_count?: number
  failure_count?: number
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

type IntegrationMappingV2 = {
  id: string
  external_system_id: string | null
  mapping_type: string
  source_field?: string | null
  target_field?: string | null
  transform_rule?: string | null
  is_required?: boolean
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
  visibility?: string
  schedule_enabled?: boolean
  created_by_id?: string | null
  created_by: string
  created_at: string
  updated_at: string
}

export type ReportSnapshot = {
  id: string
  tenant_id: string | null
  saved_report_id?: string | null
  report_type: string
  period_from: string | null
  period_to: string | null
  filters_json?: Record<string, unknown>
  payload_json: Record<string, unknown>
  generated_by_id?: string | null
  generated_at?: string
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

type LogoutRequest = {
  refresh_token?: string
}

export async function getHealth(signal?: AbortSignal): Promise<HealthResponse> {
  const response = await fetch(`${API_BASE_URL}/health`, { signal })
  if (!response.ok) throw new Error(`Backend returned ${response.status}`)
  return response.json() as Promise<HealthResponse>
}

export async function getLiveness(signal?: AbortSignal): Promise<LivenessResponse> {
  const response = await fetch(`${API_BASE_URL}/health/liveness`, { signal })
  if (!response.ok) throw new Error(`Backend returned ${response.status}`)
  return response.json() as Promise<LivenessResponse>
}

export async function getReadiness(signal?: AbortSignal): Promise<ReadinessResponse> {
  const response = await fetch(`${API_BASE_URL}/health/readiness`, { signal })
  if (![200, 503].includes(response.status)) {
    throw new Error(`Backend returned ${response.status}`)
  }
  return response.json() as Promise<ReadinessResponse>
}

export async function getDeepHealth(accessToken: string): Promise<DeepHealthResponse> {
  const response = await fetch(`${API_BASE_URL}/health/deep`, {
    headers: { Authorization: `Bearer ${accessToken}` },
  })
  return readJsonResponse<DeepHealthResponse>(response)
}

export type JobRunSummary = {
  total: number
  queued: number
  running: number
  success: number
  failed: number
}

export type JobRun = {
  id: string
  task_name: string
  status: string
  tenant_id: string | null
  actor_user_id: string | null
  correlation_id: string | null
  payload: unknown
  result: unknown
  error_message: string | null
  attempts: number
  max_attempts: number
  queued_at: string
  started_at: string | null
  finished_at: string | null
  duration_ms: number | null
  created_at: string
  updated_at: string
}

export async function fetchJobRuns(accessToken: string, limit = 20): Promise<JobRun[]> {
  const response = await fetch(`${API_BASE_URL}/jobs?limit=${limit}`, {
    headers: { Authorization: `Bearer ${accessToken}` },
  })
  return readJsonResponse<JobRun[]>(response)
}

export async function fetchJobSummary(accessToken: string): Promise<JobRunSummary> {
  const response = await fetch(`${API_BASE_URL}/jobs/summary`, {
    headers: { Authorization: `Bearer ${accessToken}` },
  })
  return readJsonResponse<JobRunSummary>(response)
}

export type AiProviderStatus = {
  active_provider: string
  model: string
  ready: boolean
  api_key_configured: boolean
  pii_redaction_enabled: boolean
  request_timeout_seconds: number
  reason: string | null
  fallback_provider: string | null
  supported_providers: string[]
}

export async function fetchAiProviderStatus(accessToken: string): Promise<AiProviderStatus> {
  const response = await fetch(`${API_BASE_URL}/ai/provider-status`, {
    headers: { Authorization: `Bearer ${accessToken}` },
  })
  return readJsonResponse<AiProviderStatus>(response)
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

export async function logoutSession(accessToken: string | undefined, request?: LogoutRequest): Promise<{ ok: boolean }> {
  const headers: Record<string, string> = { 'Content-Type': 'application/json' }
  if (accessToken) {
    headers.Authorization = `Bearer ${accessToken}`
  }
  const response = await fetch(`${API_BASE_URL}/auth/logout`, {
    method: 'POST',
    headers,
    body: JSON.stringify(request ?? {}),
  })
  return readJsonResponse<{ ok: boolean }>(response)
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
  if (params?.queue && params.queue !== 'all') search.set('queue', params.queue)
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
  const page = await fetchTicketsPage(accessToken, { page: 1, page_size: API_MAX_PAGE_SIZE })
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

export async function transitionTicket(accessToken: string, ticketId: string, request: TicketTransitionRequest): Promise<TicketDetail> {
  const response = await fetch(`${API_BASE_URL}/tickets/${ticketId}/transition`, {
    method: 'POST',
    headers: {
      Authorization: `Bearer ${accessToken}`,
      'Content-Type': 'application/json',
    },
    body: JSON.stringify(request),
  })

  return readJsonResponse<TicketDetail>(response)
}

export async function assignTicket(accessToken: string, ticketId: string, request: TicketAssignRequest): Promise<TicketDetail> {
  const response = await fetch(`${API_BASE_URL}/tickets/${ticketId}/assign`, {
    method: 'POST',
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
    page_size: params?.page_size ?? API_MAX_PAGE_SIZE,
  })
  return page.items
}

export async function fetchAssetsPage(accessToken: string, params?: AssetQueryParams): Promise<PaginatedResponse<Asset>> {
  const search = new URLSearchParams()
  if (params?.q) search.set('q', params.q)
  if (params?.asset_type && params.asset_type !== 'ALL') search.set('asset_type', params.asset_type)
  if (params?.status && params.status !== 'ALL') search.set('status', params.status)
  if (params?.source && params.source !== 'ALL') search.set('source', params.source)
  if (params?.verification_status && params.verification_status !== 'ALL') search.set('verification_status', params.verification_status)
  if (params?.room && params.room !== 'ALL') search.set('room', params.room)
  if (params?.building && params.building !== 'ALL') search.set('building', params.building)
  if (params?.responsible_person_name && params.responsible_person_name !== 'ALL') search.set('responsible_person_name', params.responsible_person_name)
  if (params?.mol_name && params.mol_name !== 'ALL') search.set('mol_name', params.mol_name)
  if (params?.missing_location) search.set('missing_location', 'true')
  if (params?.needs_verification) search.set('needs_verification', 'true')
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

export async function fetchAssetById(accessToken: string, assetId: string): Promise<AssetDetail> {
  const response = await fetch(`${API_BASE_URL}/assets/${assetId}`, {
    headers: { Authorization: `Bearer ${accessToken}` },
  })

  return readJsonResponse<AssetDetail>(response)
}

export async function fetchAssetTickets(accessToken: string, assetId: string): Promise<AssetTicket[]> {
  const response = await fetch(`${API_BASE_URL}/assets/${assetId}/tickets`, {
    headers: { Authorization: `Bearer ${accessToken}` },
  })

  return readJsonResponse<AssetTicket[]>(response)
}

export async function updateAsset(accessToken: string, assetId: string, payload: AssetUpdateRequest): Promise<AssetDetail> {
  const response = await fetch(`${API_BASE_URL}/assets/${assetId}`, {
    method: 'PATCH',
    headers: {
      Authorization: `Bearer ${accessToken}`,
      'Content-Type': 'application/json',
    },
    body: JSON.stringify(payload),
  })
  return readJsonResponse<AssetDetail>(response)
}

export async function assignAsset(accessToken: string, assetId: string, payload: AssetAssignRequest): Promise<AssetDetail> {
  const response = await fetch(`${API_BASE_URL}/assets/${assetId}/assign`, {
    method: 'POST',
    headers: {
      Authorization: `Bearer ${accessToken}`,
      'Content-Type': 'application/json',
    },
    body: JSON.stringify(payload),
  })
  return readJsonResponse<AssetDetail>(response)
}

export async function moveAsset(accessToken: string, assetId: string, payload: AssetMoveRequest): Promise<AssetDetail> {
  const response = await fetch(`${API_BASE_URL}/assets/${assetId}/move`, {
    method: 'POST',
    headers: {
      Authorization: `Bearer ${accessToken}`,
      'Content-Type': 'application/json',
    },
    body: JSON.stringify(payload),
  })
  return readJsonResponse<AssetDetail>(response)
}

export async function verifyAsset(accessToken: string, assetId: string, payload: AssetVerifyRequest): Promise<AssetDetail> {
  const response = await fetch(`${API_BASE_URL}/assets/${assetId}/verify`, {
    method: 'POST',
    headers: {
      Authorization: `Bearer ${accessToken}`,
      'Content-Type': 'application/json',
    },
    body: JSON.stringify(payload),
  })
  return readJsonResponse<AssetDetail>(response)
}

export async function disposeAsset(accessToken: string, assetId: string, payload: AssetDisposeRequest): Promise<AssetDetail> {
  const response = await fetch(`${API_BASE_URL}/assets/${assetId}/dispose`, {
    method: 'POST',
    headers: {
      Authorization: `Bearer ${accessToken}`,
      'Content-Type': 'application/json',
    },
    body: JSON.stringify(payload),
  })
  return readJsonResponse<AssetDetail>(response)
}

export async function restoreAsset(accessToken: string, assetId: string, payload: AssetRestoreRequest): Promise<AssetDetail> {
  const response = await fetch(`${API_BASE_URL}/assets/${assetId}/restore`, {
    method: 'POST',
    headers: {
      Authorization: `Bearer ${accessToken}`,
      'Content-Type': 'application/json',
    },
    body: JSON.stringify(payload),
  })
  return readJsonResponse<AssetDetail>(response)
}

export async function fetchAssetHistory(accessToken: string, assetId: string): Promise<AssetHistory[]> {
  const response = await fetch(`${API_BASE_URL}/assets/${assetId}/history`, {
    headers: { Authorization: `Bearer ${accessToken}` },
  })
  return readJsonResponse<AssetHistory[]>(response)
}

export async function fetchAssetHistoryFeed(
  accessToken: string,
  params?: { action?: string; actor?: string; asset_q?: string; date_from?: string; date_to?: string; limit?: number },
): Promise<AssetHistoryFeedItem[]> {
  const search = new URLSearchParams()
  if (params?.action && params.action !== 'ALL') search.set('action', params.action)
  if (params?.actor) search.set('actor', params.actor)
  if (params?.asset_q) search.set('asset_q', params.asset_q)
  if (params?.date_from) search.set('date_from', params.date_from)
  if (params?.date_to) search.set('date_to', params.date_to)
  if (typeof params?.limit === 'number') search.set('limit', String(params.limit))
  const query = search.toString()

  const response = await fetch(`${API_BASE_URL}/assets/history${query ? `?${query}` : ''}`, {
    headers: { Authorization: `Bearer ${accessToken}` },
  })
  return readJsonResponse<AssetHistoryFeedItem[]>(response)
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

export async function fetchKnowledgeArticlesPage(accessToken: string, params?: KnowledgeArticlesQueryParams): Promise<KnowledgeArticlePage> {
  const search = new URLSearchParams()
  if (params?.q) search.set('q', params.q)
  if (params?.category_id) search.set('category_id', params.category_id)
  if (params?.status && params.status !== 'ALL') search.set('status', params.status)
  if (params?.visibility && params.visibility !== 'ALL') search.set('visibility', params.visibility)
  if (params?.sort_by) search.set('sort_by', params.sort_by)
  if (params?.sort_dir) search.set('sort_dir', params.sort_dir)
  if (typeof params?.page === 'number') search.set('page', String(params.page))
  if (typeof params?.page_size === 'number') search.set('page_size', String(params.page_size))
  const query = search.toString()

  const response = await fetch(`${API_BASE_URL}/knowledge/articles/page${query ? `?${query}` : ''}`, {
    headers: { Authorization: `Bearer ${accessToken}` },
  })

  return readJsonResponse<KnowledgeArticlePage>(response)
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

export async function updateKnowledgeArticle(accessToken: string, articleId: string, request: UpdateKnowledgeArticleRequest): Promise<KnowledgeArticle> {
  return patchKnowledgeArticle(accessToken, articleId, request)
}

export async function publishKnowledgeArticle(accessToken: string, articleId: string): Promise<KnowledgeArticleStatusResponse> {
  const response = await fetch(`${API_BASE_URL}/knowledge/articles/${articleId}/publish`, {
    method: 'POST',
    headers: { Authorization: `Bearer ${accessToken}` },
  })
  return readJsonResponse<KnowledgeArticleStatusResponse>(response)
}

export async function archiveKnowledgeArticle(accessToken: string, articleId: string): Promise<KnowledgeArticleStatusResponse> {
  const response = await fetch(`${API_BASE_URL}/knowledge/articles/${articleId}/archive`, {
    method: 'POST',
    headers: { Authorization: `Bearer ${accessToken}` },
  })
  return readJsonResponse<KnowledgeArticleStatusResponse>(response)
}

export async function logKnowledgeArticleUsage(accessToken: string, articleId: string, request: KnowledgeUsageRequest): Promise<KnowledgeUsage> {
  const response = await fetch(`${API_BASE_URL}/knowledge/articles/${articleId}/usage`, {
    method: 'POST',
    headers: {
      Authorization: `Bearer ${accessToken}`,
      'Content-Type': 'application/json',
    },
    body: JSON.stringify(request),
  })
  return readJsonResponse<KnowledgeUsage>(response)
}

export async function createKnowledgeArticleFromTicket(accessToken: string, ticketId: string): Promise<{ id: string; article_number: string; title: string; summary: string; status: string; visibility: string }> {
  const response = await fetch(`${API_BASE_URL}/knowledge/articles/from-ticket/${ticketId}`, {
    method: 'POST',
    headers: { Authorization: `Bearer ${accessToken}` },
  })
  return readJsonResponse<{ id: string; article_number: string; title: string; summary: string; status: string; visibility: string }>(response)
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

export async function submitKnowledgeFeedback(accessToken: string, articleId: string, request: KnowledgeFeedbackRequest): Promise<KnowledgeFeedback> {
  return addKnowledgeFeedback(accessToken, articleId, request)
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

export async function analyzeTicket(accessToken: string, request: AiAnalyzeRequest): Promise<AiSuggestion> {
  return analyzeTicketWithAi(accessToken, request)
}

export async function fetchAiSuggestions(accessToken: string, ticketId: string): Promise<AiSuggestion[]> {
  const response = await fetch(`${API_BASE_URL}/ai/suggestions/${ticketId}`, {
    headers: { Authorization: `Bearer ${accessToken}` },
  })

  return readJsonResponse<AiSuggestion[]>(response)
}

export async function acceptAiSuggestion(accessToken: string, suggestionId: string, request?: AiSuggestionDecisionRequest): Promise<AiSuggestionDecisionResponse> {
  const response = await fetch(`${API_BASE_URL}/ai/suggestions/${suggestionId}/accept`, {
    method: 'POST',
    headers: {
      Authorization: `Bearer ${accessToken}`,
      'Content-Type': 'application/json',
    },
    body: JSON.stringify(request ?? {}),
  })
  return readJsonResponse<AiSuggestionDecisionResponse>(response)
}

export async function rejectAiSuggestion(accessToken: string, suggestionId: string, request?: AiSuggestionDecisionRequest): Promise<AiSuggestionDecisionResponse> {
  const response = await fetch(`${API_BASE_URL}/ai/suggestions/${suggestionId}/reject`, {
    method: 'POST',
    headers: {
      Authorization: `Bearer ${accessToken}`,
      'Content-Type': 'application/json',
    },
    body: JSON.stringify(request ?? {}),
  })
  return readJsonResponse<AiSuggestionDecisionResponse>(response)
}

export async function createArticleFromTicket(accessToken: string, ticketId: string): Promise<{ id: string; article_number: string; title: string; summary: string; status: string; visibility: string }> {
  const response = await fetch(`${API_BASE_URL}/ai/create-article-from-ticket/${ticketId}`, {
    method: 'POST',
    headers: { Authorization: `Bearer ${accessToken}` },
  })

  return readJsonResponse<{ id: string; article_number: string; title: string; summary: string; status: string; visibility: string }>(response)
}

export async function fetchTicketKnowledgeLinks(accessToken: string, ticketId: string): Promise<TicketKnowledgeLink[]> {
  const response = await fetch(`${API_BASE_URL}/tickets/${ticketId}/knowledge-links`, {
    headers: { Authorization: `Bearer ${accessToken}` },
  })
  return readJsonResponse<TicketKnowledgeLink[]>(response)
}

export async function fetchTicketKnowledge(accessToken: string, ticketId: string): Promise<TicketKnowledgeLink[]> {
  return fetchTicketKnowledgeLinks(accessToken, ticketId)
}

export async function createTicketKnowledgeLink(accessToken: string, ticketId: string, request: CreateTicketKnowledgeLinkRequest): Promise<TicketKnowledgeLink> {
  const response = await fetch(`${API_BASE_URL}/tickets/${ticketId}/knowledge-links`, {
    method: 'POST',
    headers: {
      Authorization: `Bearer ${accessToken}`,
      'Content-Type': 'application/json',
    },
    body: JSON.stringify(request),
  })
  return readJsonResponse<TicketKnowledgeLink>(response)
}

export async function attachArticleToTicket(accessToken: string, ticketId: string, request: CreateTicketKnowledgeLinkRequest): Promise<TicketKnowledgeLink> {
  return createTicketKnowledgeLink(accessToken, ticketId, request)
}

export async function useArticleForTicket(accessToken: string, ticketId: string, articleId: string): Promise<KnowledgeUsage> {
  return logKnowledgeArticleUsage(accessToken, articleId, {
    ticket_id: ticketId,
    action: 'used_for_resolution',
    context: { source: 'ticket_detail' },
  })
}

export async function deleteTicketKnowledgeLink(accessToken: string, ticketId: string, linkId: string): Promise<void> {
  const response = await fetch(`${API_BASE_URL}/tickets/${ticketId}/knowledge-links/${linkId}`, {
    method: 'DELETE',
    headers: { Authorization: `Bearer ${accessToken}` },
  })
  if (!response.ok) {
    const errorPayload = (await response.json().catch(() => null)) as { error?: { message?: string } } | null
    throw new Error(errorPayload?.error?.message ?? `Backend returned ${response.status}`)
  }
}

export async function fetchNotifications(
  accessToken: string,
  params?: { status?: string; event_type?: string; type?: string; page?: number; page_size?: number; q?: string },
): Promise<NotificationListResponse> {
  const search = new URLSearchParams()
  if (params?.status && params.status !== 'ALL') search.set('status', params.status)
  const eventType = params?.event_type ?? params?.type
  if (eventType && eventType !== 'ALL') search.set('event_type', eventType)
  if (params?.q) search.set('q', params.q)
  if (params?.page) search.set('page', String(params.page))
  if (params?.page_size) search.set('page_size', String(params.page_size))
  const query = search.toString()
  const response = await fetch(`${API_BASE_URL}/notifications${query ? `?${query}` : ''}`, {
    headers: { Authorization: `Bearer ${accessToken}` },
  })
  const payload = await readJsonResponse<NotificationListResponse | Notification[]>(response)
  if (Array.isArray(payload)) {
    const unreadCount = payload.filter((item) => item.status !== 'READ').length
    return {
      items: payload,
      total: payload.length,
      page: 1,
      page_size: payload.length,
      unread_count: unreadCount,
    }
  }
  return payload
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
  const payload = await readJsonResponse<EmailLogListResponse | EmailMessageLog[]>(response)
  if (Array.isArray(payload)) {
    return payload
  }
  return payload.items
}

export async function fetchEmailLogPage(
  accessToken: string,
  params?: { status?: string; q?: string; page?: number; page_size?: number },
): Promise<EmailLogListResponse> {
  const search = new URLSearchParams()
  if (params?.status && params.status !== 'ALL') search.set('status', params.status)
  if (params?.q) search.set('q', params.q)
  if (params?.page) search.set('page', String(params.page))
  if (params?.page_size) search.set('page_size', String(params.page_size))
  const query = search.toString()
  const response = await fetch(`${API_BASE_URL}/notifications/email-log${query ? `?${query}` : ''}`, {
    headers: { Authorization: `Bearer ${accessToken}` },
  })
  const payload = await readJsonResponse<EmailLogListResponse | EmailMessageLog[]>(response)
  if (Array.isArray(payload)) {
    return {
      items: payload,
      total: payload.length,
      page: 1,
      page_size: payload.length,
    }
  }
  return payload
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

export async function retryEmailLog(accessToken: string, emailLogId: string): Promise<EmailMessageLog> {
  const response = await fetch(`${API_BASE_URL}/notifications/email-log/${emailLogId}/retry`, {
    method: 'POST',
    headers: { Authorization: `Bearer ${accessToken}` },
  })
  return readJsonResponse<EmailMessageLog>(response)
}

export async function fetchNotificationPreferences(accessToken: string): Promise<NotificationPreference[]> {
  const response = await fetch(`${API_BASE_URL}/notifications/preferences`, {
    headers: { Authorization: `Bearer ${accessToken}` },
  })
  return readJsonResponse<NotificationPreference[]>(response)
}

export async function patchNotificationPreferences(
  accessToken: string,
  items: Array<Partial<NotificationPreference> & { event_type: string }>,
): Promise<NotificationPreference[]> {
  const response = await fetch(`${API_BASE_URL}/notifications/preferences`, {
    method: 'PATCH',
    headers: {
      Authorization: `Bearer ${accessToken}`,
      'Content-Type': 'application/json',
    },
    body: JSON.stringify({ items }),
  })
  return readJsonResponse<NotificationPreference[]>(response)
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
  const payload = (await readJsonResponse<Record<string, unknown>>(response)) ?? {}
  return {
    total_tickets: Number(payload.total_tickets ?? 0),
    open_tickets: Number(payload.total_tickets ?? 0) - Number(payload.closed_count ?? 0),
    closed_tickets: Number(payload.closed_count ?? 0),
    tickets_today: 0,
    by_status: (payload.status_distribution as AnalyticsCountItem[]) ?? [],
    by_priority: (payload.priority_distribution as AnalyticsCountItem[]) ?? [],
    by_category: (payload.category_distribution as AnalyticsCountItem[]) ?? [],
    average_response_minutes: (payload.average_first_response_minutes as number | null) ?? null,
    average_resolution_minutes: (payload.average_resolution_time_minutes as number | null) ?? null,
    top_requesters: [],
    top_assignees: ((payload.assignee_workload as Array<{ assignee: string; count: number }>) ?? []).map((item) => ({ name: item.assignee, count: item.count })),
    open_critical_tickets: ((payload.priority_distribution as Array<{ priority: string; count: number }>) ?? [])
      .filter((item) => item.priority === 'CRITICAL')
      .reduce((acc, item) => acc + Number(item.count ?? 0), 0),
  }
}

export async function fetchSlaAnalytics(accessToken: string): Promise<SlaAnalytics> {
  const response = await fetch(`${API_BASE_URL}/analytics/sla`, {
    headers: { Authorization: `Bearer ${accessToken}` },
  })
  const payload = (await readJsonResponse<Record<string, unknown>>(response)) ?? {}
  return {
    sla_compliance_percent: Number(payload.compliance_percent ?? 0),
    response_breaches: Number(payload.breached_tickets ?? 0),
    resolution_breaches: Number(payload.breached_tickets ?? 0),
    tickets_at_risk: Number(payload.at_risk_tickets ?? 0),
    critical_sla_breaches: 0,
    violations_by_priority: (payload.by_priority as Array<{ priority: string; count: number }>) ?? [],
  }
}

export async function fetchAssetAnalytics(accessToken: string): Promise<AssetAnalytics> {
  const response = await fetch(`${API_BASE_URL}/analytics/assets`, {
    headers: { Authorization: `Bearer ${accessToken}` },
  })
  const payload = (await readJsonResponse<Record<string, unknown>>(response)) ?? {}
  const byStatus = (payload.assets_by_status as Array<{ status: string; count: number }>) ?? []
  return {
    total_assets: Number(payload.total_assets ?? 0),
    assets_by_type: (payload.assets_by_type as Array<{ type: string; count: number }>) ?? [],
    assets_by_status: byStatus,
    problem_assets: [],
    problem_assets_count: 0,
    top_assets_by_ticket_count: [],
    warranty_expiring_soon: [],
    unassigned_assets: [],
    unassigned_assets_count: 0,
    imported_assets_count: 0,
    assets_missing_location_count: Number(payload.missing_location ?? 0),
    disposed_assets_count: byStatus.filter((item) => item.status === 'disposed').reduce((acc, item) => acc + item.count, 0),
    assets_by_source: [],
    assets_by_purchase_year: [],
    top_responsible_persons: ((payload.assets_by_responsible as Array<{ responsible: string; count: number }>) ?? []).map((item) => ({ name: item.responsible, count: item.count })),
    duplicate_inventory_numbers: [],
  }
}

export async function fetchAiAnalytics(accessToken: string): Promise<AiAnalytics> {
  const response = await fetch(`${API_BASE_URL}/analytics/ai`, {
    headers: { Authorization: `Bearer ${accessToken}` },
  })
  const payload = (await readJsonResponse<Record<string, unknown>>(response)) ?? {}
  return {
    total_ai_analyses: Number(payload.ai_suggestions_total ?? 0),
    average_confidence_percent: Number(payload.average_confidence ?? 0) * 100,
    recommendations_by_category: [],
    recommendations_by_priority: [],
    ai_suggestions_applied_demo: Number(payload.attach_article_count ?? 0),
    frequent_request_topics: [],
  }
}

export async function fetchKnowledgeAnalytics(accessToken: string): Promise<KnowledgeAnalytics> {
  const response = await fetch(`${API_BASE_URL}/analytics/knowledge`, {
    headers: { Authorization: `Bearer ${accessToken}` },
  })
  const payload = (await readJsonResponse<Record<string, unknown>>(response)) ?? {}
  return {
    total_articles: Number(payload.total_articles ?? 0),
    published_articles: Number(payload.published_articles ?? 0),
    top_helpful_articles: ((payload.most_used_articles as Array<{ article_number: string; title: string; count: number }>) ?? []).map((item) => ({
      article_number: item.article_number,
      title: item.title,
      helpful_count: item.count,
    })),
    articles_with_negative_feedback: [],
    categories_without_articles: [],
    tickets_resolved_via_knowledge_demo: 0,
  }
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
  const payload = (await readJsonResponse<Record<string, unknown>>(response)) ?? {}
  return {
    login_success: 0,
    login_failed: Number(payload.failed_logins ?? 0),
    audit_events_count: Number(payload.audit_events_today ?? 0),
    admin_changes_today: Number(payload.admin_actions ?? 0),
    risk_summary: {
      failed_logins_24h: Number(payload.failed_logins ?? 0),
      success_logins_24h: 0,
      active_users: 0,
      risk_level: Number(payload.high_risk_events ?? 0) > 0 ? 'high' : 'medium',
      recent_security_events: [],
    },
    sensitive_settings_count: Number(payload.sensitive_settings_changes ?? 0),
  }
}

export async function fetchExecutiveSummary(accessToken: string): Promise<ExecutiveSummary> {
  const response = await fetch(`${API_BASE_URL}/analytics/executive`, {
    headers: { Authorization: `Bearer ${accessToken}` },
  })
  const payload = (await readJsonResponse<Record<string, unknown>>(response)) ?? {}
  return {
    health_score: Number(payload.itsm_health_score ?? 0),
    it_workload_score: Math.max(0, 100 - Number(payload.open_tickets ?? 0)),
    sla_risk_score: Number(payload.sla_compliance_percent ?? 0),
    asset_risk_score: Math.max(0, 100 - Number(payload.assets_without_room ?? 0) - Number(payload.assets_without_mol ?? 0)),
    security_risk_score: Math.max(0, 100 - Number(payload.failed_logins ?? 0)),
    ai_maturity_score: Number(payload.ai_acceptance_rate ?? 0),
    integrations_health_score: Number(payload.healthy_integrations ?? 0),
    workflow_automation_score: Number(payload.automation_success_rate ?? 0),
    top_5_problems: [
      { title: 'Open tickets', value: Number(payload.open_tickets ?? 0) },
      { title: 'Critical tickets', value: Number(payload.critical_tickets ?? 0) },
      { title: 'SLA breaches', value: Number(payload.breached_sla_count ?? 0) },
      { title: 'Assets without room', value: Number(payload.assets_without_room ?? 0) },
      { title: 'Failed logins', value: Number(payload.failed_logins ?? 0) },
    ],
    top_5_recommendations: [
      'Reduce open and critical ticket load.',
      'Improve SLA compliance for overdue queues.',
      'Close asset location and ownership gaps.',
      'Increase AI suggestion acceptance and article linkage.',
      'Investigate high risk security events quickly.',
    ],
  }
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
  const page = await fetchAutomationRulesPage(accessToken, {})
  return page.items
}

export async function fetchAutomationRulesPage(
  accessToken: string,
  params: { page?: number; page_size?: number; is_active?: boolean; trigger_type?: string; q?: string },
): Promise<PaginatedResponse<AutomationRule>> {
  const searchParams = new URLSearchParams()
  if (params.page !== undefined) searchParams.set('page', String(params.page))
  if (params.page_size !== undefined) searchParams.set('page_size', String(params.page_size))
  if (params.is_active !== undefined) searchParams.set('is_active', String(params.is_active))
  if (params.trigger_type) searchParams.set('trigger_type', params.trigger_type)
  if (params.q) searchParams.set('q', params.q)
  const suffix = searchParams.toString() ? `?${searchParams.toString()}` : ''
  const response = await fetch(`${API_BASE_URL}/automation/rules${suffix}`, {
    headers: { Authorization: `Bearer ${accessToken}` },
  })
  return readJsonResponse<PaginatedResponse<AutomationRule>>(response)
}

export async function fetchAutomationRule(accessToken: string, ruleId: string): Promise<AutomationRule> {
  const response = await fetch(`${API_BASE_URL}/automation/rules/${ruleId}`, {
    headers: { Authorization: `Bearer ${accessToken}` },
  })
  return readJsonResponse<AutomationRule>(response)
}

export async function createAutomationRule(
  accessToken: string,
  payload: {
    code: string
    name: string
    description?: string | null
    trigger_type: string
    conditions_json?: Record<string, unknown> | Array<unknown>
    actions_json?: Array<Record<string, unknown>>
    is_active?: boolean
    requires_approval?: boolean
    approval_role?: string | null
    cooldown_minutes?: number
    priority?: number
  },
): Promise<AutomationRule> {
  const response = await fetch(`${API_BASE_URL}/automation/rules`, {
    method: 'POST',
    headers: { Authorization: `Bearer ${accessToken}`, 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  })
  return readJsonResponse<AutomationRule>(response)
}

export async function updateAutomationRule(
  accessToken: string,
  ruleId: string,
  request: Partial<Pick<AutomationRule, 'name' | 'description' | 'trigger_type' | 'is_active' | 'priority'>> & {
    requires_approval?: boolean
    approval_role?: string | null
    cooldown_minutes?: number
    conditions_json?: Record<string, unknown> | Array<unknown>
    actions_json?: Array<Record<string, unknown>>
  },
): Promise<AutomationRule> {
  return patchAutomationRule(accessToken, ruleId, request)
}

export async function enableAutomationRule(accessToken: string, ruleId: string): Promise<AutomationRule> {
  const response = await fetch(`${API_BASE_URL}/automation/rules/${ruleId}/enable`, {
    method: 'POST',
    headers: { Authorization: `Bearer ${accessToken}` },
  })
  return readJsonResponse<AutomationRule>(response)
}

export async function disableAutomationRule(accessToken: string, ruleId: string): Promise<AutomationRule> {
  const response = await fetch(`${API_BASE_URL}/automation/rules/${ruleId}/disable`, {
    method: 'POST',
    headers: { Authorization: `Bearer ${accessToken}` },
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

export async function runAutomationRule(accessToken: string, ruleId: string, payload: Record<string, unknown>): Promise<Record<string, unknown>> {
  const response = await fetch(`${API_BASE_URL}/automation/rules/${ruleId}/run`, {
    method: 'POST',
    headers: { Authorization: `Bearer ${accessToken}`, 'Content-Type': 'application/json' },
    body: JSON.stringify({ payload }),
  })
  return readJsonResponse<Record<string, unknown>>(response)
}

export async function manualRunAutomationRule(accessToken: string, ruleId: string, request: { trigger_type?: string; context?: Record<string, unknown> }): Promise<{ run: AutomationRun; summary: Record<string, unknown> }> {
  const result = await runAutomationRule(accessToken, ruleId, {
    ...(request.context ?? {}),
    trigger_type: request.trigger_type ?? 'manual',
  })
  return {
    run: (result.execution as AutomationRun) ?? (result.run as AutomationRun),
    summary: (result.summary as Record<string, unknown>) ?? {},
  }
}

export async function fetchAutomationExecutionsPage(
  accessToken: string,
  params: { page?: number; page_size?: number; status?: string; rule_id?: string; trigger_type?: string },
): Promise<PaginatedResponse<AutomationRun>> {
  const searchParams = new URLSearchParams()
  if (params.page !== undefined) searchParams.set('page', String(params.page))
  if (params.page_size !== undefined) searchParams.set('page_size', String(params.page_size))
  if (params.status) searchParams.set('status', params.status)
  if (params.rule_id) searchParams.set('rule_id', params.rule_id)
  if (params.trigger_type) searchParams.set('trigger_type', params.trigger_type)
  const suffix = searchParams.toString() ? `?${searchParams.toString()}` : ''
  const response = await fetch(`${API_BASE_URL}/automation/executions${suffix}`, {
    headers: { Authorization: `Bearer ${accessToken}` },
  })
  return readJsonResponse<PaginatedResponse<AutomationRun>>(response)
}

export async function fetchAutomationRuns(accessToken: string): Promise<AutomationRun[]> {
  const page = await fetchAutomationExecutionsPage(accessToken, { page: 1, page_size: API_MAX_PAGE_SIZE })
  return page.items
}

export async function fetchAutomationExecution(accessToken: string, executionId: string): Promise<AutomationExecutionDetail> {
  const response = await fetch(`${API_BASE_URL}/automation/executions/${executionId}`, {
    headers: { Authorization: `Bearer ${accessToken}` },
  })
  return readJsonResponse<AutomationExecutionDetail>(response)
}

export async function retryAutomationExecution(accessToken: string, executionId: string): Promise<AutomationRun> {
  const response = await fetch(`${API_BASE_URL}/automation/executions/${executionId}/retry`, {
    method: 'POST',
    headers: { Authorization: `Bearer ${accessToken}` },
  })
  return readJsonResponse<AutomationRun>(response)
}

export async function fetchAutomationRunLogs(accessToken: string, runId: string): Promise<AutomationActionLog[]> {
  const detail = await fetchAutomationExecution(accessToken, runId)
  return detail.action_logs
}

export async function fetchRunbooksPage(
  accessToken: string,
  params: { page?: number; page_size?: number; active?: boolean; q?: string },
): Promise<PaginatedResponse<Runbook>> {
  const searchParams = new URLSearchParams()
  if (params.page !== undefined) searchParams.set('page', String(params.page))
  if (params.page_size !== undefined) searchParams.set('page_size', String(params.page_size))
  if (params.active !== undefined) searchParams.set('active', String(params.active))
  if (params.q) searchParams.set('q', params.q)
  const suffix = searchParams.toString() ? `?${searchParams.toString()}` : ''
  const response = await fetch(`${API_BASE_URL}/automation/runbooks${suffix}`, {
    headers: { Authorization: `Bearer ${accessToken}` },
  })
  return readJsonResponse<PaginatedResponse<Runbook>>(response)
}

export async function fetchRunbooks(accessToken: string): Promise<Runbook[]> {
  const page = await fetchRunbooksPage(accessToken, { page: 1, page_size: API_MAX_PAGE_SIZE })
  return page.items
}

export async function fetchRunbook(accessToken: string, runbookId: string): Promise<Runbook> {
  const response = await fetch(`${API_BASE_URL}/automation/runbooks/${runbookId}`, {
    headers: { Authorization: `Bearer ${accessToken}` },
  })
  return readJsonResponse<Runbook>(response)
}

export async function createRunbook(accessToken: string, payload: Record<string, unknown>): Promise<Runbook> {
  const response = await fetch(`${API_BASE_URL}/automation/runbooks`, {
    method: 'POST',
    headers: { Authorization: `Bearer ${accessToken}`, 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  })
  return readJsonResponse<Runbook>(response)
}

export async function updateRunbook(accessToken: string, runbookId: string, payload: Record<string, unknown>): Promise<Runbook> {
  const response = await fetch(`${API_BASE_URL}/automation/runbooks/${runbookId}`, {
    method: 'PATCH',
    headers: { Authorization: `Bearer ${accessToken}`, 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  })
  return readJsonResponse<Runbook>(response)
}

export async function dryRunRunbook(accessToken: string, runbookId: string, payload: Record<string, unknown>): Promise<AutomationRun> {
  const response = await fetch(`${API_BASE_URL}/automation/runbooks/${runbookId}/dry-run`, {
    method: 'POST',
    headers: { Authorization: `Bearer ${accessToken}`, 'Content-Type': 'application/json' },
    body: JSON.stringify({ payload }),
  })
  return readJsonResponse<AutomationRun>(response)
}

export async function runRunbook(accessToken: string, runbookId: string, payload: Record<string, unknown>): Promise<AutomationRun> {
  const response = await fetch(`${API_BASE_URL}/automation/runbooks/${runbookId}/run`, {
    method: 'POST',
    headers: { Authorization: `Bearer ${accessToken}`, 'Content-Type': 'application/json' },
    body: JSON.stringify({ payload }),
  })
  return readJsonResponse<AutomationRun>(response)
}

export async function fetchAutomationApprovalsPage(
  accessToken: string,
  params: { page?: number; page_size?: number; status?: string },
): Promise<PaginatedResponse<ApprovalRequest>> {
  const searchParams = new URLSearchParams()
  if (params.page !== undefined) searchParams.set('page', String(params.page))
  if (params.page_size !== undefined) searchParams.set('page_size', String(params.page_size))
  if (params.status) searchParams.set('status', params.status)
  const suffix = searchParams.toString() ? `?${searchParams.toString()}` : ''
  const response = await fetch(`${API_BASE_URL}/automation/approvals${suffix}`, {
    headers: { Authorization: `Bearer ${accessToken}` },
  })
  return readJsonResponse<PaginatedResponse<ApprovalRequest>>(response)
}

export async function fetchApprovalRequests(accessToken: string): Promise<ApprovalRequest[]> {
  const page = await fetchAutomationApprovalsPage(accessToken, { page: 1, page_size: API_MAX_PAGE_SIZE })
  return page.items
}

export async function fetchAutomationApproval(accessToken: string, approvalId: string): Promise<ApprovalRequest> {
  const response = await fetch(`${API_BASE_URL}/automation/approvals/${approvalId}`, {
    headers: { Authorization: `Bearer ${accessToken}` },
  })
  return readJsonResponse<ApprovalRequest>(response)
}

export async function approveAutomationApproval(accessToken: string, approvalId: string, payload: { comment?: string }): Promise<ApprovalRequest> {
  const response = await fetch(`${API_BASE_URL}/automation/approvals/${approvalId}/approve`, {
    method: 'POST',
    headers: { Authorization: `Bearer ${accessToken}`, 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  })
  return readJsonResponse<ApprovalRequest>(response)
}

export async function rejectAutomationApproval(accessToken: string, approvalId: string, payload: { comment?: string }): Promise<ApprovalRequest> {
  const response = await fetch(`${API_BASE_URL}/automation/approvals/${approvalId}/reject`, {
    method: 'POST',
    headers: { Authorization: `Bearer ${accessToken}`, 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  })
  return readJsonResponse<ApprovalRequest>(response)
}

export async function decideApprovalRequest(accessToken: string, approvalId: string, request: { decision: 'APPROVED' | 'REJECTED'; comment?: string }): Promise<ApprovalRequest> {
  if (request.decision === 'APPROVED') {
    return approveAutomationApproval(accessToken, approvalId, { comment: request.comment })
  }
  return rejectAutomationApproval(accessToken, approvalId, { comment: request.comment })
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

export async function patchAutomationRule(accessToken: string, ruleId: string, request: Partial<Pick<AutomationRule, 'name' | 'description' | 'trigger_type' | 'is_active' | 'priority'>> & { conditions_json?: Record<string, unknown> | Array<unknown>; actions_json?: Array<Record<string, unknown>> }): Promise<AutomationRule> {
  const response = await fetch(`${API_BASE_URL}/automation/rules/${ruleId}`, {
    method: 'PATCH',
    headers: { Authorization: `Bearer ${accessToken}`, 'Content-Type': 'application/json' },
    body: JSON.stringify(request),
  })
  return readJsonResponse<AutomationRule>(response)
}

export async function fetchTicketAutomationSuggestions(accessToken: string, ticketId: string): Promise<TicketAutomationSuggestion> {
  const response = await fetch(`${API_BASE_URL}/automation/tickets/${ticketId}/suggestions`, {
    headers: { Authorization: `Bearer ${accessToken}` },
  })
  return readJsonResponse<TicketAutomationSuggestion>(response)
}

/* legacy alias */
export const retryAutomationRun = retryAutomationExecution

/* existing block kept for compatibility */
export async function fetchAutomationRulesLegacy(accessToken: string): Promise<AutomationRule[]> {
  const response = await fetch(`${API_BASE_URL}/automation/rules`, {
    headers: { Authorization: `Bearer ${accessToken}` },
  })
  const payload = await readJsonResponse<PaginatedResponse<AutomationRule> | AutomationRule[]>(response)
  return Array.isArray(payload) ? payload : payload.items
}

export async function fetchSavedReports(accessToken: string): Promise<SavedReport[]> {
  const response = await fetch(`${API_BASE_URL}/reports`, {
    headers: { Authorization: `Bearer ${accessToken}` },
  })
  return readJsonResponse<SavedReport[]>(response)
}

export async function createSavedReport(
  accessToken: string,
  request: { name: string; report_type: string; filters_json?: Record<string, unknown>; visibility?: string; schedule_enabled?: boolean },
): Promise<SavedReport> {
  const response = await fetch(`${API_BASE_URL}/reports`, {
    method: 'POST',
    headers: { Authorization: `Bearer ${accessToken}`, 'Content-Type': 'application/json' },
    body: JSON.stringify(request),
  })
  return readJsonResponse<SavedReport>(response)
}

export async function fetchReportById(accessToken: string, reportId: string): Promise<SavedReport> {
  const response = await fetch(`${API_BASE_URL}/reports/${reportId}`, {
    headers: { Authorization: `Bearer ${accessToken}` },
  })
  return readJsonResponse<SavedReport>(response)
}

export async function runSavedReport(accessToken: string, reportId: string): Promise<ReportSnapshot> {
  const response = await fetch(`${API_BASE_URL}/reports/${reportId}/run`, {
    method: 'POST',
    headers: { Authorization: `Bearer ${accessToken}` },
  })
  return readJsonResponse<ReportSnapshot>(response)
}

export async function fetchReportSnapshots(accessToken: string): Promise<ReportSnapshot[]> {
  const response = await fetch(`${API_BASE_URL}/reports/snapshots`, {
    headers: { Authorization: `Bearer ${accessToken}` },
  })
  return readJsonResponse<ReportSnapshot[]>(response)
}

export async function createReportSnapshot(
  accessToken: string,
  request: { report_type?: string | null; saved_report_id?: string | null; filters_json?: Record<string, unknown>; period_from?: string | null; period_to?: string | null },
): Promise<ReportSnapshot> {
  const response = await fetch(`${API_BASE_URL}/reports/snapshots`, {
    method: 'POST',
    headers: { Authorization: `Bearer ${accessToken}`, 'Content-Type': 'application/json' },
    body: JSON.stringify(request),
  })
  return readJsonResponse<ReportSnapshot>(response)
}

export async function fetchSnapshotById(accessToken: string, snapshotId: string): Promise<ReportSnapshot> {
  const response = await fetch(`${API_BASE_URL}/reports/snapshots/${snapshotId}`, {
    headers: { Authorization: `Bearer ${accessToken}` },
  })
  return readJsonResponse<ReportSnapshot>(response)
}

export async function exportReport(
  accessToken: string,
  request: { report_type: string; format: 'json' | 'csv'; filters_json?: Record<string, unknown> },
): Promise<DemoExport | string> {
  const response = await fetch(`${API_BASE_URL}/reports/export`, {
    method: 'POST',
    headers: { Authorization: `Bearer ${accessToken}`, 'Content-Type': 'application/json' },
    body: JSON.stringify(request),
  })
  if (!response.ok) {
    const errorPayload = (await response.json().catch(() => null)) as { error?: { message?: string } } | null
    throw new Error(errorPayload?.error?.message ?? `Backend returned ${response.status}`)
  }
  if (request.format === 'csv') {
    return response.text()
  }
  return response.json() as Promise<DemoExport>
}

export async function fetchDemoExport(accessToken: string, params?: { report_type?: string; format?: string }): Promise<DemoExport> {
  const search = new URLSearchParams()
  if (params?.report_type) search.set('report_type', params.report_type)
  search.set('format', 'json')
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
  const payload = await readJsonResponse<IntegrationSystem[] | IntegrationSystemV2[] | PaginatedResponse<IntegrationSystemV2>>(response)
  const items = Array.isArray(payload) ? payload : payload.items
  return items.map((raw) => {
    const item = raw as Record<string, unknown>
    return {
      id: String(item.id ?? ''),
      tenant_id: (item.tenant_id as string | null) ?? null,
      code: String(item.code ?? ''),
      name: String(item.name ?? ''),
      system_type: String(item.system_type ?? ''),
      base_url: (item.base_url as string | null) ?? null,
      status: String(item.status ?? ''),
      is_enabled: Boolean(item.is_enabled),
      last_health_status: (item.health_status as string | null) ?? (item.last_health_status as string | null) ?? null,
      last_health_checked_at: (item.last_health_check_at as string | null) ?? (item.last_health_checked_at as string | null) ?? null,
      description: (item.description as string | null) ?? null,
      created_at: String(item.created_at ?? ''),
      updated_at: String(item.updated_at ?? ''),
      capabilities: [],
    }
  })
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
  const payload = await readJsonResponse<IntegrationEvent[] | IntegrationEventV2[] | PaginatedResponse<IntegrationEventV2>>(response)
  const items = Array.isArray(payload) ? payload : payload.items
  return items.map((raw) => {
    const item = raw as Record<string, unknown>
    return {
      id: String(item.id ?? ''),
      tenant_id: (item.tenant_id as string | null) ?? null,
      external_system_id: (item.external_system_id as string | null) ?? null,
      direction: String(item.direction ?? ''),
      event_type: String(item.event_type ?? ''),
      status: String(item.status ?? ''),
      request_summary: (item.payload as Record<string, unknown>) ?? (item.request_summary as Record<string, unknown>) ?? {},
      response_summary: (item.response_payload as Record<string, unknown>) ?? (item.response_summary as Record<string, unknown>) ?? {},
      error_message: (item.error_message as string | null) ?? null,
      correlation_id: (item.correlation_id as string | null) ?? null,
      created_at: String(item.created_at ?? ''),
    }
  })
}

export async function fetchIntegrationImportJobs(accessToken: string): Promise<IntegrationImportJob[]> {
  const response = await fetch(`${API_BASE_URL}/integrations/import-jobs`, {
    headers: { Authorization: `Bearer ${accessToken}` },
  })
  const payload = await readJsonResponse<IntegrationImportJob[] | IntegrationImportJobV2[] | PaginatedResponse<IntegrationImportJobV2>>(response)
  const items = Array.isArray(payload) ? payload : payload.items
  return items.map((raw) => {
    const item = raw as Record<string, unknown>
    return {
      id: String(item.id ?? ''),
      tenant_id: (item.tenant_id as string | null) ?? null,
      external_system_id: (item.external_system_id as string | null) ?? null,
      job_type: String(item.job_type ?? ''),
      status: String(item.status ?? ''),
      records_total: Number(item.records_total ?? item.total_rows ?? 0),
      records_success: Number(item.records_success ?? item.success_rows ?? 0),
      records_failed: Number(item.records_failed ?? item.failed_rows ?? 0),
      started_at: (item.started_at as string | null) ?? null,
      finished_at: (item.finished_at as string | null) ?? null,
      error_message: (item.error_message as string | null) ?? null,
      created_at: String(item.created_at ?? ''),
    }
  })
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
  const payload = await readJsonResponse<IntegrationWebhook[] | IntegrationWebhookV2[] | PaginatedResponse<IntegrationWebhookV2>>(response)
  const items = Array.isArray(payload) ? payload : payload.items
  return items.map((raw) => {
    const item = raw as Record<string, unknown>
    return {
      id: String(item.id ?? ''),
      tenant_id: (item.tenant_id as string | null) ?? null,
      name: String(item.name ?? ''),
      path: String(item.path ?? ''),
      target_system: String(item.event_type ?? item.target_system ?? 'webhook'),
      is_active: Boolean(item.is_active),
      secret_ref: Boolean(item.secret_required) ? 'required' : ((item.secret_ref as string | null) ?? null),
      created_at: String(item.created_at ?? ''),
      updated_at: String(item.updated_at ?? ''),
    }
  })
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
  const payload = await readJsonResponse<IntegrationMapping[] | IntegrationMappingV2[] | PaginatedResponse<IntegrationMappingV2>>(response)
  const items = Array.isArray(payload) ? payload : payload.items
  return items.map((raw) => {
    const item = raw as Record<string, unknown>
    const sourceField = (item.source_field as string | null) ?? (item.source_entity as string | null) ?? 'unknown_source'
    const targetField = (item.target_field as string | null) ?? (item.target_entity as string | null) ?? 'unknown_target'
    return {
      id: String(item.id ?? ''),
      tenant_id: (item.tenant_id as string | null) ?? null,
      external_system_id: (item.external_system_id as string | null) ?? null,
      source_entity: sourceField,
      target_entity: targetField,
      mapping_json: (item.mapping_json as Record<string, unknown>) ?? (sourceField && targetField ? { [sourceField]: targetField } : {}),
      is_active: Boolean(item.is_active),
      created_at: String(item.created_at ?? ''),
      updated_at: String(item.updated_at ?? ''),
    }
  })
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
