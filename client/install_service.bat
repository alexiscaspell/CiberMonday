@echo off
echo ========================================
echo Instalador del Servicio CiberMonday
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

echo Verificando Python...
python --version >nul 2>&1
if %errorLevel% neq 0 (
    echo ERROR: Python no esta instalado o no esta en el PATH
    pause
    exit /b 1
)

echo.
echo Instalando dependencias...
pip install pywin32

echo.
echo Instalando servicio de Windows...
python service.py install

echo.
echo Iniciando servicio...
python service.py start

echo.
echo ========================================
echo Servicio instalado exitosamente!
echo ========================================
echo.
echo El servicio se iniciara automaticamente al arrancar Windows.
echo Puedes gestionarlo desde "Servicios" (services.msc)
echo.
echo Comandos utiles:
echo   python service.py start    - Iniciar servicio
echo   python service.py stop     - Detener servicio
echo   python service.py restart  - Reiniciar servicio
echo   python service.py remove   - Desinstalar servicio
echo.
pause
