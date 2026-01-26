@echo off
setlocal enabledelayedexpansion

echo ================================================
echo      CiberMonday Server - Android App
echo ================================================
echo Iniciando construccion del APK...
echo.

:: Verificar si Docker está instalado
docker --version >nul 2>&1
if errorlevel 1 (
    echo [ERROR] Docker no esta instalado.
    echo Por favor, instala Docker Desktop: https://docs.docker.com/desktop/windows/install/
    exit /b 1
)

:: Verificar que Docker esté corriendo
docker info >nul 2>&1
if errorlevel 1 (
    echo [ERROR] Docker no esta corriendo.
    echo Por favor, inicia Docker Desktop.
    exit /b 1
)

echo [OK] Docker esta instalado y corriendo

:: Verificar archivos necesarios
if not exist "Dockerfile.android" (
    echo [ERROR] No se encontro Dockerfile.android
    echo Asegurate de ejecutar este script desde la raiz del proyecto CiberMonday
    exit /b 1
)

if not exist "android" (
    echo [ERROR] No se encontro el directorio android/
    exit /b 1
)

if not exist "server\templates\index.html" (
    echo [ERROR] No se encontro server/templates/index.html
    exit /b 1
)

echo [OK] Archivos del proyecto verificados
echo.

:: Crear directorio de salida
if not exist "dist" mkdir dist

:: Limpiar contenedor anterior si existe
echo Limpiando builds anteriores...
docker rm -f cibermonday-android-builder >nul 2>&1

:: Construir la imagen Docker
echo.
echo Construyendo imagen Docker (esto puede tardar varios minutos la primera vez)...
echo    - Descargando Android SDK...
echo    - Instalando dependencias de Python (Chaquopy)...
echo    - Compilando Flask y dependencias...
echo.

docker build --platform linux/amd64 -t cibermonday-android-builder -f Dockerfile.android .
if errorlevel 1 (
    echo [ERROR] Error al construir la imagen Docker
    exit /b 1
)

echo.
echo [OK] Imagen Docker construida exitosamente

:: Crear contenedor temporal
echo Creando contenedor temporal...
docker create --name cibermonday-android-builder cibermonday-android-builder
if errorlevel 1 (
    echo [ERROR] Error al crear el contenedor temporal
    exit /b 1
)

:: Extraer el APK
echo Extrayendo el APK...
docker cp cibermonday-android-builder:/app/app/build/outputs/apk/debug/app-debug.apk ./dist/CiberMondayServer.apk
if errorlevel 1 (
    echo [ERROR] Error al extraer el APK
    docker rm cibermonday-android-builder >nul 2>&1
    exit /b 1
)

:: Limpiar contenedor temporal
echo Limpiando contenedor temporal...
docker rm cibermonday-android-builder >nul 2>&1

:: Verificar si el APK se generó
if exist "dist\CiberMondayServer.apk" (
    echo.
    echo ================================================
    echo APK generado exitosamente!
    echo ================================================
    echo.
    echo Archivo: %cd%\dist\CiberMondayServer.apk
    echo.
    echo Para instalar en tu dispositivo Android:
    echo   1. Conecta tu dispositivo por USB
    echo   2. Habilita 'Depuracion USB' en opciones de desarrollador
    echo   3. Ejecuta: adb install dist\CiberMondayServer.apk
    echo.
    echo O transfiere el APK a tu dispositivo y abrelo para instalar.
    echo.
) else (
    echo [ERROR] No se pudo generar el APK
    exit /b 1
)

endlocal
