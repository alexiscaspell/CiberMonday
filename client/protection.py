"""
Módulo de protección para el cliente CiberMonday
Implementa protección real contra terminación de procesos usando DACL de Windows.

Técnicas implementadas:
- Protección DACL: Niega PROCESS_TERMINATE al grupo Everyone, solo SYSTEM puede matar el proceso
- Prioridad alta: Establece el proceso con prioridad alta para que no sea fácilmente matado por falta de recursos
- Protección de proceso hijo: Permite proteger procesos lanzados como subprocesos (usado por service.py)
"""

import ctypes
import sys
import os
from ctypes import wintypes

# ============================================================================
# Windows API - Kernel32
# ============================================================================
kernel32 = ctypes.windll.kernel32
advapi32 = ctypes.windll.advapi32

# ============================================================================
# Constantes de Windows
# ============================================================================

# Derechos de proceso
PROCESS_TERMINATE = 0x0001
PROCESS_SET_INFORMATION = 0x0200
PROCESS_QUERY_INFORMATION = 0x0400
PROCESS_ALL_ACCESS = 0x001F0FFF
WRITE_DAC = 0x00040000
READ_CONTROL = 0x00020000

# Tipo de información de seguridad
DACL_SECURITY_INFORMATION = 0x00000004

# Constantes de ACL
ACL_REVISION = 2
ACCESS_DENIED_ACE_TYPE = 0x01

# Tipo de objeto para SetSecurityInfo
SE_KERNEL_OBJECT = 6

# SID conocidos
SECURITY_WORLD_SID_AUTHORITY = (0, 0, 0, 0, 0, 1)  # Everyone
SECURITY_WORLD_RID = 0  # Sub-authority para Everyone

# Prioridad de proceso
HIGH_PRIORITY_CLASS = 0x00000080

# Derechos a denegar (lo que queremos bloquear para usuarios normales)
# PROCESS_TERMINATE | PROCESS_VM_WRITE | PROCESS_VM_OPERATION | PROCESS_CREATE_THREAD
DENIED_ACCESS_MASK = 0x0001 | 0x0020 | 0x0008 | 0x0002


# ============================================================================
# Estructuras de Windows
# ============================================================================

class SID_IDENTIFIER_AUTHORITY(ctypes.Structure):
    _fields_ = [("Value", ctypes.c_ubyte * 6)]


class ACL(ctypes.Structure):
    _fields_ = [
        ("AclRevision", ctypes.c_ubyte),
        ("Sbz1", ctypes.c_ubyte),
        ("AclSize", ctypes.c_ushort),
        ("AceCount", ctypes.c_ushort),
        ("Sbz2", ctypes.c_ushort),
    ]


# ============================================================================
# Configuración de tipos de retorno y argumentos para las APIs
# ============================================================================

# AllocateAndInitializeSid
advapi32.AllocateAndInitializeSid.restype = ctypes.c_bool
advapi32.AllocateAndInitializeSid.argtypes = [
    ctypes.POINTER(SID_IDENTIFIER_AUTHORITY),  # pIdentifierAuthority
    ctypes.c_ubyte,                             # nSubAuthorityCount
    ctypes.c_ulong,                             # dwSubAuthority0
    ctypes.c_ulong,                             # dwSubAuthority1
    ctypes.c_ulong,                             # dwSubAuthority2
    ctypes.c_ulong,                             # dwSubAuthority3
    ctypes.c_ulong,                             # dwSubAuthority4
    ctypes.c_ulong,                             # dwSubAuthority5
    ctypes.c_ulong,                             # dwSubAuthority6
    ctypes.c_ulong,                             # dwSubAuthority7
    ctypes.POINTER(ctypes.c_void_p),            # pSid
]

# FreeSid
advapi32.FreeSid.restype = ctypes.c_void_p
advapi32.FreeSid.argtypes = [ctypes.c_void_p]

# InitializeAcl
advapi32.InitializeAcl.restype = ctypes.c_bool
advapi32.InitializeAcl.argtypes = [
    ctypes.c_void_p,   # pAcl
    ctypes.c_ulong,    # nAclLength
    ctypes.c_ulong,    # dwAclRevision
]

# AddAccessDeniedAce
advapi32.AddAccessDeniedAce.restype = ctypes.c_bool
advapi32.AddAccessDeniedAce.argtypes = [
    ctypes.c_void_p,   # pAcl
    ctypes.c_ulong,    # dwAceRevision
    ctypes.c_ulong,    # AccessMask
    ctypes.c_void_p,   # pSid
]

# SetSecurityInfo
advapi32.SetSecurityInfo.restype = ctypes.c_ulong
advapi32.SetSecurityInfo.argtypes = [
    ctypes.c_void_p,   # handle
    ctypes.c_ulong,    # ObjectType (SE_OBJECT_TYPE)
    ctypes.c_ulong,    # SecurityInfo
    ctypes.c_void_p,   # psidOwner
    ctypes.c_void_p,   # psidGroup
    ctypes.c_void_p,   # pDacl
    ctypes.c_void_p,   # pSacl
]

# GetLengthSid
advapi32.GetLengthSid.restype = ctypes.c_ulong
advapi32.GetLengthSid.argtypes = [ctypes.c_void_p]

# OpenProcess
kernel32.OpenProcess.restype = ctypes.c_void_p
kernel32.OpenProcess.argtypes = [ctypes.c_ulong, ctypes.c_bool, ctypes.c_ulong]

# GetCurrentProcess
kernel32.GetCurrentProcess.restype = ctypes.c_void_p

# CloseHandle
kernel32.CloseHandle.restype = ctypes.c_bool
kernel32.CloseHandle.argtypes = [ctypes.c_void_p]

# SetPriorityClass
kernel32.SetPriorityClass.restype = ctypes.c_bool
kernel32.SetPriorityClass.argtypes = [ctypes.c_void_p, ctypes.c_ulong]


# ============================================================================
# Funciones de protección
# ============================================================================

def _create_everyone_sid():
    """
    Crea un SID para el grupo Everyone (S-1-1-0).
    
    Returns:
        ctypes.c_void_p: Puntero al SID de Everyone, o None si falla.
        Debe liberarse con advapi32.FreeSid() cuando ya no se necesite.
    """
    sia = SID_IDENTIFIER_AUTHORITY()
    sia.Value[5] = 1  # SECURITY_WORLD_SID_AUTHORITY
    
    everyone_sid = ctypes.c_void_p()
    
    success = advapi32.AllocateAndInitializeSid(
        ctypes.byref(sia),
        1,                      # nSubAuthorityCount
        SECURITY_WORLD_RID,     # dwSubAuthority0 (0 = Everyone)
        0, 0, 0, 0, 0, 0, 0,   # dwSubAuthority1-7 (no usados)
        ctypes.byref(everyone_sid)
    )
    
    if not success or not everyone_sid.value:
        return None
    
    return everyone_sid


def _apply_dacl_protection(process_handle):
    """
    Aplica una DACL (Discretionary Access Control List) al proceso que niega
    PROCESS_TERMINATE y otros derechos peligrosos al grupo Everyone.
    
    Esto hace que:
    - Task Manager no pueda matar el proceso (usuarios normales e incluso admin)
    - taskkill /F no funcione desde cuentas no-SYSTEM
    - Solo SYSTEM (que ejecuta el servicio) pueda terminar el proceso
    
    Args:
        process_handle: Handle del proceso a proteger (con permisos WRITE_DAC)
    
    Returns:
        bool: True si la protección se aplicó correctamente
    """
    everyone_sid = None
    
    try:
        # Crear SID de Everyone
        everyone_sid = _create_everyone_sid()
        if not everyone_sid:
            return False
        
        # Calcular tamaño del ACL
        sid_length = advapi32.GetLengthSid(everyone_sid)
        # Tamaño base del ACL + tamaño del ACE (header + mask + SID)
        # ACE header = 4 bytes, Access mask = 4 bytes
        acl_size = ctypes.sizeof(ACL) + 4 + 4 + sid_length
        # Alinear a DWORD
        acl_size = (acl_size + 3) & ~3
        
        # Crear el buffer del ACL
        acl_buffer = ctypes.create_string_buffer(acl_size)
        
        # Inicializar el ACL
        if not advapi32.InitializeAcl(acl_buffer, acl_size, ACL_REVISION):
            return False
        
        # Agregar ACE de denegación para Everyone
        # Esto niega PROCESS_TERMINATE y otros derechos peligrosos
        if not advapi32.AddAccessDeniedAce(
            acl_buffer,
            ACL_REVISION,
            DENIED_ACCESS_MASK,
            everyone_sid
        ):
            return False
        
        # Aplicar la DACL al proceso
        result = advapi32.SetSecurityInfo(
            process_handle,
            SE_KERNEL_OBJECT,
            DACL_SECURITY_INFORMATION,
            None,   # No cambiar owner
            None,   # No cambiar group
            acl_buffer,
            None    # No cambiar SACL
        )
        
        return result == 0  # ERROR_SUCCESS
        
    except Exception:
        return False
    finally:
        if everyone_sid and everyone_sid.value:
            advapi32.FreeSid(everyone_sid)


def protect_current_process():
    """
    Protege el proceso actual contra terminación aplicando DACL.
    Niega PROCESS_TERMINATE al grupo Everyone.
    Solo SYSTEM podrá terminar este proceso.
    
    Returns:
        bool: True si la protección se aplicó correctamente
    """
    try:
        process_handle = kernel32.GetCurrentProcess()
        return _apply_dacl_protection(process_handle)
    except Exception:
        return False


def protect_process_by_pid(pid):
    """
    Protege un proceso externo (por PID) contra terminación aplicando DACL.
    Usado por service.py para proteger el proceso hijo CiberMondayClient.exe.
    
    Args:
        pid: ID del proceso a proteger
    
    Returns:
        bool: True si la protección se aplicó correctamente
    """
    process_handle = None
    try:
        # Necesitamos WRITE_DAC para modificar la DACL del proceso
        process_handle = kernel32.OpenProcess(
            WRITE_DAC | READ_CONTROL,
            False,
            pid
        )
        
        if not process_handle:
            return False
        
        return _apply_dacl_protection(process_handle)
    except Exception:
        return False
    finally:
        if process_handle:
            kernel32.CloseHandle(process_handle)


def set_process_priority_high():
    """Establece la prioridad del proceso actual como alta"""
    try:
        process_handle = kernel32.GetCurrentProcess()
        return bool(kernel32.SetPriorityClass(process_handle, HIGH_PRIORITY_CLASS))
    except Exception:
        return False


def disable_task_manager():
    """
    Deshabilita el administrador de tareas temporalmente via registro.
    ADVERTENCIA: Esto puede ser detectado por antivirus y es muy invasivo.
    Solo usar en entornos controlados (cyber cafés).
    """
    try:
        import winreg
        
        key_path = r"Software\Microsoft\Windows\CurrentVersion\Policies\System"
        
        try:
            key = winreg.OpenKey(
                winreg.HKEY_CURRENT_USER,
                key_path,
                0,
                winreg.KEY_SET_VALUE
            )
        except FileNotFoundError:
            # La clave no existe, crearla
            key = winreg.CreateKey(winreg.HKEY_CURRENT_USER, key_path)
        
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
        except FileNotFoundError:
            pass
        
        winreg.CloseKey(key)
        return True
    except Exception:
        return False


def apply_protections():
    """
    Aplica todas las protecciones disponibles al proceso actual.
    Se ejecuta al inicio del cliente.
    
    Protecciones aplicadas:
    1. Prioridad alta del proceso
    2. Protección DACL contra terminación (niega PROCESS_TERMINATE a Everyone)
    
    Returns:
        list: Lista de protecciones aplicadas exitosamente
    """
    protections_applied = []
    
    # Establecer prioridad alta
    if set_process_priority_high():
        protections_applied.append("Prioridad alta establecida")
    
    # Aplicar protección DACL (la más importante)
    if protect_current_process():
        protections_applied.append("Protección DACL aplicada (proceso protegido contra terminación)")
    
    return protections_applied
