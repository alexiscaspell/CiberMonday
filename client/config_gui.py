"""
Interfaz gráfica para configurar el cliente CiberMonday
Se muestra al iniciar si no hay configuración guardada
"""

import tkinter as tk
from tkinter import ttk, messagebox
import sys
import os

# Importar gestor de registro
try:
    from registry_manager import (
        save_config_to_registry,
        get_config_from_registry
    )
    REGISTRY_AVAILABLE = True
except ImportError:
    REGISTRY_AVAILABLE = False

def show_config_window():
    """
    Muestra la ventana de configuración con los valores actuales
    Permite modificar y actualizar la configuración
    Retorna la configuración actualizada o None si el usuario cancela
    """
    # Cargar configuración existente si hay
    current_config = None
    if REGISTRY_AVAILABLE:
        current_config = get_config_from_registry()
    
    # Crear ventana principal
    root = tk.Tk()
    root.title("CiberMonday - Configuración del Cliente")
    root.geometry("550x450")
    root.resizable(False, False)
    
    # Centrar ventana
    root.update_idletasks()
    width = root.winfo_width()
    height = root.winfo_height()
    x = (root.winfo_screenwidth() // 2) - (width // 2)
    y = (root.winfo_screenheight() // 2) - (height // 2)
    root.geometry(f'{width}x{height}+{x}+{y}')
    
    # Variable para almacenar el resultado
    config_result = None
    
    # Estilos
    style = ttk.Style()
    style.theme_use('clam')
    
    # Frame principal
    main_frame = ttk.Frame(root, padding="20")
    main_frame.pack(fill=tk.BOTH, expand=True)
    
    # Título
    title_label = tk.Label(
        main_frame,
        text="🖥️ Configuración de CiberMonday",
        font=("Arial", 16, "bold")
    )
    title_label.pack(pady=(0, 10))
    
    # Mensaje informativo
    if current_config:
        info_label = tk.Label(
            main_frame,
            text="Configuración actual detectada. Puedes modificar los valores:",
            font=("Arial", 9),
            fg="green"
        )
        info_label.pack(pady=(0, 15))
    else:
        desc_label = tk.Label(
            main_frame,
            text="Ingresa la dirección del servidor para conectarte:",
            font=("Arial", 10)
        )
        desc_label.pack(pady=(0, 15))
    
    # Frame para el campo de entrada
    input_frame = ttk.Frame(main_frame)
    input_frame.pack(fill=tk.X, pady=10)
    
    # Etiqueta
    url_label = ttk.Label(input_frame, text="URL del Servidor:")
    url_label.pack(anchor=tk.W, pady=(0, 5))
    
    # Campo de entrada
    url_var = tk.StringVar()
    # Cargar valor actual si existe
    current_url = current_config.get('server_url', 'http://localhost:5000') if current_config else 'http://localhost:5000'
    url_var.set(current_url)
    
    url_entry = ttk.Entry(input_frame, textvariable=url_var, width=50, font=("Arial", 10))
    url_entry.pack(fill=tk.X, pady=(0, 5))
    url_entry.focus()
    url_entry.select_range(0, tk.END)  # Seleccionar todo el texto para fácil edición
    
    # Ejemplos
    examples_label = tk.Label(
        input_frame,
        text="Ejemplos:\n• http://localhost:5000 (servidor local)\n• http://192.168.1.100:5000 (servidor en red local)",
        font=("Arial", 8),
        fg="gray",
        justify=tk.LEFT
    )
    examples_label.pack(anchor=tk.W, pady=(5, 15))
    
    # Frame para intervalo de chequeo
    interval_frame = ttk.Frame(main_frame)
    interval_frame.pack(fill=tk.X, pady=10)
    
    # Etiqueta para intervalo
    interval_label = ttk.Label(interval_frame, text="Intervalo de Sincronización (segundos):")
    interval_label.pack(anchor=tk.W, pady=(0, 5))
    
    # Campo de entrada para intervalo
    interval_var = tk.StringVar()
    # Cargar valor actual si existe
    current_interval = current_config.get('sync_interval', 30) if current_config else 30
    interval_var.set(str(current_interval))
    
    interval_entry = ttk.Entry(interval_frame, textvariable=interval_var, width=10, font=("Arial", 10))
    interval_entry.pack(side=tk.LEFT, pady=(0, 5))
    
    # Descripción del intervalo
    interval_desc = tk.Label(
        interval_frame,
        text="(Cada cuántos segundos se sincroniza con el servidor. Recomendado: 30)",
        font=("Arial", 8),
        fg="gray"
    )
    interval_desc.pack(side=tk.LEFT, padx=(10, 0), pady=(0, 5))
    
    # Frame para umbrales de alerta
    alerts_frame = ttk.Frame(main_frame)
    alerts_frame.pack(fill=tk.X, pady=10)
    
    # Etiqueta para alertas
    alerts_label = ttk.Label(alerts_frame, text="Umbrales de Alerta (minutos):")
    alerts_label.pack(anchor=tk.W, pady=(0, 5))
    
    # Campo de entrada para alertas
    alerts_var = tk.StringVar()
    # Cargar valor actual si existe (convertir segundos a minutos)
    current_alerts_seconds = current_config.get('alert_thresholds', [600, 300, 120, 60]) if current_config else [600, 300, 120, 60]
    current_alerts_minutes = [s // 60 for s in current_alerts_seconds]
    alerts_var.set(', '.join(map(str, current_alerts_minutes)))
    
    alerts_entry = ttk.Entry(alerts_frame, textvariable=alerts_var, width=30, font=("Arial", 10))
    alerts_entry.pack(side=tk.LEFT, pady=(0, 5))
    
    # Descripción de alertas
    alerts_desc = tk.Label(
        alerts_frame,
        text="(ej: 10, 5, 2, 1 = alertas a 10, 5, 2, 1 minutos)",
        font=("Arial", 8),
        fg="gray"
    )
    alerts_desc.pack(side=tk.LEFT, padx=(10, 0), pady=(0, 5))
    
    # Frame para botones
    button_frame = ttk.Frame(main_frame)
    button_frame.pack(fill=tk.X, pady=(20, 0))
    
    def validate_and_save():
        """Valida y guarda la configuración"""
        server_url = url_var.get().strip()
        
        if not server_url:
            messagebox.showerror("Error", "Por favor ingresa la URL del servidor")
            return
        
        # Validar formato básico
        if not server_url.startswith(('http://', 'https://')):
            messagebox.showerror("Error", "La URL debe comenzar con http:// o https://")
            return
        
        # Validar intervalo de sincronización
        try:
            sync_interval = int(interval_var.get().strip())
            if sync_interval < 5:
                messagebox.showerror("Error", "El intervalo de sincronización debe ser al menos 5 segundos")
                return
            if sync_interval > 300:
                messagebox.showerror("Error", "El intervalo de sincronización no debe ser mayor a 300 segundos (5 minutos)")
                return
        except ValueError:
            messagebox.showerror("Error", "El intervalo de sincronización debe ser un número válido")
            return
        
        # Validar umbrales de alerta (en minutos, convertir a segundos)
        try:
            alerts_str = alerts_var.get().strip()
            alert_minutes = [float(x.strip()) for x in alerts_str.split(',') if x.strip()]
            if len(alert_minutes) == 0:
                messagebox.showerror("Error", "Debes especificar al menos un umbral de alerta en minutos")
                return
            if any(t <= 0 for t in alert_minutes):
                messagebox.showerror("Error", "Los umbrales de alerta deben ser números positivos")
                return
            # Convertir minutos a segundos y ordenar de mayor a menor
            alert_thresholds = sorted([int(m * 60) for m in alert_minutes], reverse=True)
        except ValueError:
            messagebox.showerror("Error", "Los umbrales de alerta deben ser números separados por comas (ej: 10, 5, 2, 1)")
            return
        
        # Guardar configuración
        config = {
            'server_url': server_url,
            'check_interval': 5,  # Mantener para compatibilidad
            'sync_interval': sync_interval,
            'alert_thresholds': alert_thresholds
        }
        
        if REGISTRY_AVAILABLE:
            if save_config_to_registry(config):
                # Agregar el servidor a la lista de servidores conocidos
                try:
                    from registry_manager import get_servers_from_registry, save_servers_to_registry
                    from datetime import datetime
                    import re
                    
                    # Extraer IP y puerto de la URL
                    url_match = re.match(r'http://([^:]+):?(\d+)?', server_url)
                    server_ip = url_match.group(1) if url_match else None
                    server_port = int(url_match.group(2)) if url_match and url_match.group(2) else 5000
                    
                    # Obtener lista actual de servidores conocidos
                    known_servers = get_servers_from_registry()
                    
                    # Verificar si el servidor ya existe
                    server_exists = any(s.get('url') == server_url for s in known_servers)
                    
                    if not server_exists:
                        # Agregar nuevo servidor a la lista
                        known_servers.append({
                            'url': server_url,
                            'ip': server_ip,
                            'port': server_port,
                            'last_seen': datetime.now().isoformat()
                        })
                        save_servers_to_registry(known_servers)
                        print(f"[Config] Servidor {server_url} agregado a la lista de servidores conocidos")
                    else:
                        # Actualizar last_seen del servidor existente
                        for server in known_servers:
                            if server.get('url') == server_url:
                                server['last_seen'] = datetime.now().isoformat()
                                if server_ip:
                                    server['ip'] = server_ip
                                if server_port:
                                    server['port'] = server_port
                                break
                        save_servers_to_registry(known_servers)
                        print(f"[Config] Servidor {server_url} actualizado en la lista de servidores conocidos")
                except Exception as e:
                    print(f"[Config] Advertencia: No se pudo actualizar lista de servidores: {e}")
                
                nonlocal config_result
                config_result = config
                root.quit()
                root.destroy()
            else:
                messagebox.showerror(
                    "Error",
                    "No se pudo guardar la configuración.\n\n"
                    "Asegúrate de ejecutar como Administrador."
                )
        else:
            # Fallback: guardar en archivo si no hay registro
            try:
                config_file = os.path.join(os.path.dirname(__file__), 'config.py')
                with open(config_file, 'w') as f:
                    f.write(f'SERVER_URL = "{server_url}"\n')
                    f.write(f'CHECK_INTERVAL = 5\n')
                    f.write(f'SYNC_INTERVAL = {sync_interval}\n')
                    f.write(f'ALERT_THRESHOLDS = {alert_thresholds}  # En segundos\n')
                config_result = config
                root.quit()
                root.destroy()
            except Exception as e:
                messagebox.showerror("Error", f"No se pudo guardar la configuración: {e}")
    
    def cancel():
        """Cancela la configuración"""
        if current_config:
            # Si ya hay configuración, solo cerrar sin salir
            root.quit()
            root.destroy()
        else:
            # Si no hay configuración, preguntar antes de salir
            result = messagebox.askyesno(
                "Confirmar",
                "¿Estás seguro de que quieres cancelar?\n\n"
                "El cliente no podrá funcionar sin configuración."
            )
            if result:
                root.quit()
                root.destroy()
                sys.exit(0)
    
    # Botones
    if current_config:
        save_button = ttk.Button(
            button_frame,
            text="Actualizar y Continuar",
            command=validate_and_save,
            width=22
        )
        save_button.pack(side=tk.RIGHT, padx=(10, 0))
        
        cancel_button = ttk.Button(
            button_frame,
            text="Usar Valores Actuales",
            command=cancel,
            width=20
        )
        cancel_button.pack(side=tk.RIGHT)
    else:
        save_button = ttk.Button(
            button_frame,
            text="Guardar y Continuar",
            command=validate_and_save,
            width=20
        )
        save_button.pack(side=tk.RIGHT, padx=(10, 0))
        
        cancel_button = ttk.Button(
            button_frame,
            text="Cancelar",
            command=cancel,
            width=15
        )
        cancel_button.pack(side=tk.RIGHT)
    
    # Permitir Enter para guardar
    url_entry.bind('<Return>', lambda e: validate_and_save())
    
    # Manejar cierre de ventana
    root.protocol("WM_DELETE_WINDOW", cancel)
    
    # Mostrar ventana
    root.mainloop()
    
    return config_result

def get_config(always_show=False):
    """
    Obtiene la configuración desde el registro o muestra la ventana de configuración
    
    Args:
        always_show: Si es True, siempre muestra la ventana (para reconfigurar)
    
    Returns:
        dict con configuración o None si se cancela
    """
    # Si se solicita mostrar siempre, mostrar ventana
    if always_show:
        return show_config_window()
    
    # Intentar obtener del registro
    if REGISTRY_AVAILABLE:
        config = get_config_from_registry()
        if config and config.get('server_url'):
            return config
    
    # Si no hay configuración, mostrar ventana
    return show_config_window()

if __name__ == '__main__':
    # Para probar la ventana
    config = show_config_window()
    if config:
        print(f"Configuración guardada: {config}")
    else:
        print("Configuración cancelada")
