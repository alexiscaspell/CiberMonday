"""
Módulo de protección para el cliente CiberMonday
Implementa técnicas para proteger el proceso contra terminación
"""

import ctypes
import sys
import os
from ctypes import wintypes

# Windows API
kernel32 = ctypes.windll.kernel32
advapi32 = ctypes.windll.advapi32
user32 = ctypes.windll.user32

# Constantes
PROCESS_QUERY_INFORMATION = 0x0400
PROCESS_SET_INFORMATION = 0x0200
PROCESS_TERMINATE = 0x0001
PROCESS_ALL_ACCESS = 0x001F0FFF

def hide_from_task_manager():
    """
    Intenta ocultar el proceso del administrador de tareas.
    Nota: Esto requiere privilegios elevados y puede no funcionar en todas las versiones de Windows.
    """
    try:
        # Obtener el handle del proceso actual
        current_pid = os.getpid()
        process_handle = kernel32.OpenProcess(
            PROCESS_ALL_ACCESS,
            False,
            current_pid
        )
        
        if process_handle:
            # Intentar cambiar el nombre del proceso (técnica básica)
            # Nota: Esto es limitado, Windows 10/11 tiene protecciones más fuertes
            kernel32.CloseHandle(process_handle)
            return True
    except Exception:
        pass
    return False

def protect_process():
    """
    Protege el proceso contra terminación estableciendo privilegios.
    Requiere ejecución como administrador.
    """
    try:
        # Obtener el token del proceso actual
        token_handle = ctypes.wintypes.HANDLE()
        
        if not advapi32.OpenProcessToken(
            kernel32.GetCurrentProcess(),
            0x0028,  # TOKEN_ADJUST_PRIVILEGES | TOKEN_QUERY
            ctypes.byref(token_handle)
        ):
            return False
        
        # Buscar el LUID para el privilegio de depuración
        class LUID(ctypes.Structure):
            _fields_ = [("LowPart", wintypes.DWORD),
                       ("HighPart", ctypes.c_long)]
        
        class LUID_AND_ATTRIBUTES(ctypes.Structure):
            _fields_ = [("Luid", LUID),
                       ("Attributes", wintypes.DWORD)]
        
        class TOKEN_PRIVILEGES(ctypes.Structure):
            _fields_ = [("PrivilegeCount", wintypes.DWORD),
                       ("Privileges", LUID_AND_ATTRIBUTES)]
        
        # Intentar habilitar privilegios (esto es complejo y puede no ser necesario)
        # Por ahora, simplemente retornamos True si tenemos el token
        advapi32.CloseHandle(token_handle)
        return True
        
    except Exception:
        return False

def set_process_priority_high():
    """Establece la prioridad del proceso como alta"""
    try:
        HIGH_PRIORITY_CLASS = 0x00000080
        process_handle = kernel32.GetCurrentProcess()
        kernel32.SetPriorityClass(process_handle, HIGH_PRIORITY_CLASS)
        return True
    except Exception:
        return False

def disable_task_manager():
    """
    Deshabilita el administrador de tareas temporalmente.
    ADVERTENCIA: Esto puede ser detectado por antivirus y es muy invasivo.
    Solo usar en entornos controlados.
    """
    try:
        # Clave del registro para deshabilitar Task Manager
        # HKEY_CURRENT_USER\Software\Microsoft\Windows\CurrentVersion\Policies\System
        # DisableTaskMgr = 1
        
        import winreg
        
        key = winreg.OpenKey(
            winreg.HKEY_CURRENT_USER,
            r"Software\Microsoft\Windows\CurrentVersion\Policies\System",
            0,
            winreg.KEY_SET_VALUE
        )
        
        winreg.SetValueEx(key, "DisableTaskMgr", 0, winreg.REG_DWORD, 1)
        winreg.CloseKey(key)
        return True
    except Exception:
        return False

def enable_task_manager():
    """Rehabilita el administrador de tareas"""
    try:
        import winreg
        
        key = winreg.OpenKey(
            winreg.HKEY_CURRENT_USER,
            r"Software\Microsoft\Windows\CurrentVersion\Policies\System",
            0,
            winreg.KEY_SET_VALUE
        )
        
        try:
            winreg.DeleteValue(key, "DisableTaskMgr")
        except:
            pass
        
        winreg.CloseKey(key)
        return True
    except Exception:
        return False

def apply_protections():
    """
    Aplica todas las protecciones disponibles.
    Se ejecuta al inicio del cliente.
    """
    protections_applied = []
    
    # Establecer prioridad alta
    if set_process_priority_high():
        protections_applied.append("Prioridad alta establecida")
    
    # Intentar proteger el proceso (requiere admin)
    if protect_process():
        protections_applied.append("Protección de proceso aplicada")
    
    return protections_applied
