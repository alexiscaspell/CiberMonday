@echo off
REM Script para iniciar el servidor con Docker Compose en Windows

echo ========================================
echo Iniciando CiberMonday Server
echo ========================================
echo.

REM Verificar Docker
docker --version >nul 2>&1
if %errorLevel% neq 0 (
    echo ERROR: Docker no esta instalado
    echo Por favor instala Docker Desktop desde https://www.docker.com/
    pause
    exit /b 1
)

REM Verificar Docker Compose
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

REM Verificar modo
if "%1"=="dev" (
    echo Modo: Desarrollo (con hot-reload)
    %COMPOSE_CMD% -f docker-compose.dev.yml up --build
) else (
    echo Modo: Produccion
    %COMPOSE_CMD% up -d --build
    
    echo.
    echo ========================================
    echo Servidor iniciado!
    echo ========================================
    echo.
    echo El servidor esta corriendo en: http://localhost:5000
    echo.
    echo Comandos utiles:
    echo   %COMPOSE_CMD% logs -f          # Ver logs
    echo   %COMPOSE_CMD% stop             # Detener servidor
    echo   %COMPOSE_CMD% restart          # Reiniciar servidor
    echo   %COMPOSE_CMD% down             # Detener y eliminar contenedor
    echo.
    pause
)
