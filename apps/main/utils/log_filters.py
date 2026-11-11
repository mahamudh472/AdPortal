"""Logging filter that redacts credentials from log records (audit SEC-37)."""
import logging
import re

_PATTERNS = [
    (re.compile(r'(?i)((?:access_token|refresh_token|client_secret|secret|password|token|code|signed_request|developer-token)=)[^&\s"\']+'), r'\1[REDACTED]'),
    (re.compile(r'(?i)(bearer\s+)[A-Za-z0-9\-._~+/]+=*'), r'\1[REDACTED]'),
    (re.compile(r'(?i)("(?:access_token|refresh_token|client_secret|secret|password)"\s*:\s*")[^"]+'), r'\1[REDACTED]'),
    (re.compile(r"(?i)('(?:access_token|refresh_token|client_secret|secret|password)'\s*:\s*')[^']+"), r'\1[REDACTED]'),
]


def redact(text: str) -> str:
    for pattern, repl in _PATTERNS:
        text = pattern.sub(repl, text)
    return text


class RedactSecretsFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        try:
            message = record.getMessage()
        except Exception:
            return True
        redacted = redact(message)
        if redacted != message:
            record.msg = redacted
            record.args = ()
        if record.exc_info and record.exc_info[1] is not None and not record.exc_text:
            import traceback
            record.exc_text = redact(''.join(traceback.format_exception(*record.exc_info)))
        elif record.exc_text:
            record.exc_text = redact(record.exc_text)
        return True
