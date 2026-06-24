"""
TLS trust helpers for Russian market-data endpoints.

Two things conspire against a plain ``ssl.create_default_context()`` here:

  1. The python.org Python.framework build ships with an *empty* OpenSSL trust
     store unless "Install Certificates.command" was run — its default cafile
     points at a path that does not exist, so every HTTPS fetch fails with
     CERTIFICATE_VERIFY_FAILED ("unable to get local issuer certificate"),
     even for ordinary public certificates. We base the context on the
     ``certifi`` bundle instead, which is always present in the environment.
  2. iss.moex.com and www.cbr.ru can sit behind an anti-DDoS proxy whose chain
     includes a self-signed certificate that certifi doesn't know about. We
     *extend* — not replace — the trust store with a locally provided bundle so
     both the public chain and the proxy chain validate.

Bundle resolution order (additive, on top of certifi):
  1. $RISKCALC_CA_BUNDLE (explicit override)
  2. infra/certs/russian_trusted_ca.pem (extracted from the live chain)

To (re)extract after certificate rotation:
  for h in iss.moex.com www.cbr.ru; do
    echo | openssl s_client -connect $h:443 -showcerts 2>/dev/null \
      | awk '/BEGIN CERT/,/END CERT/'
  done > infra/certs/russian_trusted_ca.pem
"""

import os
import ssl
from pathlib import Path

_BUNDLE = Path(__file__).resolve().parent / "russian_trusted_ca.pem"


def _base_context() -> ssl.SSLContext:
    """Verification context seeded from certifi when the OS store is empty.

    Python.framework's default ``cafile`` often points at a path that does not
    exist; certifi gives us a populated public-CA trust store to fall back on.
    """
    try:
        import certifi

        return ssl.create_default_context(cafile=certifi.where())
    except Exception:
        return ssl.create_default_context()


def market_data_ssl_context() -> ssl.SSLContext:
    """certifi-based verification context extended with the local CA bundle."""
    ctx = _base_context()
    extra = os.environ.get("RISKCALC_CA_BUNDLE", "")
    path = Path(extra) if extra else _BUNDLE
    if path.exists():
        try:
            ctx.load_verify_locations(cafile=str(path))
        except ssl.SSLError:
            pass                      # malformed bundle: stay on base trust
    return ctx
