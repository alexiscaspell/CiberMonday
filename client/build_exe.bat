@echo off
echo ========================================
echo Compilador de CiberMonday Client
echo ========================================
echo.

REM Verificar que Python está instalado
python --version >nul 2>&1
if %errorLevel% neq 0 (
    echo ERROR: Python no esta instalado o no esta en el PATH
    pause
    exit /b 1
)

echo Instalando PyInstaller...
pip install pyinstaller

echo.
echo Compilando cliente...
echo.

REM Compilar el cliente principal
pyinstaller --onefile ^
    --windowed ^
    --name "CiberMondayClient" ^
    --icon=NONE ^
    --add-data "config.py;." ^
    --hidden-import "winreg" ^
    --hidden-import "win32serviceutil" ^
    --hidden-import "win32service" ^
    --hidden-import "win32event" ^
    --hidden-import "servicemanager" ^
    --hidden-import "win32timezone" ^
    --hidden-import "protection" ^
    --hidden-import "registry_manager" ^
    client.py

if %errorLevel% neq 0 (
    echo.
    echo ERROR: La compilacion fallo
    pause
    exit /b 1
)

echo.
echo Compilando servicio...
echo.

REM Compilar el servicio (ya no necesita client.py como data, lanza CiberMondayClient.exe)
pyinstaller --onefile ^
    --windowed ^
    --name "CiberMondayService" ^
    --icon=NONE ^
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
    echo.
    echo ERROR: La compilacion del servicio fallo
    pause
    exit /b 1
)

echo.
echo Compilando watchdog...
echo.

REM Compilar el watchdog (ahora incluye protección DACL)
pyinstaller --onefile ^
    --windowed ^
    --name "CiberMondayWatchdog" ^
    --icon=NONE ^
    --hidden-import "winreg" ^
    --hidden-import "protection" ^
    --hidden-import "ctypes" ^
    --hidden-import "ctypes.wintypes" ^
    watchdog.py

if %errorLevel% neq 0 (
    echo.
    echo ERROR: La compilacion del watchdog fallo
    pause
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
echo Puedes copiar estos archivos a cualquier PC Windows.
echo.
pause
