<p align="center">
  <img src="../resources/icono.png" alt="CiberMonday" width="80">
</p>

# CiberMonday — App Android

Aplicación Android que ejecuta el servidor CiberMonday directamente desde un teléfono o tablet. Empaqueta el servidor Flask con [Chaquopy](https://chaquo.com/chaquopy/) y expone la misma interfaz web que la versión de escritorio.

## Características

- **Servidor Flask integrado** ejecutado con Chaquopy (Python en Android).
- **WebView nativo** que muestra el panel de administración.
- **Servicio en segundo plano** con notificación persistente.
- **Wake Lock** para mantener el servidor activo con pantalla apagada.
- **Misma interfaz y API** que el servidor de escritorio/Docker.

## Requisitos

### Para compilar

| Método | Requisitos |
|--------|-----------|
| Docker (recomendado) | Solo Docker instalado |
| Android Studio | JDK 17, Android SDK 34, Gradle 8.2+ |

### Para ejecutar

- Android 7.0 (API 24) o superior.
- Los clientes Windows deben estar en la misma red Wi-Fi que el dispositivo.

## Compilar el APK

### Con Docker (recomendado)

```bash
# Desde la raíz del proyecto CiberMonday

# Linux / macOS
./build_android.sh

# Windows
build_android.bat
```

El APK se genera en `dist/CiberMondayServer.apk`.

> La primera compilación tarda varios minutos (descarga Android SDK y dependencias Python).

### Con Android Studio

1. Abrir Android Studio y seleccionar **Open** > carpeta `android/`.
2. Esperar a que Gradle sincronice.
3. Conectar dispositivo o iniciar emulador.
4. Presionar **Run**.

### Línea de comandos (requiere Android SDK)

```bash
cd android
./gradlew assembleDebug   # Linux/macOS
gradlew.bat assembleDebug  # Windows
```

APK en `app/build/outputs/apk/debug/app-debug.apk`.

## Instalar

```bash
# Por USB con adb
adb install dist/CiberMondayServer.apk

# Si hay versión anterior con distinta firma
adb uninstall com.cibermonday.server
adb install dist/CiberMondayServer.apk
```

## Estructura

```
android/
├── app/src/main/
│   ├── java/com/cibermonday/server/
│   │   ├── MainActivity.kt            # WebView + gestión de permisos
│   │   ├── FlaskServerService.kt      # Servicio que ejecuta Flask
│   │   └── ClientAdapter.kt           # Adaptador de lista de clientes
│   ├── python/
│   │   ├── server_android.py           # Wrapper del servidor Flask
│   │   ├── cibermonday_android.py      # Lógica de gestión de clientes
│   │   └── templates/index.html        # Panel web (copia del servidor)
│   ├── res/
│   │   ├── layout/                     # Layouts XML
│   │   ├── mipmap-*/                   # Íconos del launcher (todas las densidades)
│   │   ├── drawable/                   # Drawables, ícono de notificación
│   │   └── values/                     # Strings, temas
│   └── AndroidManifest.xml
├── build.gradle                        # Config de Gradle + Chaquopy
├── settings.gradle
├── gradle.properties
└── README.md                           # Este archivo
```

## Permisos

| Permiso | Motivo |
|---------|--------|
| `INTERNET` | Servir peticiones HTTP |
| `ACCESS_WIFI_STATE` | Obtener la IP del dispositivo |
| `FOREGROUND_SERVICE` | Mantener el servidor activo |
| `WAKE_LOCK` | Evitar que el servidor se detenga con pantalla apagada |
| `POST_NOTIFICATIONS` (Android 13+) | Notificación del servicio |

## Notas

- El servidor usa el puerto **5000** por defecto.
- El servidor consume batería; es recomendable conectar el dispositivo a la corriente.
- Los templates HTML se copian desde `server/templates/` al compilar.
