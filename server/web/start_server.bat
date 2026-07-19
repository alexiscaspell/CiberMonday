@echo off
REM Inicia el servidor web desde la raíz del repo
cd /d "%~dp0\..\.."
echo Iniciando servidor CiberMonday...
python server\web\app.py
pause
