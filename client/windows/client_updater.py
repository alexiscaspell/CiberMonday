"""
Actualización del cliente desde GitHub Releases.

- allow_prerelease=True: última release (incl. prereleases)
- allow_prerelease=False: solo releases estables (prerelease=false)

Requiere HTTPS saliente a api.github.com y github.com (assets).
Si el filtro de red está activo, esos hosts pueden necesitar estar en la allowlist.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
import threading
import urllib.request
from typing import Callable, Optional

GITHUB_REPO = "alexiscaspell/CiberMonday"
API_RELEASES = f"https://api.github.com/repos/{GITHUB_REPO}/releases"
UA = "CiberMondayClient-Updater/1.0"

ProgressCb = Optional[Callable[[str], None]]

WINDOWS_ASSETS = (
    "CiberMondayClient.exe",
    "CiberMondayService.exe",
    "CiberMondayWatchdog.exe",
    "install_exe_service.bat",
    "uninstall_exe_service.bat",
    "show_logs.bat",
)


def _log(cb: ProgressCb, msg: str) -> None:
    print(f"[Updater] {msg}")
    if cb:
        try:
            cb(msg)
        except Exception:
            pass


def _http_json(url: str, timeout: float = 30) -> object:
    req = urllib.request.Request(
        url,
        headers={
            "User-Agent": UA,
            "Accept": "application/vnd.github+json",
        },
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


def _http_download(url: str, dest: str, cb: ProgressCb = None) -> None:
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=120) as resp, open(dest, "wb") as out:
        total = resp.headers.get("Content-Length")
        total_n = int(total) if total and total.isdigit() else 0
        done = 0
        while True:
            chunk = resp.read(256 * 1024)
            if not chunk:
                break
            out.write(chunk)
            done += len(chunk)
            if total_n and cb:
                pct = int(100 * done / total_n)
                _log(cb, f"Descargando… {pct}% ({done // 1024} KB)")


def tag_to_version(tag: str) -> str:
    t = (tag or "").strip()
    if t.startswith("v") or t.startswith("V"):
        t = t[1:]
    return t


def list_releases(per_page: int = 30) -> list[dict]:
    data = _http_json(f"{API_RELEASES}?per_page={per_page}")
    if not isinstance(data, list):
        raise RuntimeError("Respuesta inesperada de GitHub Releases")
    return data


def pick_release(allow_prerelease: bool = True) -> dict:
    """Nueva release no-draft; si allow_prerelease=False, salta prereleases."""
    for rel in list_releases():
        if rel.get("draft"):
            continue
        if not allow_prerelease and rel.get("prerelease"):
            continue
        return rel
    kind = "prerelease o stable" if allow_prerelease else "stable"
    raise RuntimeError(f"No hay release {kind} disponible en GitHub")


def detect_platform() -> str:
    if sys.platform == "win32":
        return "windows"
    if sys.platform.startswith("linux"):
        return "linux"
    return sys.platform


def select_assets(release: dict, plat: Optional[str] = None) -> list[dict]:
    plat = plat or detect_platform()
    assets = release.get("assets") or []
    by_name = {a.get("name"): a for a in assets if a.get("name")}
    chosen = []
    if plat == "windows":
        for name in WINDOWS_ASSETS:
            a = by_name.get(name)
            if a and a.get("browser_download_url"):
                chosen.append(a)
        if not any(a.get("name") == "CiberMondayClient.exe" for a in chosen):
            raise RuntimeError("Release sin CiberMondayClient.exe")
    elif plat == "linux":
        for a in assets:
            name = a.get("name") or ""
            if name.startswith("CiberMondayClient-Linux-") and name.endswith(".tar.gz"):
                chosen.append(a)
                break
        if not chosen:
            raise RuntimeError("Release sin tarball Linux (CiberMondayClient-Linux-*.tar.gz)")
    else:
        raise RuntimeError(f"Plataforma no soportada para update: {plat}")
    return chosen


def default_install_dir() -> str:
    if getattr(sys, "frozen", False):
        return os.path.dirname(sys.executable)
    if sys.platform == "win32":
        return os.path.dirname(os.path.abspath(__file__))
    return "/opt/cibermonday"


def download_update(
    allow_prerelease: bool = True,
    progress_cb: ProgressCb = None,
    install_dir: Optional[str] = None,
) -> dict:
    """
    Descarga assets al temp. Retorna:
      {tag, version, prerelease, files: {name: path}, release}
    """
    rel = pick_release(allow_prerelease=allow_prerelease)
    tag = rel.get("tag_name") or ""
    ver = tag_to_version(tag)
    assets = select_assets(rel)
    _log(progress_cb, f"Release elegida: {tag} (prerelease={bool(rel.get('prerelease'))})")

    tmp = tempfile.mkdtemp(prefix="cm-update-")
    files = {}
    try:
        for a in assets:
            name = a["name"]
            url = a["browser_download_url"]
            dest = os.path.join(tmp, name)
            _log(progress_cb, f"Descargando {name}…")
            _http_download(url, dest, progress_cb)
            files[name] = dest
        return {
            "tag": tag,
            "version": ver,
            "prerelease": bool(rel.get("prerelease")),
            "files": files,
            "tmpdir": tmp,
            "install_dir": install_dir or default_install_dir(),
            "release": rel,
        }
    except Exception:
        shutil.rmtree(tmp, ignore_errors=True)
        raise


def _win_sc(*args: str, timeout: int = 60) -> subprocess.CompletedProcess:
    creation = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    return subprocess.run(
        ["sc", *args],
        capture_output=True,
        text=True,
        timeout=timeout,
        creationflags=creation,
    )


def install_windows(bundle: dict, progress_cb: ProgressCb = None) -> None:
    dest_dir = bundle["install_dir"]
    files: dict = bundle["files"]
    os.makedirs(dest_dir, exist_ok=True)
    _log(progress_cb, "Deteniendo servicio CiberMondayClient…")
    try:
        _win_sc("stop", "CiberMondayClient")
    except Exception as e:
        _log(progress_cb, f"stop service: {e}")

    # Esperar un poco a que suelte los .exe
    import time

    time.sleep(2)

    for name, src in files.items():
        dst = os.path.join(dest_dir, name)
        _log(progress_cb, f"Instalando {name}…")
        # En Windows no se puede sobrescribir un exe en uso: intentar rename viejo
        bak = dst + ".old"
        try:
            if os.path.isfile(dst):
                try:
                    if os.path.isfile(bak):
                        os.remove(bak)
                except OSError:
                    pass
                try:
                    os.replace(dst, bak)
                except OSError:
                    pass
            shutil.copy2(src, dst)
        except Exception as e:
            raise RuntimeError(f"No se pudo copiar {name}: {e}") from e

    _log(progress_cb, "Iniciando servicio…")
    r = _win_sc("start", "CiberMondayClient")
    if r.returncode != 0:
        # Servicio no instalado: sugerir install bat
        bat = os.path.join(dest_dir, "install_exe_service.bat")
        if os.path.isfile(bat):
            _log(progress_cb, "Servicio no arrancó; ejecutá install_exe_service.bat como admin.")
        else:
            _log(progress_cb, f"sc start: {(r.stderr or r.stdout or '').strip()}")
    _log(progress_cb, f"Listo — versión {bundle.get('version')}")


def install_linux(bundle: dict, progress_cb: ProgressCb = None) -> None:
    if os.geteuid() != 0:
        raise RuntimeError("La actualización en Linux requiere root (sudo).")
    dest_dir = bundle.get("install_dir") or "/opt/cibermonday"
    tarball = None
    for name, path in bundle["files"].items():
        if name.endswith(".tar.gz"):
            tarball = path
            break
    if not tarball:
        raise RuntimeError("No hay tarball Linux en el bundle")

    _log(progress_cb, "Deteniendo cibermonday-client…")
    subprocess.run(
        ["systemctl", "stop", "cibermonday-client.service"],
        capture_output=True,
        timeout=60,
    )

    import tarfile

    os.makedirs(dest_dir, exist_ok=True)
    _log(progress_cb, f"Extrayendo en {dest_dir}…")
    with tarfile.open(tarball, "r:gz") as tf:
        # tarball suele contener cibermonday-linux/…
        members = tf.getmembers()
        # Extraer contenido de la carpeta raíz al dest
        for m in members:
            # strip first path component if present
            parts = m.name.split("/", 1)
            if len(parts) == 2:
                m.name = parts[1]
            elif m.isdir():
                continue
            if not m.name or m.name.startswith(".."):
                continue
            tf.extract(m, path=dest_dir)

    for script in ("install_linux.sh", "uninstall_linux.sh", "update_linux.sh", "show_logs.sh"):
        p = os.path.join(dest_dir, script)
        if os.path.isfile(p):
            try:
                os.chmod(p, 0o755)
            except OSError:
                pass
    for f in os.listdir(dest_dir):
        if f.endswith(".py"):
            try:
                os.chmod(os.path.join(dest_dir, f), 0o755)
            except OSError:
                pass

    # Asegurar unit file si vino en el tarball
    unit_src = os.path.join(dest_dir, "cibermonday-client.service")
    if os.path.isfile(unit_src):
        shutil.copy2(unit_src, "/etc/systemd/system/cibermonday-client.service")
        subprocess.run(["systemctl", "daemon-reload"], capture_output=True, timeout=30)

    _log(progress_cb, "Iniciando servicio…")
    r = subprocess.run(
        ["systemctl", "start", "cibermonday-client.service"],
        capture_output=True,
        text=True,
        timeout=60,
    )
    if r.returncode != 0:
        raise RuntimeError(f"systemctl start falló: {(r.stderr or r.stdout or '').strip()}")
    _log(progress_cb, f"Listo — versión {bundle.get('version')}")


def install_update(bundle: dict, progress_cb: ProgressCb = None) -> None:
    plat = detect_platform()
    try:
        if plat == "windows":
            install_windows(bundle, progress_cb)
        elif plat == "linux":
            install_linux(bundle, progress_cb)
        else:
            raise RuntimeError(f"Plataforma no soportada: {plat}")
    finally:
        tmp = bundle.get("tmpdir")
        if tmp:
            shutil.rmtree(tmp, ignore_errors=True)


def run_update(
    allow_prerelease: bool = True,
    progress_cb: ProgressCb = None,
    install_dir: Optional[str] = None,
    current_version: Optional[str] = None,
) -> dict:
    """Descarga + instala. Retorna info del release aplicado."""
    bundle = download_update(allow_prerelease, progress_cb, install_dir)
    if current_version and tag_to_version(current_version) == bundle["version"]:
        _log(progress_cb, f"Ya estás en {bundle['version']}; se reinstala de todos modos.")
    install_update(bundle, progress_cb)
    return {"tag": bundle["tag"], "version": bundle["version"], "prerelease": bundle["prerelease"]}


def run_update_async(
    allow_prerelease: bool,
    on_progress: ProgressCb,
    on_done: Callable[[Optional[dict], Optional[BaseException]], None],
    install_dir: Optional[str] = None,
    current_version: Optional[str] = None,
) -> threading.Thread:
    def _worker():
        try:
            info = run_update(allow_prerelease, on_progress, install_dir, current_version)
            on_done(info, None)
        except BaseException as e:
            on_done(None, e)

    t = threading.Thread(target=_worker, name="cm-updater", daemon=True)
    t.start()
    return t
