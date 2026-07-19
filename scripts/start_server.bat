@echo off
setlocal
cd /d "%~dp0\.."

echo ========================================
echo Iniciando CiberMonday Server
echo ========================================

docker --version >nul 2>&1
if %errorLevel% neq 0 (
    echo ERROR: Docker no esta instalado
    pause
    exit /b 1
)

docker compose version >nul 2>&1
if %errorLevel% neq 0 (
    docker-compose --version >nul 2>&1
    if %errorLevel% neq 0 (
        echo ERROR: Docker Compose no esta instalado
        pause
        exit /b 1
    )
    set COMPOSE_CMD=docker-compose
) else (
    set COMPOSE_CMD=docker compose
)

set COMPOSE_FILE=docker\docker-compose.yml
echo Modo: Produccion
%COMPOSE_CMD% -f %COMPOSE_FILE% up -d --build

echo.
echo Servidor en http://localhost:5000
echo Logs: %COMPOSE_CMD% -f %COMPOSE_FILE% logs -f
pause
endlocal
