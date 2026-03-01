"""
CiberMonday Client - Entry point cross-platform.
Detecta la plataforma y lanza el cliente correspondiente (WindowsClient o LinuxClient).
La plataforma se puede forzar con --platform windows|linux, o se auto-detecta con sys.platform.
"""

import sys


def detect_platform():
    for i, arg in enumerate(sys.argv):
        if arg == '--platform' and i + 1 < len(sys.argv):
            return sys.argv[i + 1]
    if sys.platform == 'win32':
        return 'windows'
    elif sys.platform.startswith('linux'):
        return 'linux'
    return sys.platform


def main():
    platform = detect_platform()

    if platform == 'windows':
        from client_windows import WindowsClient
        client = WindowsClient()
    elif platform == 'linux':
        from client_linux import LinuxClient
        client = LinuxClient()
    else:
        print(f"ERROR: Plataforma no soportada: {platform}")
        print("Plataformas soportadas: windows, linux")
        print("Usa --platform windows|linux para forzar.")
        sys.exit(1)

    client.run()


if __name__ == '__main__':
    main()
