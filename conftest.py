"""Project-root pytest config.

Two AVG / Avast antivirus workarounds, both fired before any test imports SSL:

1. Clear SSLKEYLOGFILE when it points at a kernel filter-driver device path
   (AVG / Avast set it system-wide to redirect TLS key logging through their
   driver). Honoring it loads System32's LibreSSL libcrypto.dll and aborts
   the process with `OPENSSL_Uplink ... no OPENSSL_Applink`.

2. Inject truststore so Python's `ssl` module uses the Windows certificate
   store instead of certifi's bundle. AVG MitMs outbound TLS with its own
   root CA; that root is in the Windows store but not in certifi, so any
   library that pins certifi (httpx, litellm, etc.) fails with
   CERTIFICATE_VERIFY_FAILED. Conditional inject so non-AV environments
   keep their original behaviour.
"""
import os

_keylog = os.environ.get("SSLKEYLOGFILE", "")
_av_active = (
    _keylog.startswith("\\\\.\\")
    or "avgMon" in _keylog
    or "avast" in _keylog.lower()
)

if _av_active:
    os.environ.pop("SSLKEYLOGFILE", None)
    try:
        import truststore
        truststore.inject_into_ssl()
    except ImportError:
        pass
