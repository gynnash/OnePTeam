"""Conservative redaction applied before any external-model invocation."""

from __future__ import annotations

import re


MODEL_REDACTIONS = (
    (re.compile(r"(?i)(?:api[_-]?key|token|secret|password)\s*[:=]\s*[^\s,;]+"), "[已移除凭据]"),
    (re.compile(r"(?i)bearer\s+[a-z0-9._~+/-]{12,}"), "[已移除凭据]"),
    (re.compile(r"\bsk-[A-Za-z0-9_-]{16,}\b"), "[已移除凭据]"),
    (re.compile(r"\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b", re.I), "[已隐藏邮箱]"),
    (re.compile(r"(?<![\w.])(?:/Users|/home|/var|/private|[A-Z]:\\)[^\s`\"']+"), "[本地路径]"),
    (re.compile(r"\b(?:10\.|192\.168\.|172\.(?:1[6-9]|2\d|3[01])\.)\d{1,3}\.\d{1,3}\b"), "[内部地址]"),
)


def sanitize_for_model(value: str, *, max_chars: int) -> str:
    text = value or ""
    for pattern, replacement in MODEL_REDACTIONS:
        text = pattern.sub(replacement, text)
    return text[:max(0, max_chars)]

