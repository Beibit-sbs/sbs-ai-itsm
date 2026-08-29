\set ON_ERROR_STOP on

INSERT INTO tenants (id, name, slug, status, description)
VALUES
  ('10000000-0000-0000-0000-000000000001', 'Migration Tenant A', 'migration-tenant-a', 'active', 'PRG-002 fixture'),
  ('20000000-0000-0000-0000-000000000002', 'Migration Tenant B', 'migration-tenant-b', 'active', 'PRG-002 fixture')
ON CONFLICT (id) DO NOTHING;

INSERT INTO users (
  id,
  tenant_id,
  role_id,
  email,
  full_name,
  position,
  department,
  phone,
  password_hash,
  is_active,
  is_superuser,
  is_root
)
VALUES
  (
    '10000000-0000-0000-0000-000000000011',
    '10000000-0000-0000-0000-000000000001',
    NULL,
    'migration-a@rehearsal.local',
    'Migration User A',
    'Requester',
    'Operations',
    NULL,
    'rehearsal-login-disabled',
    TRUE,
    FALSE,
    FALSE
  ),
  (
    '20000000-0000-0000-0000-000000000022',
    '20000000-0000-0000-0000-000000000002',
    NULL,
    'migration-b@rehearsal.local',
    'Migration User B',
    'Requester',
    'Finance',
    NULL,
    'rehearsal-login-disabled',
    TRUE,
    FALSE,
    FALSE
  )
ON CONFLICT (id) DO NOTHING;

INSERT INTO tickets (
  id,
  tenant_id,
  ticket_number,
  title,
  requester_email,
  department,
  location,
  category,
  priority,
  status,
  requester_id,
  requester_name,
  description
)
SELECT
  '30000000-0000-0000-0000-' || lpad(series::text, 12, '0'),
  '10000000-0000-0000-0000-000000000001',
  'MIG-A-' || lpad(series::text, 4, '0'),
  'Migration rehearsal tenant A ticket ' || series,
  'migration-a@rehearsal.local',
  'Operations',
  'Local Lab',
  'Infrastructure',
  CASE WHEN series % 5 = 0 THEN 'high' ELSE 'medium' END,
  CASE WHEN series % 3 = 0 THEN 'in_progress' ELSE 'open' END,
  '10000000-0000-0000-0000-000000000011',
  'Migration User A',
  'Production-like PRG-002 fixture'
FROM generate_series(1, 25) AS series
ON CONFLICT (id) DO NOTHING;

INSERT INTO tickets (
  id,
  tenant_id,
  ticket_number,
  title,
  requester_email,
  department,
  location,
  category,
  priority,
  status,
  requester_id,
  requester_name,
  description
)
SELECT
  '40000000-0000-0000-0000-' || lpad(series::text, 12, '0'),
  '20000000-0000-0000-0000-000000000002',
  'MIG-B-' || lpad(series::text, 4, '0'),
  'Migration rehearsal tenant B ticket ' || series,
  'migration-b@rehearsal.local',
  'Finance',
  'Local Lab',
  'Business Application',
  CASE WHEN series % 7 = 0 THEN 'critical' ELSE 'low' END,
  CASE WHEN series % 4 = 0 THEN 'resolved' ELSE 'open' END,
  '20000000-0000-0000-0000-000000000022',
  'Migration User B',
  'Production-like PRG-002 fixture'
FROM generate_series(1, 25) AS series
ON CONFLICT (id) DO NOTHING;
