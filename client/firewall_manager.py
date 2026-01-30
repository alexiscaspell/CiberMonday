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
        return ctypes.windll.shell32.IsUserAnAdmin() != 0
    except:
        return False

def add_firewall_rule():
    """
    Agrega una regla al firewall de Windows para permitir tráfico UDP en el puerto de descubrimiento.
    
    Returns:
        bool: True si se agregó correctamente, False en caso contrario
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
        result = subprocess.run(check_cmd, capture_output=True, text=True, timeout=5)
        
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
        
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=10)
        
        if result.returncode == 0:
            print(f"[Firewall] ✅ Regla del firewall agregada exitosamente")
            print(f"[Firewall] Puerto UDP {DISCOVERY_PORT} ahora está permitido para recibir broadcasts")
            return True
        else:
            print(f"[Firewall] ❌ Error al agregar regla del firewall: {result.stderr}")
            return False
            
    except subprocess.TimeoutExpired:
        print(f"[Firewall] ❌ Timeout al ejecutar comando del firewall")
        return False
    except Exception as e:
        print(f"[Firewall] ❌ Error al agregar regla del firewall: {e}")
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
        
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=5)
        
        if result.returncode == 0 and FIREWALL_RULE_NAME in result.stdout:
            return True
        return False
            
    except Exception as e:
        print(f"[Firewall] Error al verificar regla: {e}")
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
