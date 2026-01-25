# 🖥️ CiberMonday - Sistema de Control de Tiempo para Cibercafés

Sistema de gestión de tiempo de uso para múltiples clientes, similar a los software de cibercafés tradicionales.

## 📋 Tabla de Contenidos

- [Arquitectura](#arquitectura)
- [Instalación del Servidor](#instalación-del-servidor)
- [Instalación del Cliente](#instalación-del-cliente)
  - [Guía Detallada de Instalación del Cliente](client/GUIA_INSTALACION.md)
- [Guía de Uso](#guía-de-uso)
- [Características](#características)
- [Solución de Problemas](#solución-de-problemas)

## 🏗️ Arquitectura

```
┌─────────────────────────────────────────────────────────────┐
│                    SERVIDOR CiberMonday                     │
│  ┌──────────────────────────────────────────────────────┐   │
│  │  Flask API (Puerto 5000)                            │   │
│  │  • Gestión de clientes                              │   │
│  │  • Asignación de tiempos                            │   │
│  │  • Panel web de control                             │   │
│  └──────────────────────────────────────────────────────┘   │
│                          │                                   │
│                          │ HTTP/REST API                     │
│                          │                                   │
└──────────────────────────┼───────────────────────────────────┘
                           │
         ┌─────────────────┼─────────────────┐
         │                 │                 │
    ┌────▼────┐      ┌────▼────┐      ┌────▼────┐
    │ Cliente │      │ Cliente │      │ Cliente │
    │  PC-01  │      │  PC-02  │      │  PC-03  │
    └────┬────┘      └────┬────┘      └────┬────┘
         │                 │                 │
    ┌────▼─────────────────▼─────────────────▼────┐
    │  • Registro en Windows                        │
    │  • Monitoreo de tiempo                        │
    │  • Bloqueo automático                         │
    └──────────────────────────────────────────────┘
```

### Flujo de Funcionamiento

```
1. CLIENTE SE REGISTRA
   ┌─────────────┐         ┌─────────────┐
   │   Cliente   │─────────▶│  Servidor   │
   │  (Windows)  │  POST    │   (Flask)   │
   │             │◀─────────│             │
   └─────────────┘  ClientID └─────────────┘

2. ADMINISTRADOR ASIGNA TIEMPO
   ┌─────────────┐         ┌─────────────┐
   │  Admin Web  │────────▶│  Servidor   │
   │  Interface  │  POST   │             │
   └─────────────┘         └──────┬──────┘
                                  │
                                  │ Sincroniza cada 30s
                                  ▼
                           ┌─────────────┐
                           │   Cliente   │
                           │  Guarda en │
                           │  Registro  │
                           └──────┬──────┘

3. CLIENTE MONITOREA Y BLOQUEA
   ┌─────────────┐
   │   Cliente   │───Lee registro cada 1s───▶ Tiempo expira?
   │             │                              │
   └─────────────┘                              │
                                                ▼
                                         ┌──────────────┐
                                         │ Bloquea PC   │
                                         │ (Windows+L)  │
                                         └──────────────┘
```

## 🚀 Instalación del Servidor

### Opción 1: Con Docker Compose (⭐ RECOMENDADO)

#### Paso 1: Verificar Docker
```bash
docker --version
docker compose version
```

#### Paso 2: Iniciar el Servidor
```bash
# Linux/macOS
./start_server.sh

# Windows
start_server.bat

# O directamente
docker compose up -d
```

#### Paso 3: Verificar que está corriendo
```bash
# Ver logs
docker compose logs -f

# Verificar estado
docker compose ps

# Probar el servidor
curl http://localhost:5000/api/health
```

**Resultado esperado:**
```
✅ Servidor corriendo en: http://localhost:5000
✅ Panel web disponible en: http://localhost:5000
```

### Opción 2: Instalación Manual

#### Paso 1: Instalar Dependencias
```bash
pip install Flask flask-cors
```

#### Paso 2: Ejecutar el Servidor
```bash
cd server
python app.py
```

**Salida esperada:**
```
==================================================
Servidor CiberMonday iniciado
==================================================
API disponible en: http://0.0.0.0:5000
Endpoints disponibles:
  POST   /api/register - Registrar nuevo cliente
  GET    /api/clients - Listar todos los clientes
  POST   /api/client/<id>/set-time - Establecer tiempo
  GET    /api/client/<id>/status - Estado del cliente
  POST   /api/client/<id>/stop - Detener sesión (deshabilitar bloqueo)
  DELETE /api/client/<id> - Eliminar cliente
==================================================
```

### 🖥️ Panel Web de Control

Una vez iniciado el servidor, abre tu navegador en:

```
http://localhost:5000
```

**Vista del Panel:**
```
┌─────────────────────────────────────────────────────┐
│  🖥️ CiberMonday - Panel de Control                │
├─────────────────────────────────────────────────────┤
│  Servidor: http://192.168.1.100:5000  [Copiar]    │
│  Servidor Activo  │  Clientes: 3                   │
├─────────────────────────────────────────────────────┤
│                                                    │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────┐ │
│  │ PC-01       │  │ PC-02       │  │ PC-03    │ │
│  │ ID: abc123  │  │ ID: def456  │  │ ID: ghi789│ │
│  │             │  │             │  │          │ │
│  │ Tiempo:     │  │ Tiempo:     │  │ Esperando│ │
│  │ 45m 30s     │  │ 1h 15m      │  │          │ │
│  │             │  │             │  │          │ │
│  │ [Establecer]│  │ [Establecer]│  │ [Establecer]│
│  │ [Detener]   │  │ [Detener]   │  │          │ │
│  │ [⚙️ Config] │  │ [⚙️ Config] │  │          │ │
│  └──────────────┘  └──────────────┘  └──────────┘ │
│                                                    │
└─────────────────────────────────────────────────────┘
```

**Características del Panel Web:**
- ✅ **Actualización en tiempo real** - El tiempo restante se actualiza sin recargar la página
- ✅ **Información del servidor** - Muestra la URL/IP del servidor para fácil configuración de clientes
- ✅ **Configuración de clientes** - Botón ⚙️ Config para ajustar parámetros desde el servidor
- ✅ **Estado de tiempo deshabilitado** - Muestra claramente cuando el bloqueo está desactivado
- ✅ **Persistencia** - Los clientes y sesiones se mantienen después de reiniciar el servidor

## 💻 Instalación del Cliente

> 📖 **Para una guía detallada paso a paso, consulta:** [`client/GUIA_INSTALACION.md`](client/GUIA_INSTALACION.md)

### Resumen Rápido

#### Opción 1: Ejecutables Pre-compilados (⭐ RECOMENDADO)

1. **Descargar Release:**
   - Ve a **Releases** en GitHub y descarga la última versión
   - O compila desde **Actions** → **Build Windows Client**

2. **Extraer archivos** en una carpeta (ej: `C:\CiberMonday\`)

3. **Ejecutar como Administrador:**
   ```bash
   CiberMondayClient.exe
   ```

4. **Configurar:**
   - Se abrirá una ventana GUI automáticamente
   - Ingresa la URL del servidor (ej: `http://192.168.1.100:5000`)
   - Haz clic en "Guardar y Continuar"

5. **Instalar como Servicio (Opcional pero recomendado):**
   ```bash
   install_exe_service.bat
   ```

**Archivos incluidos:**
```
📦 Release
├── 📄 CiberMondayClient.exe      (Cliente principal)
├── 📄 CiberMondayService.exe     (Servicio Windows)
├── 📄 CiberMondayWatchdog.exe    (Watchdog)
└── 📄 install_exe_service.bat    (Instalador)
```

#### Opción 2: Desde Código Fuente

1. **Copiar carpeta `client`** a la PC Windows
2. **Instalar dependencias:**
   ```bash
   pip install requests pywin32
   ```
3. **Ejecutar:**
   ```bash
   python client.py
   ```
   - Se abrirá la GUI de configuración automáticamente
4. **O instalar como servicio:**
   ```bash
   install_service.bat
   ```

### Características de la Configuración

- ✅ **Interfaz gráfica integrada** - No necesitas editar archivos
- ✅ **Configuración persistente** - Se guarda en el Registro de Windows
- ✅ **Reconfigurable** - La ventana aparece cada vez que ejecutas el cliente
- ✅ **Sin `config.py`** - Todo se gestiona desde la GUI
- ✅ **Parámetros avanzados configurables**:
  - Intervalo de sincronización con servidor (default: 30s)
  - Intervalo de verificación local (default: 1s)
  - Intervalo de sincronización cuando tiempo expirado (default: 2s)
  - Tiempo de espera antes de bloquear (default: 2s)
  - Umbrales de notificación en minutos (default: 10, 5, 2, 1)
- ✅ **Sincronización bidireccional** - El servidor puede actualizar la configuración del cliente
- ✅ **Actualización optimizada** - Solo se actualiza cuando hay cambios reales

### Verificación

Una vez instalado, el cliente mostrará:
```
==================================================
Cliente CiberMonday iniciado
==================================================
ID del cliente: abc123-def456-ghi789
Servidor: http://192.168.1.100:5000
Modo: Registro local (funciona sin conexión continua)
Esperando asignación de tiempo...
==================================================
```

**El cliente aparecerá automáticamente en el panel web del servidor.**

## 📖 Guía de Uso

### 🎯 Escenario Completo: De Cero a Funcionando

#### 1️⃣ Iniciar el Servidor

```bash
# Con Docker
docker compose up -d

# O manualmente
cd server && python app.py
```

**Verificar:**
- Abre `http://localhost:5000` en el navegador
- Deberías ver el panel de control

#### 2️⃣ Instalar Cliente en PC Windows

> 📖 **Consulta la guía detallada:** [`client/GUIA_INSTALACION.md`](client/GUIA_INSTALACION.md)

**Resumen rápido:**
1. Descargar release de GitHub o compilar desde código fuente
2. Ejecutar `CiberMondayClient.exe` como Administrador
3. Configurar URL del servidor en la ventana GUI que aparece automáticamente
4. (Opcional) Instalar como servicio con `install_exe_service.bat`

El cliente se registrará automáticamente en el servidor y aparecerá en el panel web.

#### 3️⃣ Asignar Tiempo desde el Panel Web

1. Abre `http://TU_IP_SERVIDOR:5000`
2. Verás el cliente recién registrado
3. Ingresa tiempo (ej: 60 minutos)
4. Haz clic en "Establecer Tiempo"

**Vista en el Panel:**
```
┌─────────────────────────────────┐
│ PC-01 (abc123-def456)          │
│                                 │
│ Tiempo asignado: 60 minutos    │
│ Tiempo restante: 59m 45s       │
│ Estado: Activo                 │
│                                 │
│ [Establecer Tiempo]             │
│ [Detener] [Eliminar]            │
│ [⚙️ Config]                    │
└─────────────────────────────────┘
```

**Después de presionar "Detener":**
```
┌─────────────────────────────────┐
│ PC-01 (abc123-def456)          │
│                                 │
│ Estado: Tiempo deshabilitado   │
│ Bloqueo: Desactivado           │
│ Cliente: Activo y conectado    │
│                                 │
│ [Establecer Tiempo]             │
│ [Eliminar]                      │
│ [⚙️ Config]                    │
└─────────────────────────────────┘
```

**Vista en el Cliente:**
```
Tiempo restante: 59m 45s
Tiempo restante: 59m 44s
Tiempo restante: 59m 43s
...

[Cuando quedan 10 minutos]
¡Atención!
Quedan 10 minutos de tiempo
[Entendido]

[Cuando quedan 5 minutos]
¡Atención!
Quedan 5 minutos de tiempo
[Entendido]

[Cuando quedan 2 minutos]
¡Atención!
Quedan 2 minutos de tiempo
[Entendido]

[Cuando quedan 1 minuto]
¡Atención!
Queda 1 minuto de tiempo
[Entendido]
```

#### 4️⃣ Cuando Expira el Tiempo

**En el Cliente:**
```
==================================================
¡TIEMPO AGOTADO!
La PC se bloqueará continuamente hasta que se asigne nuevo tiempo.
==================================================
```

**Notificaciones de Tiempo:**
- El cliente muestra alertas visuales cuando quedan 10, 5, 2 y 1 minutos
- Las notificaciones son descartables y solo se muestran una vez por umbral

**En Windows:**
- La pantalla se bloquea automáticamente (Windows+L)
- Si el usuario desbloquea, se vuelve a bloquear según el intervalo configurado
- Continúa bloqueando hasta que se asigne nuevo tiempo
- El cliente sincroniza frecuentemente con el servidor para detectar nuevo tiempo asignado

#### 5️⃣ Detener Sesión (Tiempo Deshabilitado)

**Desde el Panel Web:**
- Haz clic en "Detener" en la tarjeta del cliente
- El cliente recibirá tiempo "infinito" (bloqueo deshabilitado)
- El cliente permanecerá **activo** y visible en el panel
- El cliente mostrará: "Estado: Tiempo deshabilitado (sin límite) - Cliente activo"
- La PC **NO se bloqueará** automáticamente

**Para re-habilitar el bloqueo:**
- Simplemente asigna nuevo tiempo desde el panel web
- El bloqueo volverá a funcionar normalmente

### ⚙️ Configuración Avanzada

#### Desde la GUI del Cliente

Al ejecutar el cliente, la ventana de configuración permite ajustar:

- **URL del Servidor**: Dirección del servidor CiberMonday
- **Intervalo de Sincronización**: Cada cuántos segundos sincroniza con el servidor (default: 30s)
- **Intervalo de Verificación Local**: Cada cuántos segundos verifica el tiempo local (default: 1s)
- **Intervalo de Sincronización (Tiempo Expirado)**: Cada cuántos segundos sincroniza cuando el tiempo expiró (default: 2s)
- **Tiempo de Espera Antes de Bloquear**: Segundos de espera antes de bloquear la PC (default: 2s)
- **Umbrales de Notificación**: Minutos en los que mostrar alertas (default: 10, 5, 2, 1)

#### Desde el Panel Web del Servidor

1. Haz clic en el botón **⚙️ Config** en la tarjeta del cliente
2. Se abrirá un modal con los parámetros configurables
3. Modifica los valores deseados
4. Haz clic en "Guardar Configuración"
5. El cliente recibirá y aplicará la configuración en la próxima sincronización

**Nota:** La configuración solo se actualiza cuando hay cambios reales, optimizando el rendimiento.

### 🔧 Gestión del Servicio

**Ver estado del servicio:**
```bash
# Desde servicios.msc
# Buscar "CiberMonday Client Service"

# O desde línea de comandos
sc query CiberMondayClient
```

**Comandos útiles:**
```bash
# Iniciar servicio
CiberMondayService.exe start

# Detener servicio
CiberMondayService.exe stop

# Reiniciar servicio
CiberMondayService.exe restart

# Desinstalar servicio
CiberMondayService.exe remove
```

### 📊 API del Servidor

#### Registrar Cliente (Automático)
El cliente se registra automáticamente al iniciar.

#### Listar Clientes
```bash
curl http://localhost:5000/api/clients
```

**Respuesta:**
```json
{
  "success": true,
  "clients": [
    {
      "id": "abc123-def456",
      "name": "PC-01",
      "is_active": true,
      "current_session": {
        "time_limit": 3600,
        "remaining_seconds": 3545
      }
    }
  ]
}
```

#### Establecer Tiempo
```bash
curl -X POST http://localhost:5000/api/client/abc123-def456/set-time \
  -H "Content-Type: application/json" \
  -d '{"time": 60, "unit": "minutes"}'
```

#### Detener Sesión (Deshabilitar Bloqueo)
```bash
curl -X POST http://localhost:5000/api/client/abc123-def456/stop
```

**Respuesta:**
```json
{
  "success": true,
  "message": "Bloqueo de tiempo deshabilitado. Cliente permanece activo sin límite de tiempo.",
  "session": {
    "time_limit_seconds": 999999999,
    "time_disabled": true
  }
}
```

#### Ver Estado
```bash
curl http://localhost:5000/api/client/abc123-def456/status
```

**Respuesta (con tiempo deshabilitado):**
```json
{
  "success": true,
  "client": {
    "id": "abc123-def456",
    "name": "PC-01",
    "is_active": true,
    "time_disabled": true,
    "session": {
      "time_limit_seconds": 999999999,
      "remaining_seconds": 999999999,
      "time_disabled": true,
      "is_expired": false
    }
  }
}
```

#### Configurar Cliente desde Servidor
```bash
curl -X POST http://localhost:5000/api/client/abc123-def456/config \
  -H "Content-Type: application/json" \
  -d '{
    "sync_interval": 60,
    "local_check_interval": 2,
    "expired_sync_interval": 3,
    "lock_delay": 5,
    "warning_thresholds": [15, 10, 5]
  }'
```

#### Obtener Información del Servidor
```bash
curl http://localhost:5000/api/server-info
```

**Respuesta:**
```json
{
  "success": true,
  "hostname": "servidor-pc",
  "ip_addresses": ["192.168.1.100", "10.0.0.5"],
  "primary_ip": "192.168.1.100",
  "port": "5000",
  "server_url": "http://192.168.1.100:5000",
  "display_url": "http://192.168.1.100:5000"
}
```

## 🔒 Cómo Funciona el Bloqueo

### Sistema de Registro Local

```
┌─────────────────────────────────────────────────┐
│  SERVIDOR                                       │
│  ┌───────────────────────────────────────────┐  │
│  │ Tiempo asignado: 60 minutos              │  │
│  │ Inicio: 10:00                            │  │
│  │ Fin: 11:00                               │  │
│  │ time_disabled: false                     │  │
│  └───────────────────────────────────────────┘  │
│  ┌───────────────────────────────────────────┐  │
│  │ Persistencia: server_data.json           │  │
│  │ • Clientes registrados                    │  │
│  │ • Sesiones activas                       │  │
│  └───────────────────────────────────────────┘  │
└───────────────────┬─────────────────────────────┘
                    │
                    │ Sincroniza cada 30s
                    │ (o cada 2s si expirado)
                    ▼
┌─────────────────────────────────────────────────┐
│  CLIENTE (Windows)                              │
│  ┌───────────────────────────────────────────┐  │
│  │ Registro: HKEY_LOCAL_MACHINE\...          │  │
│  │ • SessionData: {tiempo, inicio, fin,      │  │
│  │                time_disabled}             │  │
│  │ • ClientID: abc123-def456                 │  │
│  │ • Config: {sync_interval, thresholds...} │  │
│  └───────────────────────────────────────────┘  │
│                    │                              │
│                    │ Lee cada 1s                  │
│                    ▼                              │
│         ┌──────────────────────┐                 │
│         │ ¿time_disabled?       │                 │
│         └──────┬───────────────┘                 │
│                │                                  │
│         ┌──────▼───────┐                         │
│         │ ¿Tiempo      │                         │
│         │ expirado?    │                         │
│         └──────┬───────┘                         │
│                │                                  │
│         ┌──────▼───────┐                         │
│         │ Bloquear PC  │                         │
│         │ LockWorkStation()                      │
│         └──────────────┘                         │
└─────────────────────────────────────────────────┘
```

### Ventajas del Sistema

✅ **Funciona sin conexión continua**
- Lee del registro local cada segundo
- Sincroniza con servidor cada 30 segundos (configurable)
- Sincroniza cada 2 segundos cuando el tiempo está expirado

✅ **Resistente a cortes**
- Si se corta la red, sigue funcionando
- Usa el tiempo almacenado en el registro
- Re-registra automáticamente si el servidor lo pierde

✅ **Eficiente**
- Menor carga en el servidor
- Verificación rápida local
- Solo actualiza configuración cuando hay cambios del servidor

✅ **Persistente**
- El servidor guarda clientes y sesiones en disco
- Sobrevive a reinicios del servidor
- Recupera sesiones activas automáticamente

✅ **Configurable**
- Parámetros ajustables desde GUI del cliente
- Configuración push desde el servidor
- Umbrales de notificación personalizables

## ✨ Características

- ✅ **Gestión centralizada** de múltiples clientes
- ✅ **Interfaz web moderna** y fácil de usar con actualizaciones en tiempo real (AJAX)
- ✅ **Asignación de tiempo** en minutos u horas
- ✅ **Bloqueo automático** de Windows cuando expira
- ✅ **Sistema de registro local** - Funciona sin conexión continua
- ✅ **Resistente a cortes** - Lee del registro cada segundo
- ✅ **Sincronización eficiente** - Solo consulta servidor cada 30s
- ✅ **Sincronización optimizada** - Solo actualiza configuración cuando hay cambios
- ✅ **Re-registro automático** - Si el servidor pierde un cliente, se re-registra automáticamente
- ✅ **Recuperación de sesiones** - El servidor recupera sesiones activas después de reiniciar
- ✅ **Tiempo deshabilitado** - Función "Detener" establece tiempo infinito manteniendo cliente activo
- ✅ **Configuración avanzada** - Parámetros configurables desde GUI y servidor:
  - Intervalo de sincronización
  - Intervalo de verificación local
  - Intervalo de sincronización cuando expira
  - Tiempo de espera antes de bloquear
  - Umbrales de notificación personalizables
- ✅ **Notificaciones visuales** - Alertas cuando quedan 10, 5, 2 o 1 minutos
- ✅ **Persistencia de datos** - El servidor guarda clientes y sesiones en disco
- ✅ **Información del servidor** - Muestra IP/URL del servidor en el panel web
- ✅ **Compilación como .exe** - Ejecutables standalone
- ✅ **Servicio de Windows** - Inicio automático
- ✅ **API REST** para integración

## 🛠️ Solución de Problemas

### ❌ El servidor no inicia con Docker

**Síntomas:**
```
Error: port 5000 is already in use
```

**Solución:**
```bash
# Ver qué está usando el puerto
# Windows
netstat -ano | findstr :5000

# Linux/macOS
lsof -i :5000

# Cambiar puerto en docker-compose.yml
ports:
  - "8080:5000"  # Puerto externo:interno
```

### ❌ El cliente no se conecta al servidor

**Síntomas:**
```
Error de conexión al servidor: Connection refused
```

**Solución:**
1. Verifica que el servidor esté corriendo:
   ```bash
   curl http://TU_IP_SERVIDOR:5000/api/health
   ```

2. Verifica la configuración en el registro de Windows:
   - Abre `regedit`
   - Ve a `HKEY_LOCAL_MACHINE\SOFTWARE\CiberMonday`
   - Verifica el valor `Config` (debe contener la URL del servidor)
   - O ejecuta el cliente nuevamente para reconfigurar

3. Verifica firewall:
   ```bash
   # Windows: Permitir puerto 5000 en firewall
   # Linux: sudo ufw allow 5000
   ```

### ❌ El bloqueo no funciona

**Síntomas:**
- El cliente corre pero no bloquea cuando expira el tiempo

**Solución:**
1. Ejecuta como Administrador:
   ```bash
   # Clic derecho → Ejecutar como administrador
   CiberMondayClient.exe
   ```

2. Verifica permisos de bloqueo:
   ```bash
   # Probar manualmente
   # Presiona Windows+L
   ```

3. Verifica que el usuario tenga contraseña configurada

### ❌ El servicio no se instala

**Síntomas:**
```
ERROR: No se pudo instalar el servicio
```

**Solución:**
1. Ejecuta como Administrador
2. Verifica que pywin32 esté instalado:
   ```bash
   pip install pywin32
   ```
3. Verifica permisos de administrador:
   ```bash
   net session
   ```

### ❌ El cliente aparece como inactivo después de eliminarlo

**Síntomas:**
- Eliminas un cliente desde el servidor
- El cliente se reconecta pero aparece como inactivo

**Solución:**
- Esto es normal. El cliente se re-registra automáticamente y recupera su sesión local si tiene tiempo asignado
- El cliente aparecerá como activo en la próxima sincronización (máximo 30 segundos)
- Si tiene sesión local activa, se recuperará automáticamente

### ❌ La configuración del servidor no se aplica en el cliente

**Síntomas:**
- Cambias configuración desde el servidor pero el cliente no la aplica

**Solución:**
1. Verifica que el cliente esté sincronizando con el servidor (cada 30s por defecto)
2. Revisa los logs del cliente para ver mensajes como:
   ```
   [Configuración] Configuración sincronizada desde el servidor
   ```
3. La configuración solo se actualiza cuando hay cambios reales
4. Puedes verificar la configuración actual del cliente desde el panel web (botón ⚙️ Config)

## 📁 Estructura del Proyecto

```
CiberMonday/
├── server/                    # Servidor Flask
│   ├── app.py                # API principal
│   ├── templates/
│   │   └── index.html       # Panel web (con AJAX y configuración)
│   ├── server_data.json     # Persistencia de datos (generado)
│   └── start_server.*        # Scripts de inicio
│
├── client/                    # Cliente Windows
│   ├── client.py             # Cliente principal
│   ├── service.py            # Servicio Windows
│   ├── watchdog.py           # Watchdog para mantener cliente activo
│   ├── registry_manager.py   # Gestor de registro
│   ├── config_gui.py         # GUI de configuración
│   ├── notifications.py      # Notificaciones visuales
│   ├── protection.py         # Protecciones
│   ├── CiberMondayClient.spec # PyInstaller spec
│   ├── GUIA_INSTALACION.md   # Guía detallada de instalación
│   └── *.bat                 # Scripts de instalación
│
├── server_data/              # Volumen Docker (generado)
│   └── server_data.json     # Datos persistidos
│
├── docker-compose.yml         # Docker Compose
├── Dockerfile.server         # Dockerfile servidor
├── .github/
│   └── workflows/
│       └── build-client.yml  # GitHub Actions para compilar .exe
├── requirements.txt          # Dependencias
└── README.md                 # Este archivo
```

## 🔐 Seguridad

**⚠️ IMPORTANTE**: Este es un sistema básico para demostración. Para producción:

- ✅ Implementar autenticación y autorización
- ✅ Usar HTTPS en lugar de HTTP
- ✅ Implementar base de datos real (PostgreSQL, SQLite)
- ✅ Agregar logging y auditoría
- ✅ Usar certificados SSL/TLS
- ✅ Implementar medidas anti-tampering

## 📝 Licencia

Este proyecto es de código abierto y está disponible para uso educativo y comercial.

---

**¿Necesitas ayuda?** Abre un issue en GitHub o consulta la documentación completa.
