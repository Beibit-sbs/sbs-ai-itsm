export type AccessRequirement = {
  allPermissions?: readonly string[]
  anyPermissions?: readonly string[]
  permissionPrefixes?: readonly string[]
}

export type PermissionSubject = {
  role: string
  permissions?: readonly string[]
}

export const ROUTE_ACCESS_REQUIREMENTS: Readonly<Record<string, AccessRequirement>> = {
  '/monitoring': {
    anyPermissions: ['admin.settings.read', 'admin.users.read', 'security.audit.read'],
  },
  '/events': {
    anyPermissions: [
      'monitoring.events.read',
      'monitoring.connectors.read',
      'monitoring.receipts.read',
    ],
  },
  '/tickets': {
    allPermissions: ['tickets.read'],
    anyPermissions: [
      'tickets.scope.all',
      'tickets.scope.assigned',
      'tickets.scope.requester',
      'tickets.assign',
      'tickets.self_assign',
    ],
  },
  '/major-incidents': { anyPermissions: ['major_incidents.read'] },
  '/catalog': { anyPermissions: ['catalog.read'] },
  '/requests': {
    allPermissions: ['requests.read'],
    anyPermissions: [
      'requests.scope.all',
      'requests.scope.requester',
      'requests.manage',
      'requests.fulfill',
      'requests.approve',
    ],
  },
  '/changes': { anyPermissions: ['changes.read'] },
  '/change-calendar': { anyPermissions: ['changes.read'] },
  '/releases': { anyPermissions: ['changes.read'] },
  '/problems': { anyPermissions: ['problems.read'] },
  '/problem-governance': { anyPermissions: ['problems.read'] },
  '/integrations': {
    permissionPrefixes: ['integrations.', 'integration.platform.'],
  },
  '/assets': { anyPermissions: ['assets.read'] },
  '/software-assets': { anyPermissions: ['sam.read'] },
  '/sla': { anyPermissions: ['sla.read'] },
  '/knowledge': { anyPermissions: ['knowledge.read'] },
  '/copilot': {
    anyPermissions: [
      'ai.use',
      'ai.rag.use',
      'ai.governance.read',
      'ai.runtime.read',
      'ai.actions.read',
    ],
  },
  '/notifications': {
    anyPermissions: ['notifications.read', 'notifications.templates.read'],
  },
  '/notifications/email-log': {
    anyPermissions: ['notifications.email_log.read'],
  },
  '/analytics': { anyPermissions: ['analytics.read', 'reports.read'] },
  '/automation': {
    permissionPrefixes: ['automation.', 'workflows.'],
  },
  '/admin': {
    anyPermissions: ['tenant.profile.read', 'tenant.profile.manage'],
    permissionPrefixes: ['admin.', 'security.'],
  },
  '/admin/system': {
    anyPermissions: ['admin.settings.read', 'admin.users.read', 'security.audit.read'],
  },
  '/admin/data-governance': { permissionPrefixes: ['data.'] },
  '/identity-provisioning': {
    anyPermissions: ['identity.provisioning.read'],
  },
  '/email-operations': { permissionPrefixes: ['email.'] },
  '/teams-collaboration': { permissionPrefixes: ['teams.'] },
  '/admin/custom-fields': { permissionPrefixes: ['custom_fields.'] },
  '/admin/configuration-packages': {
    permissionPrefixes: ['configuration.packages.', 'configuration.deployments.'],
  },
}

function normalizePath(pathname: string) {
  if (pathname === '/') return pathname
  return pathname.replace(/\/+$/, '')
}

export function canAccessRequirement(
  subject: PermissionSubject,
  requirement?: AccessRequirement,
) {
  if (subject.role === 'saas_root') return true
  if (!requirement) return true

  const permissions = new Set(subject.permissions ?? [])
  const required = requirement.allPermissions ?? []
  const exact = requirement.anyPermissions ?? []
  const prefixes = requirement.permissionPrefixes ?? []
  const hasRequired = required.every((permission) => permissions.has(permission))
  const hasAlternative = exact.length === 0 && prefixes.length === 0
    ? true
    : exact.some((permission) => permissions.has(permission))
      || prefixes.some((prefix) => (
        Array.from(permissions).some((permission) => permission.startsWith(prefix))
      ))

  return hasRequired && hasAlternative
}

export function canAccessPath(subject: PermissionSubject, pathname: string) {
  return canAccessRequirement(
    subject,
    ROUTE_ACCESS_REQUIREMENTS[normalizePath(pathname)],
  )
}
