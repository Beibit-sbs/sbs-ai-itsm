export const API_BASE_URL =
  import.meta.env.VITE_API_BASE_URL ?? '/api/v1'

const API_MAX_PAGE_SIZE = 200
const AUTH_SESSION_STORAGE_KEY = 'sbs-ai-itsm-session'
const rawFetch = globalThis.fetch.bind(globalThis)
let refreshInFlight: Promise<AuthSession | null> | null = null

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
  mfa_enabled: boolean
  mfa_verified: boolean
  must_change_password: boolean
}

export type AuthSession = {
  access_token: string
  token_type: string
  user: AuthUser
}

export type MfaChallenge = {
  mfa_required: true
  challenge_token: string
  expires_in_seconds: number
  methods: Array<'totp' | 'recovery_code' | string>
}

export type LoginResult = AuthSession | MfaChallenge

export type MfaStatus = {
  enabled: boolean
  verified_at: string | null
  recovery_codes_remaining: number
  locked: boolean
  policy_enforced: boolean
  required_for_role: boolean
  current_session_verified: boolean
}

export type MfaEnrollment = {
  secret: string
  otpauth_uri: string
  issuer: string
  account_name: string
}

export type MfaRecoveryCodes = {
  recovery_codes: string[]
  requires_reauthentication: boolean
}

export type MfaUserStatus = {
  user_id: string
  email: string
  full_name: string
  role: string
  active: boolean
  required: boolean
  enabled: boolean
  verified_at: string | null
  recovery_codes_remaining: number
  locked: boolean
}

export type MfaOverview = {
  enforcement_enabled: boolean
  required_role_codes: string[]
  total_users: number
  enrolled_users: number
  required_users: number
  required_users_without_mfa: number
  current_session_verified: boolean
  users: MfaUserStatus[]
}

export type AccountProfile = {
  id: string
  email: string
  full_name: string
  tenant_id: string | null
  role: string
  identity_source: 'LOCAL' | 'OIDC' | 'SCIM' | 'ENTRA' | string
  provisioning_state: string
  local_password_supported: boolean
  must_change_password: boolean
  last_login_at: string | null
}

export type SelfAuthSession = {
  id: string
  created_at: string
  refresh_expires_at: string
  revoked_at: string | null
  replaced_by_id: string | null
  ip_address: string | null
  user_agent: string | null
  auth_method: string | null
  is_active: boolean
  is_current: boolean
}

export type SsoConfig = {
  enabled: boolean
  provider_name: string | null
  button_label: string | null
  login_path: string | null
}

function readStoredAuthSession(): AuthSession | null {
  if (typeof window === 'undefined') return null
  const stored = window.sessionStorage.getItem(AUTH_SESSION_STORAGE_KEY)
  if (!stored) return null

  try {
    return JSON.parse(stored) as AuthSession
  } catch {
    return null
  }
}

function writeStoredAuthSession(session: AuthSession) {
  if (typeof window === 'undefined') return
  window.sessionStorage.setItem(AUTH_SESSION_STORAGE_KEY, JSON.stringify(session))
  window.dispatchEvent(new Event('sbs-auth-session-updated'))
}

function clearStoredAuthSession() {
  if (typeof window === 'undefined') return
  window.sessionStorage.removeItem(AUTH_SESSION_STORAGE_KEY)
  window.dispatchEvent(new Event('sbs-auth-session-updated'))
}

async function refreshStoredAuthSession(): Promise<AuthSession | null> {
  if (refreshInFlight) return refreshInFlight

  refreshInFlight = performStoredSessionRefresh()
  try {
    return await refreshInFlight
  } finally {
    refreshInFlight = null
  }
}

async function performStoredSessionRefresh(): Promise<AuthSession | null> {
  const storedSession = readStoredAuthSession()
  if (!storedSession) return null

  const response = await rawFetch(`${API_BASE_URL}/auth/refresh`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    credentials: 'include',
  })

  if (!response.ok) return null

  const refreshedSession = await readJsonResponse<AuthSession>(response)
  writeStoredAuthSession(refreshedSession)
  return refreshedSession
}

async function fetchWithAuthRetry(input: RequestInfo | URL, init: RequestInit | undefined, accessToken: string): Promise<Response> {
  const response = await rawFetch(input, {
    ...init,
    headers: {
      ...(init?.headers ?? {}),
      Authorization: `Bearer ${accessToken}`,
    },
  })

  if (response.status !== 401) return response

  const refreshedSession = await refreshStoredAuthSession()
  if (!refreshedSession?.access_token) return response

  const retryResponse = await rawFetch(input, {
    ...init,
    headers: {
      ...(init?.headers ?? {}),
      Authorization: `Bearer ${refreshedSession.access_token}`,
    },
  })

  if (retryResponse.status === 401) {
    clearStoredAuthSession()
  }

  return retryResponse
}

if (typeof window !== 'undefined') {
  const targetWindow = window as Window & { __sbsAuthFetchPatched?: boolean }
  if (!targetWindow.__sbsAuthFetchPatched) {
    targetWindow.__sbsAuthFetchPatched = true
    globalThis.fetch = (async (input: RequestInfo | URL, init?: RequestInit) => {
      const requestUrl = typeof input === 'string'
        ? input
        : input instanceof URL
          ? input.toString()
          : input.url
      const authorizationHeader = typeof init?.headers === 'object' && init?.headers !== null && 'Authorization' in init.headers
        ? String((init.headers as Record<string, string>).Authorization ?? '')
        : ''
      const shouldRetry = authorizationHeader.startsWith('Bearer ') && !requestUrl.includes('/auth/login') && !requestUrl.includes('/auth/refresh')

      const response = await rawFetch(input, init)
      if (!shouldRetry || response.status !== 401) {
        return response
      }

      const refreshedSession = await refreshStoredAuthSession()
      if (!refreshedSession?.access_token) {
        clearStoredAuthSession()
        return response
      }

      const retryHeaders: Record<string, string> = {}
      if (typeof init?.headers === 'object' && init.headers !== null && !Array.isArray(init.headers)) {
        for (const [key, value] of Object.entries(init.headers as Record<string, string>)) {
          retryHeaders[key] = value
        }
      }
      retryHeaders.Authorization = `Bearer ${refreshedSession.access_token}`

      const retryResponse = await rawFetch(input, { ...init, headers: retryHeaders })
      if (retryResponse.status === 401) {
        clearStoredAuthSession()
      }
      return retryResponse
    }) as typeof fetch
  }
}

export type Tenant = {
  id: string
  name: string
  slug: string
  status: string
  description: string | null
  created_at: string
  updated_at: string
}

export type TenantTerminology = {
  incident_singular: string
  incident_plural: string
  request_singular: string
  request_plural: string
  asset_singular: string
  asset_plural: string
  service_singular: string
  service_plural: string
  knowledge_base: string
}

export type TenantBrandLogo = {
  asset_id: string
  content_type: string
  data_url: string
  sha256: string
  size_bytes: number
  width: number
  height: number
}

export type TenantExperienceCapabilities = {
  ui_locales: string[]
  format_locales: string[]
  currencies: string[]
  date_styles: Array<'short' | 'medium' | 'long' | string>
  hour_cycles: Array<'h23' | 'h12' | string>
  first_days_of_week: number[]
  suggested_timezones: string[]
  logo_content_types: string[]
  logo_max_bytes: number
}

export type TenantExperience = {
  tenant_id: string | null
  revision: number
  is_default: boolean
  product_name: string
  short_name: string
  primary_color: string
  accent_color: string
  surface_color: string
  text_color: string
  ui_locale: string
  format_locale: string
  timezone: string
  currency_code: string
  date_style: 'short' | 'medium' | 'long'
  hour_cycle: 'h23' | 'h12'
  first_day_of_week: number
  terminology: TenantTerminology
  logo: TenantBrandLogo | null
  contrast: Record<string, number | string>
  etag: string
  updated_at: string | null
  capabilities: TenantExperienceCapabilities
}

export type TenantExperienceSettings = Pick<
  TenantExperience,
  | 'product_name'
  | 'short_name'
  | 'primary_color'
  | 'accent_color'
  | 'surface_color'
  | 'text_color'
  | 'ui_locale'
  | 'format_locale'
  | 'timezone'
  | 'currency_code'
  | 'date_style'
  | 'hour_cycle'
  | 'first_day_of_week'
  | 'terminology'
>

export type TenantExperienceRevision = {
  revision: number
  snapshot_sha256: string
  integrity_valid: boolean
  changed_by_id: string | null
  change_reason: string
  rolled_back_from_revision: number | null
  created_at: string
}

export type LocalizedResourceType =
  | 'KNOWLEDGE_ARTICLE'
  | 'NOTIFICATION_TEMPLATE'

export type LocalizedContentVariant = {
  id: string
  tenant_id: string
  resource_type: LocalizedResourceType
  resource_id: string
  locale: 'ru-RU' | 'kk-KZ' | 'en-US' | string
  version: number
  revision: number
  status: 'DRAFT' | 'IN_REVIEW' | 'PUBLISHED' | 'REJECTED' | 'RETIRED'
  source_sha256: string
  source_current: boolean
  payload: Record<string, string>
  payload_sha256: string
  integrity_valid: boolean
  created_by_id: string | null
  updated_by_id: string | null
  reviewed_by_id: string | null
  review_comment: string | null
  submitted_at: string | null
  reviewed_at: string | null
  published_at: string | null
  created_at: string
  updated_at: string
}

export type LocalizedContentSource = {
  id: string
  resource_type: LocalizedResourceType
  source_tenant_id: string | null
  inherited: boolean
  code: string
  label: string
  payload: Record<string, string>
  source_sha256: string
  updated_at: string
}

export type IdentityProviderStatus = {
  enabled: boolean
  ready: boolean
  provider_name: string
  button_label: string
  issuer_url: string | null
  redirect_uri: string | null
  client_id_configured: boolean
  client_secret_configured: boolean
  client_auth_method: string
  scopes: string[]
  allowed_algorithms: string[]
  allowed_email_domains: string[]
  auto_provision: boolean
  allow_email_linking: boolean
  default_tenant_id: string | null
  default_role_code: string
  configuration_source: string
  linked_identities: number
  linked_users: number
  successful_logins_24h: number
  failed_logins_24h: number
  readiness_issues: string[]
}

export type IdentityProviderTestResult = {
  success: boolean
  reason: string | null
  issuer: string | null
  authorization_endpoint_host: string | null
  token_endpoint_host: string | null
  jwks_host: string | null
}

export type ExternalIdentity = {
  id: string
  user_id: string
  provider_name: string
  issuer: string
  subject: string
  email_at_link: string
  created_at: string
  last_login_at: string | null
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
  tenant_id: string | null
  ticket_number: string | null
  title: string
  description: string | null
  requester_id: string | null
  requester_name: string
  requester_email: string
  requester_contact: string | null
  created_by_id: string | null
  created_by_name: string | null
  creation_channel: 'SELF_SERVICE' | 'ON_BEHALF' | 'LEGACY'
  parent_ticket_id: string | null
  merged_into_id: string | null
  governance_version: number
  merge_reason: string | null
  merged_by_id: string | null
  merged_by_name: string | null
  merged_at: string | null
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
  allowed_transitions: string[]
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

export type TicketParticipant = {
  id: string
  ticket_id: string
  user_id: string | null
  display_name: string
  email: string
  participant_role: 'WATCHER' | 'COLLABORATOR' | 'REQUESTER_REPRESENTATIVE'
  notification_scope: 'ALL' | 'PUBLIC_ONLY' | 'STATUS_ONLY' | 'NONE'
  notify_in_app: boolean
  notify_email: boolean
  is_active: boolean
  version_number: number
  added_by_id: string | null
  removed_at: string | null
  created_at: string
  updated_at: string
}

export type TicketParticipantCandidate = {
  id: string
  full_name: string
  email: string
  role: string
}

export type TicketRequesterCandidate = {
  id: string
  full_name: string
  email: string
  department: string | null
  location: string | null
  phone: string | null
  role: string
}

export type TicketDuplicateCandidate = {
  id: string
  ticket_number: string | null
  title: string
  requester_name: string
  requester_email: string
  category: string
  priority: string
  status: string
  created_at: string
  governance_version: number
  score: number
  evidence: string[]
  pair_key: string
}

export type TicketGovernanceAction = {
  id: string
  action_type: 'DUPLICATE_DISMISSED' | 'MERGED' | 'SPLIT'
  source_ticket_id: string
  target_ticket_id: string | null
  reason: string
  actor_name: string
  score: number | null
  evidence: Record<string, unknown> | null
  created_at: string
}

export type TicketGovernanceResult = {
  action: TicketGovernanceAction
  source_ticket_id: string
  target_ticket_id: string | null
  source_version: number
  target_version: number | null
  already_applied: boolean
}

export type MajorIncident = {
  id: string
  tenant_id: string
  ticket_id: string
  ticket_number: string | null
  major_number: string
  severity: 'SEV1' | 'SEV2'
  status: string
  title: string
  executive_summary: string
  impact_statement: string
  affected_service: string
  service_status: string
  customer_impact: string
  war_room_url: string | null
  conference_details: string | null
  commander_user_id: string
  commander_name: string | null
  communications_lead_user_id: string
  communications_lead_name: string | null
  declared_by_id: string | null
  declared_at: string
  next_update_due_at: string
  communication_overdue: boolean
  resolved_at: string | null
  closed_at: string | null
  cancelled_at: string | null
  version: number
  participants: Array<{ id: string; role: string; user_id: string | null; display_name: string; contact: string | null; created_at: string }>
  child_tickets: Array<{ id: string; ticket_number: string | null; title: string; status: string; priority: string }>
  updates: Array<{ id: string; update_type: string; audience: string; message: string; service_status: string | null; channel: string | null; actor_name: string; created_at: string }>
  pir: null | { id: string; status: string; summary: string; root_cause: string; contributing_factors: string; lessons_learned: string; prevention_plan: string; prepared_by_id: string | null; approved_by_id: string | null; approved_at: string | null; version: number }
  actions: Array<{ id: string; title: string; description: string; owner_user_id: string; owner_name: string | null; due_at: string; status: string; completion_evidence: string | null; completed_at: string | null; overdue: boolean; version: number }>
  created_at: string
  updated_at: string
}

export type MajorIncidentSummary = {
  active: number
  sev1_active: number
  communications_overdue: number
  resolved_awaiting_pir: number
}

export type MajorIncidentResponder = {
  id: string
  full_name: string
  position: string | null
  department: string | null
}

export type EventMatcher = {
  field: string
  operator: 'EQUALS' | 'NOT_EQUALS' | 'CONTAINS' | 'PREFIX' | 'EXISTS'
  value: string
}

export type EventOperationsSummary = {
  events_24h: number
  firing_24h: number
  suppressed_24h: number
  duplicates_lifetime: number
  open_groups: number
  ack_overdue: number
  incidents_24h: number
  noise_reduction_percent: number
  mtta_minutes_24h: number | null
}

export type EventSource = {
  id: string
  tenant_id: string
  code: string
  name: string
  source_type: string
  auth_mode: 'BEARER' | 'HMAC_SHA256'
  token_hint: string
  hmac_secret_hint: string | null
  hmac_configured: boolean
  replay_window_seconds: number
  rate_limit_per_minute: number
  max_payload_bytes: number
  allowed_ip_cidrs: string[]
  is_enabled: boolean
  total_events: number
  duplicate_events: number
  suppressed_events: number
  last_event_at: string | null
  last_error: string | null
  last_success_at: string | null
  last_failure_at: string | null
  success_count: number
  failure_count: number
  dead_letter_count: number
  version: number
  created_at: string
  updated_at: string
  ingest_token?: string
  signing_secret?: string
}

export type MonitoringWebhookReceipt = {
  id: string
  tenant_id: string
  source_id: string
  provider_type: string
  body_hash: string
  payload_size: number
  content_type: string | null
  source_ip: string | null
  signature_verified: boolean
  request_timestamp: string | null
  status: string
  attempts: number
  max_attempts: number
  next_attempt_at: string
  normalized_event_count: number
  duplicate_event_count: number
  incident_count: number
  last_error: string | null
  received_at: string
  processing_started_at: string | null
  processed_at: string | null
  created_at: string
  updated_at: string
}

export type EventResponder = {
  id: string
  full_name: string
  position: string | null
  department: string | null
}

export type EventCorrelationPolicy = {
  id: string
  tenant_id: string
  name: string
  description: string | null
  is_active: boolean
  priority_order: number
  matchers: EventMatcher[]
  group_by: string[]
  correlation_window_minutes: number
  min_occurrences: number
  incident_mode: 'CREATE_UPDATE' | 'CORRELATE_ONLY' | 'IGNORE'
  fixed_priority: string | null
  category: string
  title_template: string
  resolution_action: 'NONE' | 'RESOLVE' | 'CLOSE'
  primary_user_id: string | null
  primary_user_name: string | null
  fallback_user_id: string | null
  fallback_user_name: string | null
  acknowledge_within_minutes: number
  escalate_after_minutes: number
  version: number
  created_at: string
  updated_at: string
}

export type EventSuppressionRule = {
  id: string
  tenant_id: string
  name: string
  reason: string
  matchers: EventMatcher[]
  starts_at: string | null
  ends_at: string | null
  is_active: boolean
  version: number
  created_at: string
  updated_at: string
}

export type NormalizedEvent = {
  id: string
  source_id: string
  source_name: string | null
  external_id: string
  fingerprint: string
  state: 'FIRING' | 'RESOLVED'
  severity: string
  summary: string
  description: string | null
  service: string | null
  resource: string | null
  environment: string | null
  labels: Record<string, string>
  annotations: Record<string, string>
  raw_payload_hash: string
  occurred_at: string
  received_at: string
  disposition: string
  suppression_rule_id: string | null
  correlation_policy_id: string | null
  correlation_group_id: string | null
  ticket_id: string | null
  ticket_number: string | null
}

export type EventGroupActivity = {
  id: string
  event_id: string | null
  activity_type: string
  actor_name: string
  message: string
  metadata: Record<string, unknown>
  created_at: string
}

export type EventCorrelationGroup = {
  id: string
  tenant_id: string
  policy_id: string
  policy_name: string | null
  correlation_key: string
  title: string
  status: 'OPEN' | 'RESOLVED'
  severity: string
  first_event_at: string
  last_event_at: string
  occurrence_count: number
  ticket_id: string | null
  ticket_number: string | null
  ticket_status: string | null
  assigned_user_id: string | null
  assigned_user_name: string | null
  acknowledged_by_id: string | null
  acknowledged_by_name: string | null
  acknowledged_at: string | null
  next_escalation_at: string | null
  escalation_level: number
  escalated_at: string | null
  resolved_at: string | null
  version: number
  created_at: string
  updated_at: string
  events?: NormalizedEvent[]
  activities?: EventGroupActivity[]
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
  on_behalf_reason?: string | null
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
  expected_version?: number
  idempotency_key?: string
  satisfaction_score?: number
  reopen_reason?: string
}

export type TicketAssignRequest = {
  assignee_id?: string | null
  comment?: string
}

export type Asset = {
  id: string
  ci_class_id: string | null
  ci_class_version_id: string | null
  ci_class_code: string | null
  ci_class_name: string | null
  ci_schema_version: number | null
  ci_schema_hash: string | null
  ci_attributes: Record<string, unknown>
  lifecycle_status: string
  owner_user_id: string | null
  support_group: string | null
  criticality: 'LOW' | 'MEDIUM' | 'HIGH' | 'CRITICAL'
  environment: 'PRODUCTION' | 'STAGING' | 'TEST' | 'DEVELOPMENT' | 'OTHER'
  ci_version: number
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

export type SoftwareComplianceState =
  | 'COMPLIANT'
  | 'UNDERUTILIZED'
  | 'OVER_DEPLOYED'
  | 'UNLICENSED'
  | 'EXPIRED'
  | 'UNAUTHORIZED'
  | 'PROHIBITED'

export type SoftwareProduct = {
  id: string
  tenant_id: string
  name: string
  publisher: string
  version: string
  edition: string | null
  category: string | null
  sku: string | null
  status: 'ACTIVE' | 'RETIRED'
  is_prohibited: boolean
  prohibited_reason: string | null
  version_number: number
  created_at: string
  updated_at: string
}

export type SoftwareLicense = {
  id: string
  tenant_id: string
  product_id: string
  product_name: string
  license_reference: string
  license_type: string
  purchased_quantity: number
  vendor: string | null
  contract_reference: string | null
  starts_at: string | null
  expires_at: string | null
  renewal_at: string | null
  auto_renew: boolean
  unit_cost: string
  currency: string
  status: 'ACTIVE' | 'SUSPENDED' | 'EXPIRED' | 'RETIRED'
  version_number: number
  created_at: string
  updated_at: string
}

export type SoftwareInstallation = {
  id: string
  tenant_id: string
  product_id: string
  product_name: string
  asset_id: string
  asset_tag: string
  asset_name: string
  assigned_user_id: string | null
  detected_version: string | null
  source: string
  authorization_status: 'AUTHORIZED' | 'UNAUTHORIZED' | 'EXEMPTED'
  authorization_reason: string | null
  status: 'ACTIVE' | 'REMOVED'
  discovered_at: string
  last_seen_at: string
  removed_at: string | null
  version_number: number
  created_at: string
  updated_at: string
}

export type SoftwareCompliancePosition = {
  product_id: string
  name: string
  publisher: string
  version: string
  edition: string | null
  status: string
  is_prohibited: boolean
  purchased_quantity: number
  assigned_quantity: number
  detected_quantity: number
  unauthorized_quantity: number
  available_quantity: number
  shortfall_quantity: number
  compliance_state: SoftwareComplianceState
  purchase_cost_by_currency: Record<string, number>
  cost_at_risk_by_currency: Record<string, number>
}

export type SoftwareAssetDashboard = {
  tenant_id: string
  generated_at: string
  summary: {
    products: number
    licenses: number
    active_installations: number
    compliant_products: number
    noncompliant_products: number
    unauthorized_installations: number
    upcoming_renewals: number
    purchase_cost_by_currency: Record<string, number>
    cost_at_risk_by_currency: Record<string, number>
  }
  positions: SoftwareCompliancePosition[]
  renewals: Array<{
    license_id: string
    license_reference: string
    product_id: string
    product_name: string
    due_at: string
    status: 'OVERDUE' | 'UPCOMING'
    auto_renew: boolean
    purchased_quantity: number
    unit_cost: number
    currency: string
  }>
  unauthorized_installations: Array<{
    installation_id: string
    product_id: string
    product_name: string
    asset_id: string
    asset_tag: string | null
    asset_name: string | null
    authorization_status: string
    prohibited: boolean
    last_seen_at: string
  }>
}

export type CIClassField = {
  key: string
  label: string
  type: 'text' | 'textarea' | 'integer' | 'number' | 'boolean' | 'date' | 'datetime' | 'email' | 'select' | 'multiselect'
  required: boolean
  description: string
  options: Array<{ value: string; label: string }>
  inherited?: boolean
}

export type CIClassVersion = {
  id: string
  ci_class_id: string
  parent_version_id: string | null
  version: number
  revision: number
  status: 'DRAFT' | 'PUBLISHED' | 'RETIRED'
  schema: { fields: CIClassField[] }
  effective_schema: { fields: CIClassField[] }
  schema_hash: string
  published_at: string | null
  retired_at: string | null
  created_at: string
  updated_at: string
}

export type CIClass = {
  id: string
  tenant_id: string
  parent_class_id: string | null
  parent_class_name: string | null
  code: string
  name: string
  description: string | null
  status: 'DRAFT' | 'ACTIVE' | 'RETIRED'
  published_version: CIClassVersion | null
  draft_version: CIClassVersion | null
  created_at: string
  updated_at: string
}

export type CreateCIClassRequest = {
  tenant_id?: string
  parent_class_id?: string | null
  code: string
  name: string
  description?: string | null
  schema: { fields: CIClassField[] }
}

export type CreateConfigurationItemRequest = {
  ci_class_id: string
  asset_tag: string
  name: string
  inventory_number?: string | null
  serial_number?: string | null
  manufacturer?: string | null
  model?: string | null
  lifecycle_status: 'PLANNING' | 'ORDERED' | 'IN_STOCK' | 'ACTIVE' | 'MAINTENANCE' | 'RETIRED' | 'DISPOSED'
  support_group?: string | null
  criticality: Asset['criticality']
  environment: Asset['environment']
  location: string
  condition?: string
  description?: string | null
  attributes: Record<string, unknown>
}

export type ConfigurationItemSummary = {
  id: string
  tenant_id: string | null
  asset_tag: string
  name: string
  ci_class_id: string | null
  ci_class_version_id: string | null
  ci_class_code: string | null
  ci_class_name: string | null
  ci_schema_version: number | null
  ci_schema_hash: string | null
  attributes: Record<string, unknown>
  lifecycle_status: string
  owner_user_id: string | null
  owner_name: string
  support_group: string | null
  criticality: string
  environment: string
  version: number
  status: string
  created_at: string
  updated_at: string
}

export type CIRelationshipType = {
  id: string
  tenant_id: string
  code: string
  name: string
  forward_label: string
  reverse_label: string
  description: string | null
  source_class_id: string | null
  source_class_name: string | null
  target_class_id: string | null
  target_class_name: string | null
  source_cardinality: 'ONE' | 'MANY'
  target_cardinality: 'ONE' | 'MANY'
  allow_self_relationship: boolean
  allow_cycles: boolean
  status: 'ACTIVE' | 'INACTIVE'
  version: number
  active_relationships: number
  created_at: string
  updated_at: string
}

export type CINode = {
  id: string
  asset_tag: string
  name: string
  ci_class_id: string | null
  ci_class_code: string | null
  ci_class_name: string | null
  lifecycle_status: string
  criticality: string
  environment: string
  support_group: string | null
  depth: number | null
}

export type CIRelationship = {
  id: string
  tenant_id: string
  relationship_type_id: string
  relationship_type_code: string
  relationship_type_name: string
  forward_label: string
  reverse_label: string
  source: CINode
  target: CINode
  status: 'ACTIVE' | 'RETIRED'
  version: number
  description: string | null
  created_at: string
  updated_at: string
  retired_at: string | null
}

export type CITopology = {
  root_ci_id: string
  direction: 'upstream' | 'downstream' | 'both'
  requested_depth: number
  nodes: CINode[]
  edges: CIRelationship[]
  truncated: boolean
}

export type CMDBSource = {
  id: string
  tenant_id: string
  external_system_id: string | null
  external_system_name: string | null
  default_class_id: string | null
  default_class_name: string | null
  code: string
  name: string
  description: string | null
  source_type: 'FILE' | 'API' | 'DISCOVERY' | 'MANUAL'
  priority: number
  identification_rules: string[]
  authoritative_fields: string[]
  claim_unowned_fields: boolean
  stale_after_hours: number
  status: 'ACTIVE' | 'INACTIVE'
  version: number
  is_stale: boolean
  last_run_at: string | null
  last_success_at: string | null
  created_at: string
  updated_at: string
}

export type CMDBInputRecord = {
  external_id: string
  ci_class_id?: string
  name?: string
  asset_tag?: string
  inventory_number?: string
  serial_number?: string
  manufacturer?: string
  model?: string
  original_type?: string
  lifecycle_status?: 'PLANNING' | 'ORDERED' | 'IN_STOCK' | 'ACTIVE' | 'MAINTENANCE' | 'RETIRED' | 'DISPOSED'
  owner_user_id?: string
  support_group?: string
  criticality?: 'LOW' | 'MEDIUM' | 'HIGH' | 'CRITICAL'
  environment?: 'PRODUCTION' | 'STAGING' | 'TEST' | 'DEVELOPMENT' | 'OTHER'
  location?: string
  condition?: string
  description?: string
  assigned_to_name?: string
  purchase_date?: string
  purchase_cost?: number
  current_cost?: number
  depreciation_amount?: number
  residual_value?: number
  purchase_year?: number
  verification_status?: string
  attributes?: Record<string, unknown>
}

export type CMDBReconciliationRecord = {
  id: string
  row_number: number
  external_id: string
  outcome: 'CREATE' | 'UPDATE' | 'UNCHANGED' | 'AMBIGUOUS' | 'INVALID' | 'SKIPPED' | 'APPLIED_CREATED' | 'APPLIED_UPDATED'
  matched_ci_id: string | null
  candidate_ids: string[]
  errors: string[]
  normalized: Record<string, unknown>
  applied_at: string | null
  created_at: string
}

export type CMDBReconciliationRun = {
  id: string
  tenant_id: string
  source_id: string
  source_code: string
  source_name: string
  idempotency_key: string
  payload_hash: string
  mode: 'PREVIEW' | 'APPLY'
  status: 'PENDING' | 'PREVIEWED' | 'RUNNING' | 'COMPLETED' | 'COMPLETED_WITH_ERRORS' | 'FAILED'
  input_count: number
  create_count: number
  update_count: number
  unchanged_count: number
  ambiguous_count: number
  invalid_count: number
  skipped_count: number
  summary: Record<string, unknown>
  started_at: string | null
  completed_at: string | null
  created_at: string
  updated_at: string
  records: CMDBReconciliationRecord[] | null
}

export type CIDuplicateCandidate = {
  id: string
  tenant_id: string
  run_id: string
  record_id: string | null
  primary: {
    id: string
    asset_tag: string
    name: string
    ci_class_name: string | null
    lifecycle_status: string
    version: number
  }
  duplicate: {
    id: string
    asset_tag: string
    name: string
    ci_class_name: string | null
    lifecycle_status: string
    version: number
  }
  confidence: number
  reasons: string[]
  status: 'OPEN' | 'MERGED' | 'DISMISSED'
  version: number
  resolution_reason: string | null
  resolved_by_id: string | null
  resolved_at: string | null
  created_at: string
  updated_at: string
}

export type CMDBFieldOwnership = {
  id: string
  field_name: string
  source_id: string
  source_code: string
  source_name: string
  external_id: string
  source_priority: number
  value_hash: string
  observed_at: string
  updated_at: string
}

export type CMDBSourceHealth = {
  total_sources: number
  active_sources: number
  stale_sources: number
  open_duplicate_candidates: number
}

export type AssetDiscoveryProvider =
  | 'INTUNE'
  | 'AZURE_RESOURCE_GRAPH'
  | 'SCCM_ADMIN_SERVICE'
  | 'LANSWEEPER_DATA_API'

export type AssetDiscoveryConnector = {
  id: string
  tenant_id: string
  cmdb_source_id: string
  cmdb_source_code: string
  cmdb_source_name: string
  name: string
  provider: AssetDiscoveryProvider
  status: 'DRAFT' | 'ACTIVE' | 'PAUSED' | 'REVOKED'
  auth_type: 'OAUTH_CLIENT_CREDENTIALS' | 'API_TOKEN' | 'BASIC' | 'BEARER'
  base_url: string | null
  credential_configured: boolean
  credential_hint: string | null
  credential_version: number
  last_tested_credential_version: number | null
  configuration: Record<string, unknown>
  schedule_minutes: number
  auto_apply: boolean
  missing_threshold_runs: number
  max_records: number
  version: number
  next_run_at: string | null
  last_started_at: string | null
  last_completed_at: string | null
  last_success_at: string | null
  last_failure_at: string | null
  last_error: string | null
  successful_runs: number
  failed_runs: number
  discovered_records: number
  created_at: string
  updated_at: string
}

export type AssetDiscoveryRun = {
  id: string
  tenant_id: string
  connector_id: string
  connector_name: string
  provider: AssetDiscoveryProvider
  idempotency_key: string
  trigger_type: 'MANUAL' | 'SCHEDULED' | 'TEST'
  status: 'QUEUED' | 'RUNNING' | 'RETRY' | 'COMPLETED' | 'COMPLETED_WITH_ERRORS' | 'FAILED' | 'DEAD_LETTER' | 'CANCELLED'
  attempts: number
  max_attempts: number
  next_attempt_at: string
  pages_fetched: number
  records_fetched: number
  complete_snapshot: boolean
  reconciliation_run_ids: string[]
  created_count: number
  updated_count: number
  unchanged_count: number
  ambiguous_count: number
  invalid_count: number
  missing_count: number
  stale_count: number
  provider_request_id: string | null
  result: Record<string, unknown>
  last_error: string | null
  started_at: string | null
  completed_at: string | null
  created_at: string
  updated_at: string
}

export type AssetDiscoveryStaleCandidate = {
  id: string
  tenant_id: string
  connector_id: string
  connector_name: string
  source_identity_id: string
  asset_id: string
  asset_tag: string
  asset_name: string
  external_id: string
  status: 'OPEN' | 'DISMISSED' | 'RETIRED' | 'RECOVERED'
  missing_run_count: number
  first_missing_at: string
  last_missing_at: string
  version: number
  decision_reason: string | null
  decided_by_id: string | null
  decided_at: string | null
  created_at: string
  updated_at: string
}

export type AssetDiscoveryDashboard = {
  connectors: Record<string, number>
  runs: Record<string, number>
  open_stale_candidates: number
  unhealthy_connectors: number
}

export type CMDBImpactEntityType = 'TICKET' | 'PROBLEM' | 'CHANGE' | 'RELEASE'
export type CMDBImpactDirection = 'UPSTREAM' | 'DOWNSTREAM' | 'BOTH'

export type CMDBImpactNode = {
  id: string
  asset_tag: string
  name: string
  ci_class_id: string | null
  ci_class_code: string | null
  ci_class_name: string | null
  lifecycle_status: string
  criticality: string
  environment: string
  support_group: string | null
  depth: number
  is_root: boolean
}

export type CMDBImpactEdge = {
  id: string
  relationship_type_id: string
  relationship_type_code: string
  relationship_type_name: string
  forward_label: string
  reverse_label: string
  source_ci_id: string
  target_ci_id: string
}

export type CMDBChangeCollision = {
  change_id: string
  change_number: string
  title: string
  status: string
  risk_level: string
  planned_start_at: string | null
  planned_end_at: string | null
  window_overlap: boolean
  collision_type: 'WINDOW_OVERLAP' | 'SHARED_SCOPE' | string
  shared_ci_ids: string[]
  shared_asset_tags: string[]
}

export type CMDBImpactAnalysis = {
  tenant_id: string
  root_ci_ids: string[]
  direction: CMDBImpactDirection
  max_depth: number
  graph_hash: string
  nodes: CMDBImpactNode[]
  edges: CMDBImpactEdge[]
  truncated: boolean
  cache_hits: number
  computed_at: string
  entity_type: CMDBImpactEntityType | null
  entity_id: string | null
  severity: 'LOW' | 'MEDIUM' | 'HIGH' | 'CRITICAL'
  severity_reasons: string[]
  customer_impact: boolean
  impacted_ci_count: number
  impacted_service_count: number
  critical_ci_count: number
  production_ci_count: number
  services: CMDBImpactNode[]
  critical_cis: CMDBImpactNode[]
  collisions: CMDBChangeCollision[]
  collision_count: number
}

export type CMDBImpactAssessment = {
  id: string
  tenant_id: string
  entity_type: CMDBImpactEntityType
  entity_id: string
  entity_version: number | null
  root_ci_ids: string[]
  direction: CMDBImpactDirection
  max_depth: number
  graph_hash: string
  severity: CMDBImpactAnalysis['severity']
  impacted_ci_count: number
  impacted_service_count: number
  critical_ci_count: number
  collision_count: number
  snapshot_hash: string
  status: 'CURRENT' | 'SUPERSEDED'
  created_by_id: string | null
  created_at: string
  graph_is_stale: boolean
  entity_is_stale: boolean
  integrity_valid: boolean
  is_stale: boolean
  snapshot: CMDBImpactAnalysis
}

export type CMDBQualitySnapshot = {
  id: string
  tenant_id: string
  overall_score: number
  completeness_score: number
  correctness_score: number
  freshness_score: number
  duplicate_score: number
  orphan_score: number
  ci_count: number
  open_finding_count: number
  critical_finding_count: number
  resolved_finding_count: number
  result: Record<string, unknown>
  result_hash: string
  integrity_valid: boolean
  created_by_id: string | null
  created_at: string
}

export type CMDBQualityOverview = {
  latest: CMDBQualitySnapshot | null
  trend: CMDBQualitySnapshot[]
  open_findings: number
  overdue_findings: number
  unassigned_findings: number
  active_campaigns: number
  overdue_campaigns: number
}

export type CMDBQualityFinding = {
  id: string
  tenant_id: string
  rule_code: string
  dimension: 'COMPLETENESS' | 'CORRECTNESS' | 'FRESHNESS' | 'DUPLICATE' | 'ORPHAN' | 'CERTIFICATION'
  subject_type: string
  subject_id: string
  asset_id: string | null
  asset_tag: string | null
  asset_name: string | null
  title: string
  details: string
  evidence: Record<string, unknown>
  severity: 'LOW' | 'MEDIUM' | 'HIGH' | 'CRITICAL'
  status: 'OPEN' | 'IN_PROGRESS' | 'RESOLVED' | 'WAIVED'
  owner_user_id: string | null
  owner_name: string | null
  owner_email: string | null
  due_at: string | null
  overdue: boolean
  age_days: number
  first_detected_at: string
  last_detected_at: string
  occurrence_count: number
  resolution_note: string | null
  resolved_by_id: string | null
  resolved_at: string | null
  last_snapshot_id: string | null
  version: number
  created_at: string
  updated_at: string
}

export type CMDBCertificationScope = {
  asset_ids?: string[]
  ci_class_ids?: string[]
  criticalities?: Array<'LOW' | 'MEDIUM' | 'HIGH' | 'CRITICAL'>
  environments?: Array<'PRODUCTION' | 'STAGING' | 'TEST' | 'DEVELOPMENT' | 'OTHER'>
  lifecycle_statuses?: string[]
  only_without_owner?: boolean
  default_certifier_user_id?: string
}

export type CMDBCertificationItem = {
  id: string
  tenant_id: string
  campaign_id: string
  asset_id: string
  asset_tag: string
  asset_name: string
  asset_version: number
  current_asset_version: number
  asset_changed: boolean
  asset_snapshot: Record<string, unknown>
  asset_snapshot_hash: string
  integrity_valid: boolean
  certifier_user_id: string | null
  certifier_name: string | null
  status: 'PENDING' | 'CERTIFIED' | 'REJECTED'
  decision_note: string | null
  decided_by_id: string | null
  decided_at: string | null
  version: number
  created_at: string
  updated_at: string
}

export type CMDBCertificationCampaign = {
  id: string
  tenant_id: string
  name: string
  description: string | null
  scope: CMDBCertificationScope
  status: 'DRAFT' | 'ACTIVE' | 'COMPLETED' | 'CANCELLED'
  due_at: string
  overdue: boolean
  activated_at: string | null
  completed_at: string | null
  created_by_id: string | null
  version: number
  total_items: number
  pending_items: number
  certified_items: number
  rejected_items: number
  progress_percent: number
  items: CMDBCertificationItem[] | null
  created_at: string
  updated_at: string
}

export type CreateCIRelationshipTypeRequest = {
  tenant_id?: string
  code: string
  name: string
  forward_label: string
  reverse_label: string
  description?: string | null
  source_class_id?: string | null
  target_class_id?: string | null
  source_cardinality: 'ONE' | 'MANY'
  target_cardinality: 'ONE' | 'MANY'
  allow_self_relationship: boolean
  allow_cycles: boolean
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

export type ChangeRequest = {
  id: string
  tenant_id: string
  change_number: string
  title: string
  description: string
  change_type: 'STANDARD' | 'NORMAL' | 'EMERGENCY'
  status: string
  service_name: string | null
  environment: string
  standard_model_id: string | null
  impact_level: 'LOW' | 'MEDIUM' | 'HIGH' | 'ENTERPRISE'
  likelihood: number
  risk_score: number
  risk_level: string
  requested_by_id: string | null
  requested_by_name: string
  requested_by_email: string
  owner_id: string | null
  owner_name: string | null
  cab_required: boolean
  approval_status: string
  planned_start_at: string | null
  planned_end_at: string | null
  actual_start_at: string | null
  actual_end_at: string | null
  outage_required: boolean
  outage_minutes: number
  failure_reason: string | null
  post_implementation_review: string | null
  validation_status: string
  pir_status: string
  outcome: string | null
  blackout_override_reason: string | null
  version: number
  asset_count: number
  ticket_count: number
  created_at: string
  updated_at: string
}

export type ChangeHistory = {
  id: string
  actor_name: string
  actor_email: string
  event_type: string
  from_status: string | null
  to_status: string | null
  message: string
  metadata: Record<string, unknown>
  created_at: string
}

export type ChangeApproval = {
  id: string
  approver_id: string | null
  approver_name: string
  approver_email: string
  decision: string
  decision_comment: string
  decided_at: string
}

export type ChangeDetail = ChangeRequest & {
  business_justification: string | null
  implementation_plan: string | null
  test_plan: string | null
  rollback_plan: string | null
  validation_plan: string | null
  assets: Array<Pick<Asset, 'id' | 'asset_tag' | 'name' | 'status' | 'location'>>
  tickets: Array<Pick<Ticket, 'id' | 'ticket_number' | 'title' | 'status' | 'priority'>>
  approvals: ChangeApproval[]
  history: ChangeHistory[]
}

export type ChangeSummary = {
  open_changes: number
  awaiting_approval: number
  scheduled_next_7_days: number
  high_risk_open: number
  failed_last_30_days: number
}

export type CreateChangeRequest = {
  title: string
  description: string
  change_type: 'STANDARD' | 'NORMAL' | 'EMERGENCY'
  service_name?: string | null
  environment?: string
  impact_level: 'LOW' | 'MEDIUM' | 'HIGH' | 'ENTERPRISE'
  likelihood: number
  business_justification?: string | null
  implementation_plan?: string | null
  test_plan?: string | null
  rollback_plan?: string | null
  validation_plan?: string | null
  planned_start_at?: string | null
  planned_end_at?: string | null
  outage_required?: boolean
  outage_minutes?: number
  asset_ids?: string[]
  ticket_ids?: string[]
}

export type ChangeWindow = {
  id: string
  tenant_id: string
  name: string
  description: string | null
  window_type: 'MAINTENANCE' | 'BLACKOUT'
  starts_at: string
  ends_at: string
  timezone: string
  services: string[]
  asset_ids: string[]
  environments: string[]
  recurrence: Record<string, unknown> | null
  is_active: boolean
  version: number
  created_at: string
  updated_at: string
}

export type ChangeCalendar = {
  starts_at: string
  ends_at: string
  changes: Array<{
    id: string
    tenant_id: string
    change_number: string
    title: string
    change_type: string
    status: string
    risk_level: string
    service_name: string | null
    environment: string
    planned_start_at: string
    planned_end_at: string
    outage_required: boolean
  }>
  windows: ChangeWindow[]
}

export type ChangeWindowAssessment = {
  maintenance_coverage: Array<Record<string, unknown>>
  blackouts: Array<Record<string, unknown>>
  change_conflicts: Array<Record<string, unknown>>
  blocking_count: number
}

export type ChangeReadiness = {
  score_percent: number
  ready: boolean
  checks: Array<{
    code: string
    label: string
    passed: boolean
    blocking: boolean
  }>
  window_assessment: ChangeWindowAssessment
}

export type StandardChangeModel = {
  id: string
  tenant_id: string
  code: string
  name: string
  description: string
  service_name: string | null
  environment: string
  default_duration_minutes: number
  implementation_plan: string
  test_plan: string
  rollback_plan: string
  validation_plan: string
  task_templates: Array<Record<string, unknown>>
  scope: Record<string, unknown>
  preauthorized_until: string
  review_due_at: string
  is_active: boolean
  usage_count: number
  success_count: number
  failure_count: number
  reliability_percent: number
  version: number
  created_at: string
  updated_at: string
}

export type ChangeTask = {
  id: string
  tenant_id: string
  change_id: string
  task_type: 'IMPLEMENTATION' | 'VALIDATION' | 'ROLLBACK'
  sequence: number
  title: string
  description: string | null
  status: 'PENDING' | 'IN_PROGRESS' | 'COMPLETED' | 'FAILED' | 'SKIPPED'
  is_required: boolean
  owner_id: string | null
  owner_name: string | null
  due_at: string | null
  started_at: string | null
  completed_at: string | null
  evidence: string | null
  version: number
}

export type ChangePIR = {
  id: string
  change_id: string
  status: 'DRAFT' | 'SUBMITTED' | 'APPROVED'
  outcome: 'SUCCESS' | 'PARTIAL' | 'FAILED' | 'ROLLED_BACK'
  objectives_met: boolean
  actual_impact: string
  actual_outage_minutes: number
  incidents_caused: number
  lessons_learned: string
  follow_up_actions: Array<Record<string, unknown>>
  prepared_by_id: string | null
  prepared_by_name: string | null
  submitted_at: string | null
  approved_by_id: string | null
  approved_by_name: string | null
  approved_at: string | null
  approval_comment: string | null
  version: number
  created_at: string
  updated_at: string
}

export type CABMeeting = {
  id: string
  tenant_id: string
  title: string
  meeting_type: 'CAB' | 'ECAB'
  status: 'DRAFT' | 'PUBLISHED' | 'IN_PROGRESS' | 'COMPLETED' | 'CANCELLED'
  scheduled_at: string
  duration_minutes: number
  location_or_url: string | null
  chair_user_id: string | null
  chair_user_name: string | null
  participant_user_ids: string[]
  minutes: string | null
  version: number
  agenda: Array<{
    id: string
    change_id: string
    change_number: string | null
    sequence: number
    presenter_user_id: string | null
    recommendation: string | null
    decision: string | null
    decision_comment: string | null
    evidence: Record<string, unknown>
    decided_by_id: string | null
    decided_at: string | null
  }>
  created_at: string
  updated_at: string
}

export type ChangeAnalytics = {
  period_start: string
  period_end: string
  total_changes: number
  completed_changes: number
  successful_changes: number
  failed_changes: number
  rolled_back_changes: number
  emergency_changes: number
  success_rate_percent: number
  change_failure_rate_percent: number
  emergency_rate_percent: number
  average_lead_time_hours: number
  average_implementation_minutes: number
  open_tasks: number
  overdue_standard_reviews: number
}

export type ReleaseEnvironment = {
  id: string
  tenant_id: string
  code: string
  name: string
  environment_type: 'DEVELOPMENT' | 'TEST' | 'STAGING' | 'PRODUCTION' | 'DR'
  promotion_order: number
  requires_approval: boolean
  requires_smoke_test: boolean
  is_production: boolean
  is_active: boolean
  current_version: string | null
  version: number
  created_at: string
  updated_at: string
}

export type ReleasePackage = {
  id: string
  component_name: string
  package_type: 'APPLICATION' | 'DATABASE' | 'CONFIGURATION' | 'INFRASTRUCTURE' | 'DOCUMENTATION'
  version_name: string
  artifact_uri: string
  checksum_sha256: string
  build_reference: string | null
  dependencies: Array<Record<string, unknown>>
  verification_status: 'PENDING' | 'VERIFIED' | 'FAILED'
  verification_evidence: string | null
  verified_at: string | null
  version: number
  created_at: string
}

export type ReleaseGate = {
  id: string
  code: string
  name: string
  gate_type: 'CHANGES' | 'PACKAGES' | 'DEPENDENCIES' | 'WINDOW' | 'ROLLBACK' | 'TEST' | 'SECURITY' | 'BUSINESS' | 'MANUAL'
  is_mandatory: boolean
  stored_status: 'PENDING' | 'PASSED' | 'FAILED' | 'WAIVED'
  status: 'PENDING' | 'PASSED' | 'FAILED' | 'WAIVED'
  evidence: string | null
  decision_comment: string | null
  decided_by_name: string | null
  decided_at: string | null
  version: number
}

export type ReleaseReadiness = {
  ready: boolean
  score_percent: number
  checks: Array<{ code: string; label: string; passed: boolean }>
  gates: ReleaseGate[]
  blocking_gate_codes: string[]
  change_count: number
  package_count: number
  dependency_count: number
  environment_count: number
}

export type ReleaseDeployment = {
  id: string
  release_id: string
  environment: ReleaseEnvironment
  status: 'PLANNED' | 'IN_PROGRESS' | 'VALIDATING' | 'SUCCEEDED' | 'FAILED' | 'ROLLED_BACK' | 'CANCELLED'
  scheduled_at: string
  started_at: string | null
  completed_at: string | null
  deployed_version: string
  previous_version: string | null
  deployment_reference: string | null
  deployment_evidence: string | null
  validation_evidence: string | null
  smoke_test_status: 'PENDING' | 'PASSED' | 'FAILED'
  rollback_evidence: string | null
  failure_reason: string | null
  operator_name: string | null
  version: number
}

export type ReleaseRecord = {
  id: string
  tenant_id: string
  release_number: string
  name: string
  version_name: string
  release_type: 'MAJOR' | 'MINOR' | 'PATCH' | 'HOTFIX'
  status: 'DRAFT' | 'PLANNING' | 'READY' | 'APPROVED' | 'DEPLOYING' | 'VALIDATING' | 'RELEASED' | 'FAILED' | 'ROLLED_BACK' | 'CANCELLED'
  service_name: string
  description: string
  scope: string
  release_notes: string | null
  risk_level: 'LOW' | 'MEDIUM' | 'HIGH' | 'CRITICAL'
  target_release_at: string
  window_start_at: string | null
  window_end_at: string | null
  validation_plan: string
  rollback_plan: string
  communication_plan: string
  owner_id: string | null
  owner_name: string
  go_no_go_status: 'PENDING' | 'GO' | 'NO_GO' | 'CONDITIONAL'
  approved_decision_id: string | null
  actual_released_at: string | null
  completed_at: string | null
  version: number
  created_at: string
  updated_at: string
  change_count: number
  package_count: number
  deployment_count: number
}

export type ReleaseDetail = ReleaseRecord & {
  changes: Array<{
    link_id: string
    sequence: number
    is_mandatory: boolean
    notes: string | null
    change_id: string
    change_number: string
    title: string
    status: string
    risk_level: string
    planned_start_at: string | null
    planned_end_at: string | null
  }>
  packages: ReleasePackage[]
  dependencies: Array<{
    id: string
    dependency_type: 'REQUIRES' | 'BLOCKS' | 'FOLLOWS'
    notes: string | null
    release_id: string
    release_number: string
    name: string
    version_name: string
    status: ReleaseRecord['status']
  }>
  deployments: ReleaseDeployment[]
  decisions: Array<{
    id: string
    decision: 'GO' | 'NO_GO' | 'CONDITIONAL'
    comment: string
    conditions: Array<Record<string, unknown>>
    readiness_snapshot: Record<string, unknown>
    decided_by_name: string
    created_at: string
  }>
  readiness: ReleaseReadiness
}

export type ReleaseTimelineEvent = {
  id: string
  event_type: string
  message: string
  from_status: string | null
  to_status: string | null
  metadata: Record<string, unknown>
  actor_name: string
  created_at: string
}

export type ReleaseCalendar = {
  starts_at: string
  ends_at: string
  releases: Array<Pick<ReleaseRecord, 'id' | 'release_number' | 'name' | 'version_name' | 'service_name' | 'status' | 'risk_level' | 'target_release_at'>>
  deployments: Array<{
    id: string
    release_id: string
    release_number: string
    release_name: string
    environment_name: string
    is_production: boolean
    status: ReleaseDeployment['status']
    scheduled_at: string
  }>
}

export type ReleaseAnalytics = {
  period_start: string
  period_end: string
  total_releases: number
  released: number
  failed_or_rolled_back: number
  release_success_rate_percent: number
  total_deployments: number
  production_deployments: number
  deployment_frequency_per_week: number
  deployment_failure_rate_percent: number
  rollback_rate_percent: number
  average_release_lead_time_hours: number
  average_deployment_minutes: number
  active_deployments: number
}

export type ChangeQueryParams = {
  q?: string
  status?: string
  change_type?: string
  risk_level?: string
  tenant_id?: string
  page?: number
  page_size?: number
}

export type ProblemRecord = {
  id: string
  tenant_id: string
  problem_number: string
  title: string
  description: string
  problem_type: 'REACTIVE' | 'PROACTIVE'
  status: string
  service_name: string | null
  category: string | null
  impact_level: 'LOW' | 'MEDIUM' | 'HIGH' | 'ENTERPRISE'
  urgency_level: 'LOW' | 'MEDIUM' | 'HIGH' | 'CRITICAL'
  priority: 'P1' | 'P2' | 'P3' | 'P4'
  detection_source: string | null
  symptoms: string
  workaround_status: string
  known_error_title: string | null
  known_error_published_at: string | null
  known_error_published_by_name: string | null
  created_by_id: string | null
  created_by_name: string
  created_by_email: string
  owner_id: string | null
  owner_name: string | null
  first_observed_at: string | null
  target_resolution_at: string | null
  resolved_at: string | null
  closed_at: string | null
  version: number
  incident_count: number
  asset_count: number
  change_count: number
  age_days: number
  overdue: boolean
  is_known_error: boolean
  created_at: string
  updated_at: string
}

export type ProblemRCA = {
  id: string
  problem_id: string
  method: 'FIVE_WHYS' | 'ISHIKAWA' | 'FAULT_TREE' | 'CUSTOM'
  status: 'DRAFT' | 'SUBMITTED' | 'APPROVED' | 'REJECTED'
  problem_statement: string
  five_whys: Array<Record<string, unknown>>
  ishikawa: Record<string, string[]>
  fault_tree: Record<string, unknown>
  contributing_factors: Array<Record<string, unknown>>
  evidence: Array<Record<string, unknown>>
  conclusion: string
  prepared_by_id: string | null
  prepared_by_name: string
  submitted_at: string | null
  approved_by_id: string | null
  approved_by_name: string | null
  approved_at: string | null
  approval_comment: string | null
  version: number
  created_at: string
  updated_at: string
}

export type ProblemCorrectiveAction = {
  id: string
  problem_id: string
  action_type: 'CORRECTIVE' | 'PREVENTIVE' | 'DETECTION'
  title: string
  description: string
  status: 'OPEN' | 'IN_PROGRESS' | 'IMPLEMENTED' | 'VERIFIED' | 'INEFFECTIVE' | 'CANCELLED'
  is_required: boolean
  owner_id: string | null
  owner_name: string
  due_at: string
  effectiveness_criteria: string
  implementation_evidence: string | null
  implemented_at: string | null
  review_due_at: string | null
  effectiveness_score: number | null
  effectiveness_evidence: string | null
  reviewed_by_name: string | null
  reviewed_at: string | null
  version: number
  created_at: string
  updated_at: string
}

export type ProblemTrendSignal = {
  id: string
  tenant_id: string
  signal_type: 'RECURRENCE' | 'VOLUME_SPIKE' | 'SLA_DEGRADATION'
  signature: string
  title: string
  service_name: string | null
  category: string | null
  window_start_at: string
  window_end_at: string
  baseline_count: number
  current_count: number
  growth_percent: number
  score: number
  incident_ids: string[]
  evidence: Record<string, unknown>
  status: 'OPEN' | 'ACKNOWLEDGED' | 'CONVERTED' | 'DISMISSED'
  problem_id: string | null
  disposition_comment: string | null
  disposition_by_name: string | null
  disposition_at: string | null
  version: number
  created_at: string
  updated_at: string
}

export type ProblemGovernanceAnalytics = {
  total_actions: number
  open_actions: number
  overdue_actions: number
  verified_effective: number
  ineffective: number
  average_effectiveness_score: number
  open_trend_signals: number
}

export type KnownErrorMetrics = {
  period_start: string
  period_end: string
  views: number
  applications: number
  helpful: number
  not_helpful: number
  helpfulness_percent: number
  minutes_saved: number
  avoided_escalations: number
}

export type ProblemHistory = {
  id: string
  actor_name: string
  actor_email: string
  event_type: string
  from_status: string | null
  to_status: string | null
  message: string
  metadata: Record<string, unknown>
  created_at: string
}

export type ProblemDetail = ProblemRecord & {
  root_cause: string | null
  workaround: string | null
  resolution_summary: string | null
  validation_summary: string | null
  tickets: Array<Pick<Ticket, 'id' | 'ticket_number' | 'title' | 'status' | 'priority'>>
  assets: Array<Pick<Asset, 'id' | 'asset_tag' | 'name' | 'status' | 'location'>>
  changes: Array<Pick<ChangeRequest, 'id' | 'change_number' | 'title' | 'status' | 'risk_level'>>
  history: ProblemHistory[]
}

export type ProblemSummary = {
  open_problems: number
  investigating: number
  known_errors: number
  overdue: number
  recurring_problems: number
  critical_open: number
}

export type KnownError = {
  id: string
  problem_number: string
  title: string
  known_error_title: string
  service_name: string | null
  category: string | null
  priority: string
  status: string
  symptoms: string
  root_cause: string
  workaround: string
  workaround_status: string
  incident_count: number
  published_at: string
  updated_at: string
}

export type ProblemQueryParams = {
  q?: string
  status?: string
  problem_type?: string
  priority?: string
  known_error?: boolean
  page?: number
  page_size?: number
}

export type CreateProblemRequest = {
  title: string
  description: string
  problem_type: 'REACTIVE' | 'PROACTIVE'
  service_name?: string | null
  category?: string | null
  impact_level: 'LOW' | 'MEDIUM' | 'HIGH' | 'ENTERPRISE'
  urgency_level: 'LOW' | 'MEDIUM' | 'HIGH' | 'CRITICAL'
  detection_source?: string | null
  symptoms: string
  first_observed_at?: string | null
  target_resolution_at?: string | null
  ticket_ids?: string[]
  asset_ids?: string[]
  change_ids?: string[]
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
  calendar_id: string | null
  calendar_name: string
  priority_order: number
  scope: Record<string, unknown>
  targets: SlaTargetDefinition[]
  pause_statuses: string[]
  pause_reasons: string[]
  warning_percent: number
  escalations: SlaEscalation[]
  version: number
  created_at: string
  updated_at: string
}

export type SlaTargetDefinition = {
  type: 'RESPONSE' | 'RESOLUTION' | 'FULFILLMENT' | 'OLA' | 'SUPPLIER'
  name: string
  minutes: number
  warning_percent: number
  owner_type?: string | null
  owner_ref?: string
}

export type SlaEscalation = {
  at_percent: number
  target_type?: SlaTargetDefinition['type'] | null
  recipient_user_id?: string | null
  label: string
}

export type SlaCalendarException = {
  id: string
  exception_date: string
  kind: 'HOLIDAY' | 'WORKING_DAY'
  name: string
  intervals: string[][]
}

export type SlaCalendar = {
  id: string
  tenant_id: string
  name: string
  description: string | null
  timezone: string
  weekly_hours: Record<string, string[][]>
  is_default: boolean
  is_active: boolean
  version: number
  exceptions: SlaCalendarException[]
  created_at: string
  updated_at: string
}

export type SlaTarget = {
  id: string
  target_type: SlaTargetDefinition['type']
  name: string
  duration_minutes: number
  warning_percent: number
  warning_at: string
  due_at: string
  status: 'PENDING' | 'WARNING' | 'MET' | 'BREACHED' | 'CANCELLED'
  owner_type: string | null
  owner_ref: string
  met_at: string | null
  breached_at: string | null
  progress_percent: number
  remaining_business_minutes: number
  escalation_level: number
  last_escalated_at: string | null
  version: number
}

export type SlaInstance = {
  id: string
  tenant_id: string
  ticket_id: string
  ticket_number: string | null
  ticket_title: string | null
  ticket_priority: string | null
  ticket_status: string | null
  policy_id: string
  policy_name: string
  policy_version: number
  calendar_id: string | null
  calendar_name: string
  status: 'ACTIVE' | 'PAUSED' | 'COMPLETED' | 'BREACHED' | 'CANCELLED'
  is_current: boolean
  started_at: string
  paused_at: string | null
  completed_at: string | null
  last_evaluated_at: string | null
  total_paused_business_minutes: number
  version: number
  targets: SlaTarget[]
  policy_snapshot?: Record<string, unknown>
  calendar_snapshot?: Record<string, unknown> | null
  pauses?: Array<{
    id: string
    reason_code: string
    reason: string
    started_at: string
    ended_at: string | null
    business_minutes: number | null
    start_status: string | null
    end_status: string | null
  }>
  timeline?: Array<{
    id: string
    target_id: string | null
    event_type: string
    actor_name: string
    message: string
    data: Record<string, unknown>
    created_at: string
  }>
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
  active_instances: number
  paused_instances: number
  breached_instances: number
  warning_targets: number
  breached_targets: number
  met_targets: number
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
  content_locale?: string
  translation_version?: number | null
  translation_status?: 'SOURCE' | 'PUBLISHED' | 'STALE_FALLBACK' | string
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
  locale?: string
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
  requested_provider?: string | null
  provider?: string | null
  model?: string | null
  provider_mock?: boolean | null
  fallback_used?: boolean | null
  execution_mode?: string | null
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
  tenant_id?: string | null
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
  channel_id?: string | null
  direction?: string
  provider: string
  provider_message_id?: string | null
  internet_message_id?: string | null
  conversation_id?: string | null
  idempotency_key?: string | null
  from_email?: string | null
  from_name?: string | null
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
  related_request_id?: string | null
  created_at: string
  queued_at?: string | null
  accepted_at?: string | null
  sent_at: string | null
  delivered_at?: string | null
  bounced_at?: string | null
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

export type EmailChannelDashboard = {
  tenant_id: string
  active_channels: number
  active_production_channels: number
  queued_outbound: number
  failed_outbound: number
  accepted_outbound: number
  simulated_outbound: number
  inbound_received: number
  inbound_quarantined: number
  webhook_dead_letter: number
  attachments_quarantined: number
  channel_health: 'NOT_CONFIGURED' | 'SIMULATED' | 'DEGRADED' | 'HEALTHY' | string
  webhook_public_url_configured: boolean
  antivirus_configured: boolean
  manual_unscanned_release_enabled: boolean
  mock_provider_enabled: boolean
}

export type TeamsDashboard = {
  tenant_id: string
  active_connectors: number
  active_production_connectors: number
  queued_deliveries: number
  retrying_deliveries: number
  failed_deliveries: number
  simulated_deliveries: number
  sent_last_24h: number
  open_incident_rooms: number
  channel_health: string
  public_base_url_configured: boolean
  mock_provider_enabled: boolean
}

export type TeamsConnector = {
  id: string
  tenant_id: string
  name: string
  provider_type: 'WORKFLOW_WEBHOOK' | 'MOCK'
  status: string
  purpose: 'DEFAULT' | 'APPROVALS' | 'MAJOR_INCIDENT' | 'SECURITY'
  webhook_configured: boolean
  webhook_updated_at: string | null
  team_name: string | null
  channel_name: string | null
  channel_url: string | null
  meeting_url: string | null
  event_types: string[]
  minimum_severity: 'INFO' | 'WARNING' | 'CRITICAL'
  last_success_at: string | null
  last_failure_at: string | null
  success_count: number
  failure_count: number
  last_error: string | null
  version: number
  created_at: string
  updated_at: string
}

export type TeamsDelivery = {
  id: string
  tenant_id: string
  connector_id: string
  notification_id: string | null
  event_type: string
  severity: string
  entity_type: string | null
  entity_id: string | null
  title: string
  message: string
  action_url: string | null
  status: string
  attempts: number
  max_attempts: number
  next_attempt_at: string
  last_attempt_at: string | null
  sent_at: string | null
  provider_status_code: number | null
  provider_reference: string | null
  last_error: string | null
  created_at: string
}

export type TeamsMajorIncidentRoom = {
  id: string
  tenant_id: string
  connector_id: string
  major_incident_id: string
  status: string
  channel_url: string | null
  meeting_url: string | null
  opened_by_id: string | null
  closed_by_id: string | null
  opened_at: string
  closed_at: string | null
}

export type EmailChannel = {
  id: string
  tenant_id: string
  name: string
  provider_type: 'MICROSOFT_GRAPH' | 'MOCK'
  status: 'DRAFT' | 'ACTIVE' | 'PAUSED' | 'ERROR' | 'REVOKED'
  mailbox_address: string
  mailbox_user_id: string | null
  entra_tenant_id: string | null
  client_id: string | null
  client_secret_configured: boolean
  inbound_enabled: boolean
  outbound_enabled: boolean
  default_target: 'TICKET' | 'REQUEST'
  allowed_sender_domains: string[]
  allowed_attachment_extensions: string[]
  max_attachment_bytes: number
  graph_subscription_id: string | null
  graph_subscription_expires_at: string | null
  webhook_configured: boolean
  delta_sync_initialized: boolean
  last_sync_at: string | null
  last_success_at: string | null
  last_failure_at: string | null
  success_count: number
  failure_count: number
  last_error: string | null
  version: number
  created_at: string
  updated_at: string
}

export type EmailInboundMessage = {
  id: string
  tenant_id: string
  channel_id: string
  conversation_id: string | null
  provider_message_id: string
  internet_message_id: string | null
  from_email: string
  from_name: string | null
  subject: string
  body_preview: string
  authentication_results: string | null
  status: string
  rejection_reason: string | null
  processing_attempts: number
  related_ticket_id: string | null
  related_request_id: string | null
  received_at: string
  processed_at: string | null
  attachment_count: number
}

export type EmailConversation = {
  id: string
  channel_id: string
  thread_token_hint: string
  entity_type: 'TICKET' | 'REQUEST'
  entity_id: string
  requester_email: string
  normalized_subject: string
  last_message_at: string | null
}

export type EmailAttachment = {
  id: string
  inbound_message_id: string
  original_filename: string
  safe_filename: string
  content_type: string | null
  detected_content_type: string | null
  size_bytes: number
  sha256: string | null
  status: 'STORED' | 'QUARANTINED' | 'BLOCKED' | 'RELEASED' | string
  scan_status: 'NOT_REQUIRED' | 'PENDING' | 'CLEAN' | 'INFECTED' | 'ERROR' | string
  blocked_reason: string | null
  security_findings: string[]
  sanitization_applied: boolean
  download_count: number
  reviewed_at: string | null
}

export type EmailDeliveryEvent = {
  id: string
  email_log_id: string
  event_type: string
  reason: string | null
  metadata: Record<string, unknown>
  occurred_at: string
}

export type AdminUser = {
  id: string
  tenant_id: string | null
  email: string
  full_name: string
  position: string | null
  department: string | null
  location: string | null
  cost_center: string | null
  phone: string | null
  employee_number: string | null
  manager_id: string | null
  identity_source: 'LOCAL' | 'OIDC' | 'SCIM' | 'ENTRA' | string
  provisioning_state: 'LOCAL' | 'ACTIVE' | 'SUSPENDED' | 'DEPROVISIONED' | string
  must_change_password: boolean
  is_active: boolean
  is_superuser: boolean
  last_login_at: string | null
  deactivated_at: string | null
  created_at: string
  updated_at: string
}

export type IdentityProvisioningDashboard = {
  connectors: number
  active_connectors: number
  active_identities: number
  deprovisioned_identities: number
  retry_queue: number
  dead_letter: number
  ownership_transfers: number
}

export type IdentityConnector = {
  id: string
  tenant_id: string
  name: string
  provider_type: 'SCIM' | 'ENTRA'
  external_tenant_id: string | null
  status: 'DRAFT' | 'ACTIVE' | 'PAUSED' | 'REVOKED'
  token_hint: string
  token_rotated_at: string
  default_role_id: string
  fallback_owner_id: string
  attribute_mapping: Record<string, string>
  allowed_ip_cidrs: string[]
  retry_max_attempts: number
  last_success_at: string | null
  last_failure_at: string | null
  success_count: number
  failure_count: number
  last_error: string | null
  version: number
  created_at: string
  updated_at: string
  scim_base_path: string
  counts: {
    identities: number
    active_identities: number
    groups: number
    retry_queue: number
    dead_letter: number
  }
}

export type ProvisionedIdentity = {
  id: string
  tenant_id: string
  connector_id: string
  user_id: string
  external_id: string
  user_name: string
  lifecycle_state: 'ACTIVE' | 'SUSPENDED' | 'DEPROVISIONED'
  manager_external_id: string | null
  scim_version: number
  last_synced_at: string
  deprovisioned_at: string | null
  created_at: string
  user: {
    email: string
    full_name: string
    position: string | null
    department: string | null
    location: string | null
    employee_number: string | null
    is_active: boolean
    manager_id: string | null
    role_id: string | null
  } | null
  groups: Array<{ id: string; display_name: string }>
}

export type ProvisionedIdentityPage = {
  items: ProvisionedIdentity[]
  total: number
  page: number
  page_size: number
}

export type ProvisionedGroup = {
  id: string
  tenant_id: string
  connector_id: string
  external_id: string
  display_name: string
  mapped_role_id: string | null
  is_active: boolean
  scim_version: number
  last_synced_at: string
  member_count: number
  created_at: string
  updated_at: string
}

export type IdentityProvisioningEvent = {
  id: string
  tenant_id: string
  connector_id: string
  external_event_id: string
  resource_type: 'User' | 'Group'
  operation: string
  external_id: string | null
  status: 'RECEIVED' | 'APPLIED' | 'FAILED' | 'RETRY_SCHEDULED' | 'DEAD_LETTER'
  attempts: number
  error_code: string | null
  error_message: string | null
  next_retry_at: string | null
  applied_user_id: string | null
  completed_at: string | null
  created_at: string
  updated_at: string
}

export type IdentityProvisioningEventPage = {
  items: IdentityProvisioningEvent[]
  total: number
  page: number
  page_size: number
}

export type IdentityOwnershipTransfer = {
  id: string
  tenant_id: string
  from_user_id: string
  to_user_id: string
  provisioning_event_id: string | null
  reason: string
  counts: Record<string, number>
  sessions_revoked: number
  status: 'COMPLETED' | 'FAILED'
  initiated_by_id: string | null
  created_at: string
}

export type IdentityOwnershipTransferPage = {
  items: IdentityOwnershipTransfer[]
  total: number
  page: number
  page_size: number
}

export type IdentityOwnershipPreview = {
  identity_id?: string
  user_id: string
  email?: string
  counts: Record<string, number>
  total: number
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

export type AdminAiProviderConfig = {
  provider: 'mock' | 'openai' | 'gemini'
  openai_model: string
  openai_base_url: string
  gemini_model: string
  pii_redaction_enabled: boolean
  request_timeout_seconds: number
  openai_api_key_configured: boolean
  gemini_api_key_configured: boolean
  updated_at: string | null
}

export type AdminAiProviderConfigPatch = {
  provider?: 'mock' | 'openai' | 'gemini'
  openai_model?: string
  openai_base_url?: string
  gemini_model?: string
  pii_redaction_enabled?: boolean
  request_timeout_seconds?: number
  openai_api_key?: string | null
  gemini_api_key?: string | null
  clear_openai_api_key?: boolean
  clear_gemini_api_key?: boolean
}

export type AdminAiProviderConfigTestRequest = {
  provider?: 'mock' | 'openai' | 'gemini'
  openai_model?: string
  openai_base_url?: string
  gemini_model?: string
  request_timeout_seconds?: number
  openai_api_key?: string | null
  gemini_api_key?: string | null
  sample_text?: string
}

export type AdminAiProviderConfigTestResult = {
  requested_provider: string
  effective_provider: string
  model: string
  success: boolean
  simulation: boolean
  reason: string | null
  response_status: number | null
  summary: string | null
  category: string | null
  priority: string | null
  confidence: number | null
  rationale: string | null
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
  active_sessions: number
  revoked_sessions: number
  expired_sessions: number
  refresh_ttl_minutes: number
}

export type SecuritySession = {
  id: string
  user_id: string
  user_email: string
  user_name: string
  tenant_id: string | null
  created_at: string
  refresh_expires_at: string
  revoked_at: string | null
  replaced_by_id: string | null
  ip_address: string | null
  user_agent: string | null
  auth_method: string | null
  is_active: boolean
  is_current: boolean
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

export type IntegrationRuntimeCapabilities = {
  production_control_plane_enabled: boolean
  legacy_demo_enabled: boolean
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

export type IntegrationPlatformScope = {
  scope: string
  description: string
}

export type IntegrationServiceAccount = {
  id: string
  tenant_id: string
  client_id: string
  name: string
  description: string | null
  status: 'ACTIVE' | 'SUSPENDED' | 'REVOKED'
  allowed_scopes: string[]
  allowed_ip_cidrs: string[]
  rate_limit_per_minute: number
  max_token_ttl_days: number
  version: number
  active_tokens: number
  total_requests: number
  failed_auth_count: number
  last_used_at: string | null
  last_used_ip: string | null
  revoked_at: string | null
  created_at: string
  updated_at: string
}

export type IntegrationApiToken = {
  id: string
  tenant_id: string
  service_account_id: string
  name: string
  token_hint: string
  scopes: string[]
  status: 'ACTIVE' | 'REVOKED' | 'EXPIRED'
  version: number
  expires_at: string
  last_used_at: string | null
  last_used_ip: string | null
  revoked_at: string | null
  replaced_by_token_id: string | null
  created_at: string
  access_token: string | null
  token_type: string | null
}

export type OutboundWebhookSubscription = {
  id: string
  tenant_id: string
  name: string
  description: string | null
  status: 'DRAFT' | 'ACTIVE' | 'PAUSED' | 'REVOKED'
  event_types: string[]
  target_hint: string | null
  target_host: string | null
  target_version: number
  signing_secret_hint: string | null
  signing_secret_version: number
  last_tested_target_version: number | null
  last_tested_secret_version: number | null
  timeout_seconds: number
  max_attempts: number
  version: number
  success_count: number
  failure_count: number
  dead_letter_count: number
  last_success_at: string | null
  last_failure_at: string | null
  last_error: string | null
  created_at: string
  updated_at: string
  signing_secret: string | null
}

export type OutboundWebhookDelivery = {
  id: string
  tenant_id: string
  subscription_id: string
  replay_of_id: string | null
  event_id: string
  event_type: string
  entity_type: string | null
  entity_id: string | null
  payload_sha256: string
  payload_bytes: number
  status: 'PENDING' | 'PROCESSING' | 'RETRY' | 'SUCCEEDED' | 'FAILED' | 'DEAD_LETTER' | 'CANCELLED'
  is_test: boolean
  attempts: number
  max_attempts: number
  next_attempt_at: string
  response_status: number | null
  response_time_ms: number | null
  target_version_used: number | null
  signing_secret_version_used: number | null
  provider_request_id: string | null
  last_error: string | null
  completed_at: string | null
  created_at: string
  updated_at: string
}

export type IntegrationApiRequestLog = {
  id: string
  tenant_id: string
  service_account_id: string
  token_id: string | null
  request_id: string
  method: string
  path: string
  source_ip: string | null
  required_scope: string | null
  outcome: 'ALLOWED' | 'DENIED'
  reason: string | null
  created_at: string
}

export type IntegrationPlatformDashboard = {
  service_accounts: Record<string, number>
  webhook_subscriptions: Record<string, number>
  deliveries: Record<string, number>
  api_requests: { allowed: number; denied: number }
  average_delivery_latency_ms: number
  outbound_allowed_hosts_configured: boolean
}

export type IntegrationConnectorContract = {
  contract_version: string
  event_format: string
  service_token: {
    authorization: string
    plaintext_returned_once: boolean
    scopes: Record<string, string>
  }
  sdk_endpoints: Record<string, string>
  outbound_signature: Record<string, string>
  retryable_http_statuses: Array<number | string>
  redirects: string
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
  dead_letter: number
}

export type JobRuntime = {
  executor_mode: 'inline' | 'redis' | string
  queue_name: string
  dead_letter_queue_name: string
  retry_base_seconds: number
  retry_max_seconds: number
  worker_required: boolean
}

export type JobOutboxSummary = {
  total: number
  pending: number
  published: number
  with_failures: number
}

export type JobOutboxDiagnostics = JobOutboxSummary & {
  locked: number
  stale_locks: number
  dedup_skips: number
  publish_failure_rate_pct: number
  pending_alert_threshold: number
  failure_alert_threshold: number
  stale_lock_alert_threshold: number
  status: 'ok' | 'warn' | 'critical' | string
  recommended_actions: string[]
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

export async function fetchJobRuntime(accessToken: string): Promise<JobRuntime> {
  const response = await fetch(`${API_BASE_URL}/jobs/runtime`, {
    headers: { Authorization: `Bearer ${accessToken}` },
  })
  return readJsonResponse<JobRuntime>(response)
}

export async function fetchJobOutboxSummary(accessToken: string): Promise<JobOutboxSummary> {
  const response = await fetch(`${API_BASE_URL}/jobs/outbox-summary`, {
    headers: { Authorization: `Bearer ${accessToken}` },
  })
  return readJsonResponse<JobOutboxSummary>(response)
}

export async function fetchJobOutboxDiagnostics(accessToken: string): Promise<JobOutboxDiagnostics> {
  const response = await fetch(`${API_BASE_URL}/jobs/outbox-diagnostics`, {
    headers: { Authorization: `Bearer ${accessToken}` },
  })
  return readJsonResponse<JobOutboxDiagnostics>(response)
}

export type AiProviderStatus = {
  configured_provider: string
  active_provider: string
  model: string
  ready: boolean
  external_configured: boolean
  execution_mode: string
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
    const errorPayload = (await response.json().catch(() => null)) as {
      error?: { message?: string }
      detail?: string | { message?: string }
    } | null
    const detail = typeof errorPayload?.detail === 'string'
      ? errorPayload.detail
      : errorPayload?.detail?.message
    throw new Error(errorPayload?.error?.message ?? detail ?? `Backend returned ${response.status}`)
  }

  return response.json() as Promise<T>
}

export async function loginWithPassword(request: LoginRequest): Promise<LoginResult> {
  const response = await fetch(`${API_BASE_URL}/auth/login`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    credentials: 'include',
    body: JSON.stringify(request),
  })

  return readJsonResponse<LoginResult>(response)
}

export async function verifyMfaLogin(challengeToken: string, code: string): Promise<AuthSession> {
  const response = await fetch(`${API_BASE_URL}/auth/mfa/verify-login`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    credentials: 'include',
    body: JSON.stringify({ challenge_token: challengeToken, code }),
  })
  return readJsonResponse<AuthSession>(response)
}

export async function fetchMfaStatus(accessToken: string): Promise<MfaStatus> {
  const response = await fetch(`${API_BASE_URL}/auth/mfa/status`, {
    headers: { Authorization: `Bearer ${accessToken}` },
  })
  return readJsonResponse<MfaStatus>(response)
}

export async function startMfaEnrollment(accessToken: string, currentPassword: string): Promise<MfaEnrollment> {
  const response = await fetch(`${API_BASE_URL}/auth/mfa/enroll`, {
    method: 'POST',
    headers: { Authorization: `Bearer ${accessToken}`, 'Content-Type': 'application/json' },
    body: JSON.stringify({ current_password: currentPassword }),
  })
  return readJsonResponse<MfaEnrollment>(response)
}

export async function confirmMfaEnrollment(accessToken: string, code: string): Promise<MfaRecoveryCodes> {
  const response = await fetch(`${API_BASE_URL}/auth/mfa/confirm`, {
    method: 'POST',
    headers: { Authorization: `Bearer ${accessToken}`, 'Content-Type': 'application/json' },
    body: JSON.stringify({ code }),
  })
  return readJsonResponse<MfaRecoveryCodes>(response)
}

export async function regenerateMfaRecoveryCodes(accessToken: string, code: string): Promise<MfaRecoveryCodes> {
  const response = await fetch(`${API_BASE_URL}/auth/mfa/recovery-codes/regenerate`, {
    method: 'POST',
    headers: { Authorization: `Bearer ${accessToken}`, 'Content-Type': 'application/json' },
    body: JSON.stringify({ code }),
  })
  return readJsonResponse<MfaRecoveryCodes>(response)
}

export async function disableMfa(
  accessToken: string,
  currentPassword: string,
  code: string,
): Promise<{ disabled: boolean; sessions_revoked: number }> {
  const response = await fetch(`${API_BASE_URL}/auth/mfa/disable`, {
    method: 'POST',
    headers: { Authorization: `Bearer ${accessToken}`, 'Content-Type': 'application/json' },
    body: JSON.stringify({ current_password: currentPassword, code }),
  })
  return readJsonResponse<{ disabled: boolean; sessions_revoked: number }>(response)
}

export async function fetchSsoConfig(): Promise<SsoConfig> {
  const response = await fetch(`${API_BASE_URL}/auth/sso/config`, {
    headers: { Accept: 'application/json' },
    credentials: 'same-origin',
  })
  return readJsonResponse<SsoConfig>(response)
}

export function buildSsoLoginUrl(loginPath: string, returnTo: string): string {
  const apiUrl = new URL(API_BASE_URL, window.location.origin)
  const loginUrl = new URL(loginPath, apiUrl.origin)
  loginUrl.searchParams.set('return_to', returnTo)
  return loginUrl.toString()
}

export async function refreshAuthSession(): Promise<AuthSession> {
  const response = await fetch(`${API_BASE_URL}/auth/refresh`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    credentials: 'include',
  })

  return readJsonResponse<AuthSession>(response)
}

export async function logoutSession(accessToken: string | undefined): Promise<{ ok: boolean }> {
  const headers: Record<string, string> = { 'Content-Type': 'application/json' }
  if (accessToken) {
    headers.Authorization = `Bearer ${accessToken}`
  }
  const response = await fetch(`${API_BASE_URL}/auth/logout`, {
    method: 'POST',
    headers,
    credentials: 'include',
    body: JSON.stringify({}),
  })
  return readJsonResponse<{ ok: boolean }>(response)
}

export async function fetchCurrentUser(accessToken: string): Promise<AuthUser> {
  const response = await fetch(`${API_BASE_URL}/auth/me`, {
    headers: { Authorization: `Bearer ${accessToken}` },
  })

  return readJsonResponse<AuthUser>(response)
}

export async function fetchMyAccount(accessToken: string): Promise<AccountProfile> {
  const response = await fetchWithAuthRetry(
    `${API_BASE_URL}/auth/account`,
    undefined,
    accessToken,
  )
  return readJsonResponse<AccountProfile>(response)
}

export async function fetchMySessions(accessToken: string): Promise<SelfAuthSession[]> {
  const response = await fetchWithAuthRetry(
    `${API_BASE_URL}/auth/sessions`,
    undefined,
    accessToken,
  )
  return readJsonResponse<SelfAuthSession[]>(response)
}

export async function revokeMySession(
  accessToken: string,
  sessionId: string,
): Promise<{
  session_id: string
  revoked: boolean
  current_session_revoked: boolean
}> {
  const response = await fetchWithAuthRetry(
    `${API_BASE_URL}/auth/sessions/${sessionId}/revoke`,
    { method: 'POST' },
    accessToken,
  )
  return readJsonResponse<{
    session_id: string
    revoked: boolean
    current_session_revoked: boolean
  }>(response)
}

export async function changeMyPassword(
  accessToken: string,
  currentPassword: string,
  newPassword: string,
): Promise<{
  changed: boolean
  sessions_revoked: number
  reauthentication_required: boolean
}> {
  const response = await fetch(`${API_BASE_URL}/auth/password/change`, {
    method: 'POST',
    headers: {
      Authorization: `Bearer ${accessToken}`,
      'Content-Type': 'application/json',
    },
    credentials: 'include',
    body: JSON.stringify({
      current_password: currentPassword,
      new_password: newPassword,
    }),
  })
  return readJsonResponse<{
    changed: boolean
    sessions_revoked: number
    reauthentication_required: boolean
  }>(response)
}

export async function fetchTenants(accessToken: string): Promise<Tenant[]> {
  const response = await fetch(`${API_BASE_URL}/tenants`, {
    headers: { Authorization: `Bearer ${accessToken}` },
  })

  return readJsonResponse<Tenant[]>(response)
}

export async function createTenant(
  accessToken: string,
  request: { name: string; slug: string; description?: string | null },
): Promise<Tenant> {
  const response = await fetch(`${API_BASE_URL}/tenants`, {
    method: 'POST',
    headers: { Authorization: `Bearer ${accessToken}`, 'Content-Type': 'application/json' },
    body: JSON.stringify(request),
  })
  return readJsonResponse<Tenant>(response)
}

export async function fetchCurrentTenant(accessToken: string): Promise<Tenant | null> {
  const response = await fetch(`${API_BASE_URL}/tenants/current`, {
    headers: { Authorization: `Bearer ${accessToken}` },
  })
  return readJsonResponse<Tenant | null>(response)
}

export async function patchCurrentTenant(
  accessToken: string,
  request: { name?: string; description?: string | null },
): Promise<Tenant> {
  const response = await fetch(`${API_BASE_URL}/tenants/current`, {
    method: 'PATCH',
    headers: { Authorization: `Bearer ${accessToken}`, 'Content-Type': 'application/json' },
    body: JSON.stringify(request),
  })
  return readJsonResponse<Tenant>(response)
}

function tenantExperienceUrl(
  path: string,
  tenantId?: string | null,
): string {
  const search = new URLSearchParams()
  if (tenantId) search.set('tenant_id', tenantId)
  const query = search.toString()
  return `${API_BASE_URL}/tenant-experience${path}${query ? `?${query}` : ''}`
}

export async function fetchTenantExperience(
  accessToken: string,
  tenantId?: string | null,
): Promise<TenantExperience> {
  const response = await fetchWithAuthRetry(
    tenantExperienceUrl('/current', tenantId),
    undefined,
    accessToken,
  )
  return readJsonResponse<TenantExperience>(response)
}

export async function updateTenantExperience(
  accessToken: string,
  request: {
    expected_revision: number
    change_reason: string
    settings: TenantExperienceSettings
  },
  tenantId?: string | null,
): Promise<TenantExperience> {
  const response = await fetchWithAuthRetry(
    tenantExperienceUrl('/current', tenantId),
    {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(request),
    },
    accessToken,
  )
  return readJsonResponse<TenantExperience>(response)
}

export async function fetchTenantExperienceRevisions(
  accessToken: string,
  tenantId?: string | null,
): Promise<TenantExperienceRevision[]> {
  const response = await fetchWithAuthRetry(
    tenantExperienceUrl('/revisions', tenantId),
    undefined,
    accessToken,
  )
  return readJsonResponse<TenantExperienceRevision[]>(response)
}

export async function rollbackTenantExperience(
  accessToken: string,
  request: {
    expected_revision: number
    target_revision: number
    change_reason: string
  },
  tenantId?: string | null,
): Promise<TenantExperience> {
  const response = await fetchWithAuthRetry(
    tenantExperienceUrl('/rollback', tenantId),
    {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(request),
    },
    accessToken,
  )
  return readJsonResponse<TenantExperience>(response)
}

export async function uploadTenantLogo(
  accessToken: string,
  file: File,
  expectedRevision: number,
  changeReason: string,
  tenantId?: string | null,
): Promise<TenantExperience> {
  const form = new FormData()
  form.set('file', file)
  form.set('expected_revision', String(expectedRevision))
  form.set('change_reason', changeReason)
  const response = await fetchWithAuthRetry(
    tenantExperienceUrl('/logo', tenantId),
    { method: 'POST', body: form },
    accessToken,
  )
  return readJsonResponse<TenantExperience>(response)
}

export async function removeTenantLogo(
  accessToken: string,
  expectedRevision: number,
  changeReason: string,
  tenantId?: string | null,
): Promise<TenantExperience> {
  const response = await fetchWithAuthRetry(
    tenantExperienceUrl('/logo', tenantId),
    {
      method: 'DELETE',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        expected_revision: expectedRevision,
        change_reason: changeReason,
      }),
    },
    accessToken,
  )
  return readJsonResponse<TenantExperience>(response)
}

function localizedContentUrl(
  path = '',
  params?: {
    tenant_id?: string | null
    resource_type?: LocalizedResourceType
    resource_id?: string
    locale?: string
  },
): string {
  const search = new URLSearchParams()
  if (params?.tenant_id) search.set('tenant_id', params.tenant_id)
  if (params?.resource_type) search.set('resource_type', params.resource_type)
  if (params?.resource_id) search.set('resource_id', params.resource_id)
  if (params?.locale) search.set('locale', params.locale)
  const query = search.toString()
  return `${API_BASE_URL}/tenant-content-translations${path}${query ? `?${query}` : ''}`
}

export async function fetchLocalizedContentVariants(
  accessToken: string,
  params?: {
    tenant_id?: string | null
    resource_type?: LocalizedResourceType
    resource_id?: string
    locale?: string
  },
): Promise<LocalizedContentVariant[]> {
  const response = await fetchWithAuthRetry(
    localizedContentUrl('', params),
    undefined,
    accessToken,
  )
  return readJsonResponse<LocalizedContentVariant[]>(response)
}

export async function fetchLocalizedContentSources(
  accessToken: string,
  resourceType: LocalizedResourceType,
  tenantId?: string | null,
): Promise<LocalizedContentSource[]> {
  const response = await fetchWithAuthRetry(
    localizedContentUrl('/sources', {
      tenant_id: tenantId,
      resource_type: resourceType,
    }),
    undefined,
    accessToken,
  )
  return readJsonResponse<LocalizedContentSource[]>(response)
}

export async function createLocalizedContentVariant(
  accessToken: string,
  request: {
    tenant_id?: string | null
    resource_type: LocalizedResourceType
    resource_id: string
    locale: string
    payload: Record<string, string>
  },
): Promise<LocalizedContentVariant> {
  const response = await fetchWithAuthRetry(
    localizedContentUrl(),
    {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(request),
    },
    accessToken,
  )
  return readJsonResponse<LocalizedContentVariant>(response)
}

export async function updateLocalizedContentVariant(
  accessToken: string,
  translationId: string,
  expectedRevision: number,
  payload: Record<string, string>,
  tenantId?: string | null,
): Promise<LocalizedContentVariant> {
  const response = await fetchWithAuthRetry(
    localizedContentUrl(`/${translationId}`, { tenant_id: tenantId }),
    {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        expected_revision: expectedRevision,
        payload,
      }),
    },
    accessToken,
  )
  return readJsonResponse<LocalizedContentVariant>(response)
}

export async function submitLocalizedContentVariant(
  accessToken: string,
  translationId: string,
  expectedRevision: number,
  submissionNote: string,
  tenantId?: string | null,
): Promise<LocalizedContentVariant> {
  const response = await fetchWithAuthRetry(
    localizedContentUrl(`/${translationId}/submit`, { tenant_id: tenantId }),
    {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        expected_revision: expectedRevision,
        submission_note: submissionNote,
      }),
    },
    accessToken,
  )
  return readJsonResponse<LocalizedContentVariant>(response)
}

export async function decideLocalizedContentVariant(
  accessToken: string,
  translationId: string,
  expectedRevision: number,
  decision: 'APPROVE' | 'REJECT',
  reviewComment: string,
  tenantId?: string | null,
): Promise<LocalizedContentVariant> {
  const response = await fetchWithAuthRetry(
    localizedContentUrl(`/${translationId}/decision`, { tenant_id: tenantId }),
    {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        expected_revision: expectedRevision,
        decision,
        review_comment: reviewComment,
      }),
    },
    accessToken,
  )
  return readJsonResponse<LocalizedContentVariant>(response)
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
  const response = await fetchWithAuthRetry(`${API_BASE_URL}/tickets${query ? `?${query}` : ''}`, undefined, accessToken)

  return readJsonResponse<PaginatedResponse<Ticket>>(response)
}

export async function fetchTickets(accessToken: string): Promise<Ticket[]> {
  const page = await fetchTicketsPage(accessToken, { page: 1, page_size: API_MAX_PAGE_SIZE })
  return page.items
}

export async function fetchChangesPage(
  accessToken: string,
  params?: ChangeQueryParams,
): Promise<PaginatedResponse<ChangeRequest>> {
  const search = new URLSearchParams()
  if (params?.q) search.set('q', params.q)
  if (params?.status && params.status !== 'ALL') search.set('status', params.status)
  if (params?.change_type && params.change_type !== 'ALL') search.set('change_type', params.change_type)
  if (params?.risk_level && params.risk_level !== 'ALL') search.set('risk_level', params.risk_level)
  if (params?.tenant_id) search.set('tenant_id', params.tenant_id)
  if (typeof params?.page === 'number') search.set('page', String(params.page))
  if (typeof params?.page_size === 'number') search.set('page_size', String(params.page_size))
  const query = search.toString()
  const response = await fetchWithAuthRetry(
    `${API_BASE_URL}/changes${query ? `?${query}` : ''}`,
    undefined,
    accessToken,
  )
  return readJsonResponse<PaginatedResponse<ChangeRequest>>(response)
}

export async function fetchChangeSummary(accessToken: string): Promise<ChangeSummary> {
  const response = await fetchWithAuthRetry(`${API_BASE_URL}/changes/summary`, undefined, accessToken)
  return readJsonResponse<ChangeSummary>(response)
}

export async function fetchChange(accessToken: string, changeId: string): Promise<ChangeDetail> {
  const response = await fetchWithAuthRetry(`${API_BASE_URL}/changes/${changeId}`, undefined, accessToken)
  return readJsonResponse<ChangeDetail>(response)
}

export async function createChange(
  accessToken: string,
  request: CreateChangeRequest,
): Promise<ChangeDetail> {
  const response = await fetchWithAuthRetry(`${API_BASE_URL}/changes`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(request),
  }, accessToken)
  return readJsonResponse<ChangeDetail>(response)
}

export async function patchChange(
  accessToken: string,
  changeId: string,
  request: Record<string, unknown> & { expected_version: number },
): Promise<ChangeDetail> {
  const response = await fetchWithAuthRetry(`${API_BASE_URL}/changes/${changeId}`, {
    method: 'PATCH',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(request),
  }, accessToken)
  return readJsonResponse<ChangeDetail>(response)
}

export async function transitionChange(
  accessToken: string,
  changeId: string,
  request: {
    action: string
    expected_version: number
    comment?: string
    planned_start_at?: string
    planned_end_at?: string
    blackout_override_reason?: string
  },
): Promise<ChangeDetail> {
  const response = await fetchWithAuthRetry(`${API_BASE_URL}/changes/${changeId}/transitions`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(request),
  }, accessToken)
  return readJsonResponse<ChangeDetail>(response)
}

export async function decideChange(
  accessToken: string,
  changeId: string,
  request: { decision: 'APPROVED' | 'REJECTED'; comment: string; expected_version: number },
): Promise<ChangeDetail> {
  const response = await fetchWithAuthRetry(`${API_BASE_URL}/changes/${changeId}/decisions`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(request),
  }, accessToken)
  return readJsonResponse<ChangeDetail>(response)
}

function changeGovernanceUrl(path: string, tenantId?: string): string {
  const search = new URLSearchParams()
  if (tenantId) search.set('tenant_id', tenantId)
  const query = search.toString()
  return `${API_BASE_URL}/change-governance${path}${query ? `?${query}` : ''}`
}

export async function fetchChangeCalendar(
  accessToken: string,
  startsAt: string,
  endsAt: string,
  tenantId?: string,
): Promise<ChangeCalendar> {
  const search = new URLSearchParams({ starts_at: startsAt, ends_at: endsAt })
  if (tenantId) search.set('tenant_id', tenantId)
  const response = await fetchWithAuthRetry(
    `${API_BASE_URL}/change-governance/calendar?${search.toString()}`,
    undefined,
    accessToken,
  )
  return readJsonResponse<ChangeCalendar>(response)
}

export async function fetchChangeWindows(
  accessToken: string,
  tenantId?: string,
): Promise<ChangeWindow[]> {
  const response = await fetchWithAuthRetry(changeGovernanceUrl('/windows', tenantId), undefined, accessToken)
  return readJsonResponse<ChangeWindow[]>(response)
}

export async function createChangeWindow(
  accessToken: string,
  request: {
    tenant_id?: string
    name: string
    description?: string
    window_type: 'MAINTENANCE' | 'BLACKOUT'
    starts_at: string
    ends_at: string
    timezone: string
    services: string[]
    asset_ids: string[]
    environments: string[]
    is_active: boolean
  },
): Promise<ChangeWindow> {
  const response = await fetchWithAuthRetry(`${API_BASE_URL}/change-governance/windows`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(request),
  }, accessToken)
  return readJsonResponse<ChangeWindow>(response)
}

export async function updateChangeWindow(
  accessToken: string,
  windowId: string,
  request: { expected_version: number; is_active?: boolean },
): Promise<ChangeWindow> {
  const response = await fetchWithAuthRetry(`${API_BASE_URL}/change-governance/windows/${windowId}`, {
    method: 'PATCH',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(request),
  }, accessToken)
  return readJsonResponse<ChangeWindow>(response)
}

export async function fetchChangeReadiness(accessToken: string, changeId: string): Promise<ChangeReadiness> {
  const response = await fetchWithAuthRetry(
    `${API_BASE_URL}/change-governance/changes/${changeId}/readiness`,
    undefined,
    accessToken,
  )
  return readJsonResponse<ChangeReadiness>(response)
}

export async function fetchChangeWindowAssessment(
  accessToken: string,
  changeId: string,
): Promise<ChangeWindowAssessment> {
  const response = await fetchWithAuthRetry(
    `${API_BASE_URL}/change-governance/changes/${changeId}/window-assessment`,
    undefined,
    accessToken,
  )
  return readJsonResponse<ChangeWindowAssessment>(response)
}

export async function fetchStandardChangeModels(
  accessToken: string,
  tenantId?: string,
): Promise<StandardChangeModel[]> {
  const response = await fetchWithAuthRetry(changeGovernanceUrl('/standard-models', tenantId), undefined, accessToken)
  return readJsonResponse<StandardChangeModel[]>(response)
}

export async function createStandardChangeModel(
  accessToken: string,
  request: {
    tenant_id?: string
    code: string
    name: string
    description: string
    service_name?: string
    environment: string
    default_duration_minutes: number
    implementation_plan: string
    test_plan: string
    rollback_plan: string
    validation_plan: string
    task_templates: Array<Record<string, unknown>>
    scope: Record<string, unknown>
    preauthorized_until: string
    review_due_at: string
    is_active: boolean
  },
): Promise<StandardChangeModel> {
  const response = await fetchWithAuthRetry(`${API_BASE_URL}/change-governance/standard-models`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(request),
  }, accessToken)
  return readJsonResponse<StandardChangeModel>(response)
}

export async function updateStandardChangeModel(
  accessToken: string,
  modelId: string,
  request: { expected_version: number; is_active?: boolean },
): Promise<StandardChangeModel> {
  const response = await fetchWithAuthRetry(`${API_BASE_URL}/change-governance/standard-models/${modelId}`, {
    method: 'PATCH',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(request),
  }, accessToken)
  return readJsonResponse<StandardChangeModel>(response)
}

export async function instantiateStandardChange(
  accessToken: string,
  modelId: string,
  request: {
    title?: string
    planned_start_at?: string
    owner_id?: string
    asset_ids?: string[]
    ticket_ids?: string[]
  },
): Promise<ChangeDetail> {
  const response = await fetchWithAuthRetry(
    `${API_BASE_URL}/change-governance/standard-models/${modelId}/instantiate`,
    {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(request),
    },
    accessToken,
  )
  return readJsonResponse<ChangeDetail>(response)
}

export async function fetchChangeTasks(accessToken: string, changeId: string): Promise<ChangeTask[]> {
  const response = await fetchWithAuthRetry(
    `${API_BASE_URL}/change-governance/changes/${changeId}/tasks`,
    undefined,
    accessToken,
  )
  return readJsonResponse<ChangeTask[]>(response)
}

export async function createChangeTask(
  accessToken: string,
  changeId: string,
  request: {
    task_type: ChangeTask['task_type']
    title: string
    description?: string
    is_required: boolean
    owner_id?: string
    due_at?: string
  },
): Promise<ChangeTask> {
  const response = await fetchWithAuthRetry(`${API_BASE_URL}/change-governance/changes/${changeId}/tasks`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(request),
  }, accessToken)
  return readJsonResponse<ChangeTask>(response)
}

export async function updateChangeTask(
  accessToken: string,
  changeId: string,
  taskId: string,
  request: { expected_version: number; status: ChangeTask['status']; evidence?: string },
): Promise<ChangeTask> {
  const response = await fetchWithAuthRetry(
    `${API_BASE_URL}/change-governance/changes/${changeId}/tasks/${taskId}`,
    {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(request),
    },
    accessToken,
  )
  return readJsonResponse<ChangeTask>(response)
}

export async function fetchChangePIR(accessToken: string, changeId: string): Promise<ChangePIR> {
  const response = await fetchWithAuthRetry(
    `${API_BASE_URL}/change-governance/changes/${changeId}/pir`,
    undefined,
    accessToken,
  )
  return readJsonResponse<ChangePIR>(response)
}

export async function saveChangePIR(
  accessToken: string,
  changeId: string,
  request: {
    expected_version?: number
    outcome: ChangePIR['outcome']
    objectives_met: boolean
    actual_impact: string
    actual_outage_minutes: number
    incidents_caused: number
    lessons_learned: string
    follow_up_actions: Array<Record<string, unknown>>
  },
): Promise<ChangePIR> {
  const response = await fetchWithAuthRetry(`${API_BASE_URL}/change-governance/changes/${changeId}/pir`, {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(request),
  }, accessToken)
  return readJsonResponse<ChangePIR>(response)
}

export async function submitChangePIR(accessToken: string, changeId: string, version: number): Promise<ChangePIR> {
  const response = await fetchWithAuthRetry(`${API_BASE_URL}/change-governance/changes/${changeId}/pir/submit`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ expected_version: version }),
  }, accessToken)
  return readJsonResponse<ChangePIR>(response)
}

export async function approveChangePIR(
  accessToken: string,
  changeId: string,
  version: number,
  comment: string,
): Promise<ChangePIR> {
  const response = await fetchWithAuthRetry(`${API_BASE_URL}/change-governance/changes/${changeId}/pir/approve`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ expected_version: version, comment }),
  }, accessToken)
  return readJsonResponse<ChangePIR>(response)
}

export async function fetchCABMeetings(accessToken: string, tenantId?: string): Promise<CABMeeting[]> {
  const response = await fetchWithAuthRetry(changeGovernanceUrl('/cab/meetings', tenantId), undefined, accessToken)
  return readJsonResponse<CABMeeting[]>(response)
}

export async function createCABMeeting(
  accessToken: string,
  request: {
    tenant_id?: string
    title: string
    meeting_type: 'CAB' | 'ECAB'
    scheduled_at: string
    duration_minutes: number
    location_or_url?: string
    chair_user_id?: string
    participant_user_ids: string[]
  },
): Promise<CABMeeting> {
  const response = await fetchWithAuthRetry(`${API_BASE_URL}/change-governance/cab/meetings`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(request),
  }, accessToken)
  return readJsonResponse<CABMeeting>(response)
}

export async function addCABAgendaItem(
  accessToken: string,
  meetingId: string,
  request: { change_id: string; recommendation?: string },
): Promise<CABMeeting> {
  const response = await fetchWithAuthRetry(`${API_BASE_URL}/change-governance/cab/meetings/${meetingId}/agenda`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(request),
  }, accessToken)
  return readJsonResponse<CABMeeting>(response)
}

export async function updateCABMeeting(
  accessToken: string,
  meetingId: string,
  request: { expected_version: number; status?: CABMeeting['status']; minutes?: string },
): Promise<CABMeeting> {
  const response = await fetchWithAuthRetry(`${API_BASE_URL}/change-governance/cab/meetings/${meetingId}`, {
    method: 'PATCH',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(request),
  }, accessToken)
  return readJsonResponse<CABMeeting>(response)
}

export async function decideCABAgendaItem(
  accessToken: string,
  agendaItemId: string,
  request: { decision: 'APPROVED' | 'REJECTED' | 'DEFERRED' | 'MORE_INFO'; comment: string; evidence: Record<string, unknown> },
): Promise<CABMeeting> {
  const response = await fetchWithAuthRetry(`${API_BASE_URL}/change-governance/cab/agenda/${agendaItemId}/decision`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(request),
  }, accessToken)
  return readJsonResponse<CABMeeting>(response)
}

export async function fetchChangeAnalytics(
  accessToken: string,
  tenantId?: string,
  days = 90,
): Promise<ChangeAnalytics> {
  const search = new URLSearchParams({ days: String(days) })
  if (tenantId) search.set('tenant_id', tenantId)
  const response = await fetchWithAuthRetry(
    `${API_BASE_URL}/change-governance/analytics?${search.toString()}`,
    undefined,
    accessToken,
  )
  return readJsonResponse<ChangeAnalytics>(response)
}

function releaseUrl(path = '', tenantId?: string) {
  const search = new URLSearchParams()
  if (tenantId) search.set('tenant_id', tenantId)
  const query = search.toString()
  return `${API_BASE_URL}/releases${path}${query ? `?${query}` : ''}`
}

export async function fetchReleaseEnvironments(
  accessToken: string,
  tenantId?: string,
): Promise<ReleaseEnvironment[]> {
  const response = await fetchWithAuthRetry(releaseUrl('/environments', tenantId), undefined, accessToken)
  return readJsonResponse<ReleaseEnvironment[]>(response)
}

export async function createReleaseEnvironment(
  accessToken: string,
  request: {
    tenant_id?: string
    code: string
    name: string
    environment_type: ReleaseEnvironment['environment_type']
    promotion_order: number
    requires_approval: boolean
    requires_smoke_test: boolean
    is_production: boolean
    is_active: boolean
  },
): Promise<ReleaseEnvironment> {
  const response = await fetchWithAuthRetry(`${API_BASE_URL}/releases/environments`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(request),
  }, accessToken)
  return readJsonResponse<ReleaseEnvironment>(response)
}

export async function updateReleaseEnvironment(
  accessToken: string,
  environmentId: string,
  request: { expected_version: number; is_active?: boolean; promotion_order?: number },
): Promise<ReleaseEnvironment> {
  const response = await fetchWithAuthRetry(`${API_BASE_URL}/releases/environments/${environmentId}`, {
    method: 'PATCH',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(request),
  }, accessToken)
  return readJsonResponse<ReleaseEnvironment>(response)
}

export async function fetchReleasesPage(
  accessToken: string,
  params?: { q?: string; status?: string; service_name?: string; tenant_id?: string; page?: number; page_size?: number },
): Promise<PaginatedResponse<ReleaseRecord>> {
  const search = new URLSearchParams()
  if (params?.q) search.set('q', params.q)
  if (params?.status && params.status !== 'ALL') search.set('status', params.status)
  if (params?.service_name) search.set('service_name', params.service_name)
  if (params?.tenant_id) search.set('tenant_id', params.tenant_id)
  if (params?.page) search.set('page', String(params.page))
  if (params?.page_size) search.set('page_size', String(params.page_size))
  const query = search.toString()
  const response = await fetchWithAuthRetry(`${API_BASE_URL}/releases${query ? `?${query}` : ''}`, undefined, accessToken)
  return readJsonResponse<PaginatedResponse<ReleaseRecord>>(response)
}

export async function fetchRelease(accessToken: string, releaseId: string): Promise<ReleaseDetail> {
  const response = await fetchWithAuthRetry(`${API_BASE_URL}/releases/${releaseId}`, undefined, accessToken)
  return readJsonResponse<ReleaseDetail>(response)
}

export async function createRelease(
  accessToken: string,
  request: {
    tenant_id?: string
    name: string
    version_name: string
    release_type: ReleaseRecord['release_type']
    service_name: string
    description: string
    scope: string
    release_notes?: string
    risk_level: ReleaseRecord['risk_level']
    target_release_at: string
    window_start_at?: string
    window_end_at?: string
    validation_plan: string
    rollback_plan: string
    communication_plan: string
    owner_id?: string
  },
): Promise<ReleaseDetail> {
  const response = await fetchWithAuthRetry(`${API_BASE_URL}/releases`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(request),
  }, accessToken)
  return readJsonResponse<ReleaseDetail>(response)
}

export async function transitionRelease(
  accessToken: string,
  releaseId: string,
  request: { expected_version: number; action: 'SUBMIT' | 'MARK_READY' | 'PUBLISH' | 'CANCEL'; comment: string },
): Promise<ReleaseDetail> {
  const response = await fetchWithAuthRetry(`${API_BASE_URL}/releases/${releaseId}/transition`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(request),
  }, accessToken)
  return readJsonResponse<ReleaseDetail>(response)
}

export async function linkReleaseChange(
  accessToken: string,
  releaseId: string,
  request: { change_id: string; sequence: number; is_mandatory: boolean; notes?: string },
): Promise<ReleaseDetail> {
  const response = await fetchWithAuthRetry(`${API_BASE_URL}/releases/${releaseId}/changes`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(request),
  }, accessToken)
  return readJsonResponse<ReleaseDetail>(response)
}

export async function addReleasePackage(
  accessToken: string,
  releaseId: string,
  request: {
    component_name: string
    package_type: ReleasePackage['package_type']
    version_name: string
    artifact_uri: string
    checksum_sha256: string
    build_reference?: string
    dependencies: Array<Record<string, unknown>>
  },
): Promise<ReleaseDetail> {
  const response = await fetchWithAuthRetry(`${API_BASE_URL}/releases/${releaseId}/packages`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(request),
  }, accessToken)
  return readJsonResponse<ReleaseDetail>(response)
}

export async function verifyReleasePackage(
  accessToken: string,
  releaseId: string,
  packageId: string,
  request: { expected_version: number; verification_status: ReleasePackage['verification_status']; evidence?: string },
): Promise<ReleaseDetail> {
  const response = await fetchWithAuthRetry(`${API_BASE_URL}/releases/${releaseId}/packages/${packageId}`, {
    method: 'PATCH',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(request),
  }, accessToken)
  return readJsonResponse<ReleaseDetail>(response)
}

export async function addReleaseDependency(
  accessToken: string,
  releaseId: string,
  request: { dependency_release_id: string; dependency_type: 'REQUIRES' | 'BLOCKS' | 'FOLLOWS'; notes?: string },
): Promise<ReleaseDetail> {
  const response = await fetchWithAuthRetry(`${API_BASE_URL}/releases/${releaseId}/dependencies`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(request),
  }, accessToken)
  return readJsonResponse<ReleaseDetail>(response)
}

export async function decideReleaseGate(
  accessToken: string,
  releaseId: string,
  gateId: string,
  request: { expected_version: number; status: 'PASSED' | 'FAILED' | 'WAIVED'; evidence: string; comment: string },
): Promise<ReleaseDetail> {
  const response = await fetchWithAuthRetry(`${API_BASE_URL}/releases/${releaseId}/gates/${gateId}`, {
    method: 'PATCH',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(request),
  }, accessToken)
  return readJsonResponse<ReleaseDetail>(response)
}

export async function decideReleaseGoNoGo(
  accessToken: string,
  releaseId: string,
  request: { expected_version: number; decision: 'GO' | 'NO_GO' | 'CONDITIONAL'; comment: string; conditions: Array<Record<string, unknown>> },
): Promise<ReleaseDetail> {
  const response = await fetchWithAuthRetry(`${API_BASE_URL}/releases/${releaseId}/decision`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(request),
  }, accessToken)
  return readJsonResponse<ReleaseDetail>(response)
}

export async function planReleaseDeployment(
  accessToken: string,
  releaseId: string,
  request: { environment_id: string; scheduled_at: string; deployment_reference?: string },
): Promise<ReleaseDetail> {
  const response = await fetchWithAuthRetry(`${API_BASE_URL}/releases/${releaseId}/deployments`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(request),
  }, accessToken)
  return readJsonResponse<ReleaseDetail>(response)
}

export async function updateReleaseDeployment(
  accessToken: string,
  releaseId: string,
  deploymentId: string,
  request: {
    expected_version: number
    action: 'START' | 'VALIDATE' | 'SUCCEED' | 'FAIL' | 'ROLLBACK' | 'CANCEL'
    deployment_evidence?: string
    validation_evidence?: string
    smoke_test_status?: 'PENDING' | 'PASSED' | 'FAILED'
    failure_reason?: string
    rollback_evidence?: string
  },
): Promise<ReleaseDetail> {
  const response = await fetchWithAuthRetry(`${API_BASE_URL}/releases/${releaseId}/deployments/${deploymentId}`, {
    method: 'PATCH',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(request),
  }, accessToken)
  return readJsonResponse<ReleaseDetail>(response)
}

export async function fetchReleaseTimeline(
  accessToken: string,
  releaseId: string,
): Promise<ReleaseTimelineEvent[]> {
  const response = await fetchWithAuthRetry(`${API_BASE_URL}/releases/${releaseId}/timeline`, undefined, accessToken)
  return readJsonResponse<ReleaseTimelineEvent[]>(response)
}

export async function fetchReleaseCalendar(
  accessToken: string,
  startsAt: string,
  endsAt: string,
  tenantId?: string,
): Promise<ReleaseCalendar> {
  const search = new URLSearchParams({ starts_at: startsAt, ends_at: endsAt })
  if (tenantId) search.set('tenant_id', tenantId)
  const response = await fetchWithAuthRetry(`${API_BASE_URL}/releases/calendar?${search.toString()}`, undefined, accessToken)
  return readJsonResponse<ReleaseCalendar>(response)
}

export async function fetchReleaseAnalytics(
  accessToken: string,
  tenantId?: string,
  days = 90,
): Promise<ReleaseAnalytics> {
  const search = new URLSearchParams({ days: String(days) })
  if (tenantId) search.set('tenant_id', tenantId)
  const response = await fetchWithAuthRetry(`${API_BASE_URL}/releases/analytics?${search.toString()}`, undefined, accessToken)
  return readJsonResponse<ReleaseAnalytics>(response)
}

export async function fetchProblemRCA(accessToken: string, problemId: string): Promise<ProblemRCA> {
  const response = await fetchWithAuthRetry(`${API_BASE_URL}/problem-governance/problems/${problemId}/rca`, undefined, accessToken)
  return readJsonResponse<ProblemRCA>(response)
}

export async function saveProblemRCA(
  accessToken: string,
  problemId: string,
  request: {
    expected_version?: number
    method: ProblemRCA['method']
    problem_statement: string
    five_whys: Array<Record<string, unknown>>
    ishikawa: Record<string, string[]>
    fault_tree: Record<string, unknown>
    contributing_factors: Array<Record<string, unknown>>
    evidence: Array<Record<string, unknown>>
    conclusion: string
  },
): Promise<ProblemRCA> {
  const response = await fetchWithAuthRetry(`${API_BASE_URL}/problem-governance/problems/${problemId}/rca`, {
    method: 'PUT', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(request),
  }, accessToken)
  return readJsonResponse<ProblemRCA>(response)
}

export async function submitProblemRCA(accessToken: string, problemId: string, version: number): Promise<ProblemRCA> {
  const response = await fetchWithAuthRetry(`${API_BASE_URL}/problem-governance/problems/${problemId}/rca/submit`, {
    method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ expected_version: version }),
  }, accessToken)
  return readJsonResponse<ProblemRCA>(response)
}

export async function decideProblemRCA(
  accessToken: string,
  problemId: string,
  version: number,
  decision: 'APPROVED' | 'REJECTED',
): Promise<ProblemRCA> {
  const response = await fetchWithAuthRetry(`${API_BASE_URL}/problem-governance/problems/${problemId}/rca/decision`, {
    method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({
      expected_version: version, decision, comment: 'Независимая проверка RCA и доказательств завершена.',
    }),
  }, accessToken)
  return readJsonResponse<ProblemRCA>(response)
}

export async function fetchProblemActions(accessToken: string, problemId: string): Promise<ProblemCorrectiveAction[]> {
  const response = await fetchWithAuthRetry(`${API_BASE_URL}/problem-governance/problems/${problemId}/actions`, undefined, accessToken)
  return readJsonResponse<ProblemCorrectiveAction[]>(response)
}

export async function createProblemAction(
  accessToken: string,
  problemId: string,
  request: {
    action_type: ProblemCorrectiveAction['action_type']
    title: string
    description: string
    is_required: boolean
    due_at: string
    effectiveness_criteria: string
  },
): Promise<ProblemCorrectiveAction> {
  const response = await fetchWithAuthRetry(`${API_BASE_URL}/problem-governance/problems/${problemId}/actions`, {
    method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(request),
  }, accessToken)
  return readJsonResponse<ProblemCorrectiveAction>(response)
}

export async function updateProblemAction(
  accessToken: string,
  problemId: string,
  actionId: string,
  request: {
    expected_version: number
    status: ProblemCorrectiveAction['status']
    implementation_evidence?: string
    effectiveness_score?: number
    effectiveness_evidence?: string
  },
): Promise<ProblemCorrectiveAction> {
  const response = await fetchWithAuthRetry(`${API_BASE_URL}/problem-governance/problems/${problemId}/actions/${actionId}`, {
    method: 'PATCH', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(request),
  }, accessToken)
  return readJsonResponse<ProblemCorrectiveAction>(response)
}

export async function fetchProblemTrends(accessToken: string, tenantId?: string): Promise<ProblemTrendSignal[]> {
  const search = new URLSearchParams()
  if (tenantId) search.set('tenant_id', tenantId)
  const query = search.toString()
  const response = await fetchWithAuthRetry(`${API_BASE_URL}/problem-governance/trends${query ? `?${query}` : ''}`, undefined, accessToken)
  return readJsonResponse<ProblemTrendSignal[]>(response)
}

export async function scanProblemTrends(accessToken: string, tenantId?: string): Promise<{ signals_created_or_refreshed: number }> {
  const search = new URLSearchParams()
  if (tenantId) search.set('tenant_id', tenantId)
  const query = search.toString()
  const response = await fetchWithAuthRetry(`${API_BASE_URL}/problem-governance/trends/scan${query ? `?${query}` : ''}`, { method: 'POST' }, accessToken)
  return readJsonResponse<{ signals_created_or_refreshed: number }>(response)
}

export async function disposeProblemTrend(
  accessToken: string,
  signal: ProblemTrendSignal,
  action: 'ACKNOWLEDGE' | 'DISMISS' | 'CONVERT',
): Promise<ProblemTrendSignal> {
  const response = await fetchWithAuthRetry(`${API_BASE_URL}/problem-governance/trends/${signal.id}`, {
    method: 'PATCH', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({
      expected_version: signal.version, action, comment: `Управляемое решение по trend signal: ${action}.`,
    }),
  }, accessToken)
  return readJsonResponse<ProblemTrendSignal>(response)
}

export async function fetchProblemGovernanceAnalytics(accessToken: string, tenantId?: string): Promise<ProblemGovernanceAnalytics> {
  const search = new URLSearchParams()
  if (tenantId) search.set('tenant_id', tenantId)
  const query = search.toString()
  const response = await fetchWithAuthRetry(`${API_BASE_URL}/problem-governance/analytics${query ? `?${query}` : ''}`, undefined, accessToken)
  return readJsonResponse<ProblemGovernanceAnalytics>(response)
}

export async function fetchKnownErrorMetrics(accessToken: string, tenantId?: string): Promise<KnownErrorMetrics> {
  const search = new URLSearchParams()
  if (tenantId) search.set('tenant_id', tenantId)
  const query = search.toString()
  const response = await fetchWithAuthRetry(`${API_BASE_URL}/problem-governance/known-errors/metrics${query ? `?${query}` : ''}`, undefined, accessToken)
  return readJsonResponse<KnownErrorMetrics>(response)
}

export async function fetchProblemsPage(
  accessToken: string,
  params?: ProblemQueryParams,
): Promise<PaginatedResponse<ProblemRecord>> {
  const search = new URLSearchParams()
  if (params?.q) search.set('q', params.q)
  if (params?.status && params.status !== 'ALL') search.set('status', params.status)
  if (params?.problem_type && params.problem_type !== 'ALL') search.set('problem_type', params.problem_type)
  if (params?.priority && params.priority !== 'ALL') search.set('priority', params.priority)
  if (typeof params?.known_error === 'boolean') search.set('known_error', String(params.known_error))
  if (typeof params?.page === 'number') search.set('page', String(params.page))
  if (typeof params?.page_size === 'number') search.set('page_size', String(params.page_size))
  const query = search.toString()
  const response = await fetchWithAuthRetry(
    `${API_BASE_URL}/problems${query ? `?${query}` : ''}`,
    undefined,
    accessToken,
  )
  return readJsonResponse<PaginatedResponse<ProblemRecord>>(response)
}

export async function fetchProblemSummary(accessToken: string): Promise<ProblemSummary> {
  const response = await fetchWithAuthRetry(`${API_BASE_URL}/problems/summary`, undefined, accessToken)
  return readJsonResponse<ProblemSummary>(response)
}

export async function fetchProblem(accessToken: string, problemId: string): Promise<ProblemDetail> {
  const response = await fetchWithAuthRetry(`${API_BASE_URL}/problems/${problemId}`, undefined, accessToken)
  return readJsonResponse<ProblemDetail>(response)
}

export async function fetchKnownErrors(
  accessToken: string,
  params?: { q?: string; service_name?: string; page?: number; page_size?: number },
): Promise<PaginatedResponse<KnownError>> {
  const search = new URLSearchParams()
  if (params?.q) search.set('q', params.q)
  if (params?.service_name) search.set('service_name', params.service_name)
  if (typeof params?.page === 'number') search.set('page', String(params.page))
  if (typeof params?.page_size === 'number') search.set('page_size', String(params.page_size))
  const query = search.toString()
  const response = await fetchWithAuthRetry(
    `${API_BASE_URL}/problems/known-errors${query ? `?${query}` : ''}`,
    undefined,
    accessToken,
  )
  return readJsonResponse<PaginatedResponse<KnownError>>(response)
}

export async function createProblem(
  accessToken: string,
  request: CreateProblemRequest,
): Promise<ProblemDetail> {
  const response = await fetchWithAuthRetry(`${API_BASE_URL}/problems`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(request),
  }, accessToken)
  return readJsonResponse<ProblemDetail>(response)
}

export async function patchProblem(
  accessToken: string,
  problemId: string,
  request: Record<string, unknown> & { expected_version: number },
): Promise<ProblemDetail> {
  const response = await fetchWithAuthRetry(`${API_BASE_URL}/problems/${problemId}`, {
    method: 'PATCH',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(request),
  }, accessToken)
  return readJsonResponse<ProblemDetail>(response)
}

export async function transitionProblem(
  accessToken: string,
  problemId: string,
  request: {
    action: string
    expected_version: number
    comment?: string
    root_cause?: string
    known_error_title?: string
    workaround?: string
    resolution_summary?: string
    validation_summary?: string
  },
): Promise<ProblemDetail> {
  const response = await fetchWithAuthRetry(`${API_BASE_URL}/problems/${problemId}/transitions`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(request),
  }, accessToken)
  return readJsonResponse<ProblemDetail>(response)
}

export async function fetchTicket(accessToken: string, ticketId: string): Promise<TicketDetail> {
  const response = await fetchWithAuthRetry(`${API_BASE_URL}/tickets/${ticketId}`, undefined, accessToken)

  return readJsonResponse<TicketDetail>(response)
}

export async function fetchTicketDuplicateCandidates(
  accessToken: string,
  ticketId: string,
  minScore = 45,
): Promise<TicketDuplicateCandidate[]> {
  const response = await fetchWithAuthRetry(
    `${API_BASE_URL}/tickets/${ticketId}/duplicate-candidates?min_score=${encodeURIComponent(minScore)}`,
    undefined,
    accessToken,
  )
  return readJsonResponse<TicketDuplicateCandidate[]>(response)
}

export async function dismissTicketDuplicateCandidate(
  accessToken: string,
  ticketId: string,
  candidateId: string,
  request: {
    expected_ticket_version: number
    expected_candidate_version: number
    reason: string
    idempotency_key: string
  },
): Promise<TicketGovernanceResult> {
  const response = await fetchWithAuthRetry(
    `${API_BASE_URL}/tickets/${ticketId}/duplicate-candidates/${candidateId}/dismiss`,
    {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(request),
    },
    accessToken,
  )
  return readJsonResponse<TicketGovernanceResult>(response)
}

export async function mergeTicket(
  accessToken: string,
  sourceTicketId: string,
  request: {
    target_ticket_id: string
    expected_source_version: number
    expected_target_version: number
    reason: string
    idempotency_key: string
  },
): Promise<TicketGovernanceResult> {
  const response = await fetchWithAuthRetry(`${API_BASE_URL}/tickets/${sourceTicketId}/merge`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(request),
  }, accessToken)
  return readJsonResponse<TicketGovernanceResult>(response)
}

export async function splitTicket(
  accessToken: string,
  sourceTicketId: string,
  request: {
    title: string
    description?: string | null
    category?: string | null
    priority?: string | null
    expected_source_version: number
    reason: string
    idempotency_key: string
  },
): Promise<TicketGovernanceResult> {
  const response = await fetchWithAuthRetry(`${API_BASE_URL}/tickets/${sourceTicketId}/split`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(request),
  }, accessToken)
  return readJsonResponse<TicketGovernanceResult>(response)
}

export async function createTicket(accessToken: string, request: CreateTicketRequest): Promise<TicketDetail> {
  const response = await fetchWithAuthRetry(`${API_BASE_URL}/tickets`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(request),
  }, accessToken)

  return readJsonResponse<TicketDetail>(response)
}

export async function fetchTicketRequesterCandidates(
  accessToken: string,
  query?: string,
): Promise<TicketRequesterCandidate[]> {
  const search = new URLSearchParams()
  if (query?.trim()) search.set('q', query.trim())
  const suffix = search.toString()
  const response = await fetchWithAuthRetry(
    `${API_BASE_URL}/tickets/requester-candidates${suffix ? `?${suffix}` : ''}`,
    undefined,
    accessToken,
  )
  return readJsonResponse<TicketRequesterCandidate[]>(response)
}

export async function patchTicket(accessToken: string, ticketId: string, request: UpdateTicketRequest): Promise<TicketDetail> {
  const response = await fetchWithAuthRetry(`${API_BASE_URL}/tickets/${ticketId}`, {
    method: 'PATCH',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(request),
  }, accessToken)

  return readJsonResponse<TicketDetail>(response)
}

export async function transitionTicket(accessToken: string, ticketId: string, request: TicketTransitionRequest): Promise<TicketDetail> {
  const response = await fetchWithAuthRetry(`${API_BASE_URL}/tickets/${ticketId}/transition`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(request),
  }, accessToken)

  return readJsonResponse<TicketDetail>(response)
}

export async function assignTicket(accessToken: string, ticketId: string, request: TicketAssignRequest): Promise<TicketDetail> {
  const response = await fetchWithAuthRetry(`${API_BASE_URL}/tickets/${ticketId}/assign`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(request),
  }, accessToken)

  return readJsonResponse<TicketDetail>(response)
}

export type TicketBulkTargetPreview = {
  ticket_id: string
  ticket_number: string | null
  title: string
  current_status: string
  effective_status: string
  target_status: string | null
  current_assignee_name: string | null
  target_assignee_name: string | null
  eligible: boolean
  reason: string | null
}

export type TicketBulkPreview = {
  plan_id: string
  status: 'PREVIEWED' | string
  revision: number
  operation_sha256: string
  targets_sha256: string
  confirmation_phrase: string
  eligible_count: number
  skipped_count: number
  expires_at: string
  targets: TicketBulkTargetPreview[]
}

export type TicketBulkExecution = {
  plan_id: string
  status: 'EXECUTED' | string
  revision: number
  updated_count: number
  skipped_count: number
  already_executed: boolean
  executed_at: string
}

export async function previewTicketBulkAction(
  accessToken: string,
  payload: {
    ticket_ids: string[]
    status?: string | null
    assignee_id?: string | null
    comment?: string | null
  },
) {
  const response = await fetchWithAuthRetry(
    `${API_BASE_URL}/tickets/bulk/preview`,
    {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    },
    accessToken,
  )
  return readJsonResponse<TicketBulkPreview>(response)
}

export async function executeTicketBulkAction(
  accessToken: string,
  planId: string,
  payload: {
    expected_revision: number
    confirmation_phrase: string
  },
) {
  const response = await fetchWithAuthRetry(
    `${API_BASE_URL}/tickets/bulk/${encodeURIComponent(planId)}/execute`,
    {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    },
    accessToken,
  )
  return readJsonResponse<TicketBulkExecution>(response)
}

export async function addTicketComment(accessToken: string, ticketId: string, request: CreateCommentRequest): Promise<TicketComment> {
  const response = await fetchWithAuthRetry(`${API_BASE_URL}/tickets/${ticketId}/comments`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(request),
  }, accessToken)

  return readJsonResponse<TicketComment>(response)
}

export async function fetchTicketHistory(accessToken: string, ticketId: string): Promise<TicketHistory[]> {
  const response = await fetchWithAuthRetry(`${API_BASE_URL}/tickets/${ticketId}/history`, undefined, accessToken)

  return readJsonResponse<TicketHistory[]>(response)
}

export async function fetchTicketParticipants(accessToken: string, ticketId: string): Promise<TicketParticipant[]> {
  const response = await fetchWithAuthRetry(
    `${API_BASE_URL}/tickets/${ticketId}/participants`,
    undefined,
    accessToken,
  )
  return readJsonResponse<TicketParticipant[]>(response)
}

export async function fetchTicketParticipantCandidates(
  accessToken: string,
  ticketId: string,
): Promise<TicketParticipantCandidate[]> {
  const response = await fetchWithAuthRetry(
    `${API_BASE_URL}/tickets/${ticketId}/participant-candidates`,
    undefined,
    accessToken,
  )
  return readJsonResponse<TicketParticipantCandidate[]>(response)
}

export async function addTicketParticipant(
  accessToken: string,
  ticketId: string,
  request: {
    user_id?: string
    display_name?: string
    email?: string
    participant_role: TicketParticipant['participant_role']
    notification_scope: TicketParticipant['notification_scope']
    notify_in_app: boolean
    notify_email: boolean
    reason: string
  },
): Promise<TicketParticipant> {
  const response = await fetchWithAuthRetry(`${API_BASE_URL}/tickets/${ticketId}/participants`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(request),
  }, accessToken)
  return readJsonResponse<TicketParticipant>(response)
}

export async function watchTicket(
  accessToken: string,
  ticketId: string,
  request: {
    notification_scope: TicketParticipant['notification_scope']
    notify_in_app: boolean
    notify_email: boolean
  },
): Promise<TicketParticipant> {
  const response = await fetchWithAuthRetry(`${API_BASE_URL}/tickets/${ticketId}/participants/self`, {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(request),
  }, accessToken)
  return readJsonResponse<TicketParticipant>(response)
}

export async function updateTicketParticipant(
  accessToken: string,
  ticketId: string,
  participantId: string,
  request: {
    expected_version: number
    participant_role?: TicketParticipant['participant_role']
    notification_scope?: TicketParticipant['notification_scope']
    notify_in_app?: boolean
    notify_email?: boolean
    reason: string
  },
): Promise<TicketParticipant> {
  const response = await fetchWithAuthRetry(
    `${API_BASE_URL}/tickets/${ticketId}/participants/${participantId}`,
    {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(request),
    },
    accessToken,
  )
  return readJsonResponse<TicketParticipant>(response)
}

export async function removeTicketParticipant(
  accessToken: string,
  ticketId: string,
  participantId: string,
  reason: string,
): Promise<TicketParticipant> {
  const response = await fetchWithAuthRetry(
    `${API_BASE_URL}/tickets/${ticketId}/participants/${participantId}?reason=${encodeURIComponent(reason)}`,
    { method: 'DELETE' },
    accessToken,
  )
  return readJsonResponse<TicketParticipant>(response)
}

export async function fetchMajorIncidents(accessToken: string): Promise<MajorIncident[]> {
  const response = await fetchWithAuthRetry(`${API_BASE_URL}/major-incidents`, undefined, accessToken)
  return readJsonResponse<MajorIncident[]>(response)
}

export async function fetchMajorIncidentSummary(accessToken: string): Promise<MajorIncidentSummary> {
  const response = await fetchWithAuthRetry(`${API_BASE_URL}/major-incidents/summary`, undefined, accessToken)
  return readJsonResponse<MajorIncidentSummary>(response)
}

export async function fetchMajorIncidentResponders(
  accessToken: string,
  ticketId?: string,
): Promise<MajorIncidentResponder[]> {
  const query = ticketId ? `?ticket_id=${encodeURIComponent(ticketId)}` : ''
  const response = await fetchWithAuthRetry(`${API_BASE_URL}/major-incidents/responders${query}`, undefined, accessToken)
  return readJsonResponse<MajorIncidentResponder[]>(response)
}

export async function fetchMajorIncident(accessToken: string, incidentId: string): Promise<MajorIncident> {
  const response = await fetchWithAuthRetry(`${API_BASE_URL}/major-incidents/${incidentId}`, undefined, accessToken)
  return readJsonResponse<MajorIncident>(response)
}

export async function declareMajorIncident(
  accessToken: string,
  request: {
    ticket_id: string
    severity: 'SEV1' | 'SEV2'
    title: string
    executive_summary: string
    impact_statement: string
    affected_service: string
    customer_impact: string
    commander_user_id: string
    communications_lead_user_id: string
    war_room_url?: string
  },
): Promise<MajorIncident> {
  const response = await fetchWithAuthRetry(`${API_BASE_URL}/major-incidents`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(request),
  }, accessToken)
  return readJsonResponse<MajorIncident>(response)
}

export async function addMajorIncidentUpdate(
  accessToken: string,
  incidentId: string,
  request: { update_type: string; audience: string; message: string; service_status?: string; channel?: string },
): Promise<MajorIncident> {
  const response = await fetchWithAuthRetry(`${API_BASE_URL}/major-incidents/${incidentId}/updates`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(request),
  }, accessToken)
  return readJsonResponse<MajorIncident>(response)
}

export async function addMajorIncidentParticipant(
  accessToken: string,
  incidentId: string,
  request: { role: string; user_id?: string; display_name: string; contact?: string },
): Promise<MajorIncident> {
  const response = await fetchWithAuthRetry(`${API_BASE_URL}/major-incidents/${incidentId}/participants`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(request),
  }, accessToken)
  return readJsonResponse<MajorIncident>(response)
}

export async function linkMajorIncidentChild(
  accessToken: string,
  incidentId: string,
  ticketId: string,
): Promise<MajorIncident> {
  const response = await fetchWithAuthRetry(`${API_BASE_URL}/major-incidents/${incidentId}/children`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ ticket_id: ticketId }),
  }, accessToken)
  return readJsonResponse<MajorIncident>(response)
}

export async function createMajorIncidentAction(
  accessToken: string,
  incidentId: string,
  request: { title: string; description: string; owner_user_id: string; due_at: string },
): Promise<MajorIncident> {
  const response = await fetchWithAuthRetry(`${API_BASE_URL}/major-incidents/${incidentId}/actions`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(request),
  }, accessToken)
  return readJsonResponse<MajorIncident>(response)
}

export async function updateMajorIncidentAction(
  accessToken: string,
  incidentId: string,
  action: MajorIncident['actions'][number],
  actionStatus: string,
  completionEvidence?: string,
): Promise<MajorIncident> {
  const response = await fetchWithAuthRetry(`${API_BASE_URL}/major-incidents/${incidentId}/actions/${action.id}`, {
    method: 'PATCH',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      expected_version: action.version,
      action_status: actionStatus,
      completion_evidence: completionEvidence,
    }),
  }, accessToken)
  return readJsonResponse<MajorIncident>(response)
}

export async function transitionMajorIncident(
  accessToken: string,
  incident: MajorIncident,
  action: string,
  comment: string,
): Promise<MajorIncident> {
  const response = await fetchWithAuthRetry(`${API_BASE_URL}/major-incidents/${incident.id}/transitions`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ expected_version: incident.version, action, comment }),
  }, accessToken)
  return readJsonResponse<MajorIncident>(response)
}

export async function saveMajorIncidentPIR(
  accessToken: string,
  incident: MajorIncident,
  request: { summary: string; root_cause: string; contributing_factors: string; lessons_learned: string; prevention_plan: string },
): Promise<MajorIncident> {
  const response = await fetchWithAuthRetry(`${API_BASE_URL}/major-incidents/${incident.id}/pir`, {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ ...request, expected_version: incident.pir?.version }),
  }, accessToken)
  return readJsonResponse<MajorIncident>(response)
}

export async function approveMajorIncidentPIR(accessToken: string, incident: MajorIncident): Promise<MajorIncident> {
  const response = await fetchWithAuthRetry(`${API_BASE_URL}/major-incidents/${incident.id}/pir/approve`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ expected_version: incident.pir?.version }),
  }, accessToken)
  return readJsonResponse<MajorIncident>(response)
}

function eventOperationsUrl(path: string, tenantId?: string): string {
  const url = new URL(`${API_BASE_URL}/event-operations${path}`)
  if (tenantId) url.searchParams.set('tenant_id', tenantId)
  return url.toString()
}

export async function fetchEventOperationsSummary(
  accessToken: string,
  tenantId?: string,
): Promise<EventOperationsSummary> {
  const response = await fetchWithAuthRetry(eventOperationsUrl('/summary', tenantId), undefined, accessToken)
  return readJsonResponse<EventOperationsSummary>(response)
}

export async function fetchEventResponders(
  accessToken: string,
  tenantId?: string,
): Promise<EventResponder[]> {
  const response = await fetchWithAuthRetry(eventOperationsUrl('/responders', tenantId), undefined, accessToken)
  return readJsonResponse<EventResponder[]>(response)
}

export async function fetchEventSources(
  accessToken: string,
  tenantId?: string,
): Promise<EventSource[]> {
  const response = await fetchWithAuthRetry(eventOperationsUrl('/sources', tenantId), undefined, accessToken)
  return readJsonResponse<EventSource[]>(response)
}

export async function createEventSource(
  accessToken: string,
  request: {
    tenant_id?: string
    code: string
    name: string
    source_type: string
    auth_mode?: 'BEARER' | 'HMAC_SHA256'
    replay_window_seconds?: number
    rate_limit_per_minute?: number
    max_payload_bytes?: number
    allowed_ip_cidrs?: string[]
    signing_secret?: string
  },
): Promise<EventSource> {
  const response = await fetchWithAuthRetry(`${API_BASE_URL}/event-operations/sources`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(request),
  }, accessToken)
  return readJsonResponse<EventSource>(response)
}

export async function updateEventSource(
  accessToken: string,
  source: EventSource,
  request: {
    name?: string
    is_enabled?: boolean
    replay_window_seconds?: number
    rate_limit_per_minute?: number
    max_payload_bytes?: number
    allowed_ip_cidrs?: string[]
  },
): Promise<EventSource> {
  const response = await fetchWithAuthRetry(`${API_BASE_URL}/event-operations/sources/${source.id}`, {
    method: 'PATCH',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ ...request, expected_version: source.version }),
  }, accessToken)
  return readJsonResponse<EventSource>(response)
}

export async function rotateEventSourceToken(
  accessToken: string,
  source: EventSource,
): Promise<EventSource> {
  const response = await fetchWithAuthRetry(`${API_BASE_URL}/event-operations/sources/${source.id}/rotate-token`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ expected_version: source.version }),
  }, accessToken)
  return readJsonResponse<EventSource>(response)
}

export async function rotateEventSourceHmacSecret(
  accessToken: string,
  source: EventSource,
  signingSecret?: string,
): Promise<EventSource> {
  const response = await fetchWithAuthRetry(`${API_BASE_URL}/event-operations/sources/${source.id}/rotate-hmac-secret`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      expected_version: source.version,
      reason: 'Rotated by monitoring administrator',
      signing_secret: signingSecret || undefined,
    }),
  }, accessToken)
  return readJsonResponse<EventSource>(response)
}

export async function fetchMonitoringWebhookReceipts(
  accessToken: string,
  params?: { tenant_id?: string; source_id?: string; status?: string },
): Promise<MonitoringWebhookReceipt[]> {
  const search = new URLSearchParams()
  if (params?.tenant_id) search.set('tenant_id', params.tenant_id)
  if (params?.source_id) search.set('source_id', params.source_id)
  if (params?.status && params.status !== 'ALL') search.set('status', params.status)
  const query = search.toString()
  const response = await fetchWithAuthRetry(
    `${API_BASE_URL}/event-operations/webhook-receipts${query ? `?${query}` : ''}`,
    undefined,
    accessToken,
  )
  return readJsonResponse<MonitoringWebhookReceipt[]>(response)
}

export async function reprocessMonitoringWebhookReceipt(
  accessToken: string,
  receiptId: string,
): Promise<MonitoringWebhookReceipt> {
  const response = await fetchWithAuthRetry(
    `${API_BASE_URL}/event-operations/webhook-receipts/${receiptId}/reprocess`,
    {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ reason: 'Manual reprocess after connector correction' }),
    },
    accessToken,
  )
  return readJsonResponse<MonitoringWebhookReceipt>(response)
}

export async function fetchEventPolicies(
  accessToken: string,
  tenantId?: string,
): Promise<EventCorrelationPolicy[]> {
  const response = await fetchWithAuthRetry(eventOperationsUrl('/policies', tenantId), undefined, accessToken)
  return readJsonResponse<EventCorrelationPolicy[]>(response)
}

export type EventPolicyRequest = {
  tenant_id?: string
  name: string
  description?: string
  is_active: boolean
  priority_order: number
  matchers: EventMatcher[]
  group_by: string[]
  correlation_window_minutes: number
  min_occurrences: number
  incident_mode: 'CREATE_UPDATE' | 'CORRELATE_ONLY' | 'IGNORE'
  fixed_priority?: string
  category: string
  title_template: string
  resolution_action: 'NONE' | 'RESOLVE' | 'CLOSE'
  primary_user_id?: string
  fallback_user_id?: string
  acknowledge_within_minutes: number
  escalate_after_minutes: number
}

export async function createEventPolicy(
  accessToken: string,
  request: EventPolicyRequest,
): Promise<EventCorrelationPolicy> {
  const response = await fetchWithAuthRetry(`${API_BASE_URL}/event-operations/policies`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(request),
  }, accessToken)
  return readJsonResponse<EventCorrelationPolicy>(response)
}

export async function updateEventPolicy(
  accessToken: string,
  policy: EventCorrelationPolicy,
  request: EventPolicyRequest,
): Promise<EventCorrelationPolicy> {
  const response = await fetchWithAuthRetry(`${API_BASE_URL}/event-operations/policies/${policy.id}`, {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ ...request, expected_version: policy.version }),
  }, accessToken)
  return readJsonResponse<EventCorrelationPolicy>(response)
}

export async function fetchEventSuppressions(
  accessToken: string,
  tenantId?: string,
): Promise<EventSuppressionRule[]> {
  const response = await fetchWithAuthRetry(eventOperationsUrl('/suppressions', tenantId), undefined, accessToken)
  return readJsonResponse<EventSuppressionRule[]>(response)
}

export type EventSuppressionRequest = {
  tenant_id?: string
  name: string
  reason: string
  matchers: EventMatcher[]
  starts_at?: string
  ends_at?: string
  is_active: boolean
}

export async function createEventSuppression(
  accessToken: string,
  request: EventSuppressionRequest,
): Promise<EventSuppressionRule> {
  const response = await fetchWithAuthRetry(`${API_BASE_URL}/event-operations/suppressions`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(request),
  }, accessToken)
  return readJsonResponse<EventSuppressionRule>(response)
}

export async function updateEventSuppression(
  accessToken: string,
  suppression: EventSuppressionRule,
  request: EventSuppressionRequest,
): Promise<EventSuppressionRule> {
  const response = await fetchWithAuthRetry(`${API_BASE_URL}/event-operations/suppressions/${suppression.id}`, {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ ...request, expected_version: suppression.version }),
  }, accessToken)
  return readJsonResponse<EventSuppressionRule>(response)
}

export async function fetchNormalizedEvents(
  accessToken: string,
  params?: { tenant_id?: string; disposition?: string; severity?: string },
): Promise<NormalizedEvent[]> {
  const url = new URL(`${API_BASE_URL}/event-operations/events`)
  if (params?.tenant_id) url.searchParams.set('tenant_id', params.tenant_id)
  if (params?.disposition && params.disposition !== 'ALL') url.searchParams.set('disposition', params.disposition)
  if (params?.severity && params.severity !== 'ALL') url.searchParams.set('severity', params.severity)
  const response = await fetchWithAuthRetry(url.toString(), undefined, accessToken)
  return readJsonResponse<NormalizedEvent[]>(response)
}

export async function fetchEventGroups(
  accessToken: string,
  params?: { tenant_id?: string; group_status?: string },
): Promise<EventCorrelationGroup[]> {
  const url = new URL(`${API_BASE_URL}/event-operations/groups`)
  if (params?.tenant_id) url.searchParams.set('tenant_id', params.tenant_id)
  if (params?.group_status && params.group_status !== 'ALL') url.searchParams.set('group_status', params.group_status)
  const response = await fetchWithAuthRetry(url.toString(), undefined, accessToken)
  return readJsonResponse<EventCorrelationGroup[]>(response)
}

export async function fetchEventGroup(
  accessToken: string,
  groupId: string,
): Promise<EventCorrelationGroup> {
  const response = await fetchWithAuthRetry(`${API_BASE_URL}/event-operations/groups/${groupId}`, undefined, accessToken)
  return readJsonResponse<EventCorrelationGroup>(response)
}

export async function acknowledgeEventGroup(
  accessToken: string,
  group: EventCorrelationGroup,
  note: string,
): Promise<EventCorrelationGroup> {
  const response = await fetchWithAuthRetry(`${API_BASE_URL}/event-operations/groups/${group.id}/acknowledge`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ expected_version: group.version, note }),
  }, accessToken)
  return readJsonResponse<EventCorrelationGroup>(response)
}

export async function evaluateEventEscalations(
  accessToken: string,
  tenantId?: string,
): Promise<{ evaluated: number; group_ids: string[] }> {
  const response = await fetchWithAuthRetry(eventOperationsUrl('/escalations/evaluate', tenantId), {
    method: 'POST',
  }, accessToken)
  return readJsonResponse<{ evaluated: number; group_ids: string[] }>(response)
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

function softwareAssetsUrl(path: string, tenantId?: string): string {
  const query = tenantId ? `?tenant_id=${encodeURIComponent(tenantId)}` : ''
  return `${API_BASE_URL}/software-assets${path}${query}`
}

export async function fetchSoftwareAssetDashboard(
  accessToken: string,
  tenantId?: string,
): Promise<SoftwareAssetDashboard> {
  const response = await fetchWithAuthRetry(
    softwareAssetsUrl('/dashboard', tenantId),
    undefined,
    accessToken,
  )
  return readJsonResponse<SoftwareAssetDashboard>(response)
}

export async function fetchSoftwareProducts(
  accessToken: string,
  tenantId?: string,
): Promise<SoftwareProduct[]> {
  const response = await fetchWithAuthRetry(
    softwareAssetsUrl('/products', tenantId),
    undefined,
    accessToken,
  )
  return readJsonResponse<SoftwareProduct[]>(response)
}

export async function createSoftwareProduct(
  accessToken: string,
  request: {
    tenant_id?: string
    name: string
    publisher: string
    version: string
    edition?: string
    category?: string
    sku?: string
    is_prohibited?: boolean
    prohibited_reason?: string
  },
): Promise<SoftwareProduct> {
  const response = await fetchWithAuthRetry(`${API_BASE_URL}/software-assets/products`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(request),
  }, accessToken)
  return readJsonResponse<SoftwareProduct>(response)
}

export async function updateSoftwareProduct(
  accessToken: string,
  product: SoftwareProduct,
  request: Partial<Pick<SoftwareProduct, 'name' | 'publisher' | 'version' | 'edition' | 'category' | 'sku' | 'status' | 'is_prohibited' | 'prohibited_reason'>> & { reason: string },
): Promise<SoftwareProduct> {
  const response = await fetchWithAuthRetry(`${API_BASE_URL}/software-assets/products/${product.id}`, {
    method: 'PATCH',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ ...request, expected_version: product.version_number }),
  }, accessToken)
  return readJsonResponse<SoftwareProduct>(response)
}

export async function fetchSoftwareLicenses(
  accessToken: string,
  tenantId?: string,
): Promise<SoftwareLicense[]> {
  const response = await fetchWithAuthRetry(
    softwareAssetsUrl('/licenses', tenantId),
    undefined,
    accessToken,
  )
  return readJsonResponse<SoftwareLicense[]>(response)
}

export async function createSoftwareLicense(
  accessToken: string,
  request: {
    tenant_id?: string
    product_id: string
    license_reference: string
    license_type: string
    purchased_quantity: number
    vendor?: string
    contract_reference?: string
    expires_at?: string
    renewal_at?: string
    auto_renew?: boolean
    unit_cost: number
    currency: string
  },
): Promise<SoftwareLicense> {
  const response = await fetchWithAuthRetry(`${API_BASE_URL}/software-assets/licenses`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(request),
  }, accessToken)
  return readJsonResponse<SoftwareLicense>(response)
}

export async function fetchSoftwareInstallations(
  accessToken: string,
  tenantId?: string,
): Promise<SoftwareInstallation[]> {
  const response = await fetchWithAuthRetry(
    softwareAssetsUrl('/installations', tenantId),
    undefined,
    accessToken,
  )
  return readJsonResponse<SoftwareInstallation[]>(response)
}

export async function createSoftwareInstallation(
  accessToken: string,
  request: {
    tenant_id?: string
    product_id: string
    asset_id: string
    detected_version?: string
    source: string
    authorization_status: SoftwareInstallation['authorization_status']
    authorization_reason?: string
  },
): Promise<SoftwareInstallation> {
  const response = await fetchWithAuthRetry(`${API_BASE_URL}/software-assets/installations`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(request),
  }, accessToken)
  return readJsonResponse<SoftwareInstallation>(response)
}

export async function updateSoftwareInstallation(
  accessToken: string,
  installation: SoftwareInstallation,
  request: {
    authorization_status?: SoftwareInstallation['authorization_status']
    authorization_reason?: string
    status?: SoftwareInstallation['status']
    reason: string
  },
): Promise<SoftwareInstallation> {
  const response = await fetchWithAuthRetry(
    `${API_BASE_URL}/software-assets/installations/${installation.id}`,
    {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ ...request, expected_version: installation.version_number }),
    },
    accessToken,
  )
  return readJsonResponse<SoftwareInstallation>(response)
}

export async function reconcileSoftwareAssets(
  accessToken: string,
  tenantId?: string,
): Promise<{ expired_licenses_updated: number; dashboard: SoftwareAssetDashboard }> {
  const response = await fetchWithAuthRetry(
    softwareAssetsUrl('/reconcile', tenantId),
    { method: 'POST' },
    accessToken,
  )
  return readJsonResponse<{ expired_licenses_updated: number; dashboard: SoftwareAssetDashboard }>(response)
}

export async function fetchCIClasses(
  accessToken: string,
  tenantId?: string,
): Promise<CIClass[]> {
  const query = tenantId ? `?tenant_id=${encodeURIComponent(tenantId)}` : ''
  const response = await fetchWithAuthRetry(
    `${API_BASE_URL}/cmdb/classes${query}`,
    undefined,
    accessToken,
  )
  return readJsonResponse<CIClass[]>(response)
}

export async function createCIClass(
  accessToken: string,
  request: CreateCIClassRequest,
): Promise<CIClass> {
  const response = await fetchWithAuthRetry(`${API_BASE_URL}/cmdb/classes`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(request),
  }, accessToken)
  return readJsonResponse<CIClass>(response)
}

export async function createCIClassDraft(
  accessToken: string,
  classId: string,
): Promise<CIClass> {
  const response = await fetchWithAuthRetry(
    `${API_BASE_URL}/cmdb/classes/${classId}/draft`,
    { method: 'POST' },
    accessToken,
  )
  return readJsonResponse<CIClass>(response)
}

export async function updateCIClassDraft(
  accessToken: string,
  classId: string,
  request: { expected_revision: number; schema: { fields: CIClassField[] } },
): Promise<CIClass> {
  const response = await fetchWithAuthRetry(
    `${API_BASE_URL}/cmdb/classes/${classId}/draft`,
    {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(request),
    },
    accessToken,
  )
  return readJsonResponse<CIClass>(response)
}

export async function publishCIClass(
  accessToken: string,
  classId: string,
  request: { expected_revision: number; reason: string },
): Promise<CIClass> {
  const response = await fetchWithAuthRetry(
    `${API_BASE_URL}/cmdb/classes/${classId}/publish`,
    {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(request),
    },
    accessToken,
  )
  return readJsonResponse<CIClass>(response)
}

export async function createConfigurationItem(
  accessToken: string,
  request: CreateConfigurationItemRequest,
): Promise<{
  id: string
  asset_tag: string
  ci_class_code: string
  ci_schema_hash: string
  version: number
}> {
  const response = await fetchWithAuthRetry(`${API_BASE_URL}/cmdb/items`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(request),
  }, accessToken)
  return readJsonResponse(response)
}

export async function fetchConfigurationItems(
  accessToken: string,
  tenantId?: string,
  q?: string,
): Promise<ConfigurationItemSummary[]> {
  const search = new URLSearchParams()
  if (tenantId) search.set('tenant_id', tenantId)
  if (q) search.set('q', q)
  search.set('limit', '500')
  const response = await fetchWithAuthRetry(
    `${API_BASE_URL}/cmdb/items?${search.toString()}`,
    undefined,
    accessToken,
  )
  return readJsonResponse<ConfigurationItemSummary[]>(response)
}

export async function fetchCIRelationshipTypes(
  accessToken: string,
  tenantId?: string,
): Promise<CIRelationshipType[]> {
  const query = tenantId ? `?tenant_id=${encodeURIComponent(tenantId)}` : ''
  const response = await fetchWithAuthRetry(
    `${API_BASE_URL}/cmdb/relationship-types${query}`,
    undefined,
    accessToken,
  )
  return readJsonResponse<CIRelationshipType[]>(response)
}

export async function createCIRelationshipType(
  accessToken: string,
  request: CreateCIRelationshipTypeRequest,
): Promise<CIRelationshipType> {
  const response = await fetchWithAuthRetry(
    `${API_BASE_URL}/cmdb/relationship-types`,
    {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(request),
    },
    accessToken,
  )
  return readJsonResponse<CIRelationshipType>(response)
}

export async function createCIRelationship(
  accessToken: string,
  request: {
    relationship_type_id: string
    source_ci_id: string
    target_ci_id: string
    description?: string | null
  },
): Promise<CIRelationship> {
  const response = await fetchWithAuthRetry(
    `${API_BASE_URL}/cmdb/relationships`,
    {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(request),
    },
    accessToken,
  )
  return readJsonResponse<CIRelationship>(response)
}

export async function retireCIRelationship(
  accessToken: string,
  relationshipId: string,
  expectedVersion: number,
  reason: string,
): Promise<CIRelationship> {
  const response = await fetchWithAuthRetry(
    `${API_BASE_URL}/cmdb/relationships/${relationshipId}/retire`,
    {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        expected_version: expectedVersion,
        reason,
      }),
    },
    accessToken,
  )
  return readJsonResponse<CIRelationship>(response)
}

export async function fetchCITopology(
  accessToken: string,
  ciId: string,
  direction: 'upstream' | 'downstream' | 'both' = 'both',
  depth = 3,
): Promise<CITopology> {
  const search = new URLSearchParams({
    direction,
    depth: String(depth),
    max_nodes: '300',
  })
  const response = await fetchWithAuthRetry(
    `${API_BASE_URL}/cmdb/topology/${ciId}?${search.toString()}`,
    undefined,
    accessToken,
  )
  return readJsonResponse<CITopology>(response)
}

export async function fetchCMDBSources(
  accessToken: string,
  tenantId?: string,
): Promise<CMDBSource[]> {
  const query = tenantId ? `?tenant_id=${encodeURIComponent(tenantId)}` : ''
  const response = await fetchWithAuthRetry(
    `${API_BASE_URL}/cmdb/sources${query}`,
    undefined,
    accessToken,
  )
  return readJsonResponse<CMDBSource[]>(response)
}

export async function createCMDBSource(
  accessToken: string,
  request: {
    tenant_id?: string
    external_system_id?: string | null
    default_class_id?: string | null
    code: string
    name: string
    description?: string | null
    source_type: CMDBSource['source_type']
    priority: number
    identification_rules: string[]
    authoritative_fields: string[]
    claim_unowned_fields: boolean
    stale_after_hours: number
  },
): Promise<CMDBSource> {
  const response = await fetchWithAuthRetry(`${API_BASE_URL}/cmdb/sources`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(request),
  }, accessToken)
  return readJsonResponse<CMDBSource>(response)
}

export async function updateCMDBSource(
  accessToken: string,
  sourceId: string,
  request: {
    expected_version: number
    status?: CMDBSource['status']
    priority?: number
    stale_after_hours?: number
    claim_unowned_fields?: boolean
    reason: string
  },
): Promise<CMDBSource> {
  const response = await fetchWithAuthRetry(
    `${API_BASE_URL}/cmdb/sources/${sourceId}`,
    {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(request),
    },
    accessToken,
  )
  return readJsonResponse<CMDBSource>(response)
}

export async function previewCMDBReconciliation(
  accessToken: string,
  sourceId: string,
  idempotencyKey: string,
  records: CMDBInputRecord[],
): Promise<CMDBReconciliationRun> {
  const response = await fetchWithAuthRetry(
    `${API_BASE_URL}/cmdb/sources/${sourceId}/reconciliation/preview`,
    {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        idempotency_key: idempotencyKey,
        records,
      }),
    },
    accessToken,
  )
  return readJsonResponse<CMDBReconciliationRun>(response)
}

export async function fetchCMDBReconciliationRuns(
  accessToken: string,
  tenantId?: string,
  sourceId?: string,
): Promise<CMDBReconciliationRun[]> {
  const search = new URLSearchParams({ limit: '100' })
  if (tenantId) search.set('tenant_id', tenantId)
  if (sourceId) search.set('source_id', sourceId)
  const response = await fetchWithAuthRetry(
    `${API_BASE_URL}/cmdb/reconciliation-runs?${search.toString()}`,
    undefined,
    accessToken,
  )
  return readJsonResponse<CMDBReconciliationRun[]>(response)
}

export async function fetchCMDBReconciliationRun(
  accessToken: string,
  runId: string,
): Promise<CMDBReconciliationRun> {
  const response = await fetchWithAuthRetry(
    `${API_BASE_URL}/cmdb/reconciliation-runs/${runId}`,
    undefined,
    accessToken,
  )
  return readJsonResponse<CMDBReconciliationRun>(response)
}

export async function applyCMDBReconciliation(
  accessToken: string,
  runId: string,
): Promise<CMDBReconciliationRun> {
  const response = await fetchWithAuthRetry(
    `${API_BASE_URL}/cmdb/reconciliation-runs/${runId}/apply`,
    { method: 'POST' },
    accessToken,
  )
  return readJsonResponse<CMDBReconciliationRun>(response)
}

export async function fetchCIDuplicateCandidates(
  accessToken: string,
  tenantId?: string,
  candidateStatus: CIDuplicateCandidate['status'] = 'OPEN',
): Promise<CIDuplicateCandidate[]> {
  const search = new URLSearchParams({
    candidate_status: candidateStatus,
    limit: '200',
  })
  if (tenantId) search.set('tenant_id', tenantId)
  const response = await fetchWithAuthRetry(
    `${API_BASE_URL}/cmdb/duplicate-candidates?${search.toString()}`,
    undefined,
    accessToken,
  )
  return readJsonResponse<CIDuplicateCandidate[]>(response)
}

export async function dismissCIDuplicateCandidate(
  accessToken: string,
  candidateId: string,
  expectedVersion: number,
  reason: string,
): Promise<CIDuplicateCandidate> {
  const response = await fetchWithAuthRetry(
    `${API_BASE_URL}/cmdb/duplicate-candidates/${candidateId}/dismiss`,
    {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        expected_version: expectedVersion,
        reason,
      }),
    },
    accessToken,
  )
  return readJsonResponse<CIDuplicateCandidate>(response)
}

export async function mergeCIDuplicateCandidate(
  accessToken: string,
  candidate: CIDuplicateCandidate,
  reason: string,
): Promise<{
  candidate: CIDuplicateCandidate
  merge_summary: Record<string, number>
}> {
  const response = await fetchWithAuthRetry(
    `${API_BASE_URL}/cmdb/duplicate-candidates/${candidate.id}/merge`,
    {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        expected_version: candidate.version,
        expected_primary_version: candidate.primary.version,
        expected_duplicate_version: candidate.duplicate.version,
        reason,
      }),
    },
    accessToken,
  )
  return readJsonResponse(response)
}

export async function fetchCMDBSourceHealth(
  accessToken: string,
  tenantId?: string,
): Promise<CMDBSourceHealth> {
  const query = tenantId ? `?tenant_id=${encodeURIComponent(tenantId)}` : ''
  const response = await fetchWithAuthRetry(
    `${API_BASE_URL}/cmdb/source-health${query}`,
    undefined,
    accessToken,
  )
  return readJsonResponse<CMDBSourceHealth>(response)
}

export async function fetchAssetDiscoveryConnectors(
  accessToken: string,
  tenantId?: string,
): Promise<AssetDiscoveryConnector[]> {
  const query = tenantId ? `?tenant_id=${encodeURIComponent(tenantId)}` : ''
  const response = await fetchWithAuthRetry(
    `${API_BASE_URL}/asset-discovery/connectors${query}`,
    undefined,
    accessToken,
  )
  return readJsonResponse<AssetDiscoveryConnector[]>(response)
}

export async function createAssetDiscoveryConnector(
  accessToken: string,
  request: {
    tenant_id?: string
    cmdb_source_id: string
    name: string
    provider: AssetDiscoveryProvider
    auth_type: AssetDiscoveryConnector['auth_type']
    base_url?: string | null
    credential: Record<string, string>
    configuration: Record<string, unknown>
    schedule_minutes: number
    auto_apply: boolean
    missing_threshold_runs: number
    max_records: number
  },
): Promise<AssetDiscoveryConnector> {
  const response = await fetchWithAuthRetry(
    `${API_BASE_URL}/asset-discovery/connectors`,
    {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(request),
    },
    accessToken,
  )
  return readJsonResponse<AssetDiscoveryConnector>(response)
}

export async function updateAssetDiscoveryConnector(
  accessToken: string,
  connector: AssetDiscoveryConnector,
  request: {
    name?: string
    base_url?: string | null
    configuration?: Record<string, unknown>
    schedule_minutes?: number
    auto_apply?: boolean
    missing_threshold_runs?: number
    max_records?: number
    status?: AssetDiscoveryConnector['status']
    reason: string
  },
): Promise<AssetDiscoveryConnector> {
  const response = await fetchWithAuthRetry(
    `${API_BASE_URL}/asset-discovery/connectors/${connector.id}`,
    {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        expected_version: connector.version,
        ...request,
      }),
    },
    accessToken,
  )
  return readJsonResponse<AssetDiscoveryConnector>(response)
}

export async function rotateAssetDiscoveryCredential(
  accessToken: string,
  connectorId: string,
  credential: Record<string, string>,
  reason: string,
): Promise<AssetDiscoveryConnector> {
  const response = await fetchWithAuthRetry(
    `${API_BASE_URL}/asset-discovery/connectors/${connectorId}/rotate-credential`,
    {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ credential, reason }),
    },
    accessToken,
  )
  return readJsonResponse<AssetDiscoveryConnector>(response)
}

export async function testAssetDiscoveryConnector(
  accessToken: string,
  connectorId: string,
): Promise<{
  ok: boolean
  provider: AssetDiscoveryProvider
  pages: number
  records_returned: number
  sample: { external_id: string; name: string; original_type: string | null } | null
}> {
  const response = await fetchWithAuthRetry(
    `${API_BASE_URL}/asset-discovery/connectors/${connectorId}/test`,
    { method: 'POST' },
    accessToken,
  )
  return readJsonResponse(response)
}

export async function startAssetDiscoveryRun(
  accessToken: string,
  connectorId: string,
): Promise<AssetDiscoveryRun> {
  const response = await fetchWithAuthRetry(
    `${API_BASE_URL}/asset-discovery/connectors/${connectorId}/runs`,
    {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({}),
    },
    accessToken,
  )
  return readJsonResponse<AssetDiscoveryRun>(response)
}

export async function fetchAssetDiscoveryRuns(
  accessToken: string,
  tenantId?: string,
  connectorId?: string,
): Promise<AssetDiscoveryRun[]> {
  const search = new URLSearchParams({ limit: '200' })
  if (tenantId) search.set('tenant_id', tenantId)
  if (connectorId) search.set('connector_id', connectorId)
  const response = await fetchWithAuthRetry(
    `${API_BASE_URL}/asset-discovery/runs?${search.toString()}`,
    undefined,
    accessToken,
  )
  return readJsonResponse<AssetDiscoveryRun[]>(response)
}

export async function retryAssetDiscoveryRun(
  accessToken: string,
  runId: string,
  reason: string,
): Promise<AssetDiscoveryRun> {
  const response = await fetchWithAuthRetry(
    `${API_BASE_URL}/asset-discovery/runs/${runId}/retry`,
    {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ reason }),
    },
    accessToken,
  )
  return readJsonResponse<AssetDiscoveryRun>(response)
}

export async function fetchAssetDiscoveryStaleCandidates(
  accessToken: string,
  tenantId?: string,
  connectorId?: string,
  candidateStatus: AssetDiscoveryStaleCandidate['status'] | '' = 'OPEN',
): Promise<AssetDiscoveryStaleCandidate[]> {
  const search = new URLSearchParams()
  if (tenantId) search.set('tenant_id', tenantId)
  if (connectorId) search.set('connector_id', connectorId)
  if (candidateStatus) search.set('status', candidateStatus)
  const response = await fetchWithAuthRetry(
    `${API_BASE_URL}/asset-discovery/stale-candidates?${search.toString()}`,
    undefined,
    accessToken,
  )
  return readJsonResponse<AssetDiscoveryStaleCandidate[]>(response)
}

export async function decideAssetDiscoveryStaleCandidate(
  accessToken: string,
  candidate: AssetDiscoveryStaleCandidate,
  decision: 'RETIRE' | 'DISMISS',
  reason: string,
): Promise<AssetDiscoveryStaleCandidate> {
  const response = await fetchWithAuthRetry(
    `${API_BASE_URL}/asset-discovery/stale-candidates/${candidate.id}/decision`,
    {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        expected_version: candidate.version,
        decision,
        reason,
      }),
    },
    accessToken,
  )
  return readJsonResponse<AssetDiscoveryStaleCandidate>(response)
}

export async function fetchAssetDiscoveryDashboard(
  accessToken: string,
  tenantId?: string,
): Promise<AssetDiscoveryDashboard> {
  const query = tenantId ? `?tenant_id=${encodeURIComponent(tenantId)}` : ''
  const response = await fetchWithAuthRetry(
    `${API_BASE_URL}/asset-discovery/dashboard${query}`,
    undefined,
    accessToken,
  )
  return readJsonResponse<AssetDiscoveryDashboard>(response)
}

export async function fetchCIFieldOwnership(
  accessToken: string,
  ciId: string,
): Promise<CMDBFieldOwnership[]> {
  const response = await fetchWithAuthRetry(
    `${API_BASE_URL}/cmdb/items/${ciId}/field-ownership`,
    undefined,
    accessToken,
  )
  return readJsonResponse<CMDBFieldOwnership[]>(response)
}

export async function previewCMDBImpact(
  accessToken: string,
  request: {
    tenant_id?: string
    root_ci_ids: string[]
    direction?: CMDBImpactDirection
    max_depth?: number
  },
): Promise<CMDBImpactAnalysis> {
  const response = await fetchWithAuthRetry(
    `${API_BASE_URL}/cmdb/impact/preview`,
    {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(request),
    },
    accessToken,
  )
  return readJsonResponse<CMDBImpactAnalysis>(response)
}

export async function createCMDBImpactAssessment(
  accessToken: string,
  entityType: CMDBImpactEntityType,
  entityId: string,
  request: {
    tenant_id?: string
    root_ci_ids?: string[]
    direction?: CMDBImpactDirection
    max_depth?: number
    expected_entity_version?: number
  },
): Promise<CMDBImpactAssessment> {
  const response = await fetchWithAuthRetry(
    `${API_BASE_URL}/cmdb/impact/assessments/${entityType}/${encodeURIComponent(entityId)}`,
    {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(request),
    },
    accessToken,
  )
  return readJsonResponse<CMDBImpactAssessment>(response)
}

export async function fetchLatestCMDBImpactAssessment(
  accessToken: string,
  entityType: CMDBImpactEntityType,
  entityId: string,
): Promise<CMDBImpactAssessment | null> {
  const response = await fetchWithAuthRetry(
    `${API_BASE_URL}/cmdb/impact/assessments/${entityType}/${encodeURIComponent(entityId)}/latest`,
    undefined,
    accessToken,
  )
  if (response.status === 404) return null
  return readJsonResponse<CMDBImpactAssessment>(response)
}

export async function fetchCMDBImpactAssessmentHistory(
  accessToken: string,
  entityType: CMDBImpactEntityType,
  entityId: string,
): Promise<CMDBImpactAssessment[]> {
  const response = await fetchWithAuthRetry(
    `${API_BASE_URL}/cmdb/impact/assessments/${entityType}/${encodeURIComponent(entityId)}`,
    undefined,
    accessToken,
  )
  if (response.status === 404) return []
  return readJsonResponse<CMDBImpactAssessment[]>(response)
}

export async function fetchCMDBQualityOverview(
  accessToken: string,
  tenantId?: string,
): Promise<CMDBQualityOverview> {
  const query = tenantId ? `?tenant_id=${encodeURIComponent(tenantId)}` : ''
  const response = await fetchWithAuthRetry(
    `${API_BASE_URL}/cmdb/quality/summary${query}`,
    undefined,
    accessToken,
  )
  return readJsonResponse<CMDBQualityOverview>(response)
}

export async function runCMDBQualityScan(
  accessToken: string,
  tenantId?: string,
): Promise<CMDBQualitySnapshot> {
  const response = await fetchWithAuthRetry(
    `${API_BASE_URL}/cmdb/quality/scan`,
    {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ tenant_id: tenantId }),
    },
    accessToken,
  )
  return readJsonResponse<CMDBQualitySnapshot>(response)
}

export async function fetchCMDBQualityFindings(
  accessToken: string,
  params?: {
    tenant_id?: string
    finding_status?: string
    dimension?: string
    severity?: string
    owner_user_id?: string
    q?: string
  },
): Promise<CMDBQualityFinding[]> {
  const search = new URLSearchParams({ limit: '500' })
  for (const [key, value] of Object.entries(params ?? {})) {
    if (value) search.set(key, value)
  }
  const response = await fetchWithAuthRetry(
    `${API_BASE_URL}/cmdb/quality/findings?${search.toString()}`,
    undefined,
    accessToken,
  )
  return readJsonResponse<CMDBQualityFinding[]>(response)
}

export async function updateCMDBQualityFinding(
  accessToken: string,
  findingId: string,
  request: {
    expected_version: number
    owner_user_id?: string | null
    due_at?: string | null
    finding_status?: CMDBQualityFinding['status']
    resolution_note?: string | null
  },
): Promise<CMDBQualityFinding> {
  const response = await fetchWithAuthRetry(
    `${API_BASE_URL}/cmdb/quality/findings/${findingId}`,
    {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(request),
    },
    accessToken,
  )
  return readJsonResponse<CMDBQualityFinding>(response)
}

export async function fetchCMDBCertificationCampaigns(
  accessToken: string,
  tenantId?: string,
): Promise<CMDBCertificationCampaign[]> {
  const query = tenantId ? `?tenant_id=${encodeURIComponent(tenantId)}` : ''
  const response = await fetchWithAuthRetry(
    `${API_BASE_URL}/cmdb/quality/campaigns${query}`,
    undefined,
    accessToken,
  )
  return readJsonResponse<CMDBCertificationCampaign[]>(response)
}

export async function fetchCMDBCertificationCampaign(
  accessToken: string,
  campaignId: string,
): Promise<CMDBCertificationCampaign> {
  const response = await fetchWithAuthRetry(
    `${API_BASE_URL}/cmdb/quality/campaigns/${campaignId}`,
    undefined,
    accessToken,
  )
  return readJsonResponse<CMDBCertificationCampaign>(response)
}

export async function createCMDBCertificationCampaign(
  accessToken: string,
  request: {
    tenant_id?: string
    name: string
    description?: string
    due_at: string
    scope: CMDBCertificationScope
  },
): Promise<CMDBCertificationCampaign> {
  const response = await fetchWithAuthRetry(
    `${API_BASE_URL}/cmdb/quality/campaigns`,
    {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(request),
    },
    accessToken,
  )
  return readJsonResponse<CMDBCertificationCampaign>(response)
}

export async function activateCMDBCertificationCampaign(
  accessToken: string,
  campaign: CMDBCertificationCampaign,
): Promise<CMDBCertificationCampaign> {
  const response = await fetchWithAuthRetry(
    `${API_BASE_URL}/cmdb/quality/campaigns/${campaign.id}/activate`,
    {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ expected_version: campaign.version }),
    },
    accessToken,
  )
  return readJsonResponse<CMDBCertificationCampaign>(response)
}

export async function decideCMDBCertificationItem(
  accessToken: string,
  campaignId: string,
  item: CMDBCertificationItem,
  decision: 'CERTIFIED' | 'REJECTED',
  note: string,
): Promise<CMDBCertificationCampaign> {
  const response = await fetchWithAuthRetry(
    `${API_BASE_URL}/cmdb/quality/campaigns/${campaignId}/items/${item.id}/decision`,
    {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        expected_version: item.version,
        decision,
        note,
      }),
    },
    accessToken,
  )
  return readJsonResponse<CMDBCertificationCampaign>(response)
}

export async function completeCMDBCertificationCampaign(
  accessToken: string,
  campaign: CMDBCertificationCampaign,
): Promise<CMDBCertificationCampaign> {
  const response = await fetchWithAuthRetry(
    `${API_BASE_URL}/cmdb/quality/campaigns/${campaign.id}/complete`,
    {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ expected_version: campaign.version }),
    },
    accessToken,
  )
  return readJsonResponse<CMDBCertificationCampaign>(response)
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

function slaUrl(path: string, tenantId?: string): string {
  const search = new URLSearchParams()
  if (tenantId) search.set('tenant_id', tenantId)
  const query = search.toString()
  return `${API_BASE_URL}/sla${path}${query ? `?${query}` : ''}`
}

export async function fetchSlaPolicies(accessToken: string, tenantId?: string): Promise<SlaPolicy[]> {
  const response = await fetchWithAuthRetry(slaUrl('/policies', tenantId), undefined, accessToken)
  return readJsonResponse<SlaPolicy[]>(response)
}

export async function fetchSlaOverview(accessToken: string, tenantId?: string): Promise<SlaOverview> {
  const response = await fetchWithAuthRetry(slaUrl('/overview', tenantId), undefined, accessToken)
  return readJsonResponse<SlaOverview>(response)
}

export async function fetchSlaBreaches(accessToken: string, tenantId?: string): Promise<SlaBreach[]> {
  const response = await fetchWithAuthRetry(slaUrl('/breaches', tenantId), undefined, accessToken)
  return readJsonResponse<SlaBreach[]>(response)
}

export async function fetchSlaCalendars(accessToken: string, tenantId?: string): Promise<SlaCalendar[]> {
  const response = await fetchWithAuthRetry(slaUrl('/calendars', tenantId), undefined, accessToken)
  return readJsonResponse<SlaCalendar[]>(response)
}

export async function fetchSlaCalendar(accessToken: string, calendarId: string): Promise<SlaCalendar> {
  const response = await fetchWithAuthRetry(`${API_BASE_URL}/sla/calendars/${calendarId}`, undefined, accessToken)
  return readJsonResponse<SlaCalendar>(response)
}

export async function createSlaCalendar(
  accessToken: string,
  request: {
    tenant_id?: string
    name: string
    description?: string
    timezone: string
    weekly_hours: Record<string, string[][]>
    is_default: boolean
    is_active: boolean
  },
): Promise<SlaCalendar> {
  const response = await fetchWithAuthRetry(`${API_BASE_URL}/sla/calendars`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(request),
  }, accessToken)
  return readJsonResponse<SlaCalendar>(response)
}

export async function updateSlaCalendar(
  accessToken: string,
  calendarId: string,
  request: {
    expected_version: number
    name?: string
    description?: string
    timezone?: string
    weekly_hours?: Record<string, string[][]>
    is_default?: boolean
    is_active?: boolean
  },
): Promise<SlaCalendar> {
  const response = await fetchWithAuthRetry(`${API_BASE_URL}/sla/calendars/${calendarId}`, {
    method: 'PATCH',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(request),
  }, accessToken)
  return readJsonResponse<SlaCalendar>(response)
}

export async function upsertSlaCalendarException(
  accessToken: string,
  calendarId: string,
  exception: {
    exception_date: string
    kind: 'HOLIDAY' | 'WORKING_DAY'
    name: string
    intervals: string[][]
  },
): Promise<SlaCalendar> {
  const response = await fetchWithAuthRetry(
    `${API_BASE_URL}/sla/calendars/${calendarId}/exceptions/${exception.exception_date}`,
    {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(exception),
    },
    accessToken,
  )
  return readJsonResponse<SlaCalendar>(response)
}

export async function createSlaPolicy(
  accessToken: string,
  request: {
    tenant_id?: string
    name: string
    description?: string
    priority: string
    calendar_id?: string | null
    priority_order: number
    scope: Record<string, unknown>
    targets: SlaTargetDefinition[]
    pause_statuses: string[]
    pause_reasons: string[]
    warning_percent: number
    escalations: SlaEscalation[]
    is_active: boolean
  },
): Promise<SlaPolicy> {
  const response = await fetchWithAuthRetry(`${API_BASE_URL}/sla/policies`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(request),
  }, accessToken)
  return readJsonResponse<SlaPolicy>(response)
}

export async function updateSlaPolicy(
  accessToken: string,
  policyId: string,
  request: Partial<{
    name: string
    description: string
    priority: string
    calendar_id: string | null
    priority_order: number
    scope: Record<string, unknown>
    targets: SlaTargetDefinition[]
    pause_statuses: string[]
    pause_reasons: string[]
    warning_percent: number
    escalations: SlaEscalation[]
    is_active: boolean
  }> & { expected_version: number },
): Promise<SlaPolicy> {
  const response = await fetchWithAuthRetry(`${API_BASE_URL}/sla/policies/${policyId}`, {
    method: 'PATCH',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(request),
  }, accessToken)
  return readJsonResponse<SlaPolicy>(response)
}

export async function fetchSlaQueue(
  accessToken: string,
  options: { tenant_id?: string; states?: string[] } = {},
): Promise<SlaInstance[]> {
  const search = new URLSearchParams()
  if (options.tenant_id) search.set('tenant_id', options.tenant_id)
  for (const state of options.states ?? []) search.append('states', state)
  const query = search.toString()
  const response = await fetchWithAuthRetry(
    `${API_BASE_URL}/sla/queue${query ? `?${query}` : ''}`,
    undefined,
    accessToken,
  )
  return readJsonResponse<SlaInstance[]>(response)
}

export async function fetchSlaInstance(accessToken: string, instanceId: string): Promise<SlaInstance> {
  const response = await fetchWithAuthRetry(`${API_BASE_URL}/sla/instances/${instanceId}`, undefined, accessToken)
  return readJsonResponse<SlaInstance>(response)
}

export async function pauseSlaInstance(
  accessToken: string,
  instanceId: string,
  request: { expected_version: number; reason_code: string; reason: string },
): Promise<SlaInstance> {
  const response = await fetchWithAuthRetry(`${API_BASE_URL}/sla/instances/${instanceId}/pause`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(request),
  }, accessToken)
  return readJsonResponse<SlaInstance>(response)
}

export async function resumeSlaInstance(
  accessToken: string,
  instanceId: string,
  expectedVersion: number,
): Promise<SlaInstance> {
  const response = await fetchWithAuthRetry(`${API_BASE_URL}/sla/instances/${instanceId}/resume`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ expected_version: expectedVersion }),
  }, accessToken)
  return readJsonResponse<SlaInstance>(response)
}

export async function completeSlaTarget(
  accessToken: string,
  instanceId: string,
  targetId: string,
  request: { expected_version: number; reason: string },
): Promise<SlaInstance> {
  const response = await fetchWithAuthRetry(
    `${API_BASE_URL}/sla/instances/${instanceId}/targets/${targetId}/complete`,
    {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(request),
    },
    accessToken,
  )
  return readJsonResponse<SlaInstance>(response)
}

export async function evaluateSla(accessToken: string, tenantId?: string): Promise<{
  evaluated_at: string
  changed_count: number
  target_ids: string[]
}> {
  const response = await fetchWithAuthRetry(slaUrl('/evaluate', tenantId), { method: 'POST' }, accessToken)
  return readJsonResponse(response)
}

export async function fetchKnowledgeCategories(accessToken: string): Promise<KnowledgeCategory[]> {
  const response = await fetch(`${API_BASE_URL}/knowledge/categories`, {
    headers: { Authorization: `Bearer ${accessToken}` },
  })

  return readJsonResponse<KnowledgeCategory[]>(response)
}

export async function createKnowledgeCategory(
  accessToken: string,
  request: { code: string; name: string; description?: string | null },
): Promise<KnowledgeCategory> {
  const response = await fetchWithAuthRetry(`${API_BASE_URL}/knowledge/categories`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(request),
  }, accessToken)
  return readJsonResponse<KnowledgeCategory>(response)
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
  const response = await fetchWithAuthRetry(`${API_BASE_URL}/notifications/unread-count`, undefined, accessToken)
  return readJsonResponse<{ unread_count: number }>(response)
}

export async function markNotificationAsRead(accessToken: string, notificationId: string): Promise<Notification> {
  const response = await fetchWithAuthRetry(`${API_BASE_URL}/notifications/${notificationId}/read`, {
    method: 'PATCH',
  }, accessToken)
  return readJsonResponse<Notification>(response)
}

export async function markAllNotificationsAsRead(accessToken: string): Promise<{ updated: number }> {
  const response = await fetchWithAuthRetry(`${API_BASE_URL}/notifications/read-all`, {
    method: 'PATCH',
  }, accessToken)
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

function emailTenantQuery(tenantId?: string | null) {
  const search = new URLSearchParams()
  if (tenantId) search.set('tenant_id', tenantId)
  const query = search.toString()
  return query ? `?${query}` : ''
}

export async function fetchEmailChannelDashboard(
  accessToken: string,
  tenantId?: string | null,
): Promise<EmailChannelDashboard> {
  const response = await fetch(`${API_BASE_URL}/email/dashboard${emailTenantQuery(tenantId)}`, {
    headers: { Authorization: `Bearer ${accessToken}` },
  })
  return readJsonResponse<EmailChannelDashboard>(response)
}

export async function fetchEmailChannels(
  accessToken: string,
  tenantId?: string | null,
): Promise<EmailChannel[]> {
  const response = await fetch(`${API_BASE_URL}/email/channels${emailTenantQuery(tenantId)}`, {
    headers: { Authorization: `Bearer ${accessToken}` },
  })
  return readJsonResponse<EmailChannel[]>(response)
}

export async function createEmailChannel(
  accessToken: string,
  payload: {
    tenant_id?: string | null
    name: string
    provider_type: 'MICROSOFT_GRAPH' | 'MOCK'
    mailbox_address: string
    mailbox_user_id?: string | null
    entra_tenant_id?: string | null
    client_id?: string | null
    client_secret?: string | null
    inbound_enabled: boolean
    outbound_enabled: boolean
    default_target: 'TICKET' | 'REQUEST'
    allowed_sender_domains: string[]
    allowed_attachment_extensions: string[]
    max_attachment_bytes: number
  },
): Promise<EmailChannel> {
  const response = await fetch(`${API_BASE_URL}/email/channels`, {
    method: 'POST',
    headers: {
      Authorization: `Bearer ${accessToken}`,
      'Content-Type': 'application/json',
    },
    body: JSON.stringify(payload),
  })
  return readJsonResponse<EmailChannel>(response)
}

export async function updateEmailChannel(
  accessToken: string,
  channelId: string,
  payload: Record<string, unknown> & { expected_version: number },
): Promise<EmailChannel> {
  const response = await fetch(`${API_BASE_URL}/email/channels/${channelId}`, {
    method: 'PATCH',
    headers: {
      Authorization: `Bearer ${accessToken}`,
      'Content-Type': 'application/json',
    },
    body: JSON.stringify(payload),
  })
  return readJsonResponse<EmailChannel>(response)
}

export async function rotateEmailChannelSecret(
  accessToken: string,
  channelId: string,
  clientSecret: string,
): Promise<EmailChannel> {
  const response = await fetch(`${API_BASE_URL}/email/channels/${channelId}/rotate-secret`, {
    method: 'POST',
    headers: {
      Authorization: `Bearer ${accessToken}`,
      'Content-Type': 'application/json',
    },
    body: JSON.stringify({ client_secret: clientSecret }),
  })
  return readJsonResponse<EmailChannel>(response)
}

export async function testEmailChannelConnection(
  accessToken: string,
  channelId: string,
): Promise<{ ok: boolean; mailbox: Record<string, unknown> }> {
  const response = await fetch(`${API_BASE_URL}/email/channels/${channelId}/test-connection`, {
    method: 'POST',
    headers: { Authorization: `Bearer ${accessToken}` },
  })
  return readJsonResponse<{ ok: boolean; mailbox: Record<string, unknown> }>(response)
}

export async function changeEmailChannelState(
  accessToken: string,
  channelId: string,
  payload: { expected_version: number; action: 'ACTIVATE' | 'PAUSE' | 'REVOKE'; reason: string },
): Promise<EmailChannel> {
  const response = await fetch(`${API_BASE_URL}/email/channels/${channelId}/state`, {
    method: 'POST',
    headers: {
      Authorization: `Bearer ${accessToken}`,
      'Content-Type': 'application/json',
    },
    body: JSON.stringify(payload),
  })
  return readJsonResponse<EmailChannel>(response)
}

export async function synchronizeEmailSubscription(
  accessToken: string,
  channelId: string,
): Promise<{ subscription_id: string; expires_at: string }> {
  const response = await fetch(`${API_BASE_URL}/email/channels/${channelId}/subscription`, {
    method: 'POST',
    headers: { Authorization: `Bearer ${accessToken}` },
  })
  return readJsonResponse<{ subscription_id: string; expires_at: string }>(response)
}

export async function synchronizeEmailChannel(
  accessToken: string,
  channelId: string,
): Promise<{ received: number; processed: number; failed: number }> {
  const response = await fetch(`${API_BASE_URL}/email/channels/${channelId}/sync`, {
    method: 'POST',
    headers: { Authorization: `Bearer ${accessToken}` },
  })
  return readJsonResponse<{ received: number; processed: number; failed: number }>(response)
}

export async function sendEmailChannelTest(
  accessToken: string,
  channelId: string,
  payload: { to_email: string; subject: string; body: string },
): Promise<{ id: string; status: string }> {
  const response = await fetch(`${API_BASE_URL}/email/channels/${channelId}/test-email`, {
    method: 'POST',
    headers: {
      Authorization: `Bearer ${accessToken}`,
      'Content-Type': 'application/json',
    },
    body: JSON.stringify(payload),
  })
  return readJsonResponse<{ id: string; status: string }>(response)
}

export async function fetchInboundEmail(
  accessToken: string,
  params?: { tenant_id?: string | null; status?: string; channel_id?: string },
): Promise<EmailInboundMessage[]> {
  const search = new URLSearchParams()
  if (params?.tenant_id) search.set('tenant_id', params.tenant_id)
  if (params?.status && params.status !== 'ALL') search.set('status', params.status)
  if (params?.channel_id) search.set('channel_id', params.channel_id)
  const query = search.toString()
  const response = await fetch(`${API_BASE_URL}/email/inbound${query ? `?${query}` : ''}`, {
    headers: { Authorization: `Bearer ${accessToken}` },
  })
  return readJsonResponse<EmailInboundMessage[]>(response)
}

export async function reprocessInboundEmail(
  accessToken: string,
  messageId: string,
  payload: { override_sender_authorization: boolean; reason: string },
): Promise<EmailInboundMessage> {
  const response = await fetch(`${API_BASE_URL}/email/inbound/${messageId}/reprocess`, {
    method: 'POST',
    headers: {
      Authorization: `Bearer ${accessToken}`,
      'Content-Type': 'application/json',
    },
    body: JSON.stringify(payload),
  })
  return readJsonResponse<EmailInboundMessage>(response)
}

export async function fetchEmailConversations(
  accessToken: string,
  tenantId?: string | null,
): Promise<EmailConversation[]> {
  const response = await fetch(`${API_BASE_URL}/email/conversations${emailTenantQuery(tenantId)}`, {
    headers: { Authorization: `Bearer ${accessToken}` },
  })
  return readJsonResponse<EmailConversation[]>(response)
}

export async function fetchEmailAttachments(
  accessToken: string,
  params?: { tenant_id?: string | null; status?: string },
): Promise<EmailAttachment[]> {
  const search = new URLSearchParams()
  if (params?.tenant_id) search.set('tenant_id', params.tenant_id)
  if (params?.status && params.status !== 'ALL') search.set('status', params.status)
  const query = search.toString()
  const response = await fetch(`${API_BASE_URL}/email/attachments${query ? `?${query}` : ''}`, {
    headers: { Authorization: `Bearer ${accessToken}` },
  })
  return readJsonResponse<EmailAttachment[]>(response)
}

export async function decideEmailAttachment(
  accessToken: string,
  attachmentId: string,
  payload: { decision: 'RELEASE' | 'BLOCK'; reason: string },
): Promise<EmailAttachment> {
  const response = await fetch(`${API_BASE_URL}/email/attachments/${attachmentId}/decision`, {
    method: 'POST',
    headers: {
      Authorization: `Bearer ${accessToken}`,
      'Content-Type': 'application/json',
    },
    body: JSON.stringify(payload),
  })
  return readJsonResponse<EmailAttachment>(response)
}

export async function createEmailAttachmentDownloadToken(
  accessToken: string,
  attachmentId: string,
): Promise<{ token: string; ttl_seconds: number; expires_at: string }> {
  const response = await fetch(`${API_BASE_URL}/email/attachments/${attachmentId}/download-token`, {
    method: 'POST',
    headers: { Authorization: `Bearer ${accessToken}` },
  })
  return readJsonResponse(response)
}

export async function fetchEmailDeliveryEvents(
  accessToken: string,
  tenantId?: string | null,
): Promise<EmailDeliveryEvent[]> {
  const response = await fetch(`${API_BASE_URL}/email/delivery-events${emailTenantQuery(tenantId)}`, {
    headers: { Authorization: `Bearer ${accessToken}` },
  })
  return readJsonResponse<EmailDeliveryEvent[]>(response)
}

function teamsTenantQuery(tenantId?: string | null) {
  return tenantId ? `?tenant_id=${encodeURIComponent(tenantId)}` : ''
}

export async function fetchTeamsDashboard(
  accessToken: string,
  tenantId?: string | null,
): Promise<TeamsDashboard> {
  const response = await fetch(`${API_BASE_URL}/teams/dashboard${teamsTenantQuery(tenantId)}`, {
    headers: { Authorization: `Bearer ${accessToken}` },
  })
  return readJsonResponse<TeamsDashboard>(response)
}

export async function fetchTeamsConnectors(
  accessToken: string,
  tenantId?: string | null,
): Promise<TeamsConnector[]> {
  const response = await fetch(`${API_BASE_URL}/teams/connectors${teamsTenantQuery(tenantId)}`, {
    headers: { Authorization: `Bearer ${accessToken}` },
  })
  return readJsonResponse<TeamsConnector[]>(response)
}

export async function createTeamsConnector(
  accessToken: string,
  payload: {
    tenant_id?: string | null
    name: string
    provider_type: 'WORKFLOW_WEBHOOK' | 'MOCK'
    purpose: 'DEFAULT' | 'APPROVALS' | 'MAJOR_INCIDENT' | 'SECURITY'
    webhook_url?: string | null
    team_name?: string | null
    channel_name?: string | null
    channel_url?: string | null
    meeting_url?: string | null
    event_types: string[]
    minimum_severity: 'INFO' | 'WARNING' | 'CRITICAL'
  },
): Promise<TeamsConnector> {
  const response = await fetch(`${API_BASE_URL}/teams/connectors`, {
    method: 'POST',
    headers: {
      Authorization: `Bearer ${accessToken}`,
      'Content-Type': 'application/json',
    },
    body: JSON.stringify(payload),
  })
  return readJsonResponse<TeamsConnector>(response)
}

export async function updateTeamsConnector(
  accessToken: string,
  connectorId: string,
  payload: Record<string, unknown> & { expected_version: number },
): Promise<TeamsConnector> {
  const response = await fetch(`${API_BASE_URL}/teams/connectors/${connectorId}`, {
    method: 'PATCH',
    headers: {
      Authorization: `Bearer ${accessToken}`,
      'Content-Type': 'application/json',
    },
    body: JSON.stringify(payload),
  })
  return readJsonResponse<TeamsConnector>(response)
}

export async function rotateTeamsWebhook(
  accessToken: string,
  connectorId: string,
  webhookUrl: string,
): Promise<TeamsConnector> {
  const response = await fetch(`${API_BASE_URL}/teams/connectors/${connectorId}/rotate-webhook`, {
    method: 'POST',
    headers: {
      Authorization: `Bearer ${accessToken}`,
      'Content-Type': 'application/json',
    },
    body: JSON.stringify({ webhook_url: webhookUrl }),
  })
  return readJsonResponse<TeamsConnector>(response)
}

export async function testTeamsConnector(
  accessToken: string,
  connectorId: string,
): Promise<{ ok: boolean; provider_status_code: number; reference: string | null }> {
  const response = await fetch(`${API_BASE_URL}/teams/connectors/${connectorId}/test`, {
    method: 'POST',
    headers: {
      Authorization: `Bearer ${accessToken}`,
      'Content-Type': 'application/json',
    },
    body: JSON.stringify({}),
  })
  return readJsonResponse<{ ok: boolean; provider_status_code: number; reference: string | null }>(response)
}

export async function changeTeamsConnectorState(
  accessToken: string,
  connectorId: string,
  payload: { expected_version: number; action: 'ACTIVATE' | 'PAUSE' | 'REVOKE'; reason: string },
): Promise<TeamsConnector> {
  const response = await fetch(`${API_BASE_URL}/teams/connectors/${connectorId}/state`, {
    method: 'POST',
    headers: {
      Authorization: `Bearer ${accessToken}`,
      'Content-Type': 'application/json',
    },
    body: JSON.stringify(payload),
  })
  return readJsonResponse<TeamsConnector>(response)
}

export async function fetchTeamsDeliveries(
  accessToken: string,
  params?: { tenant_id?: string | null; connector_id?: string; status?: string },
): Promise<TeamsDelivery[]> {
  const search = new URLSearchParams()
  if (params?.tenant_id) search.set('tenant_id', params.tenant_id)
  if (params?.connector_id) search.set('connector_id', params.connector_id)
  if (params?.status && params.status !== 'ALL') search.set('status', params.status)
  const query = search.toString()
  const response = await fetch(`${API_BASE_URL}/teams/deliveries${query ? `?${query}` : ''}`, {
    headers: { Authorization: `Bearer ${accessToken}` },
  })
  return readJsonResponse<TeamsDelivery[]>(response)
}

export async function retryTeamsDelivery(
  accessToken: string,
  deliveryId: string,
  reason: string,
): Promise<TeamsDelivery> {
  const response = await fetch(`${API_BASE_URL}/teams/deliveries/${deliveryId}/retry`, {
    method: 'POST',
    headers: {
      Authorization: `Bearer ${accessToken}`,
      'Content-Type': 'application/json',
    },
    body: JSON.stringify({ reason }),
  })
  return readJsonResponse<TeamsDelivery>(response)
}

export async function fetchTeamsMajorIncidentRooms(
  accessToken: string,
  tenantId?: string | null,
): Promise<TeamsMajorIncidentRoom[]> {
  const response = await fetch(`${API_BASE_URL}/teams/major-incident-rooms${teamsTenantQuery(tenantId)}`, {
    headers: { Authorization: `Bearer ${accessToken}` },
  })
  return readJsonResponse<TeamsMajorIncidentRoom[]>(response)
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

export async function fetchAdminUserExternalIdentities(
  accessToken: string,
  userId: string,
): Promise<ExternalIdentity[]> {
  const response = await fetch(`${API_BASE_URL}/admin/users/${userId}/external-identities`, {
    headers: { Authorization: `Bearer ${accessToken}` },
  })
  return readJsonResponse<ExternalIdentity[]>(response)
}

export async function linkAdminUserExternalIdentity(
  accessToken: string,
  userId: string,
  request: { subject: string; email_at_link?: string | null },
): Promise<ExternalIdentity> {
  const response = await fetch(`${API_BASE_URL}/admin/users/${userId}/external-identities`, {
    method: 'POST',
    headers: { Authorization: `Bearer ${accessToken}`, 'Content-Type': 'application/json' },
    body: JSON.stringify(request),
  })
  return readJsonResponse<ExternalIdentity>(response)
}

export async function unlinkAdminUserExternalIdentity(
  accessToken: string,
  userId: string,
  identityId: string,
): Promise<void> {
  const response = await fetch(
    `${API_BASE_URL}/admin/users/${userId}/external-identities/${identityId}`,
    {
      method: 'DELETE',
      headers: { Authorization: `Bearer ${accessToken}` },
    },
  )
  if (!response.ok) await readJsonResponse<never>(response)
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
    location?: string | null
    cost_center?: string | null
    phone?: string | null
    role_id?: string | null
    role_ids?: string[]
  },
): Promise<AdminUser> {
  const response = await fetch(`${API_BASE_URL}/admin/users`, {
    method: 'POST',
    headers: { Authorization: `Bearer ${accessToken}`, 'Content-Type': 'application/json' },
    body: JSON.stringify(request),
  })
  return readJsonResponse<AdminUser>(response)
}

export async function patchAdminUser(accessToken: string, userId: string, request: Partial<Pick<AdminUser, 'full_name' | 'position' | 'department' | 'location' | 'cost_center' | 'phone' | 'is_active'>>): Promise<AdminUser> {
  const response = await fetch(`${API_BASE_URL}/admin/users/${userId}`, {
    method: 'PATCH',
    headers: { Authorization: `Bearer ${accessToken}`, 'Content-Type': 'application/json' },
    body: JSON.stringify(request),
  })
  return readJsonResponse<AdminUser>(response)
}

export async function resetAdminUserPassword(
  accessToken: string,
  userId: string,
  newPassword: string,
  revokeSessions = true,
): Promise<{ user_id: string; sessions_revoked: number; password_change_required: boolean }> {
  const response = await fetch(`${API_BASE_URL}/admin/users/${userId}/reset-password`, {
    method: 'POST',
    headers: { Authorization: `Bearer ${accessToken}`, 'Content-Type': 'application/json' },
    body: JSON.stringify({ new_password: newPassword, revoke_sessions: revokeSessions }),
  })
  return readJsonResponse<{
    user_id: string
    sessions_revoked: number
    password_change_required: boolean
  }>(response)
}

export async function updateAdminUser(
  accessToken: string,
  userId: string,
  request: Partial<Pick<AdminUser, 'full_name' | 'position' | 'department' | 'location' | 'cost_center' | 'phone' | 'is_active'>>,
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

export async function fetchAdminRolePermissions(accessToken: string, roleId: string): Promise<AdminPermission[]> {
  const response = await fetch(`${API_BASE_URL}/admin/roles/${roleId}/permissions`, {
    headers: { Authorization: `Bearer ${accessToken}` },
  })
  return readJsonResponse<AdminPermission[]>(response)
}

export async function replaceAdminRolePermissions(
  accessToken: string,
  roleId: string,
  permissionIds: string[],
): Promise<AdminPermission[]> {
  const response = await fetch(`${API_BASE_URL}/admin/roles/${roleId}/permissions`, {
    method: 'PUT',
    headers: { Authorization: `Bearer ${accessToken}`, 'Content-Type': 'application/json' },
    body: JSON.stringify({ permission_ids: permissionIds }),
  })
  return readJsonResponse<AdminPermission[]>(response)
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

export async function fetchAdminAiProviderConfig(accessToken: string): Promise<AdminAiProviderConfig> {
  const response = await fetch(`${API_BASE_URL}/admin/ai-provider-config`, {
    headers: { Authorization: `Bearer ${accessToken}` },
  })
  return readJsonResponse<AdminAiProviderConfig>(response)
}

export async function patchAdminAiProviderConfig(accessToken: string, payload: AdminAiProviderConfigPatch): Promise<AdminAiProviderConfig> {
  const response = await fetch(`${API_BASE_URL}/admin/ai-provider-config`, {
    method: 'PATCH',
    headers: { Authorization: `Bearer ${accessToken}`, 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  })
  return readJsonResponse<AdminAiProviderConfig>(response)
}

export async function testAdminAiProviderConfig(accessToken: string, payload: AdminAiProviderConfigTestRequest): Promise<AdminAiProviderConfigTestResult> {
  const response = await fetch(`${API_BASE_URL}/admin/ai-provider-config/test`, {
    method: 'POST',
    headers: { Authorization: `Bearer ${accessToken}`, 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  })
  return readJsonResponse<AdminAiProviderConfigTestResult>(response)
}

export async function fetchIdentityProviderStatus(
  accessToken: string,
): Promise<IdentityProviderStatus> {
  const response = await fetch(`${API_BASE_URL}/admin/identity-provider`, {
    headers: { Authorization: `Bearer ${accessToken}` },
  })
  return readJsonResponse<IdentityProviderStatus>(response)
}

export async function testIdentityProvider(
  accessToken: string,
): Promise<IdentityProviderTestResult> {
  const response = await fetch(`${API_BASE_URL}/admin/identity-provider/test`, {
    method: 'POST',
    headers: { Authorization: `Bearer ${accessToken}` },
  })
  return readJsonResponse<IdentityProviderTestResult>(response)
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

export async function fetchSecuritySessions(accessToken: string): Promise<SecuritySession[]> {
  const response = await fetch(`${API_BASE_URL}/security/sessions`, {
    headers: { Authorization: `Bearer ${accessToken}` },
  })
  return readJsonResponse<SecuritySession[]>(response)
}

export async function revokeSecuritySession(
  accessToken: string,
  sessionId: string,
): Promise<{ session_id: string; revoked: boolean }> {
  const response = await fetch(`${API_BASE_URL}/security/sessions/${sessionId}/revoke`, {
    method: 'POST',
    headers: { Authorization: `Bearer ${accessToken}` },
  })
  return readJsonResponse<{ session_id: string; revoked: boolean }>(response)
}

export async function revokeUserSessions(
  accessToken: string,
  userId: string,
): Promise<{ user_id: string; sessions_revoked: number }> {
  const response = await fetch(`${API_BASE_URL}/security/users/${userId}/revoke-sessions`, {
    method: 'POST',
    headers: { Authorization: `Bearer ${accessToken}` },
  })
  return readJsonResponse<{ user_id: string; sessions_revoked: number }>(response)
}

export async function fetchSecurityOverview(accessToken: string): Promise<SecuritySessionOverview> {
  return fetchSecuritySessionOverview(accessToken)
}

export async function fetchMfaOverview(accessToken: string): Promise<MfaOverview> {
  const response = await fetch(`${API_BASE_URL}/security/mfa/overview`, {
    headers: { Authorization: `Bearer ${accessToken}` },
  })
  return readJsonResponse<MfaOverview>(response)
}

export async function adminResetUserMfa(
  accessToken: string,
  userId: string,
): Promise<{ user_id: string; reset: boolean; sessions_revoked: number }> {
  const response = await fetch(`${API_BASE_URL}/security/users/${userId}/mfa/reset`, {
    method: 'POST',
    headers: { Authorization: `Bearer ${accessToken}` },
  })
  return readJsonResponse<{ user_id: string; reset: boolean; sessions_revoked: number }>(response)
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

export async function fetchIntegrationRuntimeCapabilities(
  accessToken: string,
): Promise<IntegrationRuntimeCapabilities> {
  const response = await fetch(`${API_BASE_URL}/integrations/runtime-capabilities`, {
    headers: { Authorization: `Bearer ${accessToken}` },
  })
  return readJsonResponse<IntegrationRuntimeCapabilities>(response)
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

function integrationPlatformTenantQuery(tenantId?: string | null) {
  if (!tenantId) return ''
  return `?tenant_id=${encodeURIComponent(tenantId)}`
}

function integrationPlatformHeaders(accessToken: string, json = false) {
  return {
    Authorization: `Bearer ${accessToken}`,
    ...(json ? { 'Content-Type': 'application/json' } : {}),
  }
}

export async function fetchIntegrationPlatformScopes(
  accessToken: string,
): Promise<IntegrationPlatformScope[]> {
  const response = await fetch(`${API_BASE_URL}/integration-platform/scopes`, {
    headers: integrationPlatformHeaders(accessToken),
  })
  return readJsonResponse<IntegrationPlatformScope[]>(response)
}

export async function fetchIntegrationPlatformDashboard(
  accessToken: string,
  tenantId?: string | null,
): Promise<IntegrationPlatformDashboard> {
  const response = await fetch(
    `${API_BASE_URL}/integration-platform/dashboard${integrationPlatformTenantQuery(tenantId)}`,
    { headers: integrationPlatformHeaders(accessToken) },
  )
  return readJsonResponse<IntegrationPlatformDashboard>(response)
}

export async function fetchIntegrationServiceAccounts(
  accessToken: string,
  tenantId?: string | null,
): Promise<IntegrationServiceAccount[]> {
  const response = await fetch(
    `${API_BASE_URL}/integration-platform/service-accounts${integrationPlatformTenantQuery(tenantId)}`,
    { headers: integrationPlatformHeaders(accessToken) },
  )
  return readJsonResponse<IntegrationServiceAccount[]>(response)
}

export async function createIntegrationServiceAccount(
  accessToken: string,
  request: {
    tenant_id?: string | null
    name: string
    description?: string
    allowed_scopes: string[]
    allowed_ip_cidrs: string[]
    rate_limit_per_minute: number
    max_token_ttl_days: number
  },
): Promise<IntegrationServiceAccount> {
  const response = await fetch(`${API_BASE_URL}/integration-platform/service-accounts`, {
    method: 'POST',
    headers: integrationPlatformHeaders(accessToken, true),
    body: JSON.stringify(request),
  })
  return readJsonResponse<IntegrationServiceAccount>(response)
}

export async function updateIntegrationServiceAccount(
  accessToken: string,
  accountId: string,
  request: {
    expected_version: number
    name?: string
    description?: string
    allowed_scopes?: string[]
    allowed_ip_cidrs?: string[]
    rate_limit_per_minute?: number
    max_token_ttl_days?: number
    status?: IntegrationServiceAccount['status']
    reason: string
  },
): Promise<IntegrationServiceAccount> {
  const response = await fetch(`${API_BASE_URL}/integration-platform/service-accounts/${accountId}`, {
    method: 'PATCH',
    headers: integrationPlatformHeaders(accessToken, true),
    body: JSON.stringify(request),
  })
  return readJsonResponse<IntegrationServiceAccount>(response)
}

export async function fetchIntegrationApiTokens(
  accessToken: string,
  accountId: string,
): Promise<IntegrationApiToken[]> {
  const response = await fetch(
    `${API_BASE_URL}/integration-platform/service-accounts/${accountId}/tokens`,
    { headers: integrationPlatformHeaders(accessToken) },
  )
  return readJsonResponse<IntegrationApiToken[]>(response)
}

export async function issueIntegrationApiToken(
  accessToken: string,
  accountId: string,
  request: { name: string; scopes: string[]; ttl_days: number },
): Promise<IntegrationApiToken> {
  const response = await fetch(
    `${API_BASE_URL}/integration-platform/service-accounts/${accountId}/tokens`,
    {
      method: 'POST',
      headers: integrationPlatformHeaders(accessToken, true),
      body: JSON.stringify(request),
    },
  )
  return readJsonResponse<IntegrationApiToken>(response)
}

export async function rotateIntegrationApiToken(
  accessToken: string,
  tokenId: string,
  request: { expected_version: number; ttl_days?: number; reason: string },
): Promise<IntegrationApiToken> {
  const response = await fetch(`${API_BASE_URL}/integration-platform/tokens/${tokenId}/rotate`, {
    method: 'POST',
    headers: integrationPlatformHeaders(accessToken, true),
    body: JSON.stringify(request),
  })
  return readJsonResponse<IntegrationApiToken>(response)
}

export async function revokeIntegrationApiToken(
  accessToken: string,
  tokenId: string,
  request: { expected_version: number; reason: string },
): Promise<IntegrationApiToken> {
  const response = await fetch(`${API_BASE_URL}/integration-platform/tokens/${tokenId}/revoke`, {
    method: 'POST',
    headers: integrationPlatformHeaders(accessToken, true),
    body: JSON.stringify(request),
  })
  return readJsonResponse<IntegrationApiToken>(response)
}

export async function fetchOutboundWebhookSubscriptions(
  accessToken: string,
  tenantId?: string | null,
): Promise<OutboundWebhookSubscription[]> {
  const response = await fetch(
    `${API_BASE_URL}/integration-platform/webhooks${integrationPlatformTenantQuery(tenantId)}`,
    { headers: integrationPlatformHeaders(accessToken) },
  )
  return readJsonResponse<OutboundWebhookSubscription[]>(response)
}

export async function createOutboundWebhookSubscription(
  accessToken: string,
  request: {
    tenant_id?: string | null
    name: string
    description?: string
    target_url: string
    event_types: string[]
    timeout_seconds: number
    max_attempts: number
  },
): Promise<OutboundWebhookSubscription> {
  const response = await fetch(`${API_BASE_URL}/integration-platform/webhooks`, {
    method: 'POST',
    headers: integrationPlatformHeaders(accessToken, true),
    body: JSON.stringify(request),
  })
  return readJsonResponse<OutboundWebhookSubscription>(response)
}

export async function updateOutboundWebhookSubscription(
  accessToken: string,
  subscriptionId: string,
  request: {
    expected_version: number
    name?: string
    description?: string
    target_url?: string
    event_types?: string[]
    timeout_seconds?: number
    max_attempts?: number
    status?: OutboundWebhookSubscription['status']
    reason: string
  },
): Promise<OutboundWebhookSubscription> {
  const response = await fetch(`${API_BASE_URL}/integration-platform/webhooks/${subscriptionId}`, {
    method: 'PATCH',
    headers: integrationPlatformHeaders(accessToken, true),
    body: JSON.stringify(request),
  })
  return readJsonResponse<OutboundWebhookSubscription>(response)
}

export async function rotateOutboundWebhookSecret(
  accessToken: string,
  subscriptionId: string,
  reason: string,
): Promise<OutboundWebhookSubscription> {
  const response = await fetch(
    `${API_BASE_URL}/integration-platform/webhooks/${subscriptionId}/rotate-secret`,
    {
      method: 'POST',
      headers: integrationPlatformHeaders(accessToken, true),
      body: JSON.stringify({ reason }),
    },
  )
  return readJsonResponse<OutboundWebhookSubscription>(response)
}

export async function testOutboundWebhookSubscription(
  accessToken: string,
  subscriptionId: string,
): Promise<OutboundWebhookDelivery> {
  const response = await fetch(
    `${API_BASE_URL}/integration-platform/webhooks/${subscriptionId}/test`,
    {
      method: 'POST',
      headers: integrationPlatformHeaders(accessToken),
    },
  )
  return readJsonResponse<OutboundWebhookDelivery>(response)
}

export async function fetchOutboundWebhookDeliveries(
  accessToken: string,
  params?: {
    tenant_id?: string | null
    subscription_id?: string
    status?: string
    limit?: number
  },
): Promise<OutboundWebhookDelivery[]> {
  const search = new URLSearchParams()
  if (params?.tenant_id) search.set('tenant_id', params.tenant_id)
  if (params?.subscription_id) search.set('subscription_id', params.subscription_id)
  if (params?.status && params.status !== 'ALL') search.set('status', params.status)
  if (params?.limit) search.set('limit', String(params.limit))
  const query = search.toString()
  const response = await fetch(
    `${API_BASE_URL}/integration-platform/deliveries${query ? `?${query}` : ''}`,
    { headers: integrationPlatformHeaders(accessToken) },
  )
  return readJsonResponse<OutboundWebhookDelivery[]>(response)
}

export async function replayOutboundWebhookDelivery(
  accessToken: string,
  deliveryId: string,
  reason: string,
): Promise<OutboundWebhookDelivery> {
  const response = await fetch(
    `${API_BASE_URL}/integration-platform/deliveries/${deliveryId}/replay`,
    {
      method: 'POST',
      headers: integrationPlatformHeaders(accessToken, true),
      body: JSON.stringify({ reason }),
    },
  )
  return readJsonResponse<OutboundWebhookDelivery>(response)
}

export async function fetchIntegrationApiRequestLogs(
  accessToken: string,
  params?: {
    tenant_id?: string | null
    account_id?: string
    outcome?: 'ALLOWED' | 'DENIED'
    limit?: number
  },
): Promise<IntegrationApiRequestLog[]> {
  const search = new URLSearchParams()
  if (params?.tenant_id) search.set('tenant_id', params.tenant_id)
  if (params?.account_id) search.set('account_id', params.account_id)
  if (params?.outcome) search.set('outcome', params.outcome)
  if (params?.limit) search.set('limit', String(params.limit))
  const query = search.toString()
  const response = await fetch(
    `${API_BASE_URL}/integration-platform/request-logs${query ? `?${query}` : ''}`,
    { headers: integrationPlatformHeaders(accessToken) },
  )
  return readJsonResponse<IntegrationApiRequestLog[]>(response)
}

export async function fetchIntegrationConnectorContract(
  accessToken: string,
): Promise<IntegrationConnectorContract> {
  const response = await fetch(`${API_BASE_URL}/integration-platform/connector-contract`, {
    headers: integrationPlatformHeaders(accessToken),
  })
  return readJsonResponse<IntegrationConnectorContract>(response)
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

// Stage 035: Dashboard and Real-Time Monitoring API Functions

export type DashboardSummary = {
  timestamp: string
  active_rollouts: number
  active_rollout_ids: string[]
  avg_health_score: number
  health_status: 'healthy' | 'degraded' | 'critical' | 'unknown'
  active_alerts: number
  critical_alerts: number
  unresolved_anomalies: number
  system_status: 'operational' | 'degraded' | 'critical'
}

export type MetricsTimeline = {
  rollout_id: string
  metric_type: string
  time_window_minutes: number
  timestamps: string[]
  values: number[]
  statistics: {
    average: number
    minimum: number
    maximum: number
  }
  data_points: number
}

export type AlertSummaryItem = {
  id: string
  alert_rule_id: string
  rule_name: string
  rollout_id: string
  metric: string
  current_value: number
  threshold: number
  operator: string
  severity: 'critical' | 'high' | 'medium' | 'low'
  status: 'active' | 'acknowledged' | 'resolved'
  triggered_at: string
  acknowledged_at: string | null
  resolved_at: string | null
  duration_seconds: number
  breach_count: number
  breach_percentage: number
}

export type ActiveAlerts = {
  alerts: AlertSummaryItem[]
  count: number
  severity_filter?: string
  timestamp: string
}

export type RolloutComparisonItem = {
  rollout_id: string
  name: string
  status: string
  canary_percentage: number
  error_rate: number | null
  latency_p99_ms: number | null
  throughput_eps: number | null
  health_score: number | null
  health_status: string | null
  active_alerts: number
  unresolved_anomalies: number
  duration_hours: number
  started_at: string | null
  error_trend: boolean | null
}

export type RolloutComparison = {
  comparison: RolloutComparisonItem[]
  count: number
  max_rollouts: number
  timestamp: string
}

export type AnomalyTimelineItem = {
  id: string
  rollout_id: string
  metric: string
  detection_method: string
  anomaly_score: number
  severity: 'critical' | 'high' | 'medium' | 'low'
  value: number
  baseline: number
  deviation_percent: number
  created_at: string
  acknowledged: boolean
  resolved_at: string | null
  resolution_notes: string | null
}

export type AnomalyTimeline = {
  anomalies: AnomalyTimelineItem[]
  count: number
  rollout_filter?: string
  time_window_minutes: number
  timestamp: string
}

export type CorrelationMatrix = {
  rollout_id: string
  correlation_matrix: Record<string, Record<string, number>>
  metric_count: number
  data_points: number
  time_window_minutes: number
  timestamp: string
}

export type SocketTokenResponse = {
  socket_token: string
  expires_in: number
  connection_url: string
}

export async function fetchDashboardSummary(accessToken: string): Promise<DashboardSummary> {
  const response = await fetch(`${API_BASE_URL}/jobs/dashboard/summary`, {
    method: 'GET',
    headers: { Authorization: `Bearer ${accessToken}` },
  })
  return readJsonResponse<DashboardSummary>(response)
}

export async function fetchMetricsTimeline(
  accessToken: string,
  rolloutId: string,
  metricType: string = 'error_rate',
  minutesBack: number = 60
): Promise<MetricsTimeline> {
  const url = new URL(`${API_BASE_URL}/jobs/dashboard/metrics/${rolloutId}`)
  url.searchParams.set('metric_type', metricType)
  url.searchParams.set('minutes_back', String(minutesBack))
  const response = await fetch(url.toString(), {
    method: 'GET',
    headers: { Authorization: `Bearer ${accessToken}` },
  })
  return readJsonResponse<MetricsTimeline>(response)
}

export async function fetchActiveAlerts(
  accessToken: string,
  severity?: string,
  limit: number = 50
): Promise<ActiveAlerts> {
  const url = new URL(`${API_BASE_URL}/jobs/dashboard/alerts`)
  if (severity) url.searchParams.set('severity', severity)
  url.searchParams.set('limit', String(limit))
  const response = await fetch(url.toString(), {
    method: 'GET',
    headers: { Authorization: `Bearer ${accessToken}` },
  })
  return readJsonResponse<ActiveAlerts>(response)
}

export async function fetchRolloutComparison(
  accessToken: string,
  rolloutIds: string[]
): Promise<RolloutComparison> {
  const url = new URL(`${API_BASE_URL}/jobs/dashboard/compare`)
  url.searchParams.set('rollout_ids', rolloutIds.slice(0, 10).join(','))
  const response = await fetch(url.toString(), {
    method: 'GET',
    headers: { Authorization: `Bearer ${accessToken}` },
  })
  return readJsonResponse<RolloutComparison>(response)
}

export async function fetchAnomalyTimeline(
  accessToken: string,
  rolloutId?: string,
  minutesBack: number = 1440
): Promise<AnomalyTimeline> {
  const url = new URL(`${API_BASE_URL}/jobs/dashboard/anomalies`)
  if (rolloutId) url.searchParams.set('rollout_id', rolloutId)
  url.searchParams.set('minutes_back', String(minutesBack))
  const response = await fetch(url.toString(), {
    method: 'GET',
    headers: { Authorization: `Bearer ${accessToken}` },
  })
  return readJsonResponse<AnomalyTimeline>(response)
}

export async function fetchCorrelationMatrix(
  accessToken: string,
  rolloutId: string,
  timeWindowMinutes: number = 60
): Promise<CorrelationMatrix> {
  const url = new URL(`${API_BASE_URL}/jobs/dashboard/correlation/${rolloutId}`)
  url.searchParams.set('time_window_minutes', String(timeWindowMinutes))
  const response = await fetch(url.toString(), {
    method: 'GET',
    headers: { Authorization: `Bearer ${accessToken}` },
  })
  return readJsonResponse<CorrelationMatrix>(response)
}

export type CatalogLifecycle = 'DRAFT' | 'IN_REVIEW' | 'PUBLISHED' | 'RETIRED'

export type CatalogCategory = {
  id: string
  tenant_id: string
  code: string
  name: string
  description: string | null
  status: string
  sort_order: number
}

export type CatalogService = {
  id: string
  tenant_id: string
  category_id: string
  code: string
  name: string
  description: string | null
  owner_user_id: string | null
  support_group: string | null
  status: string
}

export type ServiceOffering = {
  id: string
  tenant_id: string
  service_id: string
  code: string
  name: string
  description: string | null
  support_group: string | null
  expected_fulfillment_minutes: number
  status: string
}

export type CatalogItem = {
  id: string
  tenant_id: string
  category_id: string
  category_name: string
  service_id: string
  service_name: string
  offering_id: string | null
  offering_name: string | null
  code: string
  name: string
  short_description: string
  description: string
  lifecycle_status: CatalogLifecycle
  version: number
  owner_user_id: string | null
  support_group: string | null
  expected_delivery_minutes: number
  approval_required: boolean
  entitlement_rules: Record<string, unknown>
  unit_cost_minor: number
  currency: string
  cost_type: 'NO_CHARGE' | 'ONE_TIME' | 'MONTHLY' | 'ANNUAL'
  risk_level: 'LOW' | 'MEDIUM' | 'HIGH' | 'CRITICAL'
  approval_policy: Record<string, unknown>
  sla_policy: Record<string, unknown>
  is_entitled: boolean
  entitlement_reason: string
  published_at: string | null
  retired_at: string | null
  created_at: string
  updated_at: string
  is_favorite: boolean
  view_count: number
  request_count: number
  last_viewed_at: string | null
  last_requested_at: string | null
}

export type CatalogPreference = {
  catalog_item_id: string
  is_favorite: boolean
  view_count: number
  request_count: number
  last_viewed_at: string | null
  last_requested_at: string | null
}

export type CatalogKnowledgeSuggestion = {
  id: string
  article_number: string
  title: string
  summary: string
  content_preview: string
  category_name: string | null
  tags: string[]
  helpful_count: number
  relevance_score: number
}

export type CatalogHistory = {
  id: string
  version: number
  action: string
  lifecycle_status: CatalogLifecycle
  snapshot: Record<string, unknown>
  actor_name: string
  actor_email: string
  reason: string | null
  created_at: string
}

export type CatalogSummary = {
  categories: number
  services: number
  offerings: number
  draft_items: number
  review_items: number
  published_items: number
  retired_items: number
}

export type CatalogFormFieldType =
  | 'text'
  | 'textarea'
  | 'number'
  | 'boolean'
  | 'select'
  | 'multiselect'
  | 'date'
  | 'email'

export type CatalogFormOption = {
  value: string
  label: string
}

export type CatalogFormVisibility = {
  field_key: string
  operator: 'eq' | 'neq' | 'in' | 'truthy' | 'falsy'
  value?: unknown
}

export type CatalogFormField = {
  key: string
  label: string
  type: CatalogFormFieldType
  section_id: string
  required: boolean
  help_text: string
  placeholder: string
  options: CatalogFormOption[]
  validations: {
    min_length?: number
    max_length?: number
    min?: number
    max?: number
    pattern?: string
  }
  visibility?: CatalogFormVisibility
}

export type CatalogFormSection = {
  id: string
  title: string
  description: string
  order: number
}

export type CatalogFormDefinition = {
  title: string
  introduction: string
  sections: CatalogFormSection[]
  fields: CatalogFormField[]
}

export type CatalogAttachmentRules = {
  enabled: boolean
  required: boolean
  max_files: number
  max_size_mb: number
  allowed_extensions: string[]
}

export type CatalogFormVersion = {
  id: string
  tenant_id: string
  catalog_item_id: string
  version: number
  revision: number
  status: 'DRAFT' | 'PUBLISHED' | 'RETIRED'
  schema_hash: string
  schema: CatalogFormDefinition
  attachment_rules: CatalogAttachmentRules
  published_at: string | null
  retired_at: string | null
  created_at: string
  updated_at: string
}

export type CatalogFormValidation = {
  valid: boolean
  form_version: number
  schema_hash: string
  errors: Record<string, string[]>
  normalized_values: Record<string, unknown>
  visible_fields: string[]
}

export type ServiceRequestStatus =
  | 'SUBMITTED'
  | 'PENDING_APPROVAL'
  | 'APPROVED'
  | 'IN_FULFILLMENT'
  | 'COMPLETED'
  | 'REJECTED'
  | 'CANCELLED'

export type ServiceRequestSummary = {
  id: string
  tenant_id: string
  request_number: string
  requester_id: string | null
  requester_name: string
  requester_email: string
  title: string
  description: string | null
  source: string
  status: ServiceRequestStatus
  priority: 'LOW' | 'MEDIUM' | 'HIGH' | 'CRITICAL'
  requester_department: string | null
  requester_location: string | null
  cost_center: string | null
  total_cost_minor: number
  currency: string
  risk_level: 'LOW' | 'MEDIUM' | 'HIGH' | 'CRITICAL'
  version: number
  completed_at: string | null
  cancelled_at: string | null
  rejected_at: string | null
  created_at: string
  updated_at: string
}

export type RequestedItem = {
  id: string
  catalog_item_id: string | null
  catalog_form_version_id: string | null
  item_code: string
  item_name: string
  quantity: number
  status: ServiceRequestStatus
  version: number
  form_version: number | null
  schema_hash: string | null
  form_values: Record<string, unknown>
  field_labels: Record<string, string>
  support_group: string | null
  approval_required: boolean
  approval_mode: 'SEQUENTIAL' | 'PARALLEL'
  unit_cost_minor: number
  total_cost_minor: number
  currency: string
  cost_type: 'NO_CHARGE' | 'ONE_TIME' | 'MONTHLY' | 'ANNUAL'
  cost_center: string | null
  risk_level: 'LOW' | 'MEDIUM' | 'HIGH' | 'CRITICAL'
  entitlement_snapshot: Record<string, unknown>
  approval_policy_snapshot: Record<string, unknown>
  sla_policy_snapshot: Record<string, unknown>
  sla_started_at: string | null
  sla_due_at: string | null
  sla_paused_at: string | null
  sla_paused_seconds: number
  sla_status: 'NOT_STARTED' | 'ACTIVE' | 'AT_RISK' | 'PAUSED' | 'MET' | 'BREACHED' | 'CANCELLED' | 'REJECTED'
  sla_breached_at: string | null
  sla_escalation_level: number
  expected_delivery_at: string | null
  completed_at: string | null
  cancelled_at: string | null
  rejected_at: string | null
  created_at: string
  updated_at: string
}

export type RequestApproval = {
  id: string
  requested_item_id: string
  round: number
  sequence: number
  approval_mode: 'SEQUENTIAL' | 'PARALLEL'
  approver_id: string | null
  approver_name: string
  approver_email: string | null
  status: 'PENDING' | 'APPROVED' | 'REJECTED' | 'CANCELLED'
  comment: string | null
  due_at: string | null
  decided_at: string | null
  created_at: string
  updated_at: string
  can_decide: boolean
}

export type FulfillmentTask = {
  id: string
  requested_item_id: string
  task_number: string
  sequence: number
  title: string
  description: string | null
  status: 'OPEN' | 'IN_PROGRESS' | 'WAITING' | 'COMPLETED' | 'FAILED' | 'CANCELLED'
  version: number
  assignee_id: string | null
  assignee_name: string | null
  support_group: string | null
  due_at: string | null
  evidence: Record<string, unknown>
  completed_at: string | null
  created_at: string
  updated_at: string
  can_fulfill: boolean
  allowed_transitions: FulfillmentTask['status'][]
}

export type RequestActivity = {
  id: string
  requested_item_id: string | null
  entity_type: string
  entity_id: string
  event_type: string
  actor_user_id: string | null
  actor_name: string
  actor_email: string | null
  visibility: 'PUBLIC' | 'INTERNAL'
  message: string
  old_value: Record<string, unknown>
  new_value: Record<string, unknown>
  created_at: string
}

export type ServiceRequestDetail = ServiceRequestSummary & {
  items: RequestedItem[]
  approvals: RequestApproval[]
  tasks: FulfillmentTask[]
  activities: RequestActivity[]
  can_cancel: boolean
}

export type CreateServiceRequestInput = {
  catalog_item_id: string
  form_version: number
  schema_hash: string
  values: Record<string, unknown>
  attachments?: Array<{ name: string; size_bytes: number; content_type?: string }>
  quantity?: number
  idempotency_key: string
  title?: string
  description?: string
  priority?: ServiceRequestSummary['priority']
  approval_mode?: 'SEQUENTIAL' | 'PARALLEL'
}

export type CreateCatalogItemRequest = {
  category_id: string
  service_id: string
  offering_id?: string | null
  code: string
  name: string
  short_description: string
  description: string
  owner_user_id?: string | null
  support_group?: string | null
  expected_delivery_minutes: number
  approval_required: boolean
  entitlement_rules?: Record<string, unknown>
  unit_cost_minor?: number
  currency?: string
  cost_type?: CatalogItem['cost_type']
  risk_level?: CatalogItem['risk_level']
  approval_policy?: Record<string, unknown>
  sla_policy?: Record<string, unknown>
}

export type RequestGovernanceAnalytics = {
  total_requests: number
  total_requested_items: number
  currency_totals: Record<string, number>
  cost_centers: Array<{ cost_center: string; requests: number; total_cost_minor: number }>
  demand_by_item: Array<{
    item_code: string
    item_name: string
    request_count: number
    quantity: number
    total_cost_minor: number
    currency: string
  }>
  sla: Record<string, number>
  approval_required_items: number
  approval_rate_percent: number
  average_fulfillment_hours: number | null
}

export async function fetchCatalogSummary(accessToken: string): Promise<CatalogSummary> {
  const response = await fetchWithAuthRetry(`${API_BASE_URL}/catalog/summary`, undefined, accessToken)
  return readJsonResponse<CatalogSummary>(response)
}

export async function fetchCatalogCategories(accessToken: string): Promise<CatalogCategory[]> {
  const response = await fetchWithAuthRetry(`${API_BASE_URL}/catalog/categories`, undefined, accessToken)
  return readJsonResponse<CatalogCategory[]>(response)
}

export async function createCatalogCategory(
  accessToken: string,
  request: Pick<CatalogCategory, 'code' | 'name'> & { description?: string | null; sort_order?: number },
): Promise<CatalogCategory> {
  const response = await fetchWithAuthRetry(`${API_BASE_URL}/catalog/categories`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(request),
  }, accessToken)
  return readJsonResponse<CatalogCategory>(response)
}

export async function patchCatalogCategory(
  accessToken: string,
  categoryId: string,
  request: { name?: string; description?: string | null; clear_description?: boolean; status?: string; sort_order?: number },
): Promise<CatalogCategory> {
  const response = await fetchWithAuthRetry(`${API_BASE_URL}/catalog/categories/${categoryId}`, {
    method: 'PATCH',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(request),
  }, accessToken)
  return readJsonResponse<CatalogCategory>(response)
}

export async function fetchCatalogServices(accessToken: string): Promise<CatalogService[]> {
  const response = await fetchWithAuthRetry(`${API_BASE_URL}/catalog/services`, undefined, accessToken)
  return readJsonResponse<CatalogService[]>(response)
}

export async function createCatalogService(
  accessToken: string,
  request: Pick<CatalogService, 'category_id' | 'code' | 'name'> & {
    description?: string | null
    owner_user_id?: string | null
    support_group?: string | null
  },
): Promise<CatalogService> {
  const response = await fetchWithAuthRetry(`${API_BASE_URL}/catalog/services`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(request),
  }, accessToken)
  return readJsonResponse<CatalogService>(response)
}

export async function patchCatalogService(
  accessToken: string,
  serviceId: string,
  request: {
    name?: string
    description?: string | null
    clear_description?: boolean
    owner_user_id?: string | null
    clear_owner?: boolean
    support_group?: string | null
    clear_support_group?: boolean
    status?: string
  },
): Promise<CatalogService> {
  const response = await fetchWithAuthRetry(`${API_BASE_URL}/catalog/services/${serviceId}`, {
    method: 'PATCH',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(request),
  }, accessToken)
  return readJsonResponse<CatalogService>(response)
}

export async function fetchServiceOfferings(accessToken: string): Promise<ServiceOffering[]> {
  const response = await fetchWithAuthRetry(`${API_BASE_URL}/catalog/offerings`, undefined, accessToken)
  return readJsonResponse<ServiceOffering[]>(response)
}

export async function createServiceOffering(
  accessToken: string,
  request: Pick<ServiceOffering, 'service_id' | 'code' | 'name'> & {
    description?: string | null
    support_group?: string | null
    expected_fulfillment_minutes?: number
  },
): Promise<ServiceOffering> {
  const response = await fetchWithAuthRetry(`${API_BASE_URL}/catalog/offerings`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(request),
  }, accessToken)
  return readJsonResponse<ServiceOffering>(response)
}

export async function patchServiceOffering(
  accessToken: string,
  offeringId: string,
  request: {
    name?: string
    description?: string | null
    clear_description?: boolean
    support_group?: string | null
    clear_support_group?: boolean
    expected_fulfillment_minutes?: number
    status?: string
  },
): Promise<ServiceOffering> {
  const response = await fetchWithAuthRetry(`${API_BASE_URL}/catalog/offerings/${offeringId}`, {
    method: 'PATCH',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(request),
  }, accessToken)
  return readJsonResponse<ServiceOffering>(response)
}

export async function fetchCatalogItems(
  accessToken: string,
  params?: { search?: string; category_id?: string; lifecycle_status?: string },
): Promise<CatalogItem[]> {
  const search = new URLSearchParams()
  if (params?.search) search.set('search', params.search)
  if (params?.category_id) search.set('category_id', params.category_id)
  if (params?.lifecycle_status && params.lifecycle_status !== 'ALL') {
    search.set('lifecycle_status', params.lifecycle_status)
  }
  const query = search.toString()
  const response = await fetchWithAuthRetry(
    `${API_BASE_URL}/catalog/items${query ? `?${query}` : ''}`,
    undefined,
    accessToken,
  )
  return readJsonResponse<CatalogItem[]>(response)
}

export async function recordCatalogItemView(
  accessToken: string,
  itemId: string,
): Promise<CatalogPreference> {
  const response = await fetchWithAuthRetry(
    `${API_BASE_URL}/catalog/items/${itemId}/view`,
    { method: 'POST' },
    accessToken,
  )
  return readJsonResponse<CatalogPreference>(response)
}

export async function setCatalogItemFavorite(
  accessToken: string,
  itemId: string,
  isFavorite: boolean,
): Promise<CatalogPreference> {
  const response = await fetchWithAuthRetry(
    `${API_BASE_URL}/catalog/items/${itemId}/favorite`,
    {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ is_favorite: isFavorite }),
    },
    accessToken,
  )
  return readJsonResponse<CatalogPreference>(response)
}

export async function fetchCatalogKnowledgeSuggestions(
  accessToken: string,
  itemId: string,
): Promise<CatalogKnowledgeSuggestion[]> {
  const response = await fetchWithAuthRetry(
    `${API_BASE_URL}/catalog/items/${itemId}/knowledge-suggestions`,
    undefined,
    accessToken,
  )
  return readJsonResponse<CatalogKnowledgeSuggestion[]>(response)
}

export async function confirmCatalogKnowledgeDeflection(
  accessToken: string,
  itemId: string,
  articleId: string,
): Promise<{ status: 'resolved'; catalog_item_id: string; article_id: string }> {
  const response = await fetchWithAuthRetry(
    `${API_BASE_URL}/catalog/items/${itemId}/knowledge/${articleId}/resolved`,
    { method: 'POST' },
    accessToken,
  )
  return readJsonResponse(response)
}

export async function createCatalogItem(
  accessToken: string,
  request: CreateCatalogItemRequest,
): Promise<CatalogItem> {
  const response = await fetchWithAuthRetry(`${API_BASE_URL}/catalog/items`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(request),
  }, accessToken)
  return readJsonResponse<CatalogItem>(response)
}

export async function transitionCatalogItem(
  accessToken: string,
  itemId: string,
  request: { expected_version: number; target_status: CatalogLifecycle; reason: string },
): Promise<CatalogItem> {
  const response = await fetchWithAuthRetry(`${API_BASE_URL}/catalog/items/${itemId}/transition`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(request),
  }, accessToken)
  return readJsonResponse<CatalogItem>(response)
}

export async function fetchCatalogItemHistory(
  accessToken: string,
  itemId: string,
): Promise<CatalogHistory[]> {
  const response = await fetchWithAuthRetry(
    `${API_BASE_URL}/catalog/items/${itemId}/history`,
    undefined,
    accessToken,
  )
  return readJsonResponse<CatalogHistory[]>(response)
}

export async function fetchCatalogForm(
  accessToken: string,
  itemId: string,
  mode: 'published' | 'draft' = 'published',
): Promise<CatalogFormVersion | null> {
  const response = await fetchWithAuthRetry(
    `${API_BASE_URL}/catalog/items/${itemId}/form?mode=${mode}`,
    undefined,
    accessToken,
  )
  if (response.status === 404) return null
  return readJsonResponse<CatalogFormVersion>(response)
}

export async function fetchCatalogFormVersions(
  accessToken: string,
  itemId: string,
): Promise<CatalogFormVersion[]> {
  const response = await fetchWithAuthRetry(
    `${API_BASE_URL}/catalog/items/${itemId}/form/versions`,
    undefined,
    accessToken,
  )
  return readJsonResponse<CatalogFormVersion[]>(response)
}

export async function initializeCatalogFormDraft(
  accessToken: string,
  itemId: string,
): Promise<CatalogFormVersion> {
  const response = await fetchWithAuthRetry(
    `${API_BASE_URL}/catalog/items/${itemId}/form/draft`,
    { method: 'POST' },
    accessToken,
  )
  return readJsonResponse<CatalogFormVersion>(response)
}

export async function updateCatalogFormDraft(
  accessToken: string,
  itemId: string,
  request: {
    expected_revision: number
    schema: CatalogFormDefinition
    attachment_rules: CatalogAttachmentRules
  },
): Promise<CatalogFormVersion> {
  const response = await fetchWithAuthRetry(
    `${API_BASE_URL}/catalog/items/${itemId}/form/draft`,
    {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(request),
    },
    accessToken,
  )
  return readJsonResponse<CatalogFormVersion>(response)
}

export async function publishCatalogForm(
  accessToken: string,
  itemId: string,
  request: { expected_revision: number; reason: string },
): Promise<CatalogFormVersion> {
  const response = await fetchWithAuthRetry(
    `${API_BASE_URL}/catalog/items/${itemId}/form/publish`,
    {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(request),
    },
    accessToken,
  )
  return readJsonResponse<CatalogFormVersion>(response)
}

export async function validateCatalogForm(
  accessToken: string,
  itemId: string,
  request: {
    values: Record<string, unknown>
    attachments?: Array<{ name: string; size_bytes: number; content_type?: string }>
  },
): Promise<CatalogFormValidation> {
  const response = await fetchWithAuthRetry(
    `${API_BASE_URL}/catalog/items/${itemId}/form/validate`,
    {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(request),
    },
    accessToken,
  )
  return readJsonResponse<CatalogFormValidation>(response)
}

export async function createServiceRequest(
  accessToken: string,
  request: CreateServiceRequestInput,
): Promise<ServiceRequestDetail> {
  const response = await fetchWithAuthRetry(`${API_BASE_URL}/requests`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(request),
  }, accessToken)
  return readJsonResponse<ServiceRequestDetail>(response)
}

export async function fetchServiceRequests(
  accessToken: string,
  params?: { search?: string; status?: string; page?: number; page_size?: number },
): Promise<PaginatedResponse<ServiceRequestSummary>> {
  const search = new URLSearchParams()
  if (params?.search) search.set('search', params.search)
  if (params?.status && params.status !== 'ALL') search.set('status', params.status)
  if (params?.page) search.set('page', String(params.page))
  if (params?.page_size) search.set('page_size', String(params.page_size))
  const query = search.toString()
  const response = await fetchWithAuthRetry(
    `${API_BASE_URL}/requests${query ? `?${query}` : ''}`,
    undefined,
    accessToken,
  )
  return readJsonResponse<PaginatedResponse<ServiceRequestSummary>>(response)
}

export async function fetchServiceRequest(
  accessToken: string,
  requestId: string,
): Promise<ServiceRequestDetail> {
  const response = await fetchWithAuthRetry(
    `${API_BASE_URL}/requests/${requestId}`,
    undefined,
    accessToken,
  )
  return readJsonResponse<ServiceRequestDetail>(response)
}

export async function fetchRequestGovernanceAnalytics(
  accessToken: string,
): Promise<RequestGovernanceAnalytics> {
  const response = await fetchWithAuthRetry(
    `${API_BASE_URL}/requests/analytics/governance`,
    undefined,
    accessToken,
  )
  return readJsonResponse<RequestGovernanceAnalytics>(response)
}

export async function evaluateRequestSla(
  accessToken: string,
): Promise<{ evaluated_at: string; changed_count: number; changed: Array<Record<string, unknown>> }> {
  const response = await fetchWithAuthRetry(
    `${API_BASE_URL}/requests/sla/evaluate`,
    { method: 'POST' },
    accessToken,
  )
  return readJsonResponse(response)
}

export async function controlRequestedItemSla(
  accessToken: string,
  itemId: string,
  action: 'pause' | 'resume',
  request: { expected_version: number; reason: string },
): Promise<ServiceRequestDetail> {
  const response = await fetchWithAuthRetry(
    `${API_BASE_URL}/requests/items/${itemId}/sla/${action}`,
    {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(request),
    },
    accessToken,
  )
  return readJsonResponse<ServiceRequestDetail>(response)
}

export async function commentServiceRequest(
  accessToken: string,
  requestId: string,
  request: { body: string; is_internal?: boolean },
): Promise<RequestActivity> {
  const response = await fetchWithAuthRetry(
    `${API_BASE_URL}/requests/${requestId}/comments`,
    {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(request),
    },
    accessToken,
  )
  return readJsonResponse<RequestActivity>(response)
}

export async function cancelServiceRequest(
  accessToken: string,
  requestId: string,
  request: { expected_version: number; reason: string },
): Promise<ServiceRequestDetail> {
  const response = await fetchWithAuthRetry(
    `${API_BASE_URL}/requests/${requestId}/cancel`,
    {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(request),
    },
    accessToken,
  )
  return readJsonResponse<ServiceRequestDetail>(response)
}

export async function reworkRequestedItem(
  accessToken: string,
  requestId: string,
  itemId: string,
  request: { expected_version: number; reason: string },
): Promise<ServiceRequestDetail> {
  const response = await fetchWithAuthRetry(
    `${API_BASE_URL}/requests/${requestId}/items/${itemId}/rework`,
    {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(request),
    },
    accessToken,
  )
  return readJsonResponse<ServiceRequestDetail>(response)
}

export async function decideRequestApproval(
  accessToken: string,
  approvalId: string,
  request: { decision: 'APPROVED' | 'REJECTED'; comment?: string },
): Promise<ServiceRequestDetail> {
  const response = await fetchWithAuthRetry(
    `${API_BASE_URL}/requests/approvals/${approvalId}/decision`,
    {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(request),
    },
    accessToken,
  )
  return readJsonResponse<ServiceRequestDetail>(response)
}

export async function assignFulfillmentTask(
  accessToken: string,
  taskId: string,
  request: { expected_version: number; assignee_id?: string | null; comment?: string },
): Promise<ServiceRequestDetail> {
  const response = await fetchWithAuthRetry(
    `${API_BASE_URL}/requests/tasks/${taskId}/assign`,
    {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(request),
    },
    accessToken,
  )
  return readJsonResponse<ServiceRequestDetail>(response)
}

export async function transitionFulfillmentTask(
  accessToken: string,
  taskId: string,
  request: {
    expected_version: number
    target_status: FulfillmentTask['status']
    comment?: string
    evidence?: Record<string, unknown>
  },
): Promise<ServiceRequestDetail> {
  const response = await fetchWithAuthRetry(
    `${API_BASE_URL}/requests/tasks/${taskId}/transition`,
    {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(request),
    },
    accessToken,
  )
  return readJsonResponse<ServiceRequestDetail>(response)
}

function identityProvisioningUrl(
  path: string,
  params?: object,
) {
  const search = new URLSearchParams()
  Object.entries(params ?? {}).forEach(([key, value]) => {
    if (value !== null && value !== undefined && String(value) !== '') {
      search.set(key, String(value))
    }
  })
  const query = search.toString()
  return `${API_BASE_URL}/identity-provisioning${path}${query ? `?${query}` : ''}`
}

export async function fetchIdentityProvisioningDashboard(
  accessToken: string,
  tenantId?: string | null,
): Promise<IdentityProvisioningDashboard> {
  const response = await fetchWithAuthRetry(
    identityProvisioningUrl('/dashboard', { tenant_id: tenantId }),
    undefined,
    accessToken,
  )
  return readJsonResponse<IdentityProvisioningDashboard>(response)
}

export async function fetchIdentityConnectors(
  accessToken: string,
  tenantId?: string | null,
): Promise<IdentityConnector[]> {
  const response = await fetchWithAuthRetry(
    identityProvisioningUrl('/connectors', { tenant_id: tenantId }),
    undefined,
    accessToken,
  )
  return readJsonResponse<IdentityConnector[]>(response)
}

export async function createIdentityConnector(
  accessToken: string,
  request: {
    tenant_id?: string | null
    name: string
    provider_type: 'SCIM' | 'ENTRA'
    external_tenant_id?: string | null
    default_role_id: string
    fallback_owner_id: string
    attribute_mapping?: Record<string, string>
    allowed_ip_cidrs?: string[]
    retry_max_attempts?: number
  },
): Promise<{ connector: IdentityConnector; bearer_token: string; token_notice: string }> {
  const response = await fetchWithAuthRetry(
    identityProvisioningUrl('/connectors'),
    {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(request),
    },
    accessToken,
  )
  return readJsonResponse(response)
}

export async function updateIdentityConnector(
  accessToken: string,
  connectorId: string,
  request: {
    expected_version: number
    name?: string
    external_tenant_id?: string | null
    default_role_id?: string
    fallback_owner_id?: string
    attribute_mapping?: Record<string, string>
    allowed_ip_cidrs?: string[]
    retry_max_attempts?: number
  },
): Promise<IdentityConnector> {
  const response = await fetchWithAuthRetry(
    identityProvisioningUrl(`/connectors/${connectorId}`),
    {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(request),
    },
    accessToken,
  )
  return readJsonResponse<IdentityConnector>(response)
}

export async function changeIdentityConnectorState(
  accessToken: string,
  connector: IdentityConnector,
  action: 'ACTIVATE' | 'PAUSE' | 'REVOKE',
  reason: string,
): Promise<IdentityConnector> {
  const response = await fetchWithAuthRetry(
    identityProvisioningUrl(`/connectors/${connector.id}/state`),
    {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        expected_version: connector.version,
        action,
        reason,
      }),
    },
    accessToken,
  )
  return readJsonResponse<IdentityConnector>(response)
}

export async function rotateIdentityConnectorToken(
  accessToken: string,
  connectorId: string,
): Promise<{ connector: IdentityConnector; bearer_token: string; token_notice: string }> {
  const response = await fetchWithAuthRetry(
    identityProvisioningUrl(`/connectors/${connectorId}/rotate-token`),
    { method: 'POST' },
    accessToken,
  )
  return readJsonResponse(response)
}

export async function fetchProvisionedIdentities(
  accessToken: string,
  params: {
    tenant_id?: string | null
    connector_id?: string | null
    lifecycle_state?: string | null
    search?: string | null
    page?: number
    page_size?: number
  } = {},
): Promise<ProvisionedIdentityPage> {
  const response = await fetchWithAuthRetry(
    identityProvisioningUrl('/identities', params),
    undefined,
    accessToken,
  )
  return readJsonResponse<ProvisionedIdentityPage>(response)
}

export async function fetchIdentityOwnership(
  accessToken: string,
  identityId: string,
): Promise<IdentityOwnershipPreview> {
  const response = await fetchWithAuthRetry(
    identityProvisioningUrl(`/identities/${identityId}/ownership`),
    undefined,
    accessToken,
  )
  return readJsonResponse<IdentityOwnershipPreview>(response)
}

export async function deprovisionIdentity(
  accessToken: string,
  identityId: string,
  request: { fallback_owner_id: string; reason: string },
): Promise<{
  identity: ProvisionedIdentity
  ownership_transfer: {
    id: string
    from_user_id: string
    to_user_id: string
    counts: Record<string, number>
    sessions_revoked: number
  }
}> {
  const response = await fetchWithAuthRetry(
    identityProvisioningUrl(`/identities/${identityId}/deprovision`),
    {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(request),
    },
    accessToken,
  )
  return readJsonResponse(response)
}

export async function fetchProvisionedGroups(
  accessToken: string,
  params: { tenant_id?: string | null; connector_id?: string | null } = {},
): Promise<ProvisionedGroup[]> {
  const response = await fetchWithAuthRetry(
    identityProvisioningUrl('/groups', params),
    undefined,
    accessToken,
  )
  return readJsonResponse<ProvisionedGroup[]>(response)
}

export async function mapProvisionedGroupRole(
  accessToken: string,
  group: ProvisionedGroup,
  roleId: string | null,
): Promise<ProvisionedGroup> {
  const response = await fetchWithAuthRetry(
    identityProvisioningUrl(`/groups/${group.id}/role-mapping`),
    {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        expected_version: group.scim_version,
        role_id: roleId,
      }),
    },
    accessToken,
  )
  return readJsonResponse<ProvisionedGroup>(response)
}

export async function fetchIdentityProvisioningEvents(
  accessToken: string,
  params: {
    tenant_id?: string | null
    connector_id?: string | null
    status?: string | null
    page?: number
    page_size?: number
  } = {},
): Promise<IdentityProvisioningEventPage> {
  const response = await fetchWithAuthRetry(
    identityProvisioningUrl('/events', params),
    undefined,
    accessToken,
  )
  return readJsonResponse<IdentityProvisioningEventPage>(response)
}

export async function retryIdentityProvisioningEvent(
  accessToken: string,
  eventId: string,
): Promise<{ event: IdentityProvisioningEvent; result: Record<string, unknown> }> {
  const response = await fetchWithAuthRetry(
    identityProvisioningUrl(`/events/${eventId}/retry`),
    { method: 'POST' },
    accessToken,
  )
  return readJsonResponse(response)
}

export async function fetchIdentityOwnershipTransfers(
  accessToken: string,
  params: {
    tenant_id?: string | null
    page?: number
    page_size?: number
  } = {},
): Promise<IdentityOwnershipTransferPage> {
  const response = await fetchWithAuthRetry(
    identityProvisioningUrl('/ownership-transfers', params),
    undefined,
    accessToken,
  )
  return readJsonResponse<IdentityOwnershipTransferPage>(response)
}

export async function safeDeactivateUser(
  accessToken: string,
  userId: string,
  request: { fallback_owner_id: string; reason: string },
): Promise<{
  user_id: string
  is_active: boolean
  provisioning_state: string
  ownership_transfer: {
    id: string
    to_user_id: string
    counts: Record<string, number>
    sessions_revoked: number
  }
}> {
  const response = await fetchWithAuthRetry(
    identityProvisioningUrl(`/users/${userId}/safe-deactivate`),
    {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(request),
    },
    accessToken,
  )
  return readJsonResponse(response)
}

export type WorkflowDefinitionDocument = {
  schema_version: string
  trigger: { type: string }
  entrypoint: string
  on_failure?: string
  nodes: Array<Record<string, unknown>>
}

export type ProductionWorkflow = {
  id: string
  tenant_id: string
  code: string
  name: string
  description: string | null
  status: 'ACTIVE' | 'PAUSED' | 'ARCHIVED'
  trigger_type: string
  concurrency_policy: 'ALLOW' | 'SERIALIZE'
  max_active_executions: number
  publish_approval_required: boolean
  latest_version_number: number
  draft_version_number: number | null
  published_version_number: number | null
  revision: number
  total_executions: number
  failed_executions: number
  last_execution_at: string | null
  created_at: string
  updated_at: string
}

export type WorkflowValidation = {
  valid: boolean
  errors: string[]
  warnings: string[]
  stats: Record<string, number>
}

export type WorkflowVersion = {
  id: string
  tenant_id: string
  workflow_id: string
  version_number: number
  status: 'DRAFT' | 'PUBLISHED' | 'RETIRED'
  definition_sha256: string
  integrity_valid: boolean
  validation_status: 'UNKNOWN' | 'VALID' | 'INVALID'
  validation: WorkflowValidation
  review_status: 'NOT_REQUIRED' | 'PENDING' | 'APPROVED' | 'REJECTED'
  review_requested_by_id: string | null
  reviewed_by_id: string | null
  review_comment: string | null
  review_requested_at: string | null
  reviewed_at: string | null
  created_by_id: string | null
  updated_by_id: string | null
  revision: number
  based_on_version_number: number | null
  rollback_from_version_number: number | null
  change_summary: string | null
  published_at: string | null
  created_at: string
  updated_at: string
  definition?: WorkflowDefinitionDocument
}

export type WorkflowExecutionStep = {
  id: string
  node_key: string
  node_type: string
  sequence_number: number
  status: string
  attempts: number
  max_attempts: number
  input: Record<string, unknown>
  output: Record<string, unknown>
  next_retry_at: string | null
  wait_until: string | null
  last_error: string | null
  compensation_status: string | null
  compensation_output: Record<string, unknown>
  started_at: string | null
  completed_at: string | null
}

export type WorkflowExecution = {
  id: string
  tenant_id: string
  workflow_id: string
  workflow_version_id: string
  workflow_version_number: number
  replay_of_id: string | null
  idempotency_key: string
  source: string
  trigger_type: string
  trigger_entity_type: string | null
  trigger_entity_id: string | null
  status: string
  current_node_key: string | null
  context: Record<string, unknown>
  variables: Record<string, unknown>
  output: Record<string, unknown>
  attempts: number
  max_attempts: number
  next_run_at: string
  correlation_id: string | null
  last_error: string | null
  started_at: string | null
  completed_at: string | null
  created_at: string
  updated_at: string
  steps?: WorkflowExecutionStep[]
}

export type WorkflowApproval = {
  id: string
  tenant_id: string
  execution_id: string
  step_execution_id: string
  node_key: string
  approver_role: string
  allow_self_approval: boolean
  status: string
  version: number
  requested_by_id: string | null
  decided_by_id: string | null
  decision_comment: string | null
  requested_at: string
  expires_at: string
  decided_at: string | null
}

export type WorkflowDashboard = {
  tenant_id: string
  workflows: { total: number; by_status: Record<string, number> }
  executions: { total: number; by_status: Record<string, number> }
  pending_approvals: number
  generated_at: string
}

export type WorkflowCatalog = {
  schema_version: string
  node_types: string[]
  triggers: Array<Record<string, unknown>>
  actions: Array<{
    code: string
    description: string
    required: string[]
    compensatable: boolean
  }>
  template_syntax: string
  limits: Record<string, number>
}

export type WorkflowVersionDiff = {
  workflow_id: string
  from_version: number
  to_version: number
  from_sha256: string
  to_sha256: string
  summary: {
    added: number
    removed: number
    changed: number
    total: number
  }
  added: Array<{ path: string; value: unknown }>
  removed: Array<{ path: string; value: unknown }>
  changed: Array<{ path: string; before: unknown; after: unknown }>
}

export type WorkflowReview = WorkflowVersion & {
  workflow_name: string
  workflow_code: string
  publish_approval_required: boolean
}

function workflowUrl(
  path = '',
  params?: Record<string, string | number | null | undefined>,
) {
  const search = new URLSearchParams()
  Object.entries(params ?? {}).forEach(([key, value]) => {
    if (value !== null && value !== undefined && String(value) !== '') {
      search.set(key, String(value))
    }
  })
  const query = search.toString()
  return `${API_BASE_URL}/workflows${path}${query ? `?${query}` : ''}`
}

async function workflowRequest<T>(
  accessToken: string,
  path: string,
  init?: RequestInit,
): Promise<T> {
  const response = await fetchWithAuthRetry(
    workflowUrl(path),
    init,
    accessToken,
  )
  return readJsonResponse<T>(response)
}

export async function fetchWorkflowCatalog(accessToken: string) {
  return workflowRequest<WorkflowCatalog>(accessToken, '/catalog')
}

export async function fetchWorkflowDashboard(
  accessToken: string,
  tenantId?: string | null,
) {
  const response = await fetchWithAuthRetry(
    workflowUrl('/dashboard', { tenant_id: tenantId }),
    undefined,
    accessToken,
  )
  return readJsonResponse<WorkflowDashboard>(response)
}

export async function fetchProductionWorkflows(
  accessToken: string,
  tenantId?: string | null,
) {
  const response = await fetchWithAuthRetry(
    workflowUrl('', { tenant_id: tenantId }),
    undefined,
    accessToken,
  )
  return readJsonResponse<ProductionWorkflow[]>(response)
}

export async function createProductionWorkflow(
  accessToken: string,
  request: {
    tenant_id?: string | null
    code: string
    name: string
    description?: string | null
    trigger_type: string
    concurrency_policy: 'ALLOW' | 'SERIALIZE'
    max_active_executions: number
    publish_approval_required?: boolean
  },
) {
  return workflowRequest<{
    workflow: ProductionWorkflow
    draft: WorkflowVersion
  }>(accessToken, '', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(request),
  })
}

export async function updateProductionWorkflow(
  accessToken: string,
  workflowId: string,
  request: {
    expected_revision: number
    name?: string
    description?: string | null
    concurrency_policy?: 'ALLOW' | 'SERIALIZE'
    max_active_executions?: number
    publish_approval_required?: boolean
    status?: 'ACTIVE' | 'PAUSED' | 'ARCHIVED'
    reason: string
  },
) {
  return workflowRequest<ProductionWorkflow>(
    accessToken,
    `/${workflowId}`,
    {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(request),
    },
  )
}

export async function fetchWorkflowVersions(
  accessToken: string,
  workflowId: string,
) {
  return workflowRequest<WorkflowVersion[]>(
    accessToken,
    `/${workflowId}/versions`,
  )
}

export async function fetchWorkflowVersion(
  accessToken: string,
  workflowId: string,
  versionNumber: number,
) {
  return workflowRequest<WorkflowVersion>(
    accessToken,
    `/${workflowId}/versions/${versionNumber}`,
  )
}

export async function compareWorkflowVersions(
  accessToken: string,
  workflowId: string,
  fromVersion: number,
  toVersion: number,
) {
  const response = await fetchWithAuthRetry(
    workflowUrl(`/${workflowId}/versions/compare`, {
      from_version: fromVersion,
      to_version: toVersion,
    }),
    undefined,
    accessToken,
  )
  return readJsonResponse<WorkflowVersionDiff>(response)
}

export async function createWorkflowDraft(
  accessToken: string,
  workflow: ProductionWorkflow,
  changeSummary: string,
) {
  return workflowRequest<WorkflowVersion>(
    accessToken,
    `/${workflow.id}/drafts`,
    {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        expected_workflow_revision: workflow.revision,
        change_summary: changeSummary,
      }),
    },
  )
}

export async function saveWorkflowDraft(
  accessToken: string,
  workflowId: string,
  version: WorkflowVersion,
  definition: WorkflowDefinitionDocument,
  changeSummary: string,
) {
  return workflowRequest<WorkflowVersion>(
    accessToken,
    `/${workflowId}/versions/${version.version_number}`,
    {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        expected_revision: version.revision,
        definition,
        change_summary: changeSummary,
      }),
    },
  )
}

export async function validateWorkflowVersion(
  accessToken: string,
  workflowId: string,
  versionNumber: number,
) {
  return workflowRequest<WorkflowValidation>(
    accessToken,
    `/${workflowId}/versions/${versionNumber}/validate`,
    { method: 'POST' },
  )
}

export async function simulateWorkflowVersion(
  accessToken: string,
  workflowId: string,
  versionNumber: number,
  context: Record<string, unknown>,
) {
  return workflowRequest<Record<string, unknown>>(
    accessToken,
    `/${workflowId}/versions/${versionNumber}/simulate`,
    {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ context }),
    },
  )
}

export async function publishWorkflowVersion(
  accessToken: string,
  workflow: ProductionWorkflow,
  version: WorkflowVersion,
  changeTicket: string,
) {
  return workflowRequest<{
    workflow: ProductionWorkflow
    version: WorkflowVersion
  }>(
    accessToken,
    `/${workflow.id}/versions/${version.version_number}/publish`,
    {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        expected_workflow_revision: workflow.revision,
        expected_version_revision: version.revision,
        activate: true,
        change_ticket: changeTicket,
      }),
    },
  )
}

export async function requestWorkflowReview(
  accessToken: string,
  workflowId: string,
  version: WorkflowVersion,
  comment: string,
) {
  return workflowRequest<WorkflowVersion>(
    accessToken,
    `/${workflowId}/versions/${version.version_number}/review-request`,
    {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        expected_revision: version.revision,
        comment,
      }),
    },
  )
}

export async function decideWorkflowReview(
  accessToken: string,
  review: WorkflowReview,
  decision: 'APPROVED' | 'REJECTED',
  comment: string,
) {
  return workflowRequest<WorkflowVersion>(
    accessToken,
    `/${review.workflow_id}/versions/${review.version_number}/review-decision`,
    {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        expected_revision: review.revision,
        decision,
        comment,
      }),
    },
  )
}

export async function rollbackWorkflowVersion(
  accessToken: string,
  workflow: ProductionWorkflow,
  targetVersionNumber: number,
  reason: string,
) {
  return workflowRequest<{
    workflow: ProductionWorkflow
    version: WorkflowVersion
  }>(accessToken, `/${workflow.id}/rollback`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      expected_workflow_revision: workflow.revision,
      target_version_number: targetVersionNumber,
      reason,
    }),
  })
}

export async function fetchWorkflowExecutions(
  accessToken: string,
  tenantId?: string | null,
  workflowId?: string | null,
) {
  const response = await fetchWithAuthRetry(
    workflowUrl('/executions/list', {
      tenant_id: tenantId,
      workflow_id: workflowId,
      limit: 100,
    }),
    undefined,
    accessToken,
  )
  return readJsonResponse<WorkflowExecution[]>(response)
}

export async function fetchWorkflowExecution(
  accessToken: string,
  executionId: string,
) {
  return workflowRequest<WorkflowExecution>(
    accessToken,
    `/executions/${executionId}`,
  )
}

export async function startProductionWorkflow(
  accessToken: string,
  workflowId: string,
  request: {
    context: Record<string, unknown>
    idempotency_key: string
    correlation_id?: string | null
  },
) {
  return workflowRequest<{
    execution: WorkflowExecution
    deduplicated: boolean
  }>(accessToken, `/${workflowId}/executions`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(request),
  })
}

export async function cancelWorkflowExecution(
  accessToken: string,
  executionId: string,
  reason: string,
) {
  return workflowRequest<WorkflowExecution>(
    accessToken,
    `/executions/${executionId}/cancel`,
    {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ reason }),
    },
  )
}

export async function replayWorkflowExecution(
  accessToken: string,
  executionId: string,
  reason: string,
) {
  return workflowRequest<WorkflowExecution>(
    accessToken,
    `/executions/${executionId}/replay`,
    {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ reason }),
    },
  )
}

export async function fetchWorkflowApprovals(
  accessToken: string,
  tenantId?: string | null,
  status = 'PENDING',
) {
  const response = await fetchWithAuthRetry(
    workflowUrl('/approvals/list', {
      tenant_id: tenantId,
      status,
      limit: 100,
    }),
    undefined,
    accessToken,
  )
  return readJsonResponse<WorkflowApproval[]>(response)
}

export async function fetchWorkflowReviews(
  accessToken: string,
  tenantId?: string | null,
  status = 'PENDING',
) {
  const response = await fetchWithAuthRetry(
    workflowUrl('/reviews/list', {
      tenant_id: tenantId,
      status,
      limit: 100,
    }),
    undefined,
    accessToken,
  )
  return readJsonResponse<WorkflowReview[]>(response)
}

export async function decideWorkflowApproval(
  accessToken: string,
  approval: WorkflowApproval,
  decision: 'APPROVED' | 'REJECTED',
  comment: string,
) {
  return workflowRequest<WorkflowApproval>(
    accessToken,
    `/approvals/${approval.id}/decision`,
    {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        expected_version: approval.version,
        decision,
        comment,
      }),
    },
  )
}

export type CustomFieldEntityType =
  | 'ticket'
  | 'asset'
  | 'change'
  | 'problem'
  | 'request'

export type CustomFieldDefinition = {
  key: string
  label: string
  type:
    | 'text'
    | 'textarea'
    | 'number'
    | 'boolean'
    | 'select'
    | 'multiselect'
    | 'date'
    | 'email'
  section_id: string
  required: boolean
  help_text: string
  placeholder: string
  options: Array<{ value: string; label: string }>
  validations: Record<string, unknown>
  visibility?: {
    field_key: string
    operator: 'eq' | 'neq' | 'in' | 'truthy' | 'falsy'
    value?: unknown
  }
  default?: unknown
  searchable: boolean
  indexed: boolean
  reportable: boolean
  sensitive: boolean
  immutable_after_set: boolean
}

export type CustomFieldSchema = {
  schema_version: '1.0'
  title: string
  introduction: string
  sections: Array<{
    id: string
    title: string
    description: string
    order: number
  }>
  fields: CustomFieldDefinition[]
}

export type CustomFieldSet = {
  id: string
  tenant_id: string
  code: string
  name: string
  description: string | null
  entity_type: CustomFieldEntityType
  status: 'ACTIVE' | 'PAUSED' | 'ARCHIVED'
  applicability: {
    all?: Array<{ field: string; operator: 'eq' | 'neq' | 'in'; value: unknown }>
  }
  latest_version_number: number
  draft_version_number: number | null
  published_version_number: number | null
  revision: number
  created_at: string
  updated_at: string
}

export type CustomFieldValidation = {
  valid: boolean
  errors: string[]
  warnings: string[]
  stats: {
    fields: number
    searchable: number
    indexed: number
    reportable: number
    sensitive: number
  }
}

export type CustomFieldCompatibility = {
  compatible: boolean
  breaking: Array<Record<string, unknown>>
  additive: Array<Record<string, unknown>>
}

export type CustomFieldSetVersion = {
  id: string
  tenant_id: string
  field_set_id: string
  version_number: number
  status: 'DRAFT' | 'PUBLISHED' | 'RETIRED'
  schema_sha256: string
  integrity_valid: boolean
  validation_status: 'VALID' | 'INVALID'
  validation: CustomFieldValidation
  revision: number
  based_on_version_number: number | null
  change_summary: string | null
  breaking_change: boolean
  published_at: string | null
  created_at: string
  updated_at: string
  schema_definition?: CustomFieldSchema
}

export type CustomFieldDashboard = {
  tenant_id: string
  field_sets: {
    total: number
    by_status: Record<string, number>
    by_entity_type: Record<string, number>
  }
  stored_value_records: number
  invalid_drafts: number
  generated_at: string
}

export type CustomFieldCatalog = {
  schema_version: string
  entity_types: CustomFieldEntityType[]
  field_types: CustomFieldDefinition['type'][]
  field_capabilities: string[]
  applicability_operators: string[]
  limits: Record<string, number>
}

export type CustomFieldValueRecord = {
  id: string
  tenant_id: string
  field_set_id: string
  field_set_version_id: string
  field_set_version_number: number
  entity_type: CustomFieldEntityType
  entity_id: string
  values: Record<string, unknown>
  values_sha256: string
  version: number
  created_at: string
  updated_at: string
}

function customFieldsUrl(
  path = '',
  params?: Record<string, string | number | null | undefined>,
) {
  const search = new URLSearchParams()
  Object.entries(params ?? {}).forEach(([key, value]) => {
    if (value !== null && value !== undefined && String(value) !== '') {
      search.set(key, String(value))
    }
  })
  const query = search.toString()
  return `${API_BASE_URL}/custom-fields${path}${query ? `?${query}` : ''}`
}

async function customFieldsRequest<T>(
  accessToken: string,
  path: string,
  init?: RequestInit,
): Promise<T> {
  const response = await fetchWithAuthRetry(
    customFieldsUrl(path),
    init,
    accessToken,
  )
  return readJsonResponse<T>(response)
}

export async function fetchCustomFieldCatalog(accessToken: string) {
  return customFieldsRequest<CustomFieldCatalog>(accessToken, '/catalog')
}

export async function fetchCustomFieldDashboard(
  accessToken: string,
  tenantId?: string | null,
) {
  const response = await fetchWithAuthRetry(
    customFieldsUrl('/dashboard', { tenant_id: tenantId }),
    undefined,
    accessToken,
  )
  return readJsonResponse<CustomFieldDashboard>(response)
}

export async function fetchCustomFieldSets(
  accessToken: string,
  tenantId?: string | null,
  entityType?: CustomFieldEntityType | null,
) {
  const response = await fetchWithAuthRetry(
    customFieldsUrl('', {
      tenant_id: tenantId,
      entity_type: entityType,
    }),
    undefined,
    accessToken,
  )
  return readJsonResponse<CustomFieldSet[]>(response)
}

export async function createCustomFieldSet(
  accessToken: string,
  request: {
    tenant_id?: string | null
    code: string
    name: string
    description?: string | null
    entity_type: CustomFieldEntityType
    applicability: CustomFieldSet['applicability']
  },
) {
  return customFieldsRequest<{
    field_set: CustomFieldSet
    draft: CustomFieldSetVersion
  }>(accessToken, '', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(request),
  })
}

export async function updateCustomFieldSet(
  accessToken: string,
  fieldSet: CustomFieldSet,
  request: {
    name?: string
    description?: string | null
    status?: CustomFieldSet['status']
    applicability?: CustomFieldSet['applicability']
    reason: string
  },
) {
  return customFieldsRequest<CustomFieldSet>(
    accessToken,
    `/${fieldSet.id}`,
    {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        ...request,
        expected_revision: fieldSet.revision,
      }),
    },
  )
}

export async function fetchCustomFieldVersions(
  accessToken: string,
  fieldSetId: string,
) {
  return customFieldsRequest<CustomFieldSetVersion[]>(
    accessToken,
    `/${fieldSetId}/versions`,
  )
}

export async function createCustomFieldDraft(
  accessToken: string,
  fieldSet: CustomFieldSet,
  changeSummary: string,
) {
  return customFieldsRequest<{
    field_set: CustomFieldSet
    draft: CustomFieldSetVersion
  }>(accessToken, `/${fieldSet.id}/drafts`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      expected_field_set_revision: fieldSet.revision,
      change_summary: changeSummary,
    }),
  })
}

export async function saveCustomFieldDraft(
  accessToken: string,
  fieldSetId: string,
  version: CustomFieldSetVersion,
  schemaDefinition: CustomFieldSchema,
  changeSummary: string,
) {
  return customFieldsRequest<{
    version: CustomFieldSetVersion
    validation: CustomFieldValidation
    compatibility: CustomFieldCompatibility
  }>(
    accessToken,
    `/${fieldSetId}/versions/${version.version_number}`,
    {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        expected_revision: version.revision,
        schema_definition: schemaDefinition,
        change_summary: changeSummary,
      }),
    },
  )
}

export async function publishCustomFieldVersion(
  accessToken: string,
  fieldSet: CustomFieldSet,
  version: CustomFieldSetVersion,
  request: { allow_breaking_changes: boolean; reason: string },
) {
  return customFieldsRequest<{
    field_set: CustomFieldSet
    version: CustomFieldSetVersion
    compatibility: CustomFieldCompatibility
  }>(
    accessToken,
    `/${fieldSet.id}/versions/${version.version_number}/publish`,
    {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        expected_field_set_revision: fieldSet.revision,
        expected_version_revision: version.revision,
        ...request,
      }),
    },
  )
}

export async function fetchEntityCustomFieldSets(
  accessToken: string,
  entityType: CustomFieldEntityType,
  entityId: string,
  tenantId?: string | null,
) {
  const response = await fetchWithAuthRetry(
    customFieldsUrl(
      `/entities/${entityType}/${encodeURIComponent(entityId)}/field-sets`,
      { tenant_id: tenantId },
    ),
    undefined,
    accessToken,
  )
  return readJsonResponse<Array<{
    field_set: CustomFieldSet
    published_version: CustomFieldSetVersion
    value_record: CustomFieldValueRecord | null
    value_schema_current: boolean
  }>>(response)
}

export async function saveEntityCustomFieldValues(
  accessToken: string,
  fieldSetId: string,
  entityId: string,
  values: Record<string, unknown>,
  expectedVersion?: number | null,
) {
  return customFieldsRequest<CustomFieldValueRecord>(
    accessToken,
    `/${fieldSetId}/entities/${encodeURIComponent(entityId)}/values`,
    {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        values,
        expected_version: expectedVersion,
      }),
    },
  )
}

export async function searchCustomFieldValues(
  accessToken: string,
  query: string,
  tenantId?: string | null,
  entityType?: CustomFieldEntityType | null,
) {
  const response = await fetchWithAuthRetry(
    customFieldsUrl('/search', {
      query,
      tenant_id: tenantId,
      entity_type: entityType,
    }),
    undefined,
    accessToken,
  )
  return readJsonResponse<Array<{
    field_set: CustomFieldSet
    value_record: CustomFieldValueRecord
  }>>(response)
}

export type ConfigurationPackage = {
  id: string
  tenant_id: string
  code: string
  name: string
  description: string | null
  status: 'ACTIVE' | 'ARCHIVED'
  latest_version_number: number
  revision: number
  created_at: string
  updated_at: string
}

export type ConfigurationPackageManifest = {
  schema_version: '1.0'
  package: {
    code: string
    name: string
    version: number
    source_environment: string
    created_at: string
  }
  components: Array<{
    type: string
    key: string
    data: Record<string, unknown>
    dependencies: string[]
    content_sha256: string
  }>
}

export type ConfigurationPackageVersion = {
  id: string
  tenant_id: string
  package_id: string
  version_number: number
  status: 'DRAFT' | 'SEALED' | 'RETIRED'
  source_environment: string
  manifest_sha256: string
  integrity_valid: boolean
  signed: boolean
  validation_status: 'VALID' | 'INVALID'
  validation: {
    valid: boolean
    errors: string[]
    warnings: string[]
    component_count: number
    dependency_count: number
    type_counts: Record<string, number>
    size_bytes: number
  }
  component_count: number
  dependency_count: number
  change_summary: string | null
  revision: number
  imported_from_artifact: boolean
  sealed_at: string | null
  created_at: string
  updated_at: string
  manifest?: ConfigurationPackageManifest
}

export type ConfigurationDeploymentPlan = {
  valid: boolean
  validation: ConfigurationPackageVersion['validation']
  operations: Array<{
    component_type: string
    component_key: string
    action: 'CREATE' | 'UPDATE' | 'NOOP' | 'BLOCK'
    current_sha256: string | null
    desired_sha256: string
  }>
  summary: Record<'CREATE' | 'UPDATE' | 'NOOP' | 'BLOCK', number>
  target_fingerprint_sha256: string
}

export type ConfigurationDeployment = {
  id: string
  tenant_id: string
  package_version_id: string
  target_environment: string
  status:
    | 'DRAFT'
    | 'VALIDATED'
    | 'PENDING_APPROVAL'
    | 'APPROVED'
    | 'REJECTED'
    | 'APPLIED'
    | 'FAILED'
    | 'ROLLED_BACK'
  idempotency_key: string
  plan: ConfigurationDeploymentPlan
  plan_sha256: string | null
  target_fingerprint_sha256: string | null
  snapshot_before_sha256: string | null
  result: Record<string, unknown>
  result_sha256: string | null
  revision: number
  reason: string
  review_comment: string | null
  error_message: string | null
  requested_by_id: string | null
  reviewed_by_id: string | null
  applied_by_id: string | null
  rolled_back_by_id: string | null
  requested_at: string | null
  reviewed_at: string | null
  applied_at: string | null
  rolled_back_at: string | null
  created_at: string
  updated_at: string
}

export type ConfigurationArtifact = {
  artifact_format: 'sbs-itsm-configuration-package'
  artifact_version: '1.0'
  manifest: ConfigurationPackageManifest
  manifest_sha256: string
  signature_algorithm: 'HMAC-SHA256'
  signature: string
}

function configurationPackagesUrl(
  path = '',
  params?: Record<string, string | number | boolean | null | undefined>,
) {
  const query = new URLSearchParams()
  Object.entries(params ?? {}).forEach(([key, value]) => {
    if (value !== null && value !== undefined && value !== '') {
      query.set(key, String(value))
    }
  })
  return `${API_BASE_URL}/configuration-packages${path}${
    query.size ? `?${query.toString()}` : ''
  }`
}

async function configurationPackagesRequest<T>(
  accessToken: string,
  path: string,
  init?: RequestInit,
) {
  const response = await fetchWithAuthRetry(
    configurationPackagesUrl(path),
    init,
    accessToken,
  )
  return readJsonResponse<T>(response)
}

export async function fetchConfigurationPackageMeta(accessToken: string) {
  return configurationPackagesRequest<{
    artifact_format: string
    schema_version: string
    supported_component_types: string[]
    max_components: number
    max_bytes: number
    production_requires_independent_approval: boolean
    secrets_exported: boolean
  }>(accessToken, '/meta')
}

export async function fetchConfigurationPackageDashboard(
  accessToken: string,
  tenantId?: string | null,
) {
  const response = await fetchWithAuthRetry(
    configurationPackagesUrl('/dashboard', { tenant_id: tenantId }),
    undefined,
    accessToken,
  )
  return readJsonResponse<{
    active_packages: number
    sealed_versions: number
    pending_approvals: number
    applied_deployments: number
    failed_deployments: number
    rolled_back_deployments: number
  }>(response)
}

export async function fetchConfigurationPackages(
  accessToken: string,
  tenantId?: string | null,
) {
  const response = await fetchWithAuthRetry(
    configurationPackagesUrl('', { tenant_id: tenantId }),
    undefined,
    accessToken,
  )
  return readJsonResponse<{ items: ConfigurationPackage[]; count: number }>(
    response,
  )
}

export async function createConfigurationPackage(
  accessToken: string,
  payload: {
    tenant_id?: string | null
    code: string
    name: string
    description?: string
  },
) {
  return configurationPackagesRequest<ConfigurationPackage>(accessToken, '', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  })
}

export async function updateConfigurationPackage(
  accessToken: string,
  packageId: string,
  payload: {
    expected_revision: number
    name?: string
    description?: string
    status?: 'ACTIVE' | 'ARCHIVED'
    reason: string
  },
) {
  return configurationPackagesRequest<ConfigurationPackage>(
    accessToken,
    `/${packageId}`,
    {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    },
  )
}

export async function fetchConfigurationPackageVersions(
  accessToken: string,
  packageId: string,
) {
  return configurationPackagesRequest<{
    items: ConfigurationPackageVersion[]
    count: number
  }>(accessToken, `/${packageId}/versions`)
}

export async function buildConfigurationPackageVersion(
  accessToken: string,
  packageItem: ConfigurationPackage,
  payload: {
    source_environment: string
    component_types: string[]
    change_summary: string
  },
) {
  return configurationPackagesRequest<ConfigurationPackageVersion>(
    accessToken,
    `/${packageItem.id}/versions`,
    {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        expected_package_revision: packageItem.revision,
        ...payload,
      }),
    },
  )
}

export async function sealConfigurationPackageVersion(
  accessToken: string,
  version: ConfigurationPackageVersion,
  reason: string,
) {
  return configurationPackagesRequest<ConfigurationPackageVersion>(
    accessToken,
    `/versions/${version.id}/seal`,
    {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        expected_revision: version.revision,
        reason,
      }),
    },
  )
}

export async function exportConfigurationPackageVersion(
  accessToken: string,
  versionId: string,
) {
  return configurationPackagesRequest<ConfigurationArtifact>(
    accessToken,
    `/versions/${versionId}/export`,
  )
}

export async function importConfigurationPackageArtifact(
  accessToken: string,
  artifact: ConfigurationArtifact,
  changeSummary: string,
  tenantId?: string | null,
) {
  return configurationPackagesRequest<ConfigurationPackageVersion>(
    accessToken,
    '/import',
    {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        tenant_id: tenantId,
        artifact,
        change_summary: changeSummary,
      }),
    },
  )
}

export async function fetchConfigurationDeployments(
  accessToken: string,
  tenantId?: string | null,
) {
  const response = await fetchWithAuthRetry(
    configurationPackagesUrl('/deployments', { tenant_id: tenantId }),
    undefined,
    accessToken,
  )
  return readJsonResponse<{ items: ConfigurationDeployment[]; count: number }>(
    response,
  )
}

export async function createConfigurationDeployment(
  accessToken: string,
  payload: {
    tenant_id?: string | null
    package_version_id: string
    target_environment: string
    idempotency_key: string
    reason: string
  },
) {
  return configurationPackagesRequest<ConfigurationDeployment>(
    accessToken,
    '/deployments',
    {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    },
  )
}

export async function requestConfigurationDeploymentApproval(
  accessToken: string,
  deployment: ConfigurationDeployment,
  reason: string,
) {
  return configurationPackagesRequest<ConfigurationDeployment>(
    accessToken,
    `/deployments/${deployment.id}/request-approval`,
    {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        expected_revision: deployment.revision,
        reason,
      }),
    },
  )
}

export type RetentionCategory =
  | 'TICKETS'
  | 'SERVICE_REQUESTS'
  | 'COMMENTS'
  | 'NOTIFICATIONS'
  | 'LOGIN_EVENTS'
  | 'AUDIT'
  | 'EMAIL'
  | 'ATTACHMENTS'
  | 'AI_CONVERSATIONS'
  | 'AI_PROMPTS_RESPONSES'
  | 'VECTOR_EMBEDDINGS'
  | 'EXPORTS'
  | 'BACKGROUND_JOBS'
  | 'DEAD_LETTER'

export type EffectiveRetentionPolicy = {
  category: RetentionCategory
  global_minimum_days: number
  tenant_requested_days: number
  effective_retention_days: number
  archive_before_delete: boolean
  anonymize_before_delete: boolean
  tenant_revision: number
  source: 'TENANT' | 'GLOBAL_DEFAULT'
}

export type DataLegalHold = {
  id: string
  tenant_id: string
  name: string
  reason: string
  scope_type: 'TENANT' | 'CATEGORY' | 'ENTITY'
  category: RetentionCategory | null
  entity_type: string | null
  entity_id: string | null
  status: 'ACTIVE' | 'RELEASED' | 'EXPIRED'
  starts_at: string
  expires_at: string | null
  released_at: string | null
  release_reason: string | null
}

export type DataDeletionRequest = {
  id: string
  tenant_id: string
  request_type: 'RETENTION_PURGE' | 'TENANT_DELETION'
  category: RetentionCategory | null
  cutoff_at: string | null
  status: 'PREVIEWED' | 'PENDING_APPROVAL' | 'APPROVED' | 'REJECTED' | 'EXECUTING' | 'COMPLETED' | 'FAILED' | 'CANCELLED' | 'BLOCKED_EXTERNAL'
  reason: string
  preview: {
    operation: string
    counts: Record<string, number>
    estimated_rows: number
    blocked_by_legal_hold: boolean
  }
  estimated_rows: number
  plan_sha256: string
  requested_by_id: string | null
  approved_by_id: string | null
  approval_reason: string | null
  approved_at: string | null
  executed_by_id: string | null
  executed_at: string | null
  failure_reason: string | null
  created_at: string
  updated_at: string
  required_execution_confirmation: string
  evidence?: {
    id: string
    result_sha256: string
    archive_manifest_sha256: string
  }
}

export type DataGovernanceDashboard = {
  tenant_id: string
  policies: EffectiveRetentionPolicy[]
  active_holds: DataLegalHold[]
  recent_requests: DataDeletionRequest[]
  safety: {
    preview_required: boolean
    four_eyes_approval: boolean
    legal_hold_fail_closed: boolean
    explicit_execution_phrase: boolean
    audit_chain_retirement: string
  }
}

function tenantQuery(tenantId?: string | null) {
  return tenantId ? `?tenant_id=${encodeURIComponent(tenantId)}` : ''
}

export async function fetchDataGovernanceDashboard(
  accessToken: string,
  tenantId?: string | null,
): Promise<DataGovernanceDashboard> {
  const response = await fetchWithAuthRetry(
    `${API_BASE_URL}/data-governance/dashboard${tenantQuery(tenantId)}`,
    undefined,
    accessToken,
  )
  return readJsonResponse<DataGovernanceDashboard>(response)
}

export async function updateRetentionPolicy(
  accessToken: string,
  payload: {
    tenant_id?: string | null
    scope: 'GLOBAL' | 'TENANT'
    category: RetentionCategory
    retention_days: number
    archive_before_delete: boolean
    anonymize_before_delete: boolean
    is_enabled: boolean
    expected_revision: number
  },
): Promise<Record<string, unknown>> {
  const response = await fetchWithAuthRetry(
    `${API_BASE_URL}/data-governance/policies`,
    {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    },
    accessToken,
  )
  return readJsonResponse<Record<string, unknown>>(response)
}

export async function createDataLegalHold(
  accessToken: string,
  payload: {
    tenant_id?: string | null
    name: string
    reason: string
    scope_type: 'TENANT' | 'CATEGORY'
    category?: RetentionCategory | null
  },
): Promise<DataLegalHold> {
  const response = await fetchWithAuthRetry(
    `${API_BASE_URL}/data-governance/legal-holds`,
    {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    },
    accessToken,
  )
  return readJsonResponse<DataLegalHold>(response)
}

export async function releaseDataLegalHold(
  accessToken: string,
  holdId: string,
  reason: string,
): Promise<DataLegalHold> {
  const response = await fetchWithAuthRetry(
    `${API_BASE_URL}/data-governance/legal-holds/${holdId}/release`,
    {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ reason }),
    },
    accessToken,
  )
  return readJsonResponse<DataLegalHold>(response)
}

export async function previewDataDeletion(
  accessToken: string,
  payload: {
    tenant_id?: string | null
    request_type: 'RETENTION_PURGE' | 'TENANT_DELETION'
    category?: RetentionCategory | null
    reason: string
  },
): Promise<DataDeletionRequest> {
  const response = await fetchWithAuthRetry(
    `${API_BASE_URL}/data-governance/deletion-requests/preview`,
    {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    },
    accessToken,
  )
  return readJsonResponse<DataDeletionRequest>(response)
}

export async function submitDataDeletion(
  accessToken: string,
  requestId: string,
): Promise<DataDeletionRequest> {
  const response = await fetchWithAuthRetry(
    `${API_BASE_URL}/data-governance/deletion-requests/${requestId}/submit`,
    { method: 'POST' },
    accessToken,
  )
  return readJsonResponse<DataDeletionRequest>(response)
}

export async function decideDataDeletion(
  accessToken: string,
  requestId: string,
  decision: 'APPROVE' | 'REJECT',
  reason: string,
): Promise<DataDeletionRequest> {
  const response = await fetchWithAuthRetry(
    `${API_BASE_URL}/data-governance/deletion-requests/${requestId}/decision`,
    {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ decision, reason }),
    },
    accessToken,
  )
  return readJsonResponse<DataDeletionRequest>(response)
}

export async function executeDataDeletion(
  accessToken: string,
  requestId: string,
  confirmation: string,
): Promise<DataDeletionRequest> {
  const response = await fetchWithAuthRetry(
    `${API_BASE_URL}/data-governance/deletion-requests/${requestId}/execute`,
    {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ confirmation }),
    },
    accessToken,
  )
  return readJsonResponse<DataDeletionRequest>(response)
}

export async function downloadTenantDataExport(
  accessToken: string,
  tenantId?: string | null,
): Promise<{ blob: Blob; sha256: string }> {
  const response = await fetchWithAuthRetry(
    `${API_BASE_URL}/data-governance/tenant-export${tenantQuery(tenantId)}`,
    undefined,
    accessToken,
  )
  if (!response.ok) await readJsonResponse(response)
  return {
    blob: await response.blob(),
    sha256: response.headers.get('x-export-sha256') ?? '',
  }
}

export async function decideConfigurationDeployment(
  accessToken: string,
  deployment: ConfigurationDeployment,
  decision: 'APPROVED' | 'REJECTED',
  comment: string,
) {
  return configurationPackagesRequest<ConfigurationDeployment>(
    accessToken,
    `/deployments/${deployment.id}/decision`,
    {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        expected_revision: deployment.revision,
        decision,
        comment,
      }),
    },
  )
}

export async function applyConfigurationDeployment(
  accessToken: string,
  deployment: ConfigurationDeployment,
  reason: string,
) {
  return configurationPackagesRequest<ConfigurationDeployment>(
    accessToken,
    `/deployments/${deployment.id}/apply`,
    {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        expected_revision: deployment.revision,
        reason,
      }),
    },
  )
}

export async function rollbackConfigurationDeployment(
  accessToken: string,
  deployment: ConfigurationDeployment,
  reason: string,
) {
  return configurationPackagesRequest<ConfigurationDeployment>(
    accessToken,
    `/deployments/${deployment.id}/rollback`,
    {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        expected_revision: deployment.revision,
        reason,
      }),
    },
  )
}

export type AiRagSourceType =
  | 'knowledge'
  | 'ticket'
  | 'problem'
  | 'change'
  | 'asset'

export type AiRagMeta = {
  source_types: AiRagSourceType[]
  allowed_source_types: AiRagSourceType[]
  can_manage: boolean
  can_audit: boolean
  privacy: {
    stores_raw_query: boolean
    stores_raw_answer: boolean
    live_acl_recheck: boolean
    prompt_injection_filter: boolean
  }
}

export type AiRagCitation = {
  citation_id: string
  source_type: AiRagSourceType
  source_id: string
  source_key: string
  title: string
  url_path: string
  excerpt: string
  score: number
  content_sha256: string
  source_updated_at: string
  indexed_at: string
  metadata: Record<string, unknown>
}

export type AiRagSearchResult = {
  citations: AiRagCitation[]
  retrieved_count: number
  permission_denied_count: number
  stale_count: number
  unsafe_source_count: number
  latency_ms: number
}

export type AiRagAnswer = AiRagSearchResult & {
  answer: string
  requested_provider: string
  provider: string
  model: string
  provider_mock: boolean
  fallback_used: boolean
  execution_mode: string
  grounded: boolean
  rationale: string
}

export type AiRagDashboard = {
  active_documents: number
  deleted_documents: number
  source_type_counts: Partial<Record<AiRagSourceType, number>>
  total_queries: number
  grounded_queries: number
  no_result_queries: number
  stale_sources_blocked: number
  permission_denials: number
  injection_attempts: number
  latest_ingestion: {
    id: string
    status: string
    source_types: AiRagSourceType[]
    scanned_count: number
    indexed_count: number
    updated_count: number
    unchanged_count: number
    deleted_count: number
    started_at: string
    completed_at: string | null
  } | null
}

export type AiRagQuery = {
  tenant_id?: string | null
  query: string
  source_types: AiRagSourceType[]
  limit?: number
  minimum_score?: number
}

export async function fetchAiRagMeta(
  accessToken: string,
): Promise<AiRagMeta> {
  const response = await fetchWithAuthRetry(
    `${API_BASE_URL}/ai/rag/meta`,
    undefined,
    accessToken,
  )
  return readJsonResponse<AiRagMeta>(response)
}

export async function fetchAiRagDashboard(
  accessToken: string,
  tenantId?: string | null,
): Promise<AiRagDashboard> {
  const params = new URLSearchParams()
  if (tenantId) params.set('tenant_id', tenantId)
  const suffix = params.size ? `?${params.toString()}` : ''
  const response = await fetchWithAuthRetry(
    `${API_BASE_URL}/ai/rag/dashboard${suffix}`,
    undefined,
    accessToken,
  )
  return readJsonResponse<AiRagDashboard>(response)
}

export async function askAiRag(
  accessToken: string,
  payload: AiRagQuery,
): Promise<AiRagAnswer> {
  const response = await fetchWithAuthRetry(
    `${API_BASE_URL}/ai/rag/ask`,
    {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    },
    accessToken,
  )
  return readJsonResponse<AiRagAnswer>(response)
}

export async function synchronizeAiRag(
  accessToken: string,
  payload: {
    tenant_id?: string | null
    source_types: AiRagSourceType[]
  },
): Promise<{
  id: string
  status: string
  source_types: AiRagSourceType[]
  scanned: number
  indexed: number
  updated: number
  unchanged: number
  deleted: number
  started_at: string
  completed_at: string | null
}> {
  const response = await fetchWithAuthRetry(
    `${API_BASE_URL}/ai/rag/ingestion/sync`,
    {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    },
    accessToken,
  )
  return readJsonResponse(response)
}

export type AiPromptPolicy = {
  id: string
  tenant_id: string
  code: string
  name: string
  description: string | null
  use_case: 'ticket_classification' | 'grounded_answer'
  status: string
  active_version_id: string | null
  revision: number
}

export type AiPromptVersion = {
  id: string
  tenant_id: string
  policy_id: string
  version_number: number
  status: string
  system_prompt: string
  provider: 'mock' | 'openai' | 'gemini'
  model: string
  parameters: Record<string, unknown>
  content_sha256: string
  change_summary: string
  evaluation_run_id: string | null
  reviewed_by_id: string | null
  review_comment: string | null
}

export type AiEvaluationDataset = {
  id: string
  code: string
  name: string
  use_case: 'ticket_classification' | 'grounded_answer'
  status: string
  description: string | null
  revision: number
}

export type AiEvaluationRun = {
  id: string
  prompt_version_id: string
  dataset_id: string
  baseline_version_id: string | null
  status: string
  passed: boolean
  case_count: number
  metrics: {
    quality?: number
    groundedness?: number
    safety?: number
    average_latency_ms?: number
    estimated_cost_usd?: number
  }
  regression: Record<string, unknown>
  evidence_sha256: string | null
}

function aiGovernanceUrl(path: string, tenantId?: string | null) {
  const params = new URLSearchParams()
  if (tenantId) params.set('tenant_id', tenantId)
  return `${API_BASE_URL}/ai/governance${path}${params.size ? `?${params}` : ''}`
}

async function aiGovernanceRequest<T>(
  accessToken: string,
  path: string,
  init?: RequestInit,
) {
  const response = await fetchWithAuthRetry(
    `${API_BASE_URL}/ai/governance${path}`,
    init,
    accessToken,
  )
  return readJsonResponse<T>(response)
}

export async function fetchAiGovernanceDashboard(
  accessToken: string,
  tenantId?: string | null,
) {
  const response = await fetchWithAuthRetry(
    aiGovernanceUrl('/dashboard', tenantId),
    undefined,
    accessToken,
  )
  return readJsonResponse<{
    policies: number
    active_prompts: number
    datasets: number
    passed_runs: number
    failed_runs: number
  }>(response)
}

export async function fetchAiPromptPolicies(
  accessToken: string,
  tenantId?: string | null,
) {
  const response = await fetchWithAuthRetry(
    aiGovernanceUrl('/policies', tenantId),
    undefined,
    accessToken,
  )
  return readJsonResponse<AiPromptPolicy[]>(response)
}

export function createAiPromptPolicy(
  accessToken: string,
  payload: {
    tenant_id?: string | null
    code: string
    name: string
    description?: string
    use_case: 'ticket_classification' | 'grounded_answer'
  },
) {
  return aiGovernanceRequest<AiPromptPolicy>(accessToken, '/policies', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  })
}

export function fetchAiPromptVersions(
  accessToken: string,
  policyId: string,
) {
  return aiGovernanceRequest<AiPromptVersion[]>(
    accessToken,
    `/policies/${policyId}/versions`,
  )
}

export function createAiPromptVersion(
  accessToken: string,
  policyId: string,
  payload: {
    system_prompt: string
    provider: 'mock' | 'openai' | 'gemini'
    model: string
    parameters: Record<string, unknown>
    change_summary: string
  },
) {
  return aiGovernanceRequest<AiPromptVersion>(
    accessToken,
    `/policies/${policyId}/versions`,
    {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    },
  )
}

export async function fetchAiEvaluationDatasets(
  accessToken: string,
  tenantId?: string | null,
) {
  const response = await fetchWithAuthRetry(
    aiGovernanceUrl('/datasets', tenantId),
    undefined,
    accessToken,
  )
  return readJsonResponse<AiEvaluationDataset[]>(response)
}

export function createAiEvaluationDataset(
  accessToken: string,
  payload: {
    tenant_id?: string | null
    code: string
    name: string
    description?: string
    use_case: 'ticket_classification' | 'grounded_answer'
  },
) {
  return aiGovernanceRequest<AiEvaluationDataset>(accessToken, '/datasets', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  })
}

export function createAiEvaluationCase(
  accessToken: string,
  datasetId: string,
  payload: {
    case_key: string
    input_text: string
    sources: Array<Record<string, string>>
    expected: Record<string, unknown>
    forbidden_terms: string[]
    weight: number
  },
) {
  return aiGovernanceRequest<{ id: string; case_key: string }>(
    accessToken,
    `/datasets/${datasetId}/cases`,
    {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    },
  )
}

export function evaluateAiPromptVersion(
  accessToken: string,
  versionId: string,
  datasetId: string,
) {
  return aiGovernanceRequest<AiEvaluationRun>(
    accessToken,
    `/versions/${versionId}/evaluate`,
    {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ dataset_id: datasetId, thresholds: {} }),
    },
  )
}

export function reviewAiPromptVersion(
  accessToken: string,
  versionId: string,
  decision: 'APPROVED' | 'REJECTED',
  comment: string,
) {
  return aiGovernanceRequest<AiPromptVersion>(
    accessToken,
    `/versions/${versionId}/review`,
    {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ decision, comment }),
    },
  )
}

export function rolloutAiPromptVersion(
  accessToken: string,
  versionId: string,
  canaryPercent: number,
  reason: string,
) {
  return aiGovernanceRequest<{
    id: string
    status: string
    canary_percent: number
  }>(accessToken, `/versions/${versionId}/rollout`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      canary_percent: canaryPercent,
      reason,
    }),
  })
}

export type AiRuntimeDashboard = {
  policy_configured: boolean
  external_processing_enabled: boolean
  allowed_providers: string[]
  provider_regions: Record<string, string>
  maximum_external_classification: 'PUBLIC' | 'INTERNAL' | 'CONFIDENTIAL' | 'RESTRICTED'
  pii_redaction_required: boolean
  data_policy: {
    id: string
    revision: number
    external_processing_enabled: boolean
    allowed_providers: string[]
    provider_regions: Record<string, string>
    maximum_external_classification: 'PUBLIC' | 'INTERNAL' | 'CONFIDENTIAL' | 'RESTRICTED'
    pii_redaction_required: boolean
    allow_reversible_redaction: boolean
    retention_days: number
  } | null
  usage: {
    monthly_requests: number
    monthly_cost_usd: number
    daily_requests: number
  }
  budget: {
    monthly_request_limit: number
    monthly_cost_limit_usd: number
    daily_request_limit: number
    warning_percent: number
    hard_limit_enabled: boolean
    revision: number
  } | null
  circuits: Array<{
    provider: string
    state: string
    consecutive_failures: number
    failure_threshold: number
    open_until: string | null
    last_failure_code: string | null
  }>
}

function aiRuntimeUrl(path: string, tenantId?: string | null) {
  const params = new URLSearchParams()
  if (tenantId) params.set('tenant_id', tenantId)
  return `${API_BASE_URL}/ai/runtime-controls${path}${params.size ? `?${params}` : ''}`
}

export async function fetchAiRuntimeDashboard(
  accessToken: string,
  tenantId?: string | null,
) {
  const response = await fetchWithAuthRetry(
    aiRuntimeUrl('/dashboard', tenantId),
    undefined,
    accessToken,
  )
  return readJsonResponse<AiRuntimeDashboard>(response)
}

export async function updateAiDataPolicy(
  accessToken: string,
  payload: {
    tenant_id?: string | null
    expected_revision: number
    external_processing_enabled: boolean
    allowed_providers: Array<'openai' | 'gemini'>
    provider_regions: Record<string, string>
    maximum_external_classification: 'PUBLIC' | 'INTERNAL' | 'CONFIDENTIAL' | 'RESTRICTED'
    pii_redaction_required: boolean
    allow_reversible_redaction: boolean
    retention_days: number
  },
) {
  const response = await fetchWithAuthRetry(
    `${API_BASE_URL}/ai/runtime-controls/data-policy`,
    {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    },
    accessToken,
  )
  return readJsonResponse(response)
}

export async function updateAiUsageBudget(
  accessToken: string,
  payload: {
    tenant_id?: string | null
    expected_revision: number
    monthly_request_limit: number
    monthly_cost_limit_usd: number
    daily_request_limit: number
    warning_percent: number
    hard_limit_enabled: boolean
  },
) {
  const response = await fetchWithAuthRetry(
    `${API_BASE_URL}/ai/runtime-controls/budget`,
    {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    },
    accessToken,
  )
  return readJsonResponse(response)
}

export async function resetAiProviderCircuit(
  accessToken: string,
  provider: 'openai' | 'gemini',
  reason: string,
  tenantId?: string | null,
) {
  const params = new URLSearchParams({ reason })
  if (tenantId) params.set('tenant_id', tenantId)
  const response = await fetchWithAuthRetry(
    `${API_BASE_URL}/ai/runtime-controls/circuits/${provider}/reset?${params}`,
    { method: 'POST' },
    accessToken,
  )
  return readJsonResponse(response)
}

export type AiActionType =
  | 'ticket.update'
  | 'ticket.classify'
  | 'knowledge.draft'
  | 'runbook.draft'

export type AiActionPolicy = {
  id: string
  enabled: boolean
  allowed_actions: AiActionType[]
  independent_approval_for_high_risk: boolean
  proposal_ttl_minutes: number
  revision: number
}

export type AiActionMeta = {
  server_action_allowlist: AiActionType[]
  policy: AiActionPolicy | null
  counts: Record<'PROPOSED' | 'APPROVED' | 'EXECUTED' | 'FAILED' | 'ROLLED_BACK', number>
}

export type AiActionProposal = {
  id: string
  tenant_id: string
  proposal_number: string
  idempotency_key: string
  action_type: AiActionType
  risk_level: 'LOW' | 'MEDIUM' | 'HIGH'
  target_type: string
  target_id: string | null
  target_fingerprint: string | null
  parameters: Record<string, unknown>
  parameters_sha256: string
  citation_evidence: Array<Record<string, string>>
  rationale: string
  status: 'PROPOSED' | 'APPROVED' | 'REJECTED' | 'EXECUTED' | 'FAILED' | 'ROLLED_BACK' | 'EXPIRED'
  created_by_id: string | null
  reviewed_by_id: string | null
  review_comment: string | null
  reviewed_at: string | null
  executed_by_id: string | null
  executed_at: string | null
  expires_at: string
  error_code: string | null
  created_at: string
  updated_at: string
}

function aiActionsUrl(path: string, tenantId?: string | null) {
  const params = new URLSearchParams()
  if (tenantId) params.set('tenant_id', tenantId)
  return `${API_BASE_URL}/ai/actions${path}${params.size ? `?${params}` : ''}`
}

export async function fetchAiActionMeta(
  accessToken: string,
  tenantId?: string | null,
) {
  const response = await fetchWithAuthRetry(
    aiActionsUrl('/meta', tenantId),
    undefined,
    accessToken,
  )
  return readJsonResponse<AiActionMeta>(response)
}

export async function fetchAiActionProposals(
  accessToken: string,
  tenantId?: string | null,
) {
  const response = await fetchWithAuthRetry(
    aiActionsUrl('/proposals', tenantId),
    undefined,
    accessToken,
  )
  return readJsonResponse<AiActionProposal[]>(response)
}

export async function updateAiActionPolicy(
  accessToken: string,
  payload: {
    tenant_id?: string | null
    expected_revision: number
    enabled: boolean
    allowed_actions: AiActionType[]
    independent_approval_for_high_risk: boolean
    proposal_ttl_minutes: number
  },
) {
  const response = await fetchWithAuthRetry(
    `${API_BASE_URL}/ai/actions/policy`,
    {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    },
    accessToken,
  )
  return readJsonResponse<AiActionPolicy>(response)
}

export async function createAiActionProposal(
  accessToken: string,
  payload: {
    tenant_id?: string | null
    idempotency_key: string
    action_type: AiActionType
    target_id?: string | null
    parameters: Record<string, unknown>
    source_query?: string | null
    citations: Array<Record<string, unknown>>
    rationale: string
  },
) {
  const response = await fetchWithAuthRetry(
    `${API_BASE_URL}/ai/actions/proposals`,
    {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    },
    accessToken,
  )
  return readJsonResponse<AiActionProposal>(response)
}

export async function decideAiActionProposal(
  accessToken: string,
  proposalId: string,
  decision: 'APPROVED' | 'REJECTED',
  comment: string,
) {
  const response = await fetchWithAuthRetry(
    `${API_BASE_URL}/ai/actions/proposals/${proposalId}/decision`,
    {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ decision, comment }),
    },
    accessToken,
  )
  return readJsonResponse<AiActionProposal>(response)
}

export async function executeAiActionProposal(
  accessToken: string,
  proposalId: string,
) {
  const response = await fetchWithAuthRetry(
    `${API_BASE_URL}/ai/actions/proposals/${proposalId}/execute`,
    { method: 'POST' },
    accessToken,
  )
  return readJsonResponse(response)
}

export async function rollbackAiActionProposal(
  accessToken: string,
  proposalId: string,
  reason: string,
) {
  const response = await fetchWithAuthRetry(
    `${API_BASE_URL}/ai/actions/proposals/${proposalId}/rollback`,
    {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ reason }),
    },
    accessToken,
  )
  return readJsonResponse(response)
}

export type GuidedConfigurationCheck = {
  code: string
  title: string
  status: 'PASS' | 'INFO' | 'WARNING' | 'ACTION_REQUIRED' | 'NOT_APPLICABLE'
  severity: 'critical' | 'high' | 'medium' | 'info'
  diagnostic: string
  remediation: string
  route: string
  can_manage: boolean
  required_permission: string
  safe_default: string
  evidence: Record<string, unknown>
  evidence_sha256: string
  runbook: string
  audit_route: string
}

export type GuidedConfigurationAction = Pick<
  GuidedConfigurationCheck,
  | 'title'
  | 'status'
  | 'severity'
  | 'diagnostic'
  | 'remediation'
  | 'route'
  | 'can_manage'
  | 'required_permission'
  | 'runbook'
  | 'audit_route'
  | 'evidence_sha256'
> & {
  domain_code: string
  domain_title: string
  check_code: string
}

export type ConfigurationDomain = {
  code: string
  title: string
  description: string
  scope: 'global' | 'tenant'
  status: 'READY' | 'DEGRADED' | 'ACTION_REQUIRED'
  readiness_percent: number
  configured_items: number
  required_items: number
  issues: string[]
  route: string
  can_manage: boolean
  supports_test: boolean
  supports_rollback: boolean
  updated_at: string | null
  checks: GuidedConfigurationCheck[]
  owner_roles: string[]
  runbook: string | null
  safe_default: string | null
  evidence_sha256: string
}

export type TypedConfigurationSetting = {
  key: string
  domain: string
  label: string
  description: string
  value_type: 'boolean' | 'integer'
  value: boolean | number
  default_value: boolean | number
  minimum: number | null
  maximum: number | null
  scope: 'global' | 'tenant'
  source: 'default' | 'global' | 'global_inherited' | 'tenant'
  is_inherited: boolean
  revision: number
  valid: boolean
  issue: string | null
  updated_at: string | null
}

export type ConfigurationCenter = {
  scope: {
    type: 'global' | 'tenant'
    tenant_id: string | null
    label: string
  }
  overall: {
    status: 'READY' | 'DEGRADED' | 'ACTION_REQUIRED'
    readiness_percent: number
    ready_domains: number
    total_domains: number
    issues: string[]
  }
  domains: ConfigurationDomain[]
  settings: TypedConfigurationSetting[]
  guide: {
    version: string
    generated_at: string
    operator_role: string
    next_actions: GuidedConfigurationAction[]
    total_checks: number
    action_required_checks: number
    warning_checks: number
  }
  secret_storage: {
    strategy: string
    plaintext_returned: boolean
    global_provider_root_only: boolean
  }
}

export type ConfigurationSettingRevision = {
  id: string
  setting_key: string
  revision: number
  value: boolean | number
  value_sha256: string
  changed_by_id: string | null
  change_reason: string
  rolled_back_from_revision: number | null
  created_at: string
}

function configurationCenterUrl(
  path: string,
  tenantId?: string | null,
) {
  const params = new URLSearchParams()
  if (tenantId) params.set('tenant_id', tenantId)
  return `${API_BASE_URL}/admin/configuration-center${path}${
    params.size ? `?${params}` : ''
  }`
}

export async function fetchConfigurationCenter(
  accessToken: string,
  tenantId?: string | null,
) {
  const response = await fetchWithAuthRetry(
    configurationCenterUrl('', tenantId),
    undefined,
    accessToken,
  )
  return readJsonResponse<ConfigurationCenter>(response)
}

export async function updateTypedConfigurationSetting(
  accessToken: string,
  key: string,
  payload: {
    tenant_id?: string | null
    expected_revision: number
    value: boolean | number
    reason: string
  },
) {
  const response = await fetchWithAuthRetry(
    `${API_BASE_URL}/admin/configuration-center/settings/${encodeURIComponent(key)}`,
    {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    },
    accessToken,
  )
  return readJsonResponse<TypedConfigurationSetting>(response)
}

export async function fetchConfigurationSettingHistory(
  accessToken: string,
  key: string,
  tenantId?: string | null,
) {
  const response = await fetchWithAuthRetry(
    configurationCenterUrl(
      `/settings/${encodeURIComponent(key)}/history`,
      tenantId,
    ),
    undefined,
    accessToken,
  )
  return readJsonResponse<ConfigurationSettingRevision[]>(response)
}

export async function rollbackTypedConfigurationSetting(
  accessToken: string,
  key: string,
  payload: {
    tenant_id?: string | null
    expected_revision: number
    target_revision: number
    reason: string
  },
) {
  const response = await fetchWithAuthRetry(
    `${API_BASE_URL}/admin/configuration-center/settings/${encodeURIComponent(key)}/rollback`,
    {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    },
    accessToken,
  )
  return readJsonResponse<TypedConfigurationSetting>(response)
}

export type GlobalSearchEntityType =
  | 'ticket'
  | 'request'
  | 'knowledge'
  | 'asset'
  | 'change'
  | 'problem'
  | 'user'

export type GlobalSearchResult = {
  entity_type: GlobalSearchEntityType
  id: string
  tenant_id: string | null
  identifier: string
  title: string
  subtitle: string | null
  status: string | null
  href: string
  updated_at: string
  score: number
  matched_fields: string[]
}

export type GlobalSearchResponse = {
  items: GlobalSearchResult[]
  counts: Partial<Record<GlobalSearchEntityType, number>>
  selected_types: GlobalSearchEntityType[]
  total: number
  query_sha256: string
  duration_ms: number
}

export type SavedSearchQuery = {
  q: string
  types: GlobalSearchEntityType[]
}

export type SavedSearchView = {
  id: string
  tenant_id: string | null
  owner_user_id: string
  name: string
  query: SavedSearchQuery
  query_sha256: string
  is_shared: boolean
  shared_role_codes: string[]
  is_owner: boolean
  revision: number
  created_at: string
  updated_at: string
}

export async function runGlobalSearch(
  accessToken: string,
  payload: {
    q: string
    types: GlobalSearchEntityType[]
    per_type_limit?: number
    total_limit?: number
  },
) {
  const params = new URLSearchParams({
    q: payload.q,
    types: payload.types.join(','),
    per_type_limit: String(payload.per_type_limit ?? 8),
    total_limit: String(payload.total_limit ?? 40),
  })
  const response = await fetchWithAuthRetry(
    `${API_BASE_URL}/search?${params}`,
    undefined,
    accessToken,
  )
  return readJsonResponse<GlobalSearchResponse>(response)
}

export async function fetchSavedSearchViews(accessToken: string) {
  const response = await fetchWithAuthRetry(
    `${API_BASE_URL}/search/views`,
    undefined,
    accessToken,
  )
  return readJsonResponse<SavedSearchView[]>(response)
}

export async function createSavedSearchView(
  accessToken: string,
  payload: {
    name: string
    query: SavedSearchQuery
    is_shared: boolean
    shared_role_codes: string[]
  },
) {
  const response = await fetchWithAuthRetry(
    `${API_BASE_URL}/search/views`,
    {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    },
    accessToken,
  )
  return readJsonResponse<SavedSearchView>(response)
}

export async function deleteSavedSearchView(
  accessToken: string,
  viewId: string,
) {
  const response = await fetchWithAuthRetry(
    `${API_BASE_URL}/search/views/${encodeURIComponent(viewId)}`,
    { method: 'DELETE' },
    accessToken,
  )
  if (!response.ok) {
    await readJsonResponse(response)
  }
}
