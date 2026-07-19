@echo off
REM Compila el cliente Windows con PyInstaller
setlocal
cd /d "%~dp0\..\client\windows"

python --version >nul 2>&1
if %errorLevel% neq 0 (
    echo ERROR: Python no esta instalado
    exit /b 1
)

echo Instalando PyInstaller...
pip install pyinstaller

echo.
echo Compilando cliente...
pyinstaller --onefile ^
    --name "CiberMondayClient" ^
    --hidden-import "client_base" ^
    --hidden-import "client_windows" ^
    --hidden-import "winreg" ^
    --hidden-import "win32serviceutil" ^
    --hidden-import "win32service" ^
    --hidden-import "win32event" ^
    --hidden-import "servicemanager" ^
    --hidden-import "win32timezone" ^
    --hidden-import "protection" ^
    --hidden-import "registry_manager" ^
    --hidden-import "config_gui" ^
    --hidden-import "requests" ^
    --hidden-import "ctypes" ^
    --hidden-import "ctypes.wintypes" ^
    client.py
if %errorLevel% neq 0 exit /b 1

echo Compilando servicio...
pyinstaller --onefile ^
    --name "CiberMondayService" ^
    --add-data "config.py;." ^
    --hidden-import "winreg" ^
    --hidden-import "win32serviceutil" ^
    --hidden-import "win32service" ^
    --hidden-import "win32event" ^
    --hidden-import "servicemanager" ^
    --hidden-import "win32timezone" ^
    --hidden-import "protection" ^
    --hidden-import "firewall_manager" ^
    --hidden-import "ctypes" ^
    --hidden-import "ctypes.wintypes" ^
    service.py
if %errorLevel% neq 0 exit /b 1

echo Compilando watchdog...
pyinstaller --onefile ^
    --name "CiberMondayWatchdog" ^
    --hidden-import "winreg" ^
    --hidden-import "subprocess" ^
    watchdog.py
if %errorLevel% neq 0 exit /b 1

echo.
echo Compilacion completada. Ejecutables en: %cd%\dist
endlocal
