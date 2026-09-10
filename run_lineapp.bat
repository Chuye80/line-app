@echo off
setlocal

rem One double-click start for local development.
rem
rem The order below is the point of this file: check the prerequisites, bring
rem the database up to the committed migration chain, verify the result, and
rem only then start the API and the dev server. Starting FastAPI against a
rem database that is missing a table produces an unhandled 500, and because an
rem unhandled error escapes before the CORS headers are attached the browser
rem reports it as "Failed to fetch" - an error message that says nothing about
rem the actual cause. Refusing to launch is far kinder than that.

cd /d "%~dp0"

set "PYTHON=.venv\Scripts\python.exe"

echo ==== LineApp local start ====
echo.

rem --- virtual environment ---------------------------------------------------

if not exist "%PYTHON%" (
    echo No virtual environment found. Creating .venv ...
    py -3 -m venv .venv
    if not exist "%PYTHON%" python -m venv .venv
    if not exist "%PYTHON%" (
        echo Could not create a virtual environment. Is Python 3 installed and on PATH?
        goto :fail
    )
    "%PYTHON%" -m pip install --upgrade pip
    "%PYTHON%" -m pip install -r requirements.txt
    if errorlevel 1 goto :fail
)

rem Catches a virtual environment that exists but predates a dependency change.
"%PYTHON%" -c "import uvicorn, psycopg2, dotenv, sqlalchemy" >nul 2>&1
if errorlevel 1 (
    echo Installing backend dependencies ...
    "%PYTHON%" -m pip install -r requirements.txt
    if errorlevel 1 goto :fail
)

rem --- configuration ---------------------------------------------------------
rem
rem Read only. These files hold the Supabase credentials and the developer
rem tool flags, so this script never writes to them.

if not exist ".env" (
    echo MISSING: .env
    echo Copy .env.example to .env and fill in the Supabase values.
    goto :fail
)

if not exist "frontend\.env" (
    echo MISSING: frontend\.env
    echo Copy frontend\.env.example to frontend\.env and fill in the Supabase values.
    goto :fail
)

if not exist "frontend\node_modules" (
    echo Installing frontend dependencies ...
    pushd frontend
    call npm install
    popd
    if errorlevel 1 goto :fail
)

rem The developer panel needs a flag on both sides to appear. Reported, not
rem changed: which flags belong in a given checkout is the developer's call.
findstr /b /i /c:"ENABLE_DEV_ENDPOINTS=true" .env >nul 2>&1
if errorlevel 1 echo NOTE: ENABLE_DEV_ENDPOINTS is not true in .env - Developer Tools will be unavailable.

findstr /b /i /c:"VITE_ENABLE_DEV_TOOLS=true" frontend\.env >nul 2>&1
if errorlevel 1 echo NOTE: VITE_ENABLE_DEV_TOOLS is not true in frontend\.env - the Developer Tools screen will be hidden.

rem --- a stray DATABASE_URL in the environment silently beats .env -----------
rem
rem python-dotenv does not override variables that are already set, so a
rem DATABASE_URL left in the Windows environment wins over the project .env,
rem and the symptom is a database that appears to be missing its tables.

if defined DATABASE_URL (
    echo.
    echo WARNING: DATABASE_URL is set in this environment, which overrides the
    echo          value in .env. Check the "target:" line below is the database
    echo          you mean to use. Run "set DATABASE_URL=" to fall back to .env.
)

rem --- schema ---------------------------------------------------------------
rem
rem Applies whatever is outstanding, in filename order, each file in its own
rem transaction, then runs supabase/verify_schema.sql. Every migration is
rem idempotent and additive, so an already-migrated database is a no-op and
rem existing rows are left alone. A non-zero exit means either a migration
rem failed and was rolled back or the schema still does not match, and in both
rem cases the app must not start.

echo.
echo Preparing the database ...
echo.
"%PYTHON%" scripts\apply_migrations.py
if errorlevel 1 (
    echo.
    echo ==========================================================
    echo  The database is NOT ready. LineApp has not been started.
    echo.
    echo  Read the error above. The usual causes are:
    echo    - "target:" points at the wrong database, because
    echo      DATABASE_URL is set in the Windows environment
    echo    - DATABASE_URL in .env is wrong or unreachable
    echo    - a migration failed and was rolled back
    echo.
    echo  Nothing was left half-applied: each migration runs in
    echo  its own transaction.
    echo ==========================================================
    goto :fail
)

rem --- run ------------------------------------------------------------------

echo.
echo Starting the backend and the frontend in separate windows ...
start "LineApp backend" cmd /k "%PYTHON% -m uvicorn backend.main:app --reload --port 8000"
start "LineApp frontend" cmd /k "cd frontend && npm run dev"

echo Waiting for the dev server ...
timeout /t 6 /nobreak >nul
start "" http://localhost:5173

echo.
echo LineApp is running. Close the two new windows to stop it.
goto :eof

:fail
echo.
echo Startup failed. See the message above.
pause
exit /b 1
