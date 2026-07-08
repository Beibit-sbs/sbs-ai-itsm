# SBS AI ITSM — Master Plan

## Product goal

Create a commercial multi-tenant IT service management platform that can operate independently and later integrate with SBS UB, SBS Corp Brain and SBS Gov Brain.

## Delivery sequence

1. FOUNDATION-001 — monorepo and runtime foundation. **Completed**.
2. FOUNDATION-002 — Tenant, User, Role and Permission.
3. ITSM-001 — Ticket lifecycle and comments.
4. ITSM-002 — Assignment, queues, categories and priorities.
5. SLA-001 — SLA policies, timers and escalation events.
6. ASSET-001 — Asset registry, locations and assignments.
7. KB-001 — Knowledge base and solution links.
8. AI-001 — Provider layer and advisory classification.
9. ANALYTICS-001 — Operational dashboard and management reports.
10. PILOT-001 — university pilot readiness.

## Non-negotiable controls

- Tenant isolation is enforced in backend queries and tests.
- SaaS Root and Organization Admin have different permission boundaries.
- Important actions are recorded in immutable audit events.
- AI suggestions never make privileged changes without explicit confirmation.
- Every stage ends with tests, a report and a named next authorized stage.
