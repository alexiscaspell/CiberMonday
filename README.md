<p align="center">
  <img src="resources/icono.png" alt="CiberMonday" width="120">
</p>

<h1 align="center">CiberMonday</h1>
<p align="center"><strong>Sistema distribuido de control de tiempo para cibercafés</strong></p>

<p align="center">
  Gestión centralizada del tiempo de uso en múltiples PCs, con bloqueo automático al expirar la sesión.<br>
  Servidor multiplataforma (Docker, Android, escritorio) y cliente Windows con servicio integrado.
</p>

---

## Componentes

| Componente | Descripción | Documentación |
|------------|-------------|---------------|
| **Servidor Web** | API REST + panel de administración (Flask) | [`server/README.md`](server/README.md) |
| **Cliente Windows** | Agente de monitoreo y bloqueo en cada PC | [`client/README.md`](client/README.md) |
| **App Android** | Servidor portátil para correr desde un celular | [`android/README.md`](android/README.md) |
| **Core** | Lógica de negocio compartida (servidor y Android) | `core/client_manager.py` |

---

## Arquitectura

```
                       ┌─────────────────────────────────┐
                       │    SERVIDOR CiberMonday          │
                       │    (Docker / Android / Manual)   │
                       │                                  │
                       │    Flask API  ─  Puerto 5000     │
                       │    Panel Web de Administración   │
                       └──────────────┬──────────────────┘
                                      │  HTTP / REST
                  ┌───────────────────┼───────────────────┐
                  │                   │                    │
           ┌──────▼──────┐    ┌──────▼──────┐    ┌───────▼─────┐
           │  Cliente     │    │  Cliente     │    │  Cliente     │
           │  Windows     │    │  Windows     │    │  Windows     │
           │  (Servicio)  │    │  (Servicio)  │    │  (Servicio)  │
           └──────────────┘    └──────────────┘    └──────────────┘
```

### Flujo

1. **Registro** — El cliente se registra automáticamente al iniciar.
2. **Asignación** — El administrador asigna tiempo desde el panel web.
3. **Sincronización** — El cliente sincroniza cada 30s y guarda la sesión en el registro de Windows.
4. **Monitoreo** — Lee el registro cada segundo para verificar expiración.
5. **Bloqueo** — Al expirar, desconecta la sesión del usuario. Si vuelve a conectarse, lo bloquea de nuevo.

---

## Inicio Rápido

### Servidor

```bash
# Con Docker (recomendado)
docker compose up -d

# O manual
pip install -r requirements.txt
cd server && python app.py
```

Panel web: `http://localhost:5000`

### Cliente Windows

```bash
# Desde ejecutables pre-compilados (ver Releases en GitHub)
# Ejecutar como Administrador:
install_exe_service.bat

# O desde código fuente:
pip install requests pywin32
cd client && python client.py
```

### Servidor Android

```bash
# Compilar APK con Docker
./build_android.sh

# Instalar
adb install dist/CiberMondayServer.apk
```

---

## Estructura del Proyecto

```
CiberMonday/
├── server/                         # Servidor Flask
│   ├── app.py                      # API y panel web
│   ├── templates/index.html        # Panel de administración
│   ├── Dockerfile
│   └── README.md
│
├── client/                         # Cliente Windows
│   ├── client.py                   # Monitoreo, bloqueo, sincronización
│   ├── service.py                  # Servicio de Windows
│   ├── watchdog.py                 # Watchdog de recuperación
│   ├── config_gui.py               # GUI de configuración
│   ├── registry_manager.py         # Registro de Windows
│   ├── firewall_manager.py         # Reglas de firewall
│   ├── protection.py               # Anti-tampering
│   ├── icon.ico                    # Ícono de los ejecutables
│   ├── build_exe.bat               # Compilación con PyInstaller
│   └── README.md
│
├── android/                        # App Android (servidor móvil)
│   ├── app/src/main/
│   │   ├── java/.../               # MainActivity, FlaskServerService (Kotlin)
│   │   ├── python/                 # Servidor Flask para Android (Chaquopy)
│   │   └── res/                    # Layouts, íconos, temas
│   └── README.md
│
├── core/                           # Lógica compartida
│   └── client_manager.py           # Gestión de clientes y sesiones
│
├── resources/                      # Assets fuente
│   └── icono.png                   # Logo de la aplicación
│
├── .github/workflows/              # GitHub Actions
│   ├── build-client.yml            # Compilar cliente Windows
│   ├── release-android-apk.yml     # Compilar APK Android
│   └── release-combined.yml        # Release combinado
│
├── docker-compose.yml              # Orquestación del servidor
├── Dockerfile.server               # Imagen del servidor
├── Dockerfile.android              # Imagen para compilar APK
├── Dockerfile.client               # Imagen para compilar EXE
├── requirements.txt                # Dependencias Python
├── diagnose_server.py              # Diagnóstico del servidor
├── diagnose_client.py              # Diagnóstico del cliente
└── README.md                       # Este archivo
```

---

## Configuración Avanzada

### Parámetros por cliente

Configurables desde el panel web o la API (`POST /api/client/<id>/config`):

| Parámetro | Rango | Default | Descripción |
|-----------|-------|---------|-------------|
| `lock_recheck_interval` | 1–60 s | 1 | Intervalo de re-verificación tras bloqueo |
| `max_server_timeouts` | 1–100 | 10 | Timeouts antes de considerar conexión perdida |

### Bloqueo desde Session 0

El cliente corre como servicio en Session 0 (aislado). Usa `WTSDisconnectSession` como fallback a `LockWorkStation` para bloquear la PC del usuario desde el servicio.

---

## Seguridad

> **Nota:** Diseñado para redes locales de confianza. Para entornos más exigentes:

- Autenticación en API y panel web
- HTTPS con certificados TLS
- Base de datos persistente
- Logging y auditoría

---

<p align="center">
  <img src="resources/icono.png" alt="CiberMonday" width="48"><br>
  <sub>CiberMonday — Control de tiempo para cibercafés</sub>
</p>
