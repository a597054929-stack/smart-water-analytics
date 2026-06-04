@echo off
REM === Load .env from project root into current process env ===
REM Usage: call ..\_load_env.bat
REM
REM Skips blank lines and lines starting with #.
REM Lines are parsed as KEY=VALUE; only the first '=' splits.
REM
REM The caller must `cd` to the project root first so the .env path
REM resolves correctly.

if not exist ".env" (
  echo WARNING: .env not found in project root.
  echo   Create one with:  copy .env.example .env
  echo   Then fill in LLM_API_KEY=...
  echo   ^(falling back to %%USERPROFILE%%\.openclaw\openclaw.json^)
  exit /b 0
)

for /f "usebackq eol=# tokens=1,* delims==" %%a in (".env") do (
  if not "%%a"=="" set "%%a=%%b"
)
