@echo off
REM Cambiar al directorio donde esta el .bat
cd /d "%~dp0"

echo ========================================
echo  CiberMonday - Visor de Logs del Cliente
echo ========================================
echo.

if not exist "CiberMondayClient.log" (
    echo No se encontro el archivo de log.
    echo.
    echo El log se crea cuando el servicio inicia el cliente.
    echo Verifica que el servicio este corriendo:
    echo   sc query CiberMondayClient
    echo.
    pause
    exit /b 1
)

echo Archivo: %cd%\CiberMondayClient.log
echo Presiona Ctrl+C para salir.
echo.
echo ----------------------------------------
echo.

REM Mostrar las ultimas 50 lineas y seguir en tiempo real
powershell -Command "Get-Content -Path 'CiberMondayClient.log' -Tail 50 -Wait -Encoding UTF8"
