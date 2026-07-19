@echo off
setlocal
cd /d "%~dp0\.."

echo ================================================
echo   CiberMonday Client — Android APK
echo ================================================

where docker >nul 2>&1
if errorlevel 1 (
    echo Error: Docker no esta instalado.
    exit /b 1
)

if not exist docker\Dockerfile.android-client (
    echo No se encontro docker\Dockerfile.android-client
    exit /b 1
)
if not exist client\android (
    echo No se encontro client\android\
    exit /b 1
)

if not exist dist mkdir dist
docker rm -f cibermonday-android-client-builder 2>nul

echo Construyendo imagen Docker...
docker build --platform linux/amd64 -t cibermonday-android-client-builder -f docker/Dockerfile.android-client .
if errorlevel 1 exit /b 1

docker create --name cibermonday-android-client-builder cibermonday-android-client-builder
docker cp cibermonday-android-client-builder:/app/app/build/outputs/apk/debug/app-debug.apk ./dist/CiberMondayClient.apk
if errorlevel 1 (
    docker rm cibermonday-android-client-builder 2>nul
    exit /b 1
)
docker rm cibermonday-android-client-builder >nul

echo APK: %cd%\dist\CiberMondayClient.apk
echo Instalar: adb install dist\CiberMondayClient.apk
endlocal
