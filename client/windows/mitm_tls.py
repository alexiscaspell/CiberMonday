"""
CA local + certificados leaf para MITM del HostnameProxy (CONNECT).

Permite leer Referer/Origin en HTTPS (ALPN http/1.1) y decidir allowlist
por origen de página, no por heurísticas de nombre.
"""

from __future__ import annotations

import os
import ssl
import subprocess
import sys
import threading
from datetime import datetime, timedelta, timezone
from typing import Optional
from urllib.parse import urlparse

CA_CN = "CiberMonday Local MITM CA"
CA_ORG = "CiberMonday"
CA_CERT_NAME = "ca.crt"
CA_KEY_NAME = "ca.key"

_lock = threading.Lock()
_ca_cert = None
_ca_key = None
_leaf_cache: dict[str, tuple] = {}  # host -> (cert_pem, key_pem)
_ca_dir: Optional[str] = None


def _cryptography():
    from cryptography import x509
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import rsa
    from cryptography.x509.oid import ExtendedKeyUsageOID, NameOID

    return x509, hashes, serialization, rsa, ExtendedKeyUsageOID, NameOID


def set_ca_dir(path: str) -> None:
    global _ca_dir
    _ca_dir = path
    os.makedirs(path, exist_ok=True)


def ca_paths(base: Optional[str] = None) -> tuple[str, str]:
    root = base or _ca_dir
    if not root:
        raise RuntimeError("mitm_tls: CA dir no configurado (set_ca_dir)")
    return os.path.join(root, CA_CERT_NAME), os.path.join(root, CA_KEY_NAME)


def ensure_ca(base: Optional[str] = None) -> tuple[str, str]:
    """Genera CA si no existe. Retorna (cert_path, key_path)."""
    global _ca_cert, _ca_key
    x509, hashes, serialization, rsa, _EKU, NameOID = _cryptography()

    if base:
        set_ca_dir(base)
    cert_path, key_path = ca_paths()

    with _lock:
        if os.path.isfile(cert_path) and os.path.isfile(key_path):
            with open(key_path, "rb") as f:
                _ca_key = serialization.load_pem_private_key(f.read(), password=None)
            with open(cert_path, "rb") as f:
                _ca_cert = x509.load_pem_x509_certificate(f.read())
            return cert_path, key_path

        key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        subject = issuer = x509.Name([
            x509.NameAttribute(NameOID.COUNTRY_NAME, "AR"),
            x509.NameAttribute(NameOID.ORGANIZATION_NAME, CA_ORG),
            x509.NameAttribute(NameOID.COMMON_NAME, CA_CN),
        ])
        now = datetime.now(timezone.utc)
        cert = (
            x509.CertificateBuilder()
            .subject_name(subject)
            .issuer_name(issuer)
            .public_key(key.public_key())
            .serial_number(x509.random_serial_number())
            .not_valid_before(now - timedelta(days=1))
            .not_valid_after(now + timedelta(days=3650))
            .add_extension(x509.BasicConstraints(ca=True, path_length=0), critical=True)
            .add_extension(
                x509.KeyUsage(
                    digital_signature=True,
                    key_cert_sign=True,
                    crl_sign=True,
                    content_commitment=False,
                    key_encipherment=False,
                    data_encipherment=False,
                    key_agreement=False,
                    encipher_only=False,
                    decipher_only=False,
                ),
                critical=True,
            )
            .sign(key, hashes.SHA256())
        )
        key_pem = key.private_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PrivateFormat.TraditionalOpenSSL,
            encryption_algorithm=serialization.NoEncryption(),
        )
        cert_pem = cert.public_bytes(serialization.Encoding.PEM)
        with open(key_path, "wb") as f:
            f.write(key_pem)
        try:
            os.chmod(key_path, 0o600)
        except OSError:
            pass
        with open(cert_path, "wb") as f:
            f.write(cert_pem)
        _ca_key = key
        _ca_cert = cert
        _leaf_cache.clear()
        print(f"[MITM] CA creada en {cert_path}")
        return cert_path, key_path


def _load_ca() -> None:
    global _ca_cert, _ca_key
    if _ca_cert is not None and _ca_key is not None:
        return
    ensure_ca()


def leaf_pem_for_host(hostname: str) -> tuple[bytes, bytes]:
    """Retorna (cert_pem, key_pem) para el host CONNECT/SNI."""
    x509, hashes, serialization, rsa, ExtendedKeyUsageOID, NameOID = _cryptography()
    host = (hostname or "").strip().lower().rstrip(".")
    if not host:
        raise ValueError("hostname vacío")
    with _lock:
        _load_ca()
        cached = _leaf_cache.get(host)
        if cached:
            return cached
        key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        subject = x509.Name([
            x509.NameAttribute(NameOID.COUNTRY_NAME, "AR"),
            x509.NameAttribute(NameOID.ORGANIZATION_NAME, CA_ORG),
            x509.NameAttribute(NameOID.COMMON_NAME, host),
        ])
        now = datetime.now(timezone.utc)
        cert = (
            x509.CertificateBuilder()
            .subject_name(subject)
            .issuer_name(_ca_cert.subject)
            .public_key(key.public_key())
            .serial_number(x509.random_serial_number())
            .not_valid_before(now - timedelta(minutes=5))
            .not_valid_after(now + timedelta(days=825))
            .add_extension(
                x509.SubjectAlternativeName([x509.DNSName(host)]),
                critical=False,
            )
            .add_extension(
                x509.ExtendedKeyUsage([ExtendedKeyUsageOID.SERVER_AUTH]),
                critical=False,
            )
            .add_extension(
                x509.KeyUsage(
                    digital_signature=True,
                    key_encipherment=True,
                    content_commitment=False,
                    data_encipherment=False,
                    key_agreement=False,
                    key_cert_sign=False,
                    crl_sign=False,
                    encipher_only=False,
                    decipher_only=False,
                ),
                critical=True,
            )
            .sign(_ca_key, hashes.SHA256())
        )
        key_pem = key.private_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PrivateFormat.TraditionalOpenSSL,
            encryption_algorithm=serialization.NoEncryption(),
        )
        cert_pem = cert.public_bytes(serialization.Encoding.PEM)
        _leaf_cache[host] = (cert_pem, key_pem)
        if len(_leaf_cache) > 512:
            # dropear entradas viejas arbitrarias
            for k in list(_leaf_cache.keys())[:64]:
                _leaf_cache.pop(k, None)
        return cert_pem, key_pem


def client_facing_ssl_context(hostname: str) -> ssl.SSLContext:
    """TLS hacia el browser: leaf firmado por nuestra CA, solo http/1.1."""
    import tempfile

    cert_pem, key_pem = leaf_pem_for_host(hostname)
    ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    try:
        ctx.set_alpn_protocols(["http/1.1"])
    except Exception:
        pass
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    fd_c, path_c = tempfile.mkstemp(suffix=".crt")
    fd_k, path_k = tempfile.mkstemp(suffix=".key")
    try:
        os.write(fd_c, cert_pem)
        os.write(fd_k, key_pem)
        os.close(fd_c)
        os.close(fd_k)
        ctx.load_cert_chain(path_c, path_k)
    finally:
        try:
            os.unlink(path_c)
        except OSError:
            pass
        try:
            os.unlink(path_k)
        except OSError:
            pass
    return ctx


def server_facing_ssl_context() -> ssl.SSLContext:
    """TLS hacia el origen real (verificación normal)."""
    ctx = ssl.create_default_context()
    try:
        ctx.set_alpn_protocols(["http/1.1"])
    except Exception:
        pass
    return ctx


def host_from_header_value(raw: Optional[str]) -> Optional[str]:
    """Extrae hostname de Referer/Origin/Host."""
    if not raw:
        return None
    v = raw.strip()
    if not v or v == "null":
        return None
    if "://" in v:
        try:
            p = urlparse(v)
            h = (p.hostname or "").lower().rstrip(".")
            return h or None
        except Exception:
            return None
    # Host: name[:port]
    h = v.split("/")[0].split(":")[0].strip().lower().rstrip(".")
    return h or None


def parse_http11_request_head(data: bytes) -> tuple[dict[str, str], bytes]:
    """Parsea headers HTTP/1.1 hasta \\r\\n\\r\\n. Retorna (headers_lower, resto)."""
    if b"\r\n\r\n" not in data:
        return {}, data
    head, rest = data.split(b"\r\n\r\n", 1)
    lines = head.decode("latin-1", errors="ignore").split("\r\n")
    headers: dict[str, str] = {}
    if lines:
        headers[":method_line"] = lines[0]
    for line in lines[1:]:
        if ":" not in line:
            continue
        k, val = line.split(":", 1)
        headers[k.strip().lower()] = val.strip()
    return headers, rest


def install_ca_trust(cert_path: Optional[str] = None) -> bool:
    """Instala la CA en el trust store de la máquina."""
    path = cert_path or ca_paths()[0]
    if not os.path.isfile(path):
        ensure_ca()
        path = ca_paths()[0]
    try:
        if sys.platform == "win32":
            # LocalMachine\\Root — el servicio corre como SYSTEM y el browser
            # del usuario también ve las raíces de máquina.
            r = subprocess.run(
                ["certutil", "-addstore", "-f", "Root", path],
                capture_output=True,
                text=True,
                timeout=30,
                creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0,
            )
            if r.returncode != 0:
                print(f"[MITM] certutil addstore: {(r.stderr or r.stdout or '').strip()}")
                return False
            print("[MITM] CA instalada en LocalMachine\\Root")
            return True
        # Linux: sistema + nota para browsers NSS
        dest_dir = "/usr/local/share/ca-certificates"
        if os.path.isdir("/usr/local/share/ca-certificates") or os.geteuid() == 0:
            os.makedirs(dest_dir, exist_ok=True)
            dest = os.path.join(dest_dir, "cibermonday-mitm-ca.crt")
            with open(path, "rb") as src, open(dest, "wb") as out:
                out.write(src.read())
            subprocess.run(["update-ca-certificates"], capture_output=True, timeout=60)
            print(f"[MITM] CA instalada en {dest}")
            return True
        print("[MITM] Sin permisos para instalar CA del sistema (Linux)")
        return False
    except Exception as e:
        print(f"[MITM] install trust: {e}")
        return False


def uninstall_ca_trust() -> bool:
    """Quita la CA del trust store."""
    try:
        if sys.platform == "win32":
            flags = subprocess.CREATE_NO_WINDOW
            r = subprocess.run(
                ["certutil", "-delstore", "Root", CA_CN],
                capture_output=True,
                text=True,
                timeout=30,
                creationflags=flags,
            )
            # también por hash si el CN no matchea
            if r.returncode != 0:
                print(f"[MITM] certutil delstore: {(r.stderr or r.stdout or '').strip()}")
            else:
                print("[MITM] CA eliminada de LocalMachine\\Root")
            return True
        dest = "/usr/local/share/ca-certificates/cibermonday-mitm-ca.crt"
        if os.path.isfile(dest):
            os.remove(dest)
            subprocess.run(["update-ca-certificates", "--fresh"], capture_output=True, timeout=60)
            print("[MITM] CA eliminada del sistema")
        return True
    except Exception as e:
        print(f"[MITM] uninstall trust: {e}")
        return False
