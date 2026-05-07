@echo off
REM Lanza Chrome de Windows con debugging port abierto + perfil dedicado.
REM Después en otro terminal:
REM   set NR_CDP_URL=http://localhost:9222
REM   python main.py -k "Jefe de Finanzas" -l "Lima, Peru"

setlocal

set PROFILE_DIR=%~dp0browser-profile-cdp
if not exist "%PROFILE_DIR%" mkdir "%PROFILE_DIR%"

REM Detectar Chrome.exe en ubicaciones comunes
set CHROME=
if exist "%ProgramFiles%\Google\Chrome\Application\chrome.exe" set CHROME=%ProgramFiles%\Google\Chrome\Application\chrome.exe
if exist "%ProgramFiles(x86)%\Google\Chrome\Application\chrome.exe" set CHROME=%ProgramFiles(x86)%\Google\Chrome\Application\chrome.exe
if exist "%LocalAppData%\Google\Chrome\Application\chrome.exe" set CHROME=%LocalAppData%\Google\Chrome\Application\chrome.exe

if "%CHROME%"=="" (
    echo ERROR: Chrome no encontrado en ubicaciones tipicas.
    echo Editá este script y ajustá la ruta de CHROME a mano.
    exit /b 1
)

echo Lanzando Chrome con debugging port 9222
echo Profile: %PROFILE_DIR%
echo.
echo Despues correr en OTRA terminal:
echo   set NR_CDP_URL=http://localhost:9222
echo   python main.py -k "Jefe de Finanzas" -l "Lima, Peru"
echo.

start "" "%CHROME%" --remote-debugging-port=9222 --user-data-dir="%PROFILE_DIR%" --no-first-run --no-default-browser-check
