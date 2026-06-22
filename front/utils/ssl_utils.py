"""Shared SSL utilities for Arrow Front.

Production uses a self-signed certificate, so all outbound connections from
the desktop client must bypass certificate verification.
"""

import ssl

# Re-usable context for urllib.request.urlopen calls
NO_VERIFY_CTX = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
NO_VERIFY_CTX.check_hostname = False
NO_VERIFY_CTX.verify_mode = ssl.CERT_NONE
