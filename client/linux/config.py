"""
Archivo de configuración del cliente
Edita estos valores según tu configuración
"""

# URL del servidor (cambiar por la IP del servidor en producción)
SERVER_URL = "http://localhost:5000"

# Intervalo de verificación en segundos (cuánto tiempo espera entre verificaciones)
# NOTA: Este valor ya no se usa directamente. El cliente ahora:
# - Lee del registro local cada 1 segundo
# - Sincroniza con el servidor cada 30 segundos
# - Funciona sin conexión continua gracias al registro local
CHECK_INTERVAL = 5

# Archivo donde se guarda el ID del cliente (backup, también se guarda en registro)
CLIENT_ID_FILE = "client_id.txt"
