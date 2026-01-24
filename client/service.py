"""
Servicio de Windows para CiberMonday Client
Este módulo permite ejecutar el cliente como un servicio de Windows
que se inicia automáticamente y se reinicia si falla.
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

# Agregar el directorio actual al path para importar client
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

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
            except:
                try:
                    self.process.kill()
                except:
                    pass
        
    def SvcDoRun(self):
        """Ejecuta el servicio"""
        servicemanager.LogMsg(
            servicemanager.EVENTLOG_INFORMATION_TYPE,
            servicemanager.PYS_SERVICE_STARTED,
            (self._svc_name_, '')
        )
        
        self.running = True
        
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
        """Watchdog que mantiene el cliente corriendo y lo reinicia si falla"""
        client_script = os.path.join(os.path.dirname(__file__), 'client.py')
        
        while self.running:
            try:
                # Verificar si el proceso está corriendo
                if self.process is None or self.process.poll() is not None:
                    # Proceso no existe o terminó, reiniciarlo
                    servicemanager.LogMsg(
                        servicemanager.EVENTLOG_INFORMATION_TYPE,
                        servicemanager.PYS_SERVICE_STARTED,
                        (self._svc_name_, 'Reiniciando cliente...')
                    )
                    
                    # Iniciar el proceso del cliente
                    self.process = subprocess.Popen(
                        [sys.executable, client_script],
                        stdout=subprocess.PIPE,
                        stderr=subprocess.PIPE,
                        creationflags=subprocess.CREATE_NO_WINDOW  # Ocultar ventana
                    )
                
                # Esperar un poco antes de verificar de nuevo
                time.sleep(5)
                
            except Exception as e:
                servicemanager.LogErrorMsg(f"Error en watchdog: {e}")
                time.sleep(10)

def main():
    """Función principal para manejar comandos del servicio"""
    if len(sys.argv) == 1:
        # Si no hay argumentos, intentar instalar el servicio
        servicemanager.Initialize()
        servicemanager.PrepareToHostSingle(CiberMondayService)
        servicemanager.StartServiceCtrlDispatcher()
    else:
        # Manejar comandos: install, remove, start, stop, restart
        win32serviceutil.HandleCommandLine(CiberMondayService)

if __name__ == '__main__':
    main()
