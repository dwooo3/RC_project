"""
TLS trust helpers for Russian market-data endpoints.

iss.moex.com and www.cbr.ru sit behind an anti-DDoS proxy whose chain includes
a self-signed certificate; Python's default certifi store rejects it
(CERTIFICATE_VERIFY_FAILED) even though macOS curl accepts it. We extend — not
replace — the default trust store with a locally provided bundle.

Bundle resolution order:
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


def market_data_ssl_context() -> ssl.SSLContext:
    """Default-verification context extended with the local CA bundle."""
    ctx = ssl.create_default_context()
    extra = os.environ.get("RISKCALC_CA_BUNDLE", "")
    path = Path(extra) if extra else _BUNDLE
    if path.exists():
        try:
            ctx.load_verify_locations(cafile=str(path))
        except ssl.SSLError:
            pass                      # malformed bundle: stay on default trust
    return ctx
