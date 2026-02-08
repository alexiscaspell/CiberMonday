<p align="center">
  <img src="../resources/icono.png" alt="CiberMonday" width="80">
</p>

# CiberMonday — Cliente Windows

Agente que corre en cada PC del cibercafé. Se conecta al servidor, recibe el tiempo asignado, y bloquea la PC automáticamente cuando la sesión expira.

## Características

- **Registro automático** — Al iniciar, se registra en el servidor enviando hostname e IP.
- **Sincronización periódica** — Consulta al servidor cada 30 segundos para obtener actualizaciones de tiempo.
- **Almacenamiento local** — Guarda sesión y configuración en el registro de Windows. Sigue funcionando si se corta la red.
- **Bloqueo desde Session 0** — Usa `WTSDisconnectSession` para bloquear la PC incluso corriendo como servicio de Windows.
- **Re-bloqueo inteligente** — Detecta si el usuario vuelve a conectarse y lo desconecta de nuevo (intervalo configurable).
- **Auto-descubrimiento** — Encuentra servidores en la red local vía broadcast UDP.
- **Servicio de Windows** — Se instala como servicio con recuperación automática.
- **Watchdog** — Proceso independiente que reinicia el cliente si se cae.
- **Protecciones** — Medidas anti-tampering para evitar que el usuario detenga el proceso.
- **GUI de configuración** — Ventana gráfica (tkinter) para ingresar la URL del servidor en la primera ejecución.

## Archivos

| Archivo | Descripción |
|---------|-------------|
| `client.py` | Lógica principal: monitoreo de tiempo, bloqueo, sincronización con servidor |
| `service.py` | Servicio de Windows: gestiona el ciclo de vida del cliente como servicio |
| `watchdog.py` | Watchdog independiente: reinicia el cliente si se cierra inesperadamente |
| `config_gui.py` | Ventana de configuración (tkinter) para la URL del servidor |
| `registry_manager.py` | Lectura/escritura del registro de Windows |
| `firewall_manager.py` | Configuración automática de reglas de firewall |
| `protection.py` | Protecciones anti-tampering (ocultar proceso, prevenir cierre) |
| `config.py` | Configuración legacy (no se usa en modo ejecutable) |
| `icon.ico` | Ícono de los ejecutables (generado desde `resources/icono.png`) |

### Scripts

| Script | Descripción |
|--------|-------------|
| `build_exe.bat` | Compila los 3 ejecutables con PyInstaller |
| `install_exe_service.bat` | Instala el servicio desde los ejecutables |
| `install_service.bat` | Instala el servicio desde código fuente |
| `uninstall_exe_service.bat` | Desinstala el servicio (ejecutables) |
| `uninstall_service.bat` | Desinstala el servicio (código fuente) |
| `start_client.bat` | Ejecuta el cliente directamente |
| `start_watchdog.bat` | Ejecuta el watchdog directamente |
| `show_logs.bat` | Muestra los logs del cliente |

## Instalación

### Opción 1: Ejecutables pre-compilados (recomendado)

Descargar desde **GitHub Releases** o compilar localmente:

```bash
cd client
build_exe.bat
```

Genera en `dist/`:

| Ejecutable | Descripción |
|------------|-------------|
| `CiberMondayClient.exe` | Cliente principal |
| `CiberMondayService.exe` | Servicio de Windows |
| `CiberMondayWatchdog.exe` | Watchdog de recuperación |

#### Instalar como servicio

```bash
# Copiar los .exe a la carpeta destino (ej: C:\CiberMonday\)
# Ejecutar como Administrador:
install_exe_service.bat
```

#### Ejecución directa (sin servicio)

```bash
# Como Administrador
CiberMondayClient.exe
```

### Opción 2: Desde código fuente

```bash
pip install requests pywin32

# Ejecución directa
python client.py

# O instalar como servicio
install_service.bat
```

## Configuración

### Primera ejecución

Al ejecutar el cliente por primera vez (en modo interactivo, no como servicio), se abre una ventana de configuración para ingresar la URL del servidor:

```
URL del Servidor: http://192.168.1.100:5000
```

La configuración se guarda en el registro de Windows y se usa en todas las ejecuciones posteriores.

### Registro de Windows

Toda la persistencia está en:

```
HKEY_LOCAL_MACHINE\SOFTWARE\CiberMonday
├── Config          JSON con server_url, client_id, etc.
├── SessionData     JSON con tiempo asignado, inicio, fin
└── ServerConfig    JSON con parámetros recibidos del servidor
```

### Parámetros configurables desde el servidor

El administrador puede ajustar estos parámetros por cliente desde el panel web:

| Parámetro | Rango | Default | Descripción |
|-----------|-------|---------|-------------|
| `lock_recheck_interval` | 1–60 s | 1 | Cada cuántos segundos re-verificar si el usuario se reconectó tras bloqueo |
| `max_server_timeouts` | 1–100 | 10 | Timeouts de sincronización antes de considerar conexión perdida |

## Mecanismo de bloqueo

El cliente soporta dos métodos de bloqueo:

1. **`LockWorkStation()`** — Método estándar. Solo funciona desde la sesión interactiva del usuario.
2. **`WTSDisconnectSession()`** — Fallback para Session 0. Desconecta la sesión activa del usuario desde el servicio.

### Flujo al expirar el tiempo

1. Se detecta que `remaining_seconds <= 0`.
2. Se llama a `lock_workstation()` (intenta método 1, luego método 2).
3. Se espera `lock_recheck_interval` segundos.
4. Se verifica si la sesión del usuario está activa (`WTSQuerySessionInformationW`).
5. Si el usuario se reconectó, se vuelve a bloquear. Si no, se espera.
6. El ciclo continúa hasta que el servidor asigne nuevo tiempo.

## Gestión del servicio

```bash
# Estado
sc query CiberMondayClient

# Control
CiberMondayService.exe start
CiberMondayService.exe stop
CiberMondayService.exe restart
CiberMondayService.exe remove
```

### Logs

```bash
# Ver logs en vivo
show_logs.bat

# Ubicación del log
%INSTALL_DIR%\cibermonday_client.log
```

## Solución de problemas

| Problema | Solución |
|----------|----------|
| No se conecta al servidor | Verificar URL en registro (`regedit` > `HKLM\SOFTWARE\CiberMonday\Config`). Verificar firewall puerto 5000. |
| No bloquea la PC | Verificar que corre como Administrador o como servicio. Verificar que el usuario tiene contraseña. |
| El servicio no se instala | Ejecutar como Administrador. Si ya existe: `CiberMondayService.exe remove` primero. |
| Sin logs al correr como servicio | El servicio pasa `--service` al cliente. Verificar que el log file se crea en el directorio de instalación. |
| Antivirus bloquea el .exe | Falso positivo de PyInstaller. Agregar excepción para la carpeta. |
| Tarda en bloquear tras expirar | Ajustar `lock_recheck_interval` a 1 segundo desde el panel web del servidor. |
