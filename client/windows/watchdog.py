"""
Watchdog independiente para el cliente CiberMonday
Este script se ejecuta como proceso separado y reinicia el cliente
si se cierra o es terminado.

Alternativa al servicio de Windows para entornos donde no se puede
instalar un servicio. Detecta entorno congelado (PyInstaller) para
lanzar CiberMondayClient.exe correctamente.
"""

import subprocess
import time
import sys
import os
import ctypes

# Intervalo de verificación del watchdog en segundos
WATCHDOG_CHECK_INTERVAL = 3


def is_admin():
    """Verifica si el script se ejecuta como administrador"""
    try:
        return ctypes.windll.shell32.IsUserAnAdmin()
    except Exception:
        return False


def get_client_command():
    """
    Determina el comando correcto para lanzar el cliente según el entorno.
    - Entorno congelado (PyInstaller): busca CiberMondayClient.exe en el mismo directorio
    - Entorno Python normal: ejecuta client.py con el intérprete actual
    
    Returns:
        list: Comando como lista para subprocess.Popen
    """
    if getattr(sys, 'frozen', False):
        exe_dir = os.path.dirname(sys.executable)
        client_exe = os.path.join(exe_dir, 'CiberMondayClient.exe')
        if not os.path.exists(client_exe):
            print(f"ERROR: No se encontró CiberMondayClient.exe en {exe_dir}")
            print("Asegúrate de que ambos EXE estén en la misma carpeta.")
            sys.exit(1)
        return [client_exe]
    else:
        client_script = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'client.py')
        if not os.path.exists(client_script):
            print(f"ERROR: No se encontró client.py en {os.path.dirname(os.path.abspath(__file__))}")
            sys.exit(1)
        return [sys.executable, client_script]


def protect_child(pid):
    """Aplica protección DACL al proceso hijo"""
    try:
        from protection import protect_process_by_pid
        if protect_process_by_pid(pid):
            print(f"[{time.strftime('%H:%M:%S')}] Protección DACL aplicada al cliente (PID: {pid})")
    except ImportError:
        pass
    except Exception:
        pass


def main():
    """Función principal del watchdog"""
    if sys.platform != 'win32':
        print("ERROR: Este watchdog solo funciona en Windows.")
        sys.exit(1)
    
    if not is_admin():
        print("ADVERTENCIA: Se recomienda ejecutar como administrador para mejor protección.")
    
    # Aplicar protección al proceso del watchdog mismo
    try:
        from protection import apply_protections
        protections = apply_protections()
        if protections:
            print(f"Protecciones del watchdog: {', '.join(protections)}")
    except ImportError:
        pass
    except Exception:
        pass
    
    client_cmd = get_client_command()
    
    print("=" * 50)
    print("Watchdog CiberMonday iniciado")
    print("=" * 50)
    print(f"Comando: {' '.join(client_cmd)}")
    print(f"Intervalo de verificación: {WATCHDOG_CHECK_INTERVAL}s")
    print("Presiona Ctrl+C para detener el watchdog")
    print("=" * 50)
    
    process = None
    restart_count = 0
    
    try:
        while True:
            # Verificar si el proceso del cliente está corriendo
            if process is None or process.poll() is not None:
                # Proceso no existe o terminó
                if process is not None:
                    restart_count += 1
                    print(f"\n[{time.strftime('%H:%M:%S')}] Cliente terminado (código: {process.returncode}). Reiniciando... (intento {restart_count})")
                
                # Iniciar el cliente
                try:
                    process = subprocess.Popen(
                        client_cmd,
                        creationflags=subprocess.CREATE_NO_WINDOW
                    )
                    print(f"[{time.strftime('%H:%M:%S')}] Cliente iniciado (PID: {process.pid})")
                    
                    # Proteger el proceso hijo contra terminación
                    protect_child(process.pid)
                    
                except Exception as e:
                    print(f"[{time.strftime('%H:%M:%S')}] Error al iniciar cliente: {e}")
                    time.sleep(10)
                    continue
            
            # Esperar antes de verificar de nuevo
            time.sleep(WATCHDOG_CHECK_INTERVAL)
            
    except KeyboardInterrupt:
        print("\n\nWatchdog detenido por el usuario.")
        if process:
            try:
                process.terminate()
                process.wait(timeout=5)
            except Exception:
                try:
                    process.kill()
                except Exception:
                    pass
        sys.exit(0)
    except Exception as e:
        print(f"\nError fatal en watchdog: {e}")
        sys.exit(1)


if __name__ == '__main__':
    main()
