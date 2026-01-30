"""
Módulo para gestionar reglas del firewall de Windows.
Permite agregar/eliminar excepciones para el cliente CiberMonday.
"""

import subprocess
import sys
import os

# Puerto UDP usado por el cliente para recibir broadcasts
DISCOVERY_PORT = 5001

# Nombre de la regla del firewall
FIREWALL_RULE_NAME = "CiberMonday Client UDP Discovery"

def is_admin():
    """Verifica si el script se está ejecutando con privilegios de administrador."""
    try:
        import ctypes
        import sys
        # En Windows, verificar si somos administrador
        try:
            return ctypes.windll.shell32.IsUserAnAdmin() != 0
        except AttributeError:
            # Si IsUserAnAdmin no está disponible, intentar otra forma
            try:
                # Intentar abrir una clave del registro que requiere admin
                import winreg
                winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, "SOFTWARE", 0, winreg.KEY_WRITE)
                return True
            except PermissionError:
                return False
            except:
                return False
    except:
        return False

def add_firewall_rule():
    """
    Agrega una regla al firewall de Windows para permitir tráfico UDP en el puerto de descubrimiento.
    
    Returns:
        bool: True si se agregó correctamente o ya existe, False en caso contrario
    """
    if not is_admin():
        print(f"[Firewall] ⚠️  Se requieren privilegios de administrador para agregar regla del firewall")
        print(f"[Firewall] Ejecuta este script como administrador")
        return False
    
    try:
        # Verificar si la regla ya existe
        check_cmd = [
            'netsh', 'advfirewall', 'firewall', 'show', 'rule',
            f'name={FIREWALL_RULE_NAME}'
        ]
        result = subprocess.run(check_cmd, capture_output=True, text=True, timeout=5, creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == 'win32' else 0)
        
        if result.returncode == 0 and FIREWALL_RULE_NAME in result.stdout:
            print(f"[Firewall] ✅ La regla '{FIREWALL_RULE_NAME}' ya existe")
            return True
        
        # Agregar regla del firewall
        cmd = [
            'netsh', 'advfirewall', 'firewall', 'add', 'rule',
            f'name={FIREWALL_RULE_NAME}',
            'dir=in',
            'action=allow',
            'protocol=UDP',
            f'localport={DISCOVERY_PORT}',
            'enable=yes',
            'profile=any',
            'description=Permite que el cliente CiberMonday reciba broadcasts UDP de servidores en la red local'
        ]
        
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=10, creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == 'win32' else 0)
        
        if result.returncode == 0:
            print(f"[Firewall] ✅ Regla del firewall agregada exitosamente")
            print(f"[Firewall] Puerto UDP {DISCOVERY_PORT} ahora está permitido para recibir broadcasts")
            return True
        else:
            error_msg = result.stderr if result.stderr else result.stdout
            print(f"[Firewall] ❌ Error al agregar regla del firewall")
            print(f"[Firewall] Código de salida: {result.returncode}")
            if error_msg:
                print(f"[Firewall] Mensaje: {error_msg}")
            return False
            
    except subprocess.TimeoutExpired:
        print(f"[Firewall] ❌ Timeout al ejecutar comando del firewall")
        return False
    except FileNotFoundError:
        print(f"[Firewall] ❌ Error: netsh no encontrado. Asegúrate de estar en Windows.")
        return False
    except Exception as e:
        print(f"[Firewall] ❌ Error al agregar regla del firewall: {e}")
        import traceback
        traceback.print_exc()
        return False

def remove_firewall_rule():
    """
    Elimina la regla del firewall de Windows.
    
    Returns:
        bool: True si se eliminó correctamente, False en caso contrario
    """
    if not is_admin():
        print(f"[Firewall] ⚠️  Se requieren privilegios de administrador para eliminar regla del firewall")
        return False
    
    try:
        cmd = [
            'netsh', 'advfirewall', 'firewall', 'delete', 'rule',
            f'name={FIREWALL_RULE_NAME}'
        ]
        
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=10)
        
        if result.returncode == 0:
            print(f"[Firewall] ✅ Regla del firewall eliminada exitosamente")
            return True
        else:
            # Si la regla no existe, netsh retorna código de error pero no es crítico
            if "No rules match" in result.stderr or "No se encontraron reglas" in result.stderr:
                print(f"[Firewall] ℹ️  La regla '{FIREWALL_RULE_NAME}' no existe")
                return True
            print(f"[Firewall] ❌ Error al eliminar regla del firewall: {result.stderr}")
            return False
            
    except subprocess.TimeoutExpired:
        print(f"[Firewall] ❌ Timeout al ejecutar comando del firewall")
        return False
    except Exception as e:
        print(f"[Firewall] ❌ Error al eliminar regla del firewall: {e}")
        return False

def check_firewall_rule():
    """
    Verifica si la regla del firewall existe.
    
    Returns:
        bool: True si la regla existe, False en caso contrario
    """
    try:
        cmd = [
            'netsh', 'advfirewall', 'firewall', 'show', 'rule',
            f'name={FIREWALL_RULE_NAME}'
        ]
        
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=5, creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == 'win32' else 0)
        
        if result.returncode == 0 and FIREWALL_RULE_NAME in result.stdout:
            return True
        return False
            
    except FileNotFoundError:
        # netsh no encontrado, probablemente no es Windows
        return False
    except Exception as e:
        # Silenciar errores en verificación para no molestar al usuario
        return False

if __name__ == '__main__':
    """Permite ejecutar este script directamente para agregar/eliminar la regla"""
    import argparse
    
    parser = argparse.ArgumentParser(description='Gestiona reglas del firewall para CiberMonday')
    parser.add_argument('action', choices=['add', 'remove', 'check'], 
                       help='Acción a realizar: add (agregar), remove (eliminar), check (verificar)')
    
    args = parser.parse_args()
    
    if args.action == 'add':
        success = add_firewall_rule()
        sys.exit(0 if success else 1)
    elif args.action == 'remove':
        success = remove_firewall_rule()
        sys.exit(0 if success else 1)
    elif args.action == 'check':
        exists = check_firewall_rule()
        if exists:
            print(f"[Firewall] ✅ La regla '{FIREWALL_RULE_NAME}' existe")
        else:
            print(f"[Firewall] ❌ La regla '{FIREWALL_RULE_NAME}' no existe")
        sys.exit(0 if exists else 1)
