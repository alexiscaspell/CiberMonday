"""
Servicio de Windows para CiberMonday Client
Este módulo permite ejecutar el cliente como un servicio de Windows
que se inicia automáticamente y se reinicia si falla.

Protección multicapa:
- Watchdog interno: reinicia el cliente si muere (cada 3 segundos)
- Protección DACL: impide que usuarios no-SYSTEM maten el proceso
- Recovery options: Windows reinicia el servicio si se cae (configurado en instalador)
- Security descriptor: restringe quién puede detener el servicio (configurado en instalador)
"""

import win32serviceutil
import win32service
import win32event
import servicemanager
import sys
import os
import subprocess
import time
import threading

# Agregar el directorio actual al path para importar módulos locales
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# Intervalo del watchdog en segundos (qué tan rápido detecta que el cliente murió)
WATCHDOG_CHECK_INTERVAL = 3
# Espera antes de reiniciar tras un error del watchdog
WATCHDOG_ERROR_WAIT = 10


def _get_client_command():
    """
    Determina el comando correcto para lanzar el cliente según el entorno.
    - Entorno congelado (PyInstaller): busca CiberMondayClient.exe en el mismo directorio
    - Entorno Python normal: ejecuta client.py con el intérprete actual
    
    Returns:
        list: Comando como lista para subprocess.Popen
    
    Raises:
        FileNotFoundError: Si no se encuentra el ejecutable/script del cliente
    """
    if getattr(sys, 'frozen', False):
        # Entorno congelado (PyInstaller) - buscar el EXE del cliente
        exe_dir = os.path.dirname(sys.executable)
        client_exe = os.path.join(exe_dir, 'CiberMondayClient.exe')
        if not os.path.exists(client_exe):
            raise FileNotFoundError(
                f"No se encontró CiberMondayClient.exe en {exe_dir}. "
                "Asegúrate de que ambos EXE estén en la misma carpeta."
            )
        return [client_exe]
    else:
        # Entorno Python normal - ejecutar script directamente
        client_script = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'client.py')
        if not os.path.exists(client_script):
            raise FileNotFoundError(
                f"No se encontró client.py en {os.path.dirname(os.path.abspath(__file__))}"
            )
        return [sys.executable, client_script]


def _protect_child_process(pid):
    """
    Aplica protección DACL al proceso hijo para impedir que usuarios lo maten.
    Solo SYSTEM podrá terminar el proceso.
    
    Args:
        pid: ID del proceso hijo a proteger
    """
    try:
        from protection import protect_process_by_pid
        protect_process_by_pid(pid)
    except ImportError:
        pass  # protection.py no disponible
    except Exception:
        pass  # No es crítico, el watchdog lo reiniciará de todas formas


class CiberMondayService(win32serviceutil.ServiceFramework):
    """Servicio de Windows para el cliente CiberMonday"""
    
    _svc_name_ = "CiberMondayClient"
    _svc_display_name_ = "CiberMonday Client Service"
    _svc_description_ = "Servicio de control de tiempo para CiberMonday. Bloquea la PC cuando expira el tiempo asignado."
    
    def __init__(self, args):
        win32serviceutil.ServiceFramework.__init__(self, args)
        self.stop_event = win32event.CreateEvent(None, 0, 0, None)
        self.process = None
        self.watchdog_thread = None
        self.running = False
        
    def SvcStop(self):
        """Detiene el servicio"""
        self.ReportServiceStatus(win32service.SERVICE_STOP_PENDING)
        self.running = False
        win32event.SetEvent(self.stop_event)
        
        # Terminar el proceso del cliente si está corriendo
        if self.process:
            try:
                self.process.terminate()
                self.process.wait(timeout=5)
            except Exception:
                try:
                    self.process.kill()
                except Exception:
                    pass
        
    def SvcDoRun(self):
        """Ejecuta el servicio"""
        servicemanager.LogMsg(
            servicemanager.EVENTLOG_INFORMATION_TYPE,
            servicemanager.PYS_SERVICE_STARTED,
            (self._svc_name_, '')
        )
        
        self.running = True
        
        # Proteger el proceso del servicio mismo
        try:
            from protection import protect_current_process
            protect_current_process()
        except ImportError:
            pass
        except Exception:
            pass
        
        # Iniciar el watchdog en un hilo separado
        self.watchdog_thread = threading.Thread(target=self.watchdog, daemon=True)
        self.watchdog_thread.start()
        
        # Mantener el servicio corriendo
        while self.running:
            win32event.WaitForSingleObject(self.stop_event, 1000)
        
        servicemanager.LogMsg(
            servicemanager.EVENTLOG_INFORMATION_TYPE,
            servicemanager.PYS_SERVICE_STOPPED,
            (self._svc_name_, '')
        )
    
    def watchdog(self):
        """
        Watchdog que mantiene el cliente corriendo y lo reinicia si falla.
        
        - Detecta entorno congelado (PyInstaller) vs Python para lanzar el comando correcto
        - Aplica protección DACL al proceso hijo después de lanzarlo
        - Reinicia el cliente en WATCHDOG_CHECK_INTERVAL segundos si muere
        """
        try:
            client_cmd = _get_client_command()
        except FileNotFoundError as e:
            servicemanager.LogErrorMsg(f"Error fatal en watchdog: {e}")
            return
        
        servicemanager.LogMsg(
            servicemanager.EVENTLOG_INFORMATION_TYPE,
            servicemanager.PYS_SERVICE_STARTED,
            (self._svc_name_, f'Watchdog iniciado. Comando: {" ".join(client_cmd)}')
        )
        
        while self.running:
            try:
                # Verificar si el proceso está corriendo
                if self.process is None or self.process.poll() is not None:
                    if self.process is not None:
                        exit_code = self.process.returncode
                        servicemanager.LogMsg(
                            servicemanager.EVENTLOG_INFORMATION_TYPE,
                            servicemanager.PYS_SERVICE_STARTED,
                            (self._svc_name_, f'Cliente terminó (código: {exit_code}). Reiniciando...')
                        )
                    else:
                        servicemanager.LogMsg(
                            servicemanager.EVENTLOG_INFORMATION_TYPE,
                            servicemanager.PYS_SERVICE_STARTED,
                            (self._svc_name_, 'Iniciando cliente...')
                        )
                    
                    # Iniciar el proceso del cliente
                    self.process = subprocess.Popen(
                        client_cmd,
                        stdout=subprocess.PIPE,
                        stderr=subprocess.PIPE,
                        creationflags=subprocess.CREATE_NO_WINDOW
                    )
                    
                    # Aplicar protección DACL al proceso hijo
                    _protect_child_process(self.process.pid)
                
                # Esperar antes de verificar de nuevo
                time.sleep(WATCHDOG_CHECK_INTERVAL)
                
            except Exception as e:
                servicemanager.LogErrorMsg(f"Error en watchdog: {e}")
                time.sleep(WATCHDOG_ERROR_WAIT)


def main():
    """Función principal para manejar comandos del servicio"""
    if len(sys.argv) == 1:
        # Sin argumentos: podría ser el SCM (Service Control Manager) o el usuario
        # haciendo doble clic. Intentamos conectar al SCM; si falla, mostramos ayuda.
        try:
            servicemanager.Initialize()
            servicemanager.PrepareToHostSingle(CiberMondayService)
            servicemanager.StartServiceCtrlDispatcher()
        except Exception as e:
            # Si falla es porque el usuario ejecutó el EXE directamente,
            # no a través del SCM de Windows
            print("=" * 55)
            print("  CiberMonday Service - Servicio de Windows")
            print("=" * 55)
            print()
            print("  Este ejecutable es un servicio de Windows.")
            print("  No se puede ejecutar directamente con doble clic.")
            print()
            print("  Usa el instalador para configurar todo:")
            print("    install_exe_service.bat   (como Administrador)")
            print()
            print("  O usa estos comandos (como Administrador):")
            print("    CiberMondayService.exe install  - Instalar servicio")
            print("    CiberMondayService.exe start    - Iniciar servicio")
            print("    CiberMondayService.exe stop     - Detener servicio")
            print("    CiberMondayService.exe remove   - Desinstalar servicio")
            print()
            print("  Para desinstalar completamente:")
            print("    uninstall_exe_service.bat   (como Administrador)")
            print()
            input("  Presiona Enter para cerrar...")
    else:
        # Manejar comandos: install, remove, start, stop, restart
        command = sys.argv[1].lower() if len(sys.argv) > 1 else ''
        
        # Si se está instalando, agregar regla del firewall
        if command == 'install':
            try:
                from firewall_manager import add_firewall_rule
                print("\n[Instalación] Configurando firewall...")
                add_firewall_rule()
            except ImportError:
                print("\n[Instalación] No se pudo importar firewall_manager. La regla del firewall no se agregará automáticamente.")
            except Exception as e:
                print(f"\n[Instalación] Error al configurar firewall: {e}")
        
        win32serviceutil.HandleCommandLine(CiberMondayService)


if __name__ == '__main__':
    main()
