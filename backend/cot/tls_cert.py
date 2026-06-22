"""Self-signed PKI for the CoT TLS listener (ATAK SSL connections).

Generates, once and reused across restarts (under ``data/cot_tls/``):

  * ``ca.pem`` / ``ca.key``            — a private CA
  * ``cot-server.pem`` / ``.key``      — the server cert (signed by the CA, with
                                         a SAN covering this host's IPs/names),
                                         loaded by the TLS listener
  * ``atak-truststore.p12``            — CA-only PKCS12; import into ATAK as the
                                         *CA / truststore* so it trusts us
  * ``atak-client.p12``                — client keystore (key+cert), for ATAK
                                         builds that insist on a client cert
                                         (the server does not require one)

The truststore/keystore password defaults to ``atakatak`` (ATAK's conventional
default) and can be overridden with ``ARROW_COT_TLS_PASSWORD``.

The server cert's SAN must include the address ATAK dials. Add your public IP
via ``ARROW_COT_EXTRA_IPS=78.21.255.210`` (``ARROW_WEB_EXTRA_IPS`` is also
honoured) — otherwise ATAK may reject the cert on hostname mismatch.
"""

from __future__ import annotations

import datetime
import ipaddress
import logging
import os
import socket
from pathlib import Path

log = logging.getLogger("backend.cot.tls")

_DIR = Path("data/cot_tls")
_CA_CERT = _DIR / "ca.pem"
_CA_KEY = _DIR / "ca.key"
_SRV_CERT = _DIR / "cot-server.pem"
_SRV_KEY = _DIR / "cot-server.key"
_TRUSTSTORE = _DIR / "atak-truststore.p12"
_CLIENT_P12 = _DIR / "atak-client.p12"
_VALIDITY = datetime.timedelta(days=3650)

PASSWORD = os.environ.get("ARROW_COT_TLS_PASSWORD", "atakatak")


def _collect_sans() -> tuple[list[str], list]:
    """Return (dns_names, ip_addresses) for the server cert SAN."""
    dns: list[str] = ["localhost"]
    ips: list = []

    try:
        hn = socket.gethostname()
        dns.append(hn)
        for info in socket.getaddrinfo(hn, None):
            try:
                ips.append(ipaddress.ip_address(info[4][0]))
            except ValueError:
                pass
    except Exception:
        pass

    for lo in ("127.0.0.1", "::1"):
        try:
            ips.append(ipaddress.ip_address(lo))
        except ValueError:
            pass

    extra = ",".join(
        filter(
            None,
            (
                os.environ.get("ARROW_COT_EXTRA_IPS", ""),
                os.environ.get("ARROW_WEB_EXTRA_IPS", ""),
            ),
        )
    )
    for token in (t.strip() for t in extra.split(",") if t.strip()):
        try:
            ips.append(ipaddress.ip_address(token))
        except ValueError:
            dns.append(token)

    return list(dict.fromkeys(dns)), list(dict.fromkeys(ips))


def _covers_current(cert_path: Path) -> bool:
    """True if the existing server cert's SAN already includes all current IPs."""
    try:
        from cryptography import x509

        cert = x509.load_pem_x509_certificate(cert_path.read_bytes())
        san = cert.extensions.get_extension_for_class(x509.SubjectAlternativeName)
        have = {str(n.value) for n in san.value if isinstance(n, x509.IPAddress)}
        _, needed = _collect_sans()
        return all(str(ip) in have for ip in needed)
    except Exception:
        return False


def ensure_cot_tls() -> tuple[str, str]:
    """Generate the CA/server/client PKI if missing or stale.

    Returns ``(server_cert_path, server_key_path)`` for the TLS listener.
    """
    from cryptography import x509
    from cryptography.hazmat.primitives import hashes
    from cryptography.hazmat.primitives.asymmetric import rsa
    from cryptography.hazmat.primitives.serialization import (
        BestAvailableEncryption,
        Encoding,
        NoEncryption,
        PrivateFormat,
        pkcs12,
    )
    from cryptography.x509.oid import ExtendedKeyUsageOID, NameOID

    _DIR.mkdir(parents=True, exist_ok=True)

    if (
        _SRV_CERT.exists()
        and _SRV_KEY.exists()
        and _CA_CERT.exists()
        and _covers_current(_SRV_CERT)
    ):
        return str(_SRV_CERT), str(_SRV_KEY)

    now = datetime.datetime.now(datetime.timezone.utc)
    dns_names, ip_addrs = _collect_sans()
    log.info(
        "Generating CoT TLS PKI — SAN: %s + %s", dns_names, [str(i) for i in ip_addrs]
    )

    def _new_key():
        return rsa.generate_private_key(public_exponent=65537, key_size=2048)

    def _name(cn: str) -> "x509.Name":
        return x509.Name(
            [
                x509.NameAttribute(NameOID.COMMON_NAME, cn),
                x509.NameAttribute(NameOID.ORGANIZATION_NAME, "Arrow"),
            ]
        )

    # ── Certificate authority ──────────────────────────────────────────────
    ca_key = _new_key()
    ca_name = _name("Arrow CoT CA")
    ca_cert = (
        x509.CertificateBuilder()
        .subject_name(ca_name)
        .issuer_name(ca_name)
        .public_key(ca_key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now)
        .not_valid_after(now + _VALIDITY)
        .add_extension(x509.BasicConstraints(ca=True, path_length=None), critical=True)
        .add_extension(
            x509.KeyUsage(
                digital_signature=True,
                key_cert_sign=True,
                crl_sign=True,
                key_encipherment=False,
                content_commitment=False,
                data_encipherment=False,
                key_agreement=False,
                encipher_only=False,
                decipher_only=False,
            ),
            critical=True,
        )
        .sign(ca_key, hashes.SHA256())
    )

    # ── Server certificate (SAN-covered, signed by the CA) ─────────────────
    srv_key = _new_key()
    srv_san = [x509.DNSName(d) for d in dns_names] + [
        x509.IPAddress(ip) for ip in ip_addrs
    ]
    srv_cert = (
        x509.CertificateBuilder()
        .subject_name(_name(dns_names[0] if dns_names else "arrow-cot"))
        .issuer_name(ca_name)
        .public_key(srv_key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now)
        .not_valid_after(now + _VALIDITY)
        .add_extension(x509.SubjectAlternativeName(srv_san), critical=False)
        .add_extension(x509.BasicConstraints(ca=False, path_length=None), critical=True)
        .add_extension(
            x509.ExtendedKeyUsage([ExtendedKeyUsageOID.SERVER_AUTH]), critical=False
        )
        .sign(ca_key, hashes.SHA256())
    )

    # ── Client certificate (optional convenience for ATAK keystores) ───────
    cli_key = _new_key()
    cli_cert = (
        x509.CertificateBuilder()
        .subject_name(_name("arrow-atak-client"))
        .issuer_name(ca_name)
        .public_key(cli_key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now)
        .not_valid_after(now + _VALIDITY)
        .add_extension(x509.BasicConstraints(ca=False, path_length=None), critical=True)
        .add_extension(
            x509.ExtendedKeyUsage([ExtendedKeyUsageOID.CLIENT_AUTH]), critical=False
        )
        .sign(ca_key, hashes.SHA256())
    )

    # ── Write PEMs (server PEM carries the CA so ATAK gets the full chain) ──
    _CA_CERT.write_bytes(ca_cert.public_bytes(Encoding.PEM))
    _CA_KEY.write_bytes(
        ca_key.private_bytes(
            Encoding.PEM, PrivateFormat.TraditionalOpenSSL, NoEncryption()
        )
    )
    _SRV_CERT.write_bytes(
        srv_cert.public_bytes(Encoding.PEM) + ca_cert.public_bytes(Encoding.PEM)
    )
    _SRV_KEY.write_bytes(
        srv_key.private_bytes(
            Encoding.PEM, PrivateFormat.TraditionalOpenSSL, NoEncryption()
        )
    )

    # ── PKCS12 bundles for ATAK ────────────────────────────────────────────
    enc = BestAvailableEncryption(PASSWORD.encode())
    _TRUSTSTORE.write_bytes(
        pkcs12.serialize_key_and_certificates(
            b"arrow-cot-ca", None, None, [ca_cert], enc
        )
    )
    _CLIENT_P12.write_bytes(
        pkcs12.serialize_key_and_certificates(
            b"arrow-atak-client", cli_key, cli_cert, [ca_cert], enc
        )
    )

    log.info("CoT TLS PKI written to %s (truststore password: %s)", _DIR, PASSWORD)
    print(
        f"[Arrow CoT] TLS truststore for ATAK: {_TRUSTSTORE}  (password: {PASSWORD})",
        flush=True,
    )
    return str(_SRV_CERT), str(_SRV_KEY)


# Logical artifact name → (path, suggested download filename, mime type)
ARTIFACTS: dict[str, tuple[Path, str, str]] = {
    "truststore": (_TRUSTSTORE, "atak-truststore.p12", "application/x-pkcs12"),
    "client": (_CLIENT_P12, "atak-client.p12", "application/x-pkcs12"),
    "ca": (_CA_CERT, "arrow-cot-ca.pem", "application/x-pem-file"),
    "server-cert": (_SRV_CERT, "cot-server.pem", "application/x-pem-file"),
}


def info() -> dict:
    """Metadata about the generated PKI, for the admin UI."""
    dns, ips = _collect_sans()
    files = {
        name: {
            "filename": fname,
            "exists": path.exists(),
            "size": (path.stat().st_size if path.exists() else 0),
        }
        for name, (path, fname, _mime) in ARTIFACTS.items()
    }
    return {
        "dir": str(_DIR),
        "password": PASSWORD,
        "generated": _SRV_CERT.exists() and _CA_CERT.exists(),
        "san_dns": dns,
        "san_ips": [str(i) for i in ips],
        "files": files,
    }


def artifact(name: str) -> tuple[bytes, str, str] | None:
    """Return ``(data, download_filename, mime)`` for a logical artifact, or None."""
    entry = ARTIFACTS.get(name)
    if not entry:
        return None
    path, fname, mime = entry
    if not path.exists():
        return None
    return path.read_bytes(), fname, mime


def regenerate() -> tuple[str, str]:
    """Delete the existing PKI and build a fresh one (new CA + certs)."""
    for path, _fn, _m in ARTIFACTS.values():
        path.unlink(missing_ok=True)
    for p in (_CA_KEY, _SRV_KEY):
        p.unlink(missing_ok=True)
    return ensure_cot_tls()
