<p align="center">
  <img src="../resources/icono.png" alt="CiberMonday" width="80">
</p>

# CiberMonday — Servidor Web

Servidor central que gestiona los clientes del cibercafé. Provee una API REST para registro, asignación de tiempo y control de sesiones, junto con un panel web de administración.

## Características

- **API REST completa** — Registro de clientes, asignación de tiempo, control de sesiones, configuración remota.
- **Panel web de administración** — Interfaz moderna para gestionar todos los clientes desde el navegador.
- **Auto-descubrimiento** — Broadcast UDP en la red local para que los clientes encuentren el servidor automáticamente.
- **Control de acceso** — Las rutas de administración solo son accesibles desde localhost (configurable via `ADMIN_ALLOWED_IPS`).
- **Health check** — Endpoint `/api/health` para monitoreo y Docker healthcheck.
- **Multiplataforma** — Corre en Docker, directamente en Python, o embebido en la app Android.

## Archivos

| Archivo | Descripción |
|---------|-------------|
| `app.py` | Aplicación Flask: rutas API, broadcast UDP, control de acceso |
| `templates/index.html` | Panel web de administración (HTML/CSS/JS single-page) |
| `Dockerfile` | Imagen Docker del servidor |
| `start_server.sh` | Script de inicio para Linux/macOS |
| `start_server.bat` | Script de inicio para Windows |

La lógica de negocio está en `core/client_manager.py` (compartida con la app Android).

## Instalación

### Con Docker Compose (recomendado)

```bash
# Desde la raíz del proyecto
docker compose up -d

# Verificar
docker compose logs -f
curl http://localhost:5000/api/health
```

El panel queda disponible en `http://localhost:5000`.

### Manual

```bash
pip install Flask flask-cors
cd server
python app.py
```

### Variables de entorno

| Variable | Default | Descripción |
|----------|---------|-------------|
| `PORT` | `5000` | Puerto del servidor |
| `HOST` | `0.0.0.0` | Dirección de escucha |
| `FLASK_ENV` | `production` | `development` para modo debug |
| `ADMIN_ALLOWED_IPS` | _(vacío)_ | IPs adicionales autorizadas para admin (separadas por coma) |
| `HOST_IP` | _(auto)_ | IP de la máquina en la LAN (para broadcast). Necesario en Docker. |

## API REST

### Rutas públicas (acceso desde clientes)

| Método | Ruta | Descripción |
|--------|------|-------------|
| `POST` | `/api/register` | Registrar cliente (envía name, client_id, session, config) |
| `GET` | `/api/client/<id>/status` | Obtener estado y tiempo restante |
| `GET` | `/api/client/<id>/config` | Obtener configuración del cliente |
| `POST` | `/api/client/<id>/config` | Reportar configuración (con `from_client: true`) |
| `POST` | `/api/client/<id>/report-session` | Reportar sesión activa al servidor |
| `GET` | `/api/health` | Health check |
| `GET` | `/api/servers` | Lista de servidores conocidos en la red |

### Rutas de administración (solo localhost por defecto)

| Método | Ruta | Descripción |
|--------|------|-------------|
| `GET` | `/` | Panel web de administración |
| `GET` | `/api/clients` | Listar todos los clientes |
| `POST` | `/api/client/<id>/set-time` | Asignar tiempo (`time`, `unit`) |
| `POST` | `/api/client/<id>/stop` | Detener sesión activa |
| `POST` | `/api/client/<id>/config` | Modificar configuración del cliente |
| `DELETE` | `/api/client/<id>` | Eliminar cliente |

### Ejemplos

```bash
# Listar clientes
curl http://localhost:5000/api/clients

# Asignar 60 minutos
curl -X POST http://localhost:5000/api/client/<id>/set-time \
  -H "Content-Type: application/json" \
  -d '{"time": 60, "unit": "minutes"}'

# Ver estado
curl http://localhost:5000/api/client/<id>/status

# Configurar cliente
curl -X POST http://localhost:5000/api/client/<id>/config \
  -H "Content-Type: application/json" \
  -d '{"lock_recheck_interval": 2, "max_server_timeouts": 10}'

# Detener sesión
curl -X POST http://localhost:5000/api/client/<id>/stop

# Eliminar cliente
curl -X DELETE http://localhost:5000/api/client/<id>
```

## Panel Web

El panel de administración (`templates/index.html`) es una single-page application que permite:

- Ver todos los clientes registrados con su estado en tiempo real.
- Asignar tiempo a cada cliente (minutos u horas).
- Detener sesiones activas.
- Renombrar clientes.
- Configurar parámetros por cliente (intervalo de re-bloqueo, timeouts).
- Eliminar clientes.
- Ver estadísticas generales (clientes activos, totales).

Se actualiza automáticamente cada pocos segundos.

## Auto-descubrimiento (Broadcast UDP)

El servidor envía periódicamente un broadcast UDP en el puerto `5001` con su URL. Los clientes Windows escuchan estos broadcasts para encontrar el servidor automáticamente sin configuración manual.

```
Puerto UDP: 5001
Intervalo: 1 segundo (configurable)
Payload: JSON con server_url e identificador
```

> **Nota:** En Docker para macOS, los broadcasts UDP no llegan a la LAN. Para auto-descubrimiento en ese caso, ejecutar el servidor sin Docker o configurar la URL manualmente en los clientes.

## Docker

### docker-compose.yml

```yaml
services:
  server:
    build:
      context: .
      dockerfile: Dockerfile.server
    ports:
      - "${PORT:-5000}:5000"
      - "5001:5001/udp"
    environment:
      - PORT=5000
      - HOST_IP=192.168.1.100  # Tu IP en la LAN
    restart: unless-stopped
```

### Dockerfile

El `Dockerfile.server` (en la raíz del proyecto) construye una imagen basada en Python con Flask y las dependencias necesarias.

## Solución de problemas

| Problema | Solución |
|----------|----------|
| Puerto 5000 en uso | Cambiar `PORT` en `.env` o `docker-compose.yml` |
| Panel no accesible desde otra PC | El panel está restringido a localhost. Agregar la IP en `ADMIN_ALLOWED_IPS`. |
| Broadcast no llega a los clientes | En Docker/macOS, usar servidor sin Docker. Verificar firewall puerto 5001/UDP. |
| Cliente no aparece en el panel | Verificar que el cliente puede alcanzar `http://IP_SERVIDOR:5000`. Verificar firewall. |
