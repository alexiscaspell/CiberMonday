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
    root.geometry("700x800")
    root.resizable(True, True)
    root.minsize(650, 750)
    
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
    
    # Frame para botones (primero, para que quede en la parte inferior)
    button_container = ttk.Frame(root)
    button_container.pack(fill=tk.X, side=tk.BOTTOM, padx=20, pady=15)
    
    # Frame principal con scroll (arriba de los botones)
    canvas_frame = ttk.Frame(root)
    canvas_frame.pack(fill=tk.BOTH, expand=True, before=button_container)
    
    canvas = tk.Canvas(canvas_frame)
    scrollbar = ttk.Scrollbar(canvas_frame, orient="vertical", command=canvas.yview)
    scrollable_frame = ttk.Frame(canvas)
    
    scrollable_frame.bind(
        "<Configure>",
        lambda e: canvas.configure(scrollregion=canvas.bbox("all"))
    )
    
    canvas.create_window((0, 0), window=scrollable_frame, anchor="nw")
    canvas.configure(yscrollcommand=scrollbar.set)
    
    # Frame principal (ahora dentro del scrollable_frame)
    main_frame = ttk.Frame(scrollable_frame, padding="20")
    main_frame.pack(fill=tk.BOTH, expand=True)
    
    # Pack canvas y scrollbar
    canvas.pack(side="left", fill="both", expand=True)
    scrollbar.pack(side="right", fill="y")
    
    # Configurar scroll con mouse wheel
    def _on_mousewheel(event):
        canvas.yview_scroll(int(-1*(event.delta/120)), "units")
    canvas.bind_all("<MouseWheel>", _on_mousewheel)
    
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
    
    # Frame para intervalo de sincronización
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
    
    # Separador para configuración avanzada
    separator = ttk.Separator(main_frame, orient='horizontal')
    separator.pack(fill=tk.X, pady=(15, 10))
    
    # Título de configuración avanzada
    advanced_label = tk.Label(
        main_frame,
        text="⚙️ Configuración Avanzada",
        font=("Arial", 11, "bold")
    )
    advanced_label.pack(anchor=tk.W, pady=(0, 10))
    
    # Frame para intervalo de verificación local
    local_check_frame = ttk.Frame(main_frame)
    local_check_frame.pack(fill=tk.X, pady=5)
    
    local_check_label = ttk.Label(local_check_frame, text="Intervalo de Verificación Local (segundos):")
    local_check_label.pack(anchor=tk.W, pady=(0, 5))
    
    local_check_var = tk.StringVar()
    current_local_check = current_config.get('local_check_interval', 1) if current_config else 1
    local_check_var.set(str(current_local_check))
    
    local_check_entry = ttk.Entry(local_check_frame, textvariable=local_check_var, width=10, font=("Arial", 10))
    local_check_entry.pack(side=tk.LEFT, pady=(0, 5))
    
    local_check_desc = tk.Label(
        local_check_frame,
        text="(Cada cuántos segundos verifica el tiempo local. Recomendado: 1)",
        font=("Arial", 8),
        fg="gray"
    )
    local_check_desc.pack(side=tk.LEFT, padx=(10, 0), pady=(0, 5))
    
    # Frame para intervalo de sincronización cuando está expirado
    expired_sync_frame = ttk.Frame(main_frame)
    expired_sync_frame.pack(fill=tk.X, pady=5)
    
    expired_sync_label = ttk.Label(expired_sync_frame, text="Intervalo de Sincronización (Tiempo Expirado) (segundos):")
    expired_sync_label.pack(anchor=tk.W, pady=(0, 5))
    
    expired_sync_var = tk.StringVar()
    current_expired_sync = current_config.get('expired_sync_interval', 2) if current_config else 2
    expired_sync_var.set(str(current_expired_sync))
    
    expired_sync_entry = ttk.Entry(expired_sync_frame, textvariable=expired_sync_var, width=10, font=("Arial", 10))
    expired_sync_entry.pack(side=tk.LEFT, pady=(0, 5))
    
    expired_sync_desc = tk.Label(
        expired_sync_frame,
        text="(Cada cuántos segundos sincroniza cuando el tiempo expiró. Recomendado: 2)",
        font=("Arial", 8),
        fg="gray"
    )
    expired_sync_desc.pack(side=tk.LEFT, padx=(10, 0), pady=(0, 5))
    
    # Frame para tiempo de bloqueo (delay antes de bloquear)
    lock_delay_frame = ttk.Frame(main_frame)
    lock_delay_frame.pack(fill=tk.X, pady=5)
    
    lock_delay_label = ttk.Label(lock_delay_frame, text="Tiempo de Espera Antes de Bloquear (segundos):")
    lock_delay_label.pack(anchor=tk.W, pady=(0, 5))
    
    lock_delay_var = tk.StringVar()
    current_lock_delay = current_config.get('lock_delay', 2) if current_config else 2
    lock_delay_var.set(str(current_lock_delay))
    
    lock_delay_entry = ttk.Entry(lock_delay_frame, textvariable=lock_delay_var, width=10, font=("Arial", 10))
    lock_delay_entry.pack(side=tk.LEFT, pady=(0, 5))
    
    lock_delay_desc = tk.Label(
        lock_delay_frame,
        text="(Tiempo de espera antes de bloquear cuando se desloguea. Recomendado: 2-5)",
        font=("Arial", 8),
        fg="gray"
    )
    lock_delay_desc.pack(side=tk.LEFT, padx=(10, 0), pady=(0, 5))
    
    # Frame para umbrales de notificación
    warning_thresholds_frame = ttk.Frame(main_frame)
    warning_thresholds_frame.pack(fill=tk.X, pady=5)
    
    warning_thresholds_label = ttk.Label(warning_thresholds_frame, text="Umbrales de Notificación (minutos, separados por comas):")
    warning_thresholds_label.pack(anchor=tk.W, pady=(0, 5))
    
    warning_thresholds_var = tk.StringVar()
    current_thresholds = current_config.get('warning_thresholds', [10, 5, 2, 1]) if current_config else [10, 5, 2, 1]
    warning_thresholds_var.set(','.join(map(str, current_thresholds)))
    
    warning_thresholds_entry = ttk.Entry(warning_thresholds_frame, textvariable=warning_thresholds_var, width=30, font=("Arial", 10))
    warning_thresholds_entry.pack(side=tk.LEFT, pady=(0, 5))
    
    warning_thresholds_desc = tk.Label(
        warning_thresholds_frame,
        text="(Minutos restantes para mostrar notificaciones. Ej: 10,5,2,1)",
        font=("Arial", 8),
        fg="gray"
    )
    warning_thresholds_desc.pack(side=tk.LEFT, padx=(10, 0), pady=(0, 5))
    
    # Frame para botones (ya está creado arriba, solo crear el frame interno)
    button_frame = ttk.Frame(button_container)
    button_frame.pack(fill=tk.X)
    
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
        
        # Validar intervalo de verificación local
        try:
            local_check_interval = int(local_check_var.get().strip())
            if local_check_interval < 1:
                messagebox.showerror("Error", "El intervalo de verificación local debe ser al menos 1 segundo")
                return
            if local_check_interval > 60:
                messagebox.showerror("Error", "El intervalo de verificación local no debe ser mayor a 60 segundos")
                return
        except ValueError:
            messagebox.showerror("Error", "El intervalo de verificación local debe ser un número válido")
            return
        
        # Validar intervalo de sincronización cuando está expirado
        try:
            expired_sync_interval = int(expired_sync_var.get().strip())
            if expired_sync_interval < 1:
                messagebox.showerror("Error", "El intervalo de sincronización (tiempo expirado) debe ser al menos 1 segundo")
                return
            if expired_sync_interval > 60:
                messagebox.showerror("Error", "El intervalo de sincronización (tiempo expirado) no debe ser mayor a 60 segundos")
                return
        except ValueError:
            messagebox.showerror("Error", "El intervalo de sincronización (tiempo expirado) debe ser un número válido")
            return
        
        # Validar tiempo de espera antes de bloquear
        try:
            lock_delay = int(lock_delay_var.get().strip())
            if lock_delay < 0:
                messagebox.showerror("Error", "El tiempo de espera antes de bloquear no puede ser negativo")
                return
            if lock_delay > 30:
                messagebox.showerror("Error", "El tiempo de espera antes de bloquear no debe ser mayor a 30 segundos")
                return
        except ValueError:
            messagebox.showerror("Error", "El tiempo de espera antes de bloquear debe ser un número válido")
            return
        
        # Validar umbrales de notificación
        try:
            thresholds_str = warning_thresholds_var.get().strip()
            if thresholds_str:
                thresholds_list = [int(x.strip()) for x in thresholds_str.split(',') if x.strip()]
                if not thresholds_list:
                    messagebox.showerror("Error", "Debe ingresar al menos un umbral de notificación")
                    return
                # Validar que sean números positivos y ordenados de mayor a menor
                if any(t <= 0 for t in thresholds_list):
                    messagebox.showerror("Error", "Los umbrales de notificación deben ser números positivos")
                    return
                # Ordenar de mayor a menor
                thresholds_list.sort(reverse=True)
            else:
                thresholds_list = [10, 5, 2, 1]  # Valores por defecto
        except ValueError:
            messagebox.showerror("Error", "Los umbrales de notificación deben ser números separados por comas (ej: 10,5,2,1)")
            return
        
        # Guardar configuración
        config = {
            'server_url': server_url,
            'check_interval': 5,  # Mantener para compatibilidad
            'sync_interval': sync_interval,
            'local_check_interval': local_check_interval,
            'expired_sync_interval': expired_sync_interval,
            'lock_delay': lock_delay,
            'warning_thresholds': thresholds_list
        }
        
        if REGISTRY_AVAILABLE:
            if save_config_to_registry(config):
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
