"""Deterministic text normalization for knowledge ingestion (Gate 7D.5B)."""


def normalize_text(text: str) -> str:
    """Deterministically normalize text content for canonical ingestion.

    Enforces:
    1. Line endings: CRLF -> LF, CR -> LF.
    2. Prohibited control chars: ASCII 0-8, 11-12, 14-31, 127 are filtered out.
    3. Preserved control chars: LF (\n, 0x0A) and TAB (\t, 0x09) are preserved.
    4. Line trailing whitespace: Each line's trailing spaces and tabs are stripped.
    5. Document boundaries: Leading and trailing empty lines are removed.
    6. Idempotence: normalize_text(normalize_text(s)) == normalize_text(s).
    """
    if not text:
        return ""

    # 1. Normalize line endings
    text = text.replace("\r\n", "\n").replace("\r", "\n")

    # 2. Filter prohibited ASCII control characters (keeping \n and \t)
    cleaned_chars: list[str] = []
    for ch in text:
        code = ord(ch)
        if (code < 32 and ch not in ("\n", "\t")) or code == 127:
            continue
        cleaned_chars.append(ch)
    text = "".join(cleaned_chars)

    # 3. Strip trailing whitespace from each line
    lines = [line.rstrip(" \t") for line in text.split("\n")]

    # 4. Remove leading and trailing empty lines
    while lines and not lines[0]:
        lines.pop(0)
    while lines and not lines[-1]:
        lines.pop()

    return "\n".join(lines)
