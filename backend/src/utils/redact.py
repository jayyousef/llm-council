from __future__ import annotations

import re


_RE_BEARER = re.compile(r"(?i)\bBearer\s+([A-Za-z0-9._\-+/=]{8,})")
_RE_OPENAI_SK = re.compile(r"\bsk-[A-Za-z0-9_\-]{10,}\b")
_RE_OPENROUTER_SK = re.compile(r"\bsk-or-v1-[A-Za-z0-9_\-]{10,}\b")
_RE_LC_KEY = re.compile(r"\blc_[A-Za-z0-9_\-]{16,}\b")
_RE_PEM = re.compile(r"-----BEGIN [^-]+-----.*?-----END [^-]+-----", re.DOTALL)


def redact_secrets(text: str) -> str:
    """
    Best-effort secret redaction for logs and stored error text.

    NOTE: Do not rely on this as the only control; also avoid logging/storing secrets in the first place.
    """
    if not text:
        return text

    out = text
    out = _RE_PEM.sub("-----BEGIN [REDACTED]-----\n[REDACTED]\n-----END [REDACTED]-----", out)
    out = _RE_BEARER.sub("Bearer [REDACTED]", out)
    out = _RE_OPENROUTER_SK.sub("[REDACTED]", out)
    out = _RE_OPENAI_SK.sub("[REDACTED]", out)
    out = _RE_LC_KEY.sub("[REDACTED]", out)
    return out

