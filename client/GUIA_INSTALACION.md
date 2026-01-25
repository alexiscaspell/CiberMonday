# 📋 Guía de Instalación del Cliente CiberMonday

Esta guía te llevará paso a paso para instalar y configurar el cliente CiberMonday en una PC Windows.

## 📦 Requisitos Previos

- ✅ PC con Windows 7 o superior
- ✅ Permisos de Administrador
- ✅ Conexión de red al servidor CiberMonday
- ✅ IP o URL del servidor (ej: `http://192.168.1.100:5000`)

---

## 🚀 Instalación Paso a Paso

### **Paso 1: Obtener los Archivos**

Tienes dos opciones:

#### **Opción A: Descargar desde GitHub Release (Recomendado)**

1. Ve a la página de releases del proyecto en GitHub
2. Descarga el archivo `CiberMondayClient.exe` (y opcionalmente `CiberMondayService.exe`)
3. Crea una carpeta en tu PC, por ejemplo: `C:\CiberMonday\`
4. Copia los archivos descargados a esa carpeta

#### **Opción B: Compilar desde Código Fuente**

Si tienes el código fuente:

1. Abre PowerShell o CMD como Administrador
2. Navega a la carpeta `client` del proyecto
3. Ejecuta:
   ```bash
   build_exe.bat
   ```
4. Los ejecutables se generarán en `client\dist\`
5. Copia los archivos a `C:\CiberMonday\`

**Archivos necesarios:**
```
C:\CiberMonday\
├── CiberMondayClient.exe          (Obligatorio)
├── CiberMondayService.exe          (Opcional - para servicio)
├── CiberMondayWatchdog.exe        (Opcional - watchdog independiente)
└── install_exe_service.bat         (Opcional - script de instalación)
```

---

### **Paso 2: Configurar el Cliente (Primera Vez)**

1. **Ejecuta `CiberMondayClient.exe` como Administrador**
   - Haz clic derecho → "Ejecutar como administrador"
   - O ejecuta desde CMD/PowerShell como Admin

2. **Se abrirá una ventana de configuración** con estos campos:

   ```
   ╔═══════════════════════════════════════════╗
   ║  CiberMonday - Configuración del Cliente ║
   ╠═══════════════════════════════════════════╣
   ║                                           ║
   ║  URL del Servidor:                        ║
   ║  [http://192.168.1.100:5000        ]     ║
   ║                                           ║
   ║  Intervalo de Sincronización (segundos): ║
   ║  [30                                ]     ║
   ║                                           ║
   ║  [Guardar y Continuar]  [Cancelar]       ║
   ╚═══════════════════════════════════════════╝
   ```

3. **Completa los datos:**
   - **URL del Servidor**: Ingresa la IP o URL de tu servidor
     - Ejemplo: `http://192.168.1.100:5000`
     - Ejemplo: `http://servidor.local:5000`
   - **Intervalo de Sincronización**: Cuántos segundos espera entre sincronizaciones (por defecto: 30)

4. **Haz clic en "Guardar y Continuar"**

5. **El cliente se registrará automáticamente** en el servidor y mostrará:
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

✅ **¡Configuración completada!** La configuración se guardó en el registro de Windows.

---

### **Paso 3: Elegir Modo de Ejecución**

Tienes dos opciones:

#### **Opción A: Ejecución Manual (Simple)**

**Ventajas:**
- ✅ Fácil de iniciar/detener
- ✅ Puedes ver los logs en tiempo real
- ✅ Útil para pruebas

**Desventajas:**
- ❌ Se cierra si cierras la ventana
- ❌ No inicia automáticamente al arrancar Windows

**Cómo usar:**
- Simplemente ejecuta `CiberMondayClient.exe` cada vez que quieras usarlo
- La ventana de configuración aparecerá cada vez (puedes hacer clic en "Usar Valores Actuales" para continuar sin cambios)

---

#### **Opción B: Como Servicio de Windows (Recomendado para Producción)**

**Ventajas:**
- ✅ Se ejecuta automáticamente al iniciar Windows
- ✅ Corre en segundo plano (sin ventana visible)
- ✅ No se puede cerrar fácilmente desde el Administrador de Tareas
- ✅ Incluye watchdog integrado (se reinicia si falla)

**Desventajas:**
- ❌ Requiere permisos de Administrador para instalar
- ❌ Más difícil de depurar si hay problemas

**Cómo instalar:**

1. **Asegúrate de tener `CiberMondayService.exe`** en la carpeta `C:\CiberMonday\`

2. **Ejecuta como Administrador:**
   ```bash
   # Opción 1: Usar el script (más fácil)
   install_exe_service.bat
   
   # Opción 2: Manualmente
   CiberMondayService.exe install
   CiberMondayService.exe start
   ```

3. **Verifica que el servicio esté corriendo:**
   - Abre `services.msc` (Servicios de Windows)
   - Busca "CiberMonday Client Service"
   - Debe estar en estado "En ejecución"

**Comandos útiles del servicio:**
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

---

### **Paso 4: Verificar que Funciona**

1. **Abre el panel web del servidor:**
   - Ve a `http://TU_IP_SERVIDOR:5000` en tu navegador
   - Deberías ver tu PC cliente listada

2. **Asigna tiempo de prueba:**
   - En el panel web, ingresa un tiempo pequeño (ej: 1 minuto)
   - Haz clic en "Establecer Tiempo"

3. **Verifica en el cliente:**
   - Si está ejecutándose manualmente, verás: `Tiempo restante: 59s`
   - Si está como servicio, puedes verificar en los logs del sistema

4. **Espera a que expire:**
   - Cuando llegue a 0, la PC se bloqueará automáticamente
   - Verás notificaciones a los 10, 5, 2 y 1 minuto restante

---

## 🔧 Configuración Adicional

### **Modificar la Configuración**

**Método 1: Desde el Cliente (Recomendado)**
- Ejecuta `CiberMondayClient.exe` nuevamente
- Se abrirá la ventana con los valores actuales
- Modifica lo que necesites y haz clic en "Guardar y Continuar"

**Método 2: Desde el Registro de Windows**
1. Abre `regedit` como Administrador
2. Navega a: `HKEY_LOCAL_MACHINE\SOFTWARE\CiberMonday`
3. Edita el valor `Config` (es un JSON)
4. Reinicia el cliente o servicio

### **Usar el Watchdog Independiente (Opcional)**

Si ejecutas el cliente manualmente y quieres protección adicional:

1. Ejecuta `CiberMondayWatchdog.exe` como Administrador
2. El watchdog monitoreará `CiberMondayClient.exe`
3. Si el cliente se cierra, el watchdog lo reiniciará automáticamente

**Nota:** Si usas el servicio (`CiberMondayService.exe`), NO necesitas el watchdog independiente, ya que el servicio incluye su propio watchdog.

---

## ✅ Checklist de Instalación

Marca cada paso cuando lo completes:

- [ ] Archivos descargados/copiados a `C:\CiberMonday\`
- [ ] `CiberMondayClient.exe` ejecutado por primera vez
- [ ] Configuración completada (URL del servidor ingresada)
- [ ] Cliente registrado en el servidor (aparece en el panel web)
- [ ] Modo de ejecución elegido (Manual o Servicio)
- [ ] Si es servicio: instalado y corriendo
- [ ] Tiempo de prueba asignado desde el panel web
- [ ] Verificado que el tiempo cuenta correctamente
- [ ] Verificado que el bloqueo funciona cuando expira

---

## 🆘 Solución de Problemas

### **El cliente no se conecta al servidor**

1. Verifica que el servidor esté corriendo:
   ```bash
   curl http://TU_IP_SERVIDOR:5000/api/health
   ```

2. Verifica la configuración:
   - Ejecuta `CiberMondayClient.exe` nuevamente
   - Revisa que la URL del servidor sea correcta

3. Verifica el firewall:
   - Asegúrate de que el puerto 5000 (o el que uses) esté abierto

### **El bloqueo no funciona**

1. Verifica permisos de Administrador:
   - El cliente debe ejecutarse como Administrador
   - Si es servicio, debe estar instalado como Administrador

2. Verifica que el tiempo haya expirado:
   - Revisa en el panel web el tiempo restante
   - Espera a que llegue a 0

### **El servicio no inicia**

1. Verifica los logs:
   - Abre `Event Viewer` (Visor de eventos)
   - Ve a `Windows Logs` → `Application`
   - Busca errores relacionados con "CiberMonday"

2. Reinstala el servicio:
   ```bash
   CiberMondayService.exe remove
   CiberMondayService.exe install
   CiberMondayService.exe start
   ```

### **La ventana de configuración no aparece**

- Asegúrate de ejecutar `CiberMondayClient.exe` directamente (no como servicio)
- Si ejecutas como servicio, la configuración debe hacerse antes de instalar el servicio

---

## 📝 Notas Importantes

- ✅ La configuración se guarda en el **Registro de Windows** (`HKEY_LOCAL_MACHINE\SOFTWARE\CiberMonday`)
- ✅ **Cada vez que ejecutas el cliente manualmente**, aparece la ventana de configuración
- ✅ Puedes hacer clic en **"Usar Valores Actuales"** para continuar sin cambios
- ✅ El cliente funciona **sin conexión continua** - lee del registro local cada segundo
- ✅ Sincroniza con el servidor cada 30 segundos (configurable)
- ✅ Si el servidor se reinicia, el cliente recupera automáticamente su sesión

---

## 🎯 Resumen Rápido

```bash
# 1. Copiar archivos a C:\CiberMonday\
# 2. Ejecutar como Administrador:
CiberMondayClient.exe

# 3. Configurar URL del servidor en la ventana que aparece
# 4. (Opcional) Instalar como servicio:
install_exe_service.bat

# ¡Listo! El cliente está funcionando
```

---

¿Necesitas ayuda? Revisa la documentación completa en `README.md` o abre un issue en GitHub.
