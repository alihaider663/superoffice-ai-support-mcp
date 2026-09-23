"""Secret scanner for inspecting extracted SuperOffice script bodies."""

import re

_SECRET_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    (
        "Private Key header detected",
        re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----", re.IGNORECASE),
    ),
    (
        "Potential hardcoded password assignment",
        re.compile(r'(?:password|passwd|pwd)\s*=\s*["\'][^"\']{4,}["\']', re.IGNORECASE),
    ),
    (
        "Bearer token detected",
        re.compile(r"Bearer\s+[a-zA-Z0-9_\-\.]{20,}", re.IGNORECASE),
    ),
    (
        "Potential API key or secret token",
        re.compile(
            r'(?:api_key|apikey|secret_key|client_secret)\s*=\s*["\'][^"\']{10,}["\']',
            re.IGNORECASE,
        ),
    ),
    (
        "Connection string with embedded credentials",
        re.compile(
            r"(?:Server|Data Source)=.+;(?:Uid|User Id|UID)=.+;(?:Pwd|Password)=[^;]+",
            re.IGNORECASE,
        ),
    ),
]


def scan_script_for_secrets(body: str) -> list[str]:
    """Scan script source code for obvious embedded credentials or private keys.

    Returns a list of descriptive warning messages with line numbers.
    Does not include the detected secret values in the warnings.
    """
    if not body:
        return []

    warnings: list[str] = []
    lines = body.splitlines()

    for line_idx, line in enumerate(lines, start=1):
        # Skip pure comment lines in CRMScript (// or /*)
        trimmed = line.strip()
        if trimmed.startswith("//") or trimmed.startswith("/*") or trimmed.startswith("*"):
            continue

        for label, pattern in _SECRET_PATTERNS:
            if pattern.search(line):
                warnings.append(f"{label} on line {line_idx}")

    return warnings
