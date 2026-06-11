"""Observability - Structured logging and optional OpenTelemetry instrumentation.

Provides:
- ``configure_logging()``: Sets up structlog with ConsoleRenderer (dev) or
  JSONRenderer (production) based on ``HIVEFLOW_ENV`` env var.  Bridges stdlib
  logging through structlog ProcessorFormatter so existing ``logging.getLogger()``
  calls render consistently.
- OTel tracer / meter / metrics that are ``None`` when ``opentelemetry`` is not
  installed or ``HIVEFLOW_OTEL_ENABLED`` is not ``"true"``.

See: R6, R7, data-model.md Observability section.
"""

import logging
import os
import re

import structlog

# ---------------------------------------------------------------------------
# OTel instrumentation (optional)
# ---------------------------------------------------------------------------

_otel_enabled = os.environ.get("HIVEFLOW_OTEL_ENABLED", "false").lower() == "true"

try:
    from opentelemetry import metrics, trace

    tracer = trace.get_tracer("hiveflow.llm")
    meter = metrics.get_meter("hiveflow.llm")
except ImportError:
    tracer = None  # type: ignore[assignment]
    meter = None  # type: ignore[assignment]

if meter and _otel_enabled:
    llm_duration = meter.create_histogram(
        "gen_ai.client.operation.duration",
        unit="s",
        description="Duration of LLM provider operations",
    )
    llm_token_usage = meter.create_counter(
        "gen_ai.client.token.usage",
        unit="{token}",
        description="Token usage by LLM provider operations",
    )
else:
    llm_duration = None  # type: ignore[assignment]
    llm_token_usage = None  # type: ignore[assignment]

# ---------------------------------------------------------------------------
# structlog configuration
# ---------------------------------------------------------------------------

_logging_configured = False

# Patterns matching sensitive values in log output
_SENSITIVE_PATTERNS = [
    re.compile(r"sk-[a-zA-Z0-9_-]{20,}"),  # OpenAI API keys
    re.compile(r"sk-ant-[a-zA-Z0-9_-]{20,}"),  # Anthropic API keys
    re.compile(r"Bearer\s+[a-zA-Z0-9._-]{20,}"),  # Bearer tokens
    re.compile(
        r"(?i)(?:password|secret|token|api[_-]?key)\s*[:=]\s*\S+",
    ),
]


def _redact_sensitive(
    _logger: logging.Logger,
    _method: str,
    event_dict: dict[str, object],
) -> dict[str, object]:
    """Structlog processor that redacts sensitive values from log events."""
    for key, value in event_dict.items():
        if isinstance(value, str):
            redacted = value
            for pattern in _SENSITIVE_PATTERNS:
                redacted = pattern.sub("[REDACTED]", redacted)
            if redacted != value:
                event_dict[key] = redacted
    return event_dict


def configure_logging() -> None:
    """Configure structlog with stdlib bridge.

    Call once at application startup.  Safe to call multiple times (no-op
    after the first invocation).

    Environment variables:
        HIVEFLOW_ENV: ``"development"`` (default) for pretty console output,
                      ``"production"`` for JSON lines.
    """
    global _logging_configured  # noqa: PLW0603
    if _logging_configured:
        return
    _logging_configured = True

    is_dev = os.environ.get("HIVEFLOW_ENV", "development") == "development"

    shared_processors: list[structlog.types.Processor] = [
        structlog.contextvars.merge_contextvars,
        structlog.stdlib.add_logger_name,
        structlog.stdlib.add_log_level,
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.processors.StackInfoRenderer(),
        _redact_sensitive,
    ]

    renderer: structlog.types.Processor = (
        structlog.dev.ConsoleRenderer() if is_dev else structlog.processors.JSONRenderer()
    )

    structlog.configure(
        processors=[
            *shared_processors,
            structlog.stdlib.ProcessorFormatter.wrap_for_formatter,
        ],
        logger_factory=structlog.stdlib.LoggerFactory(),
        wrapper_class=structlog.stdlib.BoundLogger,
        cache_logger_on_first_use=True,
    )

    formatter = structlog.stdlib.ProcessorFormatter(
        processors=[
            structlog.stdlib.ProcessorFormatter.remove_processors_meta,
            renderer,
        ],
    )
    handler = logging.StreamHandler()
    handler.setFormatter(formatter)

    root = logging.getLogger()
    root.addHandler(handler)
    root.setLevel(logging.INFO)
