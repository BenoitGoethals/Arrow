"""Auto-generate a self-signed TLS certificate for the Arrow web server.

Cert is stored in data/ssl/ and reused across restarts.  On first run (or
when the cert doesn't cover the current machine's IPs) a new cert is created.

Environment variables
---------------------
ARROW_WEB_HTTP=1          Disable HTTPS, serve plain HTTP.
ARROW_WEB_EXTRA_IPS       Comma-separated extra IPs/hostnames to add to the
                          cert SAN.  Example: ARROW_WEB_EXTRA_IPS=78.21.255.210
"""
from __future__ import annotations

import datetime
import ipaddress
import logging
import os
import socket
from pathlib import Path

log = logging.getLogger(__name__)

_SSL_DIR  = Path("data/ssl")
_CERT     = _SSL_DIR / "web-cert.pem"
_KEY      = _SSL_DIR / "web-key.pem"
_VALIDITY = datetime.timedelta(days=3650)


def _collect_sans() -> tuple[list[str], list[ipaddress.IPv4Address | ipaddress.IPv6Address]]:
    """Return (dns_names, ip_addresses) for the SAN extension."""
    dns: list[str]  = ["localhost"]
    ips: list       = []

    # Machine hostname
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

    # Loopback
    for lo in ("127.0.0.1", "::1"):
        try:
            ips.append(ipaddress.ip_address(lo))
        except ValueError:
            pass

    # Extra IPs/hostnames from environment
    extra = os.environ.get("ARROW_WEB_EXTRA_IPS", "")
    for token in (t.strip() for t in extra.split(",") if t.strip()):
        try:
            ips.append(ipaddress.ip_address(token))
        except ValueError:
            dns.append(token)   # treat as DNS name

    # Deduplicate
    dns = list(dict.fromkeys(dns))
    ips = list(dict.fromkeys(ips))
    return dns, ips


def _cert_covers_current_ips(cert_path: Path) -> bool:
    """Return True if the existing cert's SAN includes all current IPs."""
    try:
        from cryptography import x509
        cert = x509.load_pem_x509_certificate(cert_path.read_bytes())
        san  = cert.extensions.get_extension_for_class(x509.SubjectAlternativeName)
        cert_ips = {str(n.value) for n in san.value if isinstance(n, x509.IPAddress)}
        _, needed = _collect_sans()
        return all(str(ip) in cert_ips for ip in needed)
    except Exception:
        return False


def ensure_cert() -> tuple[str, str]:
    """Return (cert_path, key_path), generating/regenerating if needed."""
    from cryptography import x509
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import rsa
    from cryptography.x509.oid import NameOID

    _SSL_DIR.mkdir(parents=True, exist_ok=True)

    # Reuse existing cert only if it already covers all current IPs
    if _CERT.exists() and _KEY.exists():
        if _cert_covers_current_ips(_CERT):
            return str(_CERT), str(_KEY)
        log.info("Cert doesn't cover current IPs — regenerating")

    dns_names, ip_addrs = _collect_sans()
    log.info("Generating TLS cert — SANs: %s + %s", dns_names, [str(i) for i in ip_addrs])

    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)

    hostname = socket.gethostname()
    subject = issuer = x509.Name([
        x509.NameAttribute(NameOID.COMMON_NAME, hostname),
        x509.NameAttribute(NameOID.ORGANIZATION_NAME, "Arrow"),
    ])

    now = datetime.datetime.now(datetime.timezone.utc)

    san_entries: list[x509.GeneralName] = [x509.DNSName(d) for d in dns_names]
    san_entries += [x509.IPAddress(ip) for ip in ip_addrs]

    cert = (
        x509.CertificateBuilder()
        .subject_name(subject)
        .issuer_name(issuer)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now)
        .not_valid_after(now + _VALIDITY)
        .add_extension(x509.SubjectAlternativeName(san_entries), critical=False)
        .add_extension(x509.BasicConstraints(ca=True, path_length=None), critical=True)
        .sign(key, hashes.SHA256())
    )

    _CERT.write_bytes(cert.public_bytes(serialization.Encoding.PEM))
    _KEY.write_bytes(
        key.private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.TraditionalOpenSSL,
            serialization.NoEncryption(),
        )
    )

    all_sans = dns_names + [str(i) for i in ip_addrs]
    log.info("TLS cert written — covers: %s", ", ".join(all_sans))
    print(f"[Arrow Web] TLS cert covers: {', '.join(all_sans)}", flush=True)
    print("[Arrow Web] First visit: click Advanced → Proceed to accept the self-signed cert", flush=True)
    return str(_CERT), str(_KEY)
