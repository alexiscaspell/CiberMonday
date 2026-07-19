@echo off
setlocal
cd /d "%~dp0\.."

echo ================================================
echo   CiberMonday Server — Android APK
echo ================================================

docker --version >nul 2>&1
if errorlevel 1 (
    echo [ERROR] Docker no esta instalado.
    exit /b 1
)
docker info >nul 2>&1
if errorlevel 1 (
    echo [ERROR] Docker no esta corriendo.
    exit /b 1
)

if not exist "docker\Dockerfile.android" (
    echo [ERROR] No se encontro docker\Dockerfile.android
    exit /b 1
)
if not exist "server\android" (
    echo [ERROR] No se encontro server\android\
    exit /b 1
)
if not exist "server\web\templates\index.html" (
    echo [ERROR] No se encontro server\web\templates\index.html
    exit /b 1
)

if not exist "dist" mkdir dist
docker rm -f cibermonday-android-builder >nul 2>&1

echo Construyendo imagen Docker...
docker build --platform linux/amd64 -t cibermonday-android-builder -f docker/Dockerfile.android .
if errorlevel 1 exit /b 1

docker create --name cibermonday-android-builder cibermonday-android-builder
docker cp cibermonday-android-builder:/app/app/build/outputs/apk/debug/app-debug.apk ./dist/CiberMondayServer.apk
if errorlevel 1 (
    docker rm cibermonday-android-builder >nul 2>&1
    exit /b 1
)
docker rm cibermonday-android-builder >nul

echo APK: %cd%\dist\CiberMondayServer.apk
echo Instalar: adb install dist\CiberMondayServer.apk
endlocal
