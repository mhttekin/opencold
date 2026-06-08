"""Bearer-token auth shared by all data endpoints.

The secret is read from the OPENCOLD_API_SECRET env var and is known only to
this service and the Next.js BFF that calls it. We fail closed: if the secret
is not configured the service refuses every authenticated request.
"""

import hmac
import os

from fastapi import Header, HTTPException


def require_bearer(authorization: str = Header(default="")) -> None:
    expected = os.environ.get("OPENCOLD_API_SECRET", "")
    if not expected:
        raise HTTPException(status_code=503, detail="server not configured")
    scheme, _, token = authorization.partition(" ")
    if scheme.lower() != "bearer" or not token or not hmac.compare_digest(token, expected):
        raise HTTPException(status_code=401, detail="unauthorized")
