@echo off
setlocal EnableExtensions EnableDelayedExpansion
chcp 65001 >nul
cd /d "%~dp0"

rem ==========================================================================
rem  MiniLMS - chay Database + Backend + Frontend chi bang mot lenh
rem
rem  Cach dung:
rem    run.bat          : kiem tra DB, cai thieu thu vien, chay Flask (BE + FE)
rem    run.bat db       : chi kiem tra / khoi dong PostgreSQL va tao database
rem    run.bat app      : chi chay Flask
rem    run.bat test     : chay test tren database lms_test
rem
rem  Frontend cua du an la giao dien server-side (Jinja2 + CSS) do chinh Flask
rem  phuc vu, nen khong co tien trinh FE rieng: chay Flask la co ca BE va FE.
rem ==========================================================================

set "APP_PORT=5000"
set "PG_PORT=2010"
set "PG_SERVICE=postgresql-x64-18"
set "DB_NAME=lms"
set "PY=python"

echo ============================================================
echo   MiniLMS - Database + Backend + Frontend
echo ============================================================

if not exist ".env" call :setup_env
call :load_env

if /i "%~1"=="db"   goto :db_only
if /i "%~1"=="app"  goto :app_only
if /i "%~1"=="test" goto :test
goto :all

rem --------------------------------------------------------------------------
:all
call :ensure_db
if errorlevel 1 goto :fail
call :ensure_deps
if errorlevel 1 goto :fail
call :run_app
goto :done

:db_only
call :ensure_db
if errorlevel 1 goto :fail
echo.
echo [OK] Database "%DB_NAME%" san sang tren cong %PG_PORT%.
goto :done

:app_only
call :ensure_deps
if errorlevel 1 goto :fail
call :run_app
goto :done

:test
call :ensure_db
if errorlevel 1 goto :fail
call :ensure_test_db
set "TEST_DATABASE_URL=postgresql://postgres@127.0.0.1:%PG_PORT%/lms_test"
echo [..] Chay test...
%PY% -m pytest -q --cov=app --cov-fail-under=80
goto :done

rem --------------------------------------------------------------------------
rem  Tao .env lan dau: sinh JWT secret, bo mat khau mac dinh khoi URL, hoi
rem  mat khau PostgreSQL va luu vao .env (file da nam trong .gitignore).
rem --------------------------------------------------------------------------
:setup_env
if exist ".env" exit /b 0
echo [i] Chua co .env - tao tu .env.example...
copy /y ".env.example" ".env" >nul
powershell -NoProfile -Command "$s=-join((48..57)+(97..122)|Get-Random -Count 48|ForEach-Object{[char]$_}); $t=Get-Content -Raw '.env'; $t=$t -replace 'JWT_SECRET=.*',('JWT_SECRET='+$s); $t=$t -replace 'postgresql://postgres:postgres@','postgresql://postgres@'; $t=$t -replace 'PUBLIC_BASE_URL=.*','PUBLIC_BASE_URL=http://127.0.0.1:5000'; Set-Content -NoNewline -Encoding ASCII -Path '.env' -Value $t"
echo.
echo Nhap mat khau PostgreSQL cua user "postgres" (bo trong neu khong co):
set /p "PGPASSWORD="
if defined PGPASSWORD powershell -NoProfile -Command "Add-Content -Encoding ASCII -Path '.env' -Value ('PGPASSWORD=' + $env:PGPASSWORD)"
echo [i] Da luu cau hinh vao .env (khong commit len git).
exit /b 0

rem --------------------------------------------------------------------------
:load_env
for /f "usebackq eol=# tokens=1,* delims==" %%A in (".env") do (
  if not "%%~A"=="" set "%%~A=%%~B"
)
exit /b 0

rem --------------------------------------------------------------------------
:ensure_db
call :is_port_open %PG_PORT%
if errorlevel 1 (
  echo [..] PostgreSQL chua chay, thu khoi dong service "%PG_SERVICE%"...
  net start %PG_SERVICE% >nul 2>&1
  timeout /t 3 >nul
  call :is_port_open %PG_PORT%
  if errorlevel 1 (
    echo [x] Khong ket noi duoc PostgreSQL o cong %PG_PORT%.
    echo     - Mo "Services" va khoi dong "%PG_SERVICE%", hoac
    echo     - Chay lenh sau trong PowerShell quan tri vien:
    echo         net start %PG_SERVICE%
    exit /b 1
  )
)
echo [OK] PostgreSQL dang chay o cong %PG_PORT%.

set "PSQL=psql"
where psql >nul 2>&1 || set "PSQL=C:\Program Files\PostgreSQL\18\bin\psql.exe"
if /i not "%PSQL%"=="psql" if not exist "%PSQL%" (
  echo [!] Khong tim thay psql - bo qua buoc kiem tra/tao database.
  exit /b 0
)

"%PSQL%" -h 127.0.0.1 -p %PG_PORT% -U postgres -d postgres -tAc "SELECT 1 FROM pg_database WHERE datname='%DB_NAME%'" > "%TEMP%\lms_dbcheck.txt" 2>nul
set /p DB_EXISTS=<"%TEMP%\lms_dbcheck.txt"
if not "%DB_EXISTS%"=="1" (
  echo [..] Tao database "%DB_NAME%"...
  "%PSQL%" -h 127.0.0.1 -p %PG_PORT% -U postgres -c "CREATE DATABASE %DB_NAME%" >nul 2>&1
  if errorlevel 1 (
    echo [!] Khong tao duoc database. Kiem tra PGPASSWORD trong .env.
  ) else (
    echo [OK] Da tao database "%DB_NAME%".
  )
) else (
  echo [OK] Database "%DB_NAME%" da ton tai.
)
exit /b 0

:ensure_test_db
set "PSQL=psql"
where psql >nul 2>&1 || set "PSQL=C:\Program Files\PostgreSQL\18\bin\psql.exe"
if /i not "%PSQL%"=="psql" if not exist "%PSQL%" exit /b 0
"%PSQL%" -h 127.0.0.1 -p %PG_PORT% -U postgres -d postgres -tAc "SELECT 1 FROM pg_database WHERE datname='lms_test'" > "%TEMP%\lms_dbtest.txt" 2>nul
set /p TEST_EXISTS=<"%TEMP%\lms_dbtest.txt"
if not "%TEST_EXISTS%"=="1" (
  "%PSQL%" -h 127.0.0.1 -p %PG_PORT% -U postgres -c "CREATE DATABASE lms_test" >nul 2>&1
)
exit /b 0

rem --------------------------------------------------------------------------
:ensure_deps
%PY% -c "import flask, psycopg, jwt, bcrypt" >nul 2>&1
if errorlevel 1 (
  echo [..] Thieu thu vien Python, dang cai dat tu requirements.txt...
  %PY% -m pip install -r requirements.txt
  if errorlevel 1 (
    echo [x] Cai dat thu vien that bai. Kiem tra Python/pip.
    exit /b 1
  )
)
echo [OK] Thu vien Python da san sang.
exit /b 0

rem --------------------------------------------------------------------------
:run_app
echo.
echo [i] Backend + Frontend: http://127.0.0.1:%APP_PORT%
echo     (Flask phuc vu ca API lan giao dien; nhan Ctrl+C de dung)
start "" cmd /c "timeout /t 3 >nul & start "" http://127.0.0.1:%APP_PORT%"
%PY% -m flask --app app run --host 127.0.0.1 --port %APP_PORT%
goto :done

rem --------------------------------------------------------------------------
:is_port_open
powershell -NoProfile -Command "try{ $c=New-Object Net.Sockets.TcpClient; $c.Connect('127.0.0.1',%1); $c.Close(); exit 0 } catch { exit 1 }"
exit /b %errorlevel%

:fail
echo.
echo [x] Khoi dong that bai. Xem huong dan o tren.
endlocal
exit /b 1

:done
endlocal
exit /b 0
