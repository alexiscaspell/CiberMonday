@echo off
REM Script para compilar el cliente CiberMonday como .exe en Windows
REM Este script puede ejecutarse directamente o desde Docker

cd client

REM Verificar Python
python --version >nul 2>&1
if %errorLevel% neq 0 (
    echo ERROR: Python no esta instalado
    exit /b 1
)

echo Instalando PyInstaller...
pip install pyinstaller

echo.
echo Compilando cliente...
echo.

REM Compilar el cliente principal
pyinstaller --onefile ^
    --name "CiberMondayClient" ^
    --add-data "config.py;." ^
    --hidden-import "winreg" ^
    --hidden-import "win32serviceutil" ^
    --hidden-import "win32service" ^
    --hidden-import "win32event" ^
    --hidden-import "servicemanager" ^
    --hidden-import "win32timezone" ^
    --hidden-import "protection" ^
    --hidden-import "registry_manager" ^
    --hidden-import "requests" ^
    --hidden-import "ctypes" ^
    --hidden-import "ctypes.wintypes" ^
    client.py

if %errorLevel% neq 0 (
    echo ERROR: La compilacion del cliente fallo
    exit /b 1
)

echo.
echo Compilando servicio...
echo.

REM Compilar el servicio
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

if %errorLevel% neq 0 (
    echo ERROR: La compilacion del servicio fallo
    exit /b 1
)

echo.
echo Compilando watchdog...
echo.

REM Compilar el watchdog
pyinstaller --onefile ^
    --name "CiberMondayWatchdog" ^
    --hidden-import "winreg" ^
    --hidden-import "subprocess" ^
    watchdog.py

if %errorLevel% neq 0 (
    echo ERROR: La compilacion del watchdog fallo
    exit /b 1
)

echo.
echo ========================================
echo Compilacion completada!
echo ========================================
echo.
echo Los ejecutables estan en la carpeta 'dist':
echo   - CiberMondayClient.exe
echo   - CiberMondayService.exe
echo   - CiberMondayWatchdog.exe
echo.
