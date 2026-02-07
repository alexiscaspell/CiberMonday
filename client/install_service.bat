@echo off
echo ========================================
echo Instalador del Servicio CiberMonday
echo (Version Python - requiere Python instalado)
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
echo [1/7] Instalando dependencias...
pip install pywin32 >nul 2>&1
if %errorLevel% equ 0 (
    echo    Dependencias instaladas.
) else (
    echo    ADVERTENCIA: Error al instalar pywin32. El servicio podria no funcionar.
)

echo.
echo [2/7] Configurando firewall de Windows...
python firewall_manager.py add
if %errorLevel% neq 0 (
    echo    ADVERTENCIA: No se pudo agregar la regla del firewall automaticamente.
    echo    Puedes agregarla manualmente ejecutando: python firewall_manager.py add
    echo.
)

REM Agregar regla del firewall para push notifications (puerto 5002)
netsh advfirewall firewall show rule name="CiberMonday Client Push Notifications" >nul 2>&1
if %errorLevel% neq 0 (
    netsh advfirewall firewall add rule name="CiberMonday Client Push Notifications" dir=in action=allow protocol=TCP localport=5002 enable=yes profile=any description="Permite que el cliente CiberMonday reciba push notifications de servidores" >nul 2>&1
    if %errorLevel% equ 0 (
        echo    Regla de push notifications agregada exitosamente.
    ) else (
        echo    ADVERTENCIA: No se pudo agregar regla de push notifications.
    )
) else (
    echo    Regla de push notifications ya existe.
)

echo.
echo [3/7] Instalando servicio de Windows...
python service.py install

if %errorLevel% neq 0 (
    echo ERROR: No se pudo instalar el servicio.
    echo Si el servicio ya existe, intenta: python service.py remove
    pause
    exit /b 1
)

echo.
echo [4/7] Configurando inicio automatico...
sc config CiberMondayClient start= auto >nul 2>&1
if %errorLevel% equ 0 (
    echo    Servicio configurado para inicio automatico.
) else (
    echo    ADVERTENCIA: No se pudo configurar inicio automatico.
)

echo.
echo [5/7] Configurando recuperacion automatica...
REM Si el servicio falla, reiniciar automaticamente:
REM   1ra falla: reiniciar en 5 segundos
REM   2da falla: reiniciar en 5 segundos
REM   Fallas subsiguientes: reiniciar en 5 segundos
REM   Resetear contador de fallas despues de 60 segundos sin fallas
sc failure CiberMondayClient reset= 60 actions= restart/5000/restart/5000/restart/5000 >nul 2>&1
if %errorLevel% equ 0 (
    echo    Recuperacion automatica configurada (reinicio en 5s tras falla).
) else (
    echo    ADVERTENCIA: No se pudo configurar recuperacion automatica.
)

echo.
echo [6/7] Restringiendo permisos del servicio...
REM Configurar Security Descriptor para restringir quien puede controlar el servicio:
REM   SY (SYSTEM): Control total
REM   BA (Built-in Administrators): Control total
REM   IU (Interactive Users): Solo lectura (no pueden detener/pausar/eliminar)
REM   SU (Service Users): Solo lectura
sc sdset CiberMondayClient D:(A;;CCLCSWRPWPDTLOCRRC;;;SY)(A;;CCDCLCSWRPWPDTLOCRSDRCWDWO;;;BA)(A;;CCLCSWLOCRRC;;;IU)(A;;CCLCSWLOCRRC;;;SU) >nul 2>&1
if %errorLevel% equ 0 (
    echo    Permisos del servicio restringidos (solo admin puede detenerlo).
) else (
    echo    ADVERTENCIA: No se pudieron restringir los permisos del servicio.
)

echo.
echo [7/7] Iniciando servicio...
python service.py start

if %errorLevel% neq 0 (
    echo ADVERTENCIA: No se pudo iniciar el servicio automaticamente.
    echo Intenta iniciarlo manualmente: net start CiberMondayClient
)

echo.
echo ========================================
echo Servicio instalado exitosamente!
echo ========================================
echo.
echo Protecciones activas:
echo   - Inicio automatico con Windows
echo   - Reinicio automatico si el servicio falla (cada 5 segundos)
echo   - Solo administradores pueden detener el servicio
echo   - Proteccion DACL contra terminacion del proceso
echo   - Watchdog interno reinicia el cliente si muere
echo.
echo El servicio se iniciara automaticamente al arrancar Windows.
echo Puedes gestionarlo desde "Servicios" (services.msc)
echo.
echo Comandos de administracion (requieren admin):
echo   net start CiberMondayClient    - Iniciar servicio
echo   net stop CiberMondayClient     - Detener servicio
echo   python service.py remove       - Desinstalar servicio
echo.
pause
