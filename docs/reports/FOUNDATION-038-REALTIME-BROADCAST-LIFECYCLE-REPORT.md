# Stage 038: Real-Time Broadcast Lifecycle - Implementation Report

## Scope

Stage 038 converts dashboard WebSocket infrastructure into active runtime behavior and aligns frontend data refresh with stream-driven updates.

Implemented in this stage:
- Backend broadcaster loops are activated in application lifespan.
- Stream loops fetch tenant dashboard data and broadcast by stream interval.
- Frontend monitoring page switches from fixed polling intervals to websocket-driven invalidation (hybrid realtime).

## Backend Changes

### 1) App lifecycle integration

File: `backend/app/main.py`
- Added broadcaster import.
- Started broadcaster at app startup.
- Stopped broadcaster in lifespan shutdown block.

Effect:
- Broadcast loops are no longer dormant.
- Runtime behavior is deterministic on startup/shutdown.

### 2) Active dashboard stream broadcaster

File: `backend/app/services/jobs/dashboard_websocket_service.py`
- Reworked `DashboardStreamBroadcaster` into global runtime service.
- Added task-managed `start()` / `stop()` API.
- Added tenant-aware `_run_stream_loop(...)` for all stream types.
- Added real fetchers calling Stage 035 dashboard service methods.
- Added active rollout selection helper for metrics/comparison/correlation streams.
- Added global singleton `dashboard_stream_broadcaster`.

Intervals:
- `summary`: 30s
- `metrics`: 30s
- `alerts`: 30s
- `comparison`: 60s
- `anomalies`: 60s
- `correlation`: 120s

### 3) Broadcaster tests

File: `backend/tests/test_websocket_stage_037.py`
- Added lifecycle test: start creates 6 tasks, stop cancels and clears tasks.
- Added stream loop behavior test for connected tenant broadcast path.

## Frontend Changes

### 1) WebSocket hook guard

File: `frontend/src/api/websocket.ts`
- Added early return in hook when `accessToken` is empty.

Effect:
- Prevents unnecessary connection attempts before authentication is ready.

### 2) Monitoring page hybrid realtime mode

File: `frontend/src/pages/MonitoringPage.tsx`
- Removed `refetchInterval` from all monitoring queries.
- Added websocket client hookup using existing websocket API.
- Subscribes to all dashboard streams after realtime connect.
- On stream messages, invalidates corresponding query keys.
- Added realtime connection indicator in UI.

Effect:
- Data refresh is now event-driven by streams rather than periodic polling timers.
- Existing typed REST query flow remains as compatibility fallback path (hybrid model).

## Validation

### Backend tests

Command:
- `cd backend && python -m pytest tests/test_websocket_stage_037.py tests/test_dashboard_stage_035.py -q`

Result:
- `45 passed`

### Frontend build

Command:
- `cd frontend && npm run build`

Result:
- TypeScript + Vite build successful.

## Outcome

Stage 038 is complete.

Delivered value:
- Real-time dashboard streams are now actively produced in runtime.
- Frontend monitoring traffic shifted from timer polling to websocket-triggered refresh behavior.
- Platform is prepared for Stage 039 full push updates (`setQueryData`) and stream filter optimization.
