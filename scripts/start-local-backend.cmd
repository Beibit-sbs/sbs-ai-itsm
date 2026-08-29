@echo off
setlocal
set "PROJECT_ROOT=%~dp0.."
set "BACKEND_ROOT=%PROJECT_ROOT%\backend"
set "BACKEND_LOG=%PROJECT_ROOT%\.local-backend.out.log"
set "BACKEND_ERROR_LOG=%PROJECT_ROOT%\.local-backend.err.log"

if not defined SBS_PYTHON set "SBS_PYTHON=%USERPROFILE%\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe"
if not exist "%SBS_PYTHON%" (
  >"%BACKEND_ERROR_LOG%" echo Python runtime not found. Set SBS_PYTHON to a Python executable with backend dependencies installed.
  exit /b 1
)

if not defined SBS_DATABASE_URL (
  set "SBS_DATABASE_URL=sqlite:///%LOCALAPPDATA:\=/%/Temp/sbs-ai-itsm-visible.db"
)
set "DATABASE_URL=%SBS_DATABASE_URL%"
set "DEMO_MODE=true"
set "SEED_DEMO_CATALOG=true"
set "RUN_STARTUP_DDL=true"

cd /d "%BACKEND_ROOT%"
"%SBS_PYTHON%" -m uvicorn app.main:app --host 127.0.0.1 --port 8000 1>"%BACKEND_LOG%" 2>"%BACKEND_ERROR_LOG%"
