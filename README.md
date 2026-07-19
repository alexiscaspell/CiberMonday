<p align="center">
  <img src="resources/icono.png" alt="CiberMonday" width="120">
</p>

<h1 align="center">CiberMonday</h1>
<p align="center"><strong>Sistema distribuido de control de tiempo para cibercafés</strong></p>

<p align="center">
  Gestión centralizada del tiempo de uso en PCs y teléfonos, con bloqueo automático al expirar la sesión.
</p>

---

## Estructura

```
CiberMonday/
├── docker/                 # Dockerfiles y docker-compose
├── scripts/                # Build, start y diagnóstico
├── server/
│   ├── web/                # API Flask + panel (static Expo)
│   ├── admin/              # Panel Expo (web + estilo Android)
│   ├── android/            # App Android (servidor portátil + WebView)
│   └── core/               # Lógica de negocio compartida
├── client/
│   ├── windows/            # Cliente Windows
│   ├── linux/              # Cliente Linux
│   └── android/            # Cliente Android (bloqueo)
├── resources/
├── requirements.txt
└── README.md
```

## Componentes

| Componente | Descripción | Docs |
|------------|-------------|------|
| **Servidor Web** | API REST + panel Expo | [`server/web/README.md`](server/web/README.md) |
| **Panel Admin** | UI Expo (web / WebView) | [`server/admin/README.md`](server/admin/README.md) |
| **Servidor Android** | Servidor en el teléfono | [`server/android/README.md`](server/android/README.md) |
| **Cliente Windows** | Agente PC | [`client/windows/README.md`](client/windows/README.md) |
| **Cliente Linux** | Agente Linux / systemd | [`client/linux/README.md`](client/linux/README.md) |
| **Cliente Android** | Agente teléfono (Kidslox-style) | [`client/android/README.md`](client/android/README.md) |
| **Core** | Lógica compartida servidor | `server/core/` |

---

## Inicio rápido

### Servidor (Docker)

```bash
./scripts/start_server.sh
# o: docker compose -f docker/docker-compose.yml up -d --build
```

Panel: `http://localhost:5000`

### Servidor sin Docker

```bash
./scripts/build_admin.sh   # genera server/web/static
./server/web/start_server.sh
```

### Cliente Windows

```bash
cd client/windows
build_exe.bat          # o GitHub Actions
install_exe_service.bat
```

### Cliente Linux

```bash
cd client/linux
sudo bash install_linux.sh
```

### APK servidor Android

```bash
./scripts/build_android.sh
adb install dist/CiberMondayServer.apk
```

### APK cliente Android

```bash
./scripts/build_android_client.sh
adb install dist/CiberMondayClient.apk
```

---

## Flujo

1. El cliente se registra en el servidor.
2. El admin asigna tiempo desde el panel.
3. Push a `:5002` + countdown local (funciona offline).
4. Al expirar, el cliente bloquea el dispositivo.

---

## Scripts útiles

| Script | Uso |
|--------|-----|
| `scripts/start_server.sh` | Levantar servidor Docker |
| `scripts/build_android.sh` | APK servidor Android |
| `scripts/build_android_client.sh` | APK cliente Android |
| `scripts/build_client.sh` | Cliente Windows vía Docker |
| `scripts/diagnose_server.py` | Diagnóstico de red del servidor |
| `scripts/diagnose_client.py` | Diagnóstico de red del cliente |
