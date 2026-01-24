"""
Watchdog independiente para el cliente CiberMonday
Este script se ejecuta como proceso separado y reinicia el cliente
si se cierra o es terminado.
"""

import subprocess
import time
import sys
import os
import ctypes

def is_admin():
    """Verifica si el script se ejecuta como administrador"""
    try:
        return ctypes.windll.shell32.IsUserAnAdmin()
    except:
        return False

def is_process_running(process_name):
    """Verifica si un proceso está corriendo"""
    try:
        result = subprocess.run(
            ['tasklist', '/FI', f'IMAGENAME eq {process_name}'],
            capture_output=True,
            text=True
        )
        return process_name.lower() in result.stdout.lower()
    except:
        return False

def main():
    """Función principal del watchdog"""
    if sys.platform != 'win32':
        print("ERROR: Este watchdog solo funciona en Windows.")
        sys.exit(1)
    
    if not is_admin():
        print("ADVERTENCIA: Se recomienda ejecutar como administrador para mejor protección.")
    
    client_script = os.path.join(os.path.dirname(__file__), 'client.py')
    python_exe = sys.executable
    
    print("=" * 50)
    print("Watchdog CiberMonday iniciado")
    print("=" * 50)
    print(f"Monitoreando: {client_script}")
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
                    print(f"\n[{time.strftime('%H:%M:%S')}] Cliente terminado. Reiniciando... (intento {restart_count})")
                
                # Iniciar el cliente
                try:
                    process = subprocess.Popen(
                        [python_exe, client_script],
                        creationflags=subprocess.CREATE_NO_WINDOW  # Ocultar ventana
                    )
                    print(f"[{time.strftime('%H:%M:%S')}] Cliente iniciado (PID: {process.pid})")
                except Exception as e:
                    print(f"[{time.strftime('%H:%M:%S')}] Error al iniciar cliente: {e}")
                    time.sleep(10)
                    continue
            
            # Esperar antes de verificar de nuevo
            time.sleep(5)
            
    except KeyboardInterrupt:
        print("\n\nWatchdog detenido por el usuario.")
        if process:
            try:
                process.terminate()
                process.wait(timeout=5)
            except:
                try:
                    process.kill()
                except:
                    pass
        sys.exit(0)
    except Exception as e:
        print(f"\nError fatal en watchdog: {e}")
        sys.exit(1)

if __name__ == '__main__':
    main()
