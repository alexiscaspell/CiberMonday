@echo off
echo ========================================
echo Instalador del Servicio CiberMonday (EXE)
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

REM Verificar que existe el ejecutable
if not exist "CiberMondayService.exe" (
    echo ERROR: No se encontro CiberMondayService.exe
    echo Por favor compila primero el ejecutable usando build_exe.bat
    pause
    exit /b 1
)

echo Configurando firewall de Windows...
REM Intentar agregar regla del firewall usando Python si está disponible
python firewall_manager.py add 2>nul
if %errorLevel% neq 0 (
    echo ADVERTENCIA: No se pudo agregar la regla del firewall automáticamente.
    echo Puedes agregarla manualmente ejecutando: python firewall_manager.py add
    echo O desde PowerShell como administrador:
    echo netsh advfirewall firewall add rule name="CiberMonday Client UDP Discovery" dir=in action=allow protocol=UDP localport=5001 enable=yes
    echo.
)

echo Instalando servicio de Windows...
CiberMondayService.exe install

if %errorLevel% neq 0 (
    echo ERROR: No se pudo instalar el servicio
    pause
    exit /b 1
)

echo.
echo Iniciando servicio...
CiberMondayService.exe start

if %errorLevel% neq 0 (
    echo ERROR: No se pudo iniciar el servicio
    pause
    exit /b 1
)

echo.
echo ========================================
echo Servicio instalado exitosamente!
echo ========================================
echo.
echo El servicio se iniciara automaticamente al arrancar Windows.
echo Puedes gestionarlo desde "Servicios" (services.msc)
echo.
echo Comandos utiles:
echo   CiberMondayService.exe start    - Iniciar servicio
echo   CiberMondayService.exe stop     - Detener servicio
echo   CiberMondayService.exe restart  - Reiniciar servicio
echo   CiberMondayService.exe remove   - Desinstalar servicio
echo.
pause
