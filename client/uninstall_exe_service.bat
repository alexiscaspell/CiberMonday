@echo off
echo ========================================
echo Desinstalador del Servicio CiberMonday
echo ========================================
echo.

REM Verificar que se ejecuta como administrador
net session >nul 2>&1
if %errorLevel% neq 0 (
    echo ERROR: Este script debe ejecutarse como Administrador.
    echo Haz clic derecho en el archivo y selecciona "Ejecutar como administrador"
    pause
    exit /b 1
)

echo ATENCION: Esto desinstalara completamente el servicio CiberMonday.
echo El cliente dejara de ejecutarse y la PC ya no sera controlada.
echo.
set /p CONFIRM=Escribi SI para confirmar la desinstalacion: 
if /I not "%CONFIRM%"=="SI" (
    echo Desinstalacion cancelada.
    pause
    exit /b 0
)

echo.
echo [1/5] Desactivando recuperacion automatica...
REM Desactivar recovery para que no se reinicie mientras desinstalamos
sc failure CiberMondayClient reset= 0 actions= "" >nul 2>&1
echo    Recuperacion automatica desactivada.

echo.
echo [2/5] Deteniendo servicio...
net stop CiberMondayClient >nul 2>&1
if %errorLevel% equ 0 (
    echo    Servicio detenido.
) else (
    echo    El servicio no estaba corriendo o ya fue detenido.
)
REM Esperar a que el servicio termine completamente
timeout /t 3 /nobreak >nul 2>&1

REM Matar cualquier proceso residual del cliente
taskkill /F /IM CiberMondayClient.exe >nul 2>&1
taskkill /F /IM CiberMondayService.exe >nul 2>&1
taskkill /F /IM CiberMondayWatchdog.exe >nul 2>&1

echo.
echo [3/5] Eliminando servicio de Windows...
if exist "CiberMondayService.exe" (
    CiberMondayService.exe remove >nul 2>&1
)
REM Respaldo: usar sc delete directamente por si el EXE no funciona
sc delete CiberMondayClient >nul 2>&1
if %errorLevel% equ 0 (
    echo    Servicio eliminado del registro de Windows.
) else (
    echo    Servicio ya fue eliminado o no existia.
)

echo.
echo [4/5] Eliminando reglas del firewall...
netsh advfirewall firewall delete rule name="CiberMonday Client UDP Discovery" >nul 2>&1
if %errorLevel% equ 0 (
    echo    Regla de descubrimiento UDP eliminada.
) else (
    echo    Regla de descubrimiento UDP no existia.
)
netsh advfirewall firewall delete rule name="CiberMonday Client Push Notifications" >nul 2>&1
if %errorLevel% equ 0 (
    echo    Regla de push notifications eliminada.
) else (
    echo    Regla de push notifications no existia.
)

echo.
echo [5/5] Rehabilitando Task Manager (si fue deshabilitado)...
reg delete "HKCU\Software\Microsoft\Windows\CurrentVersion\Policies\System" /v DisableTaskMgr /f >nul 2>&1
echo    Task Manager rehabilitado.

echo.
echo ========================================
echo Servicio desinstalado exitosamente!
echo ========================================
echo.
echo El servicio CiberMonday ha sido removido completamente.
echo La PC ya no sera controlada por CiberMonday.
echo.
echo Nota: Los archivos ejecutables no fueron eliminados.
echo Puedes eliminar esta carpeta manualmente si lo deseas.
echo.
pause
