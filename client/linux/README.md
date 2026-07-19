# CiberMonday — Cliente Linux

Agente para PCs Linux. Mismo protocolo que Windows: registro, discovery UDP, push HTTP, sesión offline y bloqueo con `loginctl`.

## Archivos

| Archivo | Descripción |
|---------|-------------|
| `client.py` | Entry point |
| `client_base.py` | Lógica compartida |
| `client_linux.py` | Bloqueo / almacenamiento Linux |
| `config_gui.py` | Configuración inicial |
| `install_linux.sh` | Instala servicio systemd |
| `uninstall_linux.sh` | Desinstalación |
| `cibermonday-client.service` | Unit de systemd |

## Instalación

```bash
cd client/linux
sudo bash install_linux.sh
```

Gestión:

```bash
sudo systemctl status cibermonday-client
journalctl -u cibermonday-client -f
```

Ver también el README raíz y [`client/windows/README.md`](../windows/README.md) para el protocolo compartido.
