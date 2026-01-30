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

echo Deteniendo servicio...
python service.py stop

echo.
echo Desinstalando servicio...
python service.py remove

echo.
echo NOTA: La regla del firewall no se eliminará automáticamente.
echo Si deseas eliminarla, ejecuta: python firewall_manager.py remove

echo.
echo ========================================
echo Servicio desinstalado exitosamente!
echo ========================================
echo.
pause
