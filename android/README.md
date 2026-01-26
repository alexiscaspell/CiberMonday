# CiberMonday Server - App Android

Aplicación Android que ejecuta el servidor CiberMonday y muestra la interfaz web en un WebView.

## Requisitos para compilar

### Opción Docker (Recomendada)
- Docker instalado y corriendo
- No necesitas Android Studio ni Java instalados

### Opción Android Studio
- Android Studio Arctic Fox (2020.3.1) o superior
- JDK 17
- Android SDK 34

### Para ejecutar la app
- Dispositivo Android 7.0 (API 24) o superior

## Cómo compilar

### Opción 1: Docker (Recomendada) 🐳

La forma más fácil de compilar sin instalar Android Studio.

```bash
# Desde la raíz del proyecto CiberMonday

# En Linux/Mac
./build_android.sh

# En Windows
build_android.bat
```

El APK se generará en `dist/CiberMondayServer.apk`

**Nota**: La primera compilación tarda varios minutos porque descarga el Android SDK y las dependencias de Python.

### Opción 2: Android Studio

1. Abre Android Studio
2. Selecciona "Open" y navega a la carpeta `android`
3. Espera a que Gradle sincronice el proyecto
4. Conecta un dispositivo Android o inicia un emulador
5. Presiona el botón "Run" (▶️)

### Opción 3: Línea de comandos (requiere Android SDK)

```bash
cd android

# En Linux/Mac
./gradlew assembleDebug

# En Windows
gradlew.bat assembleDebug
```

El APK se generará en `app/build/outputs/apk/debug/app-debug.apk`

## Características

- **Servidor Flask integrado**: Ejecuta el servidor Python usando Chaquopy
- **WebView nativo**: Muestra la misma interfaz web sin duplicar código
- **Servicio en segundo plano**: El servidor sigue corriendo aunque minimices la app
- **Notificación persistente**: Indica que el servidor está activo
- **Wake Lock**: Mantiene el servidor activo incluso con la pantalla apagada

## Estructura del proyecto

```
android/
├── app/
│   ├── src/main/
│   │   ├── java/com/cibermonday/server/
│   │   │   ├── MainActivity.kt       # Actividad principal con WebView
│   │   │   └── FlaskServerService.kt # Servicio que ejecuta Flask
│   │   ├── python/
│   │   │   ├── server_android.py     # Wrapper del servidor Flask
│   │   │   └── templates/            # Se copian automáticamente
│   │   ├── res/
│   │   │   ├── layout/
│   │   │   ├── values/
│   │   │   └── drawable/
│   │   └── AndroidManifest.xml
│   └── build.gradle
├── build.gradle
├── settings.gradle
└── gradle.properties
```

## Notas importantes

1. **Templates**: Los templates HTML se copian automáticamente desde `server/templates/` al compilar
2. **Puerto**: El servidor usa el puerto 5000 por defecto
3. **Red**: Los clientes deben estar en la misma red WiFi que el dispositivo Android
4. **Batería**: El servidor consume batería, considera conectar el dispositivo a la corriente

## Permisos requeridos

- `INTERNET`: Para servir peticiones HTTP
- `ACCESS_WIFI_STATE`: Para obtener la IP del dispositivo
- `FOREGROUND_SERVICE`: Para mantener el servidor activo
- `WAKE_LOCK`: Para evitar que el servidor se detenga con la pantalla apagada
- `POST_NOTIFICATIONS` (Android 13+): Para mostrar la notificación del servicio
