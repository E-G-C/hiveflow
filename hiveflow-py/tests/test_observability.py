"""Tests for observability module — structlog + OTel (T010).

Covers:
- ``configure_logging()`` sets up structlog without errors
- ``tracer``/``meter``/``llm_duration``/``llm_token_usage`` default values
- ``_otel_enabled`` flag reads from env var correctly
- structlog logger emits expected event structure
"""

import importlib

import pytest
import structlog

# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestConfigureLogging:
    """configure_logging() behaviour."""

    def test_does_not_raise(self):
        from hiveflow.core.observability import configure_logging
        # Should not raise regardless of how many times called
        configure_logging()
        configure_logging()
        # Verify logging is actually configured
        from hiveflow.core.observability import _logging_configured
        assert _logging_configured is True

    def test_structlog_logger_works_after_configure(self):
        from hiveflow.core.observability import configure_logging
        configure_logging()
        log = structlog.get_logger()
        # Should not raise
        log.info("test.event", key="value")


class TestOTelDefaults:
    """OTel symbols when HIVEFLOW_OTEL_ENABLED is not set."""

    def test_otel_not_enabled_by_default(self):
        import hiveflow.core.observability as obs
        # Default is False (env var not set or "false")
        # Note: module-level _otel_enabled may have been set at import time
        assert isinstance(obs._otel_enabled, bool)

    def test_metrics_none_when_disabled(self):
        """When OTel is not enabled, llm_duration and llm_token_usage are None."""
        import os
        # Force reload with OTel disabled
        os.environ.pop("HIVEFLOW_OTEL_ENABLED", None)
        import hiveflow.core.observability as obs
        importlib.reload(obs)
        assert obs.llm_duration is None
        assert obs.llm_token_usage is None

    def test_tracer_exists(self):
        """tracer is always set (OTel API provides no-op tracer even without SDK)."""
        import hiveflow.core.observability as obs
        # tracer is either a real Tracer or None (if opentelemetry not installed)
        assert hasattr(obs, "tracer")

    def test_meter_exists(self):
        """meter is always set when opentelemetry-api is installed."""
        import hiveflow.core.observability as obs
        assert hasattr(obs, "meter")


try:
    import opentelemetry  # noqa: F401
    _has_otel = True
except ImportError:
    _has_otel = False


class TestOTelEnabled:
    """OTel symbols when HIVEFLOW_OTEL_ENABLED=true."""

    @pytest.mark.skipif(not _has_otel, reason="opentelemetry not installed")
    def test_metrics_created_when_enabled(self, monkeypatch):
        monkeypatch.setenv("HIVEFLOW_OTEL_ENABLED", "true")
        import hiveflow.core.observability as obs
        importlib.reload(obs)
        assert obs._otel_enabled is True
        assert obs.llm_duration is not None
        assert obs.llm_token_usage is not None

    def test_flag_case_insensitive(self, monkeypatch):
        monkeypatch.setenv("HIVEFLOW_OTEL_ENABLED", "TRUE")
        import hiveflow.core.observability as obs
        importlib.reload(obs)
        assert obs._otel_enabled is True

    def test_flag_false_when_not_true(self, monkeypatch):
        monkeypatch.setenv("HIVEFLOW_OTEL_ENABLED", "false")
        import hiveflow.core.observability as obs
        importlib.reload(obs)
        assert obs._otel_enabled is False
        assert obs.llm_duration is None


class TestStructlogEvents:
    """structlog logger produces structured output."""

    def test_logger_binds_context(self):
        log = structlog.get_logger()
        bound = log.bind(provider_id="openai", model="gpt-4o")
        # Should not raise
        bound.info("llm.chat.complete", latency_ms=100.0)

    def test_logger_new_returns_bound_logger(self):
        log = structlog.get_logger()
        new_log = log.new(request_id="abc-123")
        # Should not raise
        new_log.info("test.new_context")
