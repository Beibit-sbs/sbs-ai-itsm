# FOUNDATION Architecture

```text
Browser
  │
  ▼
React SPA :5173
  │  HTTP /api/v1
  ▼
FastAPI :8000
  ├── PostgreSQL :5432
  └── Redis :6379
```

## Backend layers

- `api` — transport and versioned routes;
- `core` — settings, exceptions and application-level infrastructure;
- `db` — SQLAlchemy engine/session foundation;
- future modules: models, repositories, services, permissions, audit.

## Frontend layers

- `app` — providers and routing;
- `api` — typed API client;
- `components` — reusable UI;
- `pages` — route-level screens.
