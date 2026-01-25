# 🖥️ CiberMonday - Sistema de Control de Tiempo para Cibercafés

Sistema de gestión de tiempo de uso para múltiples clientes, similar a los software de cibercafés tradicionales.

## 📋 Tabla de Contenidos

- [Arquitectura](#arquitectura)
- [Instalación del Servidor](#instalación-del-servidor)
- [Instalación del Cliente](#instalación-del-cliente)
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
  POST   /api/client/<id>/stop - Detener sesión
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
│  └──────────────┘  └──────────────┘  └──────────┘ │
│                                                    │
└─────────────────────────────────────────────────────┘
```

## 💻 Instalación del Cliente

### Opción 1: Ejecutables Pre-compilados (⭐ MÁS FÁCIL)

#### Paso 1: Descargar Release

**Opción A: Desde Releases existentes**
1. Ve a **Releases** en GitHub
2. Descarga la última versión
3. Extrae **todos los archivos** en una carpeta (ej: `C:\CiberMonday\`)

**Opción B: Compilar nuevo release**
1. Ve a **Actions** → **Build Windows Client**
2. Haz clic en **"Run workflow"**
3. Ingresa la versión (ej: `1.0.0`)
4. Marca "prerelease" si es necesario
5. Haz clic en **"Run workflow"**
6. Espera a que termine (5-10 minutos)
7. Ve a **Releases** para descargar los ejecutables

**Archivos incluidos en el release:**
```
📦 Release v1.0.0
├── 📄 CiberMondayClient.exe      (Cliente principal)
├── 📄 CiberMondayService.exe     (Servicio Windows)
├── 📄 CiberMondayWatchdog.exe    (Watchdog)
└── 📄 install_exe_service.bat    (Instalador)
```

#### Paso 2: Configurar (Ventana GUI Automática)

**✨ Ya no necesitas `config.py` - El cliente tiene interfaz gráfica integrada**

Al ejecutar el cliente por primera vez, se abrirá automáticamente una ventana de configuración:

```
┌─────────────────────────────────────────────┐
│  🖥️ Configuración de CiberMonday          │
├─────────────────────────────────────────────┤
│                                             │
│  Ingresa la dirección del servidor para    │
│  conectarte:                                │
│                                             │
│  URL del Servidor:                          │
│  ┌─────────────────────────────────────┐   │
│  │ http://192.168.1.100:5000          │   │
│  └─────────────────────────────────────┘   │
│                                             │
│  Ejemplos:                                   │
│  • http://localhost:5000 (servidor local)   │
│  • http://192.168.1.100:5000 (red local)    │
│                                             │
│  [Cancelar]        [Guardar y Continuar]    │
└─────────────────────────────────────────────┘
```

**Cómo funciona:**
1. **Primera vez**: Ejecuta `CiberMondayClient.exe` como Administrador
   - Se abre la ventana de configuración vacía
   - Ingresa la URL del servidor (ej: `http://192.168.1.100:5000`)
   - Haz clic en **"Guardar y Continuar"**

2. **Ejecuciones siguientes**: Cada vez que ejecutas el cliente
   - Se abre la ventana con los valores actuales cargados
   - Puedes modificar la URL del servidor si es necesario
   - Haz clic en **"Actualizar y Continuar"** para guardar cambios
   - O haz clic en **"Usar Valores Actuales"** para continuar sin cambios

3. La configuración se guarda automáticamente en el registro de Windows
4. El cliente se conectará al servidor con la configuración guardada

**Estructura de archivos:**
```
C:\CiberMonday\
├── CiberMondayClient.exe
├── CiberMondayService.exe
├── CiberMondayWatchdog.exe
└── install_exe_service.bat
```

**Nota**: 
- La configuración se guarda en el registro de Windows (`HKEY_LOCAL_MACHINE\SOFTWARE\CiberMonday`)
- **Cada vez que ejecutas el cliente**, se abre la ventana de configuración con los valores actuales
- Puedes modificar la URL del servidor en cualquier momento
- Si haces clic en "Usar Valores Actuales", continúa con la configuración guardada sin cambios

#### Paso 3: Instalar como Servicio (Recomendado)
```bash
# Ejecutar como Administrador
install_exe_service.bat
```

**O ejecutar directamente:**
```bash
# Ejecutar como Administrador
CiberMondayClient.exe
```

### Opción 2: Desde Código Fuente

#### Paso 1: Copiar Archivos
Copia la carpeta `client` a la PC Windows.

#### Paso 2: Instalar Dependencias
```bash
pip install requests pywin32
```

#### Paso 3: Configurar

**Opción A: Usando la GUI (Recomendado)**
Al ejecutar `client.py` por primera vez, se abrirá una ventana de configuración donde puedes ingresar la URL del servidor.

**Opción B: Configuración manual en registro**
Si prefieres configurar manualmente, puedes editar el registro de Windows:
- Clave: `HKEY_LOCAL_MACHINE\SOFTWARE\CiberMonday`
- Valor: `Config` (JSON con `server_url`)

**Nota**: Ya no se usa `config.py` - la configuración se guarda en el registro de Windows.

#### Paso 4: Ejecutar

**Opción A: Ejecución Normal**
```bash
python client.py
```

**Opción B: Como Servicio (Recomendado)**
```bash
# Ejecutar como Administrador
install_service.bat
```

**Salida esperada del cliente:**
```
==================================================
Cliente CiberMonday iniciado
==================================================
ID del cliente: abc123-def456-ghi789
Servidor: http://192.168.1.100:5000
Modo: Registro local (funciona sin conexión continua)
Esperando asignación de tiempo...
==================================================
Tiempo restante: 45m 30s
```

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

```bash
# En la PC cliente (Windows)
# 1. Descargar release de GitHub
# 2. Extraer archivos en una carpeta
# 3. Ejecutar como Administrador:
CiberMondayClient.exe
# O instalar como servicio:
install_exe_service.bat
```

**Primera vez - Ventana de configuración:**
```
Se abre automáticamente una ventana donde ingresas:
• URL del servidor: http://192.168.1.100:5000
• Haz clic en "Guardar y Continuar"
```

**El cliente se registrará automáticamente:**
```
[Cliente] Registrando en servidor...
[Cliente] ✅ Cliente registrado. ID: abc123-def456
[Cliente] Esperando asignación de tiempo...
```

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
│                                 │
│ [Detener] [Eliminar]            │
└─────────────────────────────────┘
```

**Vista en el Cliente:**
```
Tiempo restante: 59m 45s
Tiempo restante: 59m 44s
Tiempo restante: 59m 43s
...
```

#### 4️⃣ Cuando Expira el Tiempo

**En el Cliente:**
```
==================================================
¡TIEMPO AGOTADO!
La PC se bloqueará continuamente hasta que se asigne nuevo tiempo.
==================================================
```

**En Windows:**
- La pantalla se bloquea automáticamente (Windows+L)
- Si el usuario desbloquea, se vuelve a bloquear en 1 segundo
- Continúa bloqueando hasta que se asigne nuevo tiempo

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

#### Ver Estado
```bash
curl http://localhost:5000/api/client/abc123-def456/status
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
│  └───────────────────────────────────────────┘  │
└───────────────────┬─────────────────────────────┘
                    │
                    │ Sincroniza cada 30s
                    ▼
┌─────────────────────────────────────────────────┐
│  CLIENTE (Windows)                              │
│  ┌───────────────────────────────────────────┐  │
│  │ Registro: HKEY_LOCAL_MACHINE\...          │  │
│  │ • SessionData: {tiempo, inicio, fin}      │  │
│  │ • ClientID: abc123-def456                 │  │
│  └───────────────────────────────────────────┘  │
│                    │                              │
│                    │ Lee cada 1s                  │
│                    ▼                              │
│         ┌──────────────────────┐                 │
│         │ ¿Tiempo expirado?    │                 │
│         └──────┬───────────────┘                 │
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
- Sincroniza con servidor cada 30 segundos

✅ **Resistente a cortes**
- Si se corta la red, sigue funcionando
- Usa el tiempo almacenado en el registro

✅ **Eficiente**
- Menor carga en el servidor
- Verificación rápida local

## ✨ Características

- ✅ **Gestión centralizada** de múltiples clientes
- ✅ **Interfaz web moderna** y fácil de usar
- ✅ **Asignación de tiempo** en minutos u horas
- ✅ **Bloqueo automático** de Windows cuando expira
- ✅ **Sistema de registro local** - Funciona sin conexión continua
- ✅ **Resistente a cortes** - Lee del registro cada segundo
- ✅ **Sincronización eficiente** - Solo consulta servidor cada 30s
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

## 📁 Estructura del Proyecto

```
CiberMonday/
├── server/                    # Servidor Flask
│   ├── app.py                # API principal
│   ├── templates/
│   │   └── index.html       # Panel web
│   └── start_server.*        # Scripts de inicio
│
├── client/                    # Cliente Windows
│   ├── client.py             # Cliente principal
│   ├── service.py            # Servicio Windows
│   ├── registry_manager.py   # Gestor de registro
│   ├── protection.py         # Protecciones
│   ├── config.py             # Configuración
│   └── *.bat                 # Scripts de instalación
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
