@echo off
setlocal
set "PROJECT_ROOT=%~dp0.."
set "FRONTEND_ROOT=%PROJECT_ROOT%\frontend"
set "FRONTEND_LOG=%PROJECT_ROOT%\.local-frontend.out.log"
set "FRONTEND_ERROR_LOG=%PROJECT_ROOT%\.local-frontend.err.log"

if not defined SBS_NODE set "SBS_NODE=%USERPROFILE%\.cache\codex-runtimes\codex-primary-runtime\dependencies\node\bin\node.exe"
if not exist "%SBS_NODE%" (
  >"%FRONTEND_ERROR_LOG%" echo Node.js runtime not found. Set SBS_NODE to a Node.js executable.
  exit /b 1
)

cd /d "%FRONTEND_ROOT%"
"%SBS_NODE%" "%FRONTEND_ROOT%\node_modules\vite\bin\vite.js" --host 127.0.0.1 --port 5173 1>"%FRONTEND_LOG%" 2>"%FRONTEND_ERROR_LOG%"
