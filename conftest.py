"""Project-root pytest config.

Clears SSLKEYLOGFILE if it points at an antivirus filter-driver device path
(AVG / Avast set this system-wide to redirect TLS key logging through their
kernel driver). Honoring that path causes Python's SSL stack to load
System32's LibreSSL libcrypto.dll and abort with `OPENSSL_Uplink ... no
OPENSSL_Applink`. Conditional pop so a deliberate SSLKEYLOGFILE on a real
file path still works.
"""
import os

_keylog = os.environ.get("SSLKEYLOGFILE", "")
if _keylog.startswith("\\\\.\\") or "avgMon" in _keylog or "avast" in _keylog.lower():
    os.environ.pop("SSLKEYLOGFILE", None)
