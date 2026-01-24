# Compilación del Cliente como Ejecutable (.exe)

Este documento explica cómo compilar el cliente de CiberMonday como un ejecutable .exe para facilitar la distribución e instalación.

## Requisitos

- Python 3.7 o superior instalado
- Windows (para compilar y ejecutar)
- Conexión a Internet (para descargar PyInstaller)

## Compilación

### Método Automático (Recomendado)

1. Abre una terminal en la carpeta `client`
2. Ejecuta el script de compilación:
```bash
build_exe.bat
```

Este script:
- Instala PyInstaller automáticamente
- Compila el cliente principal (`CiberMondayClient.exe`)
- Compila el servicio (`CiberMondayService.exe`)
- Compila el watchdog (`CiberMondayWatchdog.exe`)

### Método Manual

Si prefieres compilar manualmente:

```bash
# Instalar PyInstaller
pip install pyinstaller

# Compilar el cliente
pyinstaller --onefile --name CiberMondayClient client.py

# Compilar el servicio
pyinstaller --onefile --name CiberMondayService service.py

# Compilar el watchdog
pyinstaller --onefile --name CiberMondayWatchdog watchdog.py
```

Los ejecutables se generarán en la carpeta `dist/`.

## Archivos Generados

Después de compilar, encontrarás en la carpeta `dist/`:

- **CiberMondayClient.exe**: Cliente principal (ejecutable standalone)
- **CiberMondayService.exe**: Servicio de Windows (ejecutable standalone)
- **CiberMondayWatchdog.exe**: Watchdog independiente (ejecutable standalone)

## Instalación del Ejecutable

### Opción 1: Ejecución Directa

Simplemente ejecuta `CiberMondayClient.exe`. Asegúrate de tener un archivo `config.py` en la misma carpeta con la configuración del servidor.

### Opción 2: Como Servicio de Windows

1. Copia `CiberMondayService.exe` y `config.py` a la carpeta donde quieras instalarlo
2. Ejecuta como Administrador:
```bash
install_exe_service.bat
```

O manualmente:
```bash
# Como Administrador
CiberMondayService.exe install
CiberMondayService.exe start
```

## Configuración

El ejecutable necesita un archivo `config.py` en la misma carpeta. Crea este archivo con el siguiente contenido:

```python
SERVER_URL = "http://192.168.1.100:5000"  # IP del servidor
CHECK_INTERVAL = 5
CLIENT_ID_FILE = "client_id.txt"
```

## Distribución

Para distribuir el cliente:

1. Compila los ejecutables usando `build_exe.bat`
2. Copia los siguientes archivos:
   - `CiberMondayClient.exe` (o `CiberMondayService.exe` para servicio)
   - `config.py` (opcional, puede crearse después)
   - `install_exe_service.bat` (si vas a instalar como servicio)

3. Distribuye estos archivos a las PCs cliente

## Ventajas del Ejecutable

- ✅ **No requiere Python instalado** en las PCs cliente
- ✅ **Más fácil de distribuir**: Solo copiar archivos
- ✅ **Más difícil de modificar**: El código está compilado
- ✅ **Ejecución más rápida**: No necesita interpretar Python
- ✅ **Todo incluido**: Todas las dependencias están empaquetadas

## Notas Importantes

- El primer arranque del .exe puede ser más lento (PyInstaller extrae archivos temporalmente)
- Los ejecutables son específicos de Windows (no funcionan en Linux/Mac)
- El tamaño del .exe será mayor (~10-20 MB) porque incluye Python y todas las dependencias
- Si cambias `config.py`, reinicia el cliente para que cargue la nueva configuración

## Solución de Problemas

### El ejecutable no inicia
- Verifica que estés en Windows
- Ejecuta como Administrador si es necesario
- Verifica que `config.py` exista en la misma carpeta

### Error al instalar como servicio
- Asegúrate de ejecutar como Administrador
- Verifica que el servicio no esté ya instalado
- Revisa los logs del sistema en `services.msc`

### El ejecutable es detectado como virus
- Algunos antivirus detectan PyInstaller como sospechoso
- Agrega una excepción en tu antivirus
- Esto es un falso positivo común con ejecutables compilados con PyInstaller
