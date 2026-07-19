<p align="center">
  <img src="../../resources/icono.png" alt="CiberMonday" width="80">
</p>

# CiberMonday — Cliente Android

Agente para teléfonos/tablets Android. Se registra en el servidor CiberMonday, recibe tiempo por push, cuenta **offline** con reloj local y bloquea el dispositivo al expirar (estilo Kidslox: Device Admin + Accesibilidad + pantalla de bloqueo).

## Características

- Mismo protocolo que Windows/Linux: `register`, UDP discovery `:5001`, push HTTP `:5002`, `report-session`
- Sesión persistida en SharedPreferences — sigue contando sin internet
- Foreground Service con notificación persistente
- Bloqueo: `LockActivity` + Device Admin (`lockNow`) + Accessibility (re-bloqueo si el usuario escapa)
- Auto-inicio tras reinicio si el setup está completo

## Requisitos

| Método | Requisitos |
|--------|-----------|
| Docker (recomendado) | Solo Docker |
| Android Studio | JDK 17, Android SDK 34, Gradle 8+ |

Dispositivo: Android 7.0 (API 24)+. Misma red Wi‑Fi que el servidor.

## Compilar

Desde la raíz del repo:

```bash
./scripts/build_android_client.sh
# Windows: scripts/build_android_client.bat
```

APK: `dist/CiberMondayClient.apk`

Con Android Studio: abrir la carpeta `client/android/` y Run.

## Instalación en el teléfono

```bash
adb install dist/CiberMondayClient.apk
```

O copiá el APK y abrilo (fuentes desconocidas).

### Setup en el dispositivo

1. Activar **Device Admin**
2. Activar el servicio de **Accesibilidad** de CiberMonday
3. (Recomendado) Eximir de optimización de batería
4. Ingresar URL del servidor (`http://IP:5000`) o **Buscar en red**
5. **Guardar e iniciar**

El cliente aparece en el panel del servidor como cualquier PC.

## Uso

Desde el panel (servidor Docker, PC o app Android Server):

- **Asignar tiempo** → push a `:5002/api/push/session` → countdown local
- **Detener** → limpia sesión y quita el bloqueo
- Sin Wi‑Fi: el tiempo sigue bajando; al llegar a 0 se bloquea igual

## Limitaciones (v1 Kidslox-style)

No es Device Owner / kiosk empresarial. Un usuario avanzado puede intentar salir con ADB, modo seguro o reset. Suficiente para control de tiempo típico; no a prueba de root.

## Arquitectura

```
client/android/app/src/main/java/com/cibermonday/client/
  ui/          SetupActivity, StatusActivity, LockActivity
  service/     ClientService (FGS), BootReceiver
  net/         ApiClient, DiscoveryListener, PushServer (NanoHTTPD)
  session/     SessionStore
  lock/        DeviceAdminReceiver, LockAccessibilityService, LockController
```

Puertos en el teléfono:

| Puerto | Uso |
|--------|-----|
| 5002 TCP | Push / diagnóstico (debe ser alcanzable desde el servidor en LAN) |
| 5001 UDP | Escucha broadcasts de discovery del servidor |

## Diferencia con `server/android/`

| Carpeta | Rol |
|---------|-----|
| `server/android/` | **Servidor** portátil (panel + API) |
| `client/android/` | **Cliente** que se bloquea |
