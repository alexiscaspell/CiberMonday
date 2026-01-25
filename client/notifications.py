"""
Módulo para mostrar notificaciones de tiempo restante al usuario
"""

import threading
import sys

try:
    import tkinter as tk
    from tkinter import ttk
    TKINTER_AVAILABLE = True
except ImportError:
    TKINTER_AVAILABLE = False

def show_time_warning(remaining_minutes):
    """
    Muestra una ventana de advertencia con el tiempo restante.
    
    Args:
        remaining_minutes: Minutos restantes (int)
    """
    if not TKINTER_AVAILABLE:
        # Si Tkinter no está disponible, solo imprimir en consola
        print(f"\n{'='*50}")
        print(f"ADVERTENCIA: Quedan {remaining_minutes} minutos")
        print(f"{'='*50}\n")
        return
    
    def create_window():
        """Crea y muestra la ventana de notificación en un hilo separado"""
        try:
            root = tk.Tk()
            root.title("CiberMonday - Advertencia de Tiempo")
            
            # Configurar ventana siempre visible
            root.attributes('-topmost', True)
            root.resizable(False, False)
            
            # Centrar ventana en pantalla
            window_width = 400
            window_height = 200
            screen_width = root.winfo_screenwidth()
            screen_height = root.winfo_screenheight()
            x = (screen_width - window_width) // 2
            y = (screen_height - window_height) // 2
            root.geometry(f"{window_width}x{window_height}+{x}+{y}")
            
            # Estilo
            root.configure(bg='#f0f0f0')
            
            # Frame principal
            main_frame = tk.Frame(root, bg='#f0f0f0', padx=20, pady=20)
            main_frame.pack(fill=tk.BOTH, expand=True)
            
            # Icono de advertencia (emoji o texto)
            warning_label = tk.Label(
                main_frame,
                text="⚠️",
                font=("Arial", 32),
                bg='#f0f0f0',
                fg='#ff6600'
            )
            warning_label.pack(pady=(0, 10))
            
            # Mensaje principal
            if remaining_minutes == 1:
                message = f"¡Atención!\nQueda {remaining_minutes} minuto de tiempo"
            else:
                message = f"¡Atención!\nQuedan {remaining_minutes} minutos de tiempo"
            
            message_label = tk.Label(
                main_frame,
                text=message,
                font=("Arial", 14, "bold"),
                bg='#f0f0f0',
                fg='#333333',
                justify=tk.CENTER
            )
            message_label.pack(pady=(0, 20))
            
            # Mensaje secundario
            info_label = tk.Label(
                main_frame,
                text="La PC se bloqueará automáticamente\ncuando se agote el tiempo.",
                font=("Arial", 10),
                bg='#f0f0f0',
                fg='#666666',
                justify=tk.CENTER
            )
            info_label.pack(pady=(0, 20))
            
            # Botón de cerrar
            close_button = tk.Button(
                main_frame,
                text="Entendido",
                font=("Arial", 11, "bold"),
                bg='#4CAF50',
                fg='white',
                activebackground='#45a049',
                activeforeground='white',
                relief=tk.FLAT,
                padx=30,
                pady=10,
                cursor='hand2',
                command=root.destroy
            )
            close_button.pack()
            
            # Hacer focus en el botón
            close_button.focus_set()
            
            # Cerrar con Enter
            root.bind('<Return>', lambda e: root.destroy())
            root.bind('<Escape>', lambda e: root.destroy())
            
            # Mostrar ventana
            root.mainloop()
        except Exception as e:
            print(f"Error al mostrar notificación: {e}")
            # Fallback a consola
            print(f"\n{'='*50}")
            print(f"ADVERTENCIA: Quedan {remaining_minutes} minutos")
            print(f"{'='*50}\n")
    
    # Crear y ejecutar ventana en un hilo separado para no bloquear el cliente
    thread = threading.Thread(target=create_window, daemon=True)
    thread.start()
