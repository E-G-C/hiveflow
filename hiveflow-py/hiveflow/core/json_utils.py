"""JSON Parse Resilience - Robust JSON parsing for LLM outputs.

LLM-generated JSON is frequently malformed. This module provides a
resilient parsing pipeline:
  json.loads() -> json_repair.loads() -> regex extraction -> default fallback
"""

import json
import re
from typing import Any

import structlog

logger = structlog.get_logger()


def parse_json_resilient(
    text: str,
    default: Any = None,
    expect_type: type | None = None,
) -> Any:
    """Parse JSON from potentially malformed LLM output.

    Tries multiple strategies in order:
    1. Standard json.loads()
    2. json_repair library
    3. Regex extraction of JSON blocks
    4. Return default fallback

    Args:
        text: Raw text that should contain JSON
        default: Fallback value if all parsing fails
        expect_type: Expected type (dict, list) for validation

    Returns:
        Parsed JSON value, or default if all parsing fails
    """
    if not text or not text.strip():
        return default

    # Strategy 1: Standard json.loads
    result = _try_standard_parse(text)
    if result is not None and _validate_type(result, expect_type):
        return result

    # Strategy 2: json_repair library
    result = _try_json_repair(text)
    if result is not None and _validate_type(result, expect_type):
        return result

    # Strategy 3: Regex extraction
    result = _try_regex_extraction(text)
    if result is not None and _validate_type(result, expect_type):
        return result

    logger.warning("All JSON parsing strategies failed for text: %.100s...", text)
    return default


def _try_standard_parse(text: str) -> Any | None:
    """Try standard json.loads()."""
    try:
        return json.loads(text.strip())
    except (json.JSONDecodeError, ValueError):
        return None


def _try_json_repair(text: str) -> Any | None:
    """Try json_repair library for malformed JSON."""
    try:
        import json_repair
    except ImportError:
        return None
    try:
        return json_repair.loads(text.strip())
    except (ValueError, TypeError):
        return None


def _try_regex_extraction(text: str) -> Any | None:
    """Try to extract JSON from markdown code blocks or embedded JSON."""
    # Try to find JSON in markdown code blocks
    patterns = [
        r"```json\s*([\s\S]*?)\s*```",  # ```json ... ```
        r"```\s*([\s\S]*?)\s*```",  # ``` ... ```
        r"(\{[\s\S]*\})",  # { ... } (greedy, last resort for objects)
        r"(\[[\s\S]*\])",  # [ ... ] (greedy, last resort for arrays)
    ]

    for pattern in patterns:
        match = re.search(pattern, text)
        if match:
            candidate = match.group(1).strip()
            result = _try_standard_parse(candidate)
            if result is not None:
                return result
            # Also try json_repair on extracted content
            result = _try_json_repair(candidate)
            if result is not None:
                return result

    return None


def _validate_type(value: Any, expect_type: type | None) -> bool:
    """Validate parsed value matches expected type.

    Args:
        value: Parsed value
        expect_type: Expected type (dict, list, etc.) or None for any

    Returns:
        True if type matches or no type expectation
    """
    if expect_type is None:
        return True
    return isinstance(value, expect_type)


def extract_json_from_response(
    response: str,
    expect_type: type = dict,
) -> dict[str, Any] | list[Any] | None:
    """Extract structured JSON from an LLM response.

    Convenience wrapper for common case of extracting dict/list from response.

    Args:
        response: LLM response text
        expect_type: Expected JSON type (dict or list)

    Returns:
        Parsed JSON or None
    """
    result: Any = parse_json_resilient(response, default=None, expect_type=expect_type)
    return result  # type: ignore[no-any-return]
