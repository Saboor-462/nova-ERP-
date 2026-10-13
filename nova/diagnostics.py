"""Server-side failure logging with credentials removed. Web pages show only short, fixed messages."""
import logging
import re
import traceback

_URL_CREDENTIALS = re.compile(r'([A-Za-z][\w+.-]*://)[^\s/@]+@')
_PASSWORD_FIELDS = re.compile(r'((?:password|passwd|pwd|secret|token)\s*[=:]\s*)[^\s&;,\'"]+', re.IGNORECASE)


def redact(text):
    text = _URL_CREDENTIALS.sub(r'\1***@', str(text))
    return _PASSWORD_FIELDS.sub(r'\1***', text)


def log_failure(message, exc, logger=None):
    detail = ''.join(traceback.format_exception(type(exc), exc, exc.__traceback__))
    (logger or logging.getLogger('nova')).error('%s\n%s', message, redact(detail))
