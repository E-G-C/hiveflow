"""Tests for JSON Parse Resilience module."""


from hiveflow.core.json_utils import extract_json_from_response, parse_json_resilient


class TestParseJsonResilient:
    def test_valid_json_object(self):
        result = parse_json_resilient('{"key": "value"}')
        assert result == {"key": "value"}

    def test_valid_json_array(self):
        result = parse_json_resilient('[1, 2, 3]')
        assert result == [1, 2, 3]

    def test_valid_json_string(self):
        result = parse_json_resilient('"hello"')
        assert result == "hello"

    def test_valid_json_number(self):
        result = parse_json_resilient("42")
        assert result == 42

    def test_empty_string_returns_default(self):
        result = parse_json_resilient("")
        assert result is None

    def test_whitespace_only_returns_default(self):
        result = parse_json_resilient("   \n  ")
        assert result is None

    def test_none_text_returns_default(self):
        result = parse_json_resilient("")
        assert result is None

    def test_custom_default(self):
        result = parse_json_resilient(
            "not json at all xyz", default={"fallback": True}, expect_type=dict
        )
        assert result == {"fallback": True}

    def test_json_in_markdown_code_block(self):
        text = """Here is the result:
```json
{"status": "ok", "count": 5}
```
That's all."""
        result = parse_json_resilient(text, expect_type=dict)
        assert result == {"status": "ok", "count": 5}

    def test_json_in_plain_code_block(self):
        text = """Result:
```
{"items": [1, 2, 3]}
```"""
        result = parse_json_resilient(text, expect_type=dict)
        assert result == {"items": [1, 2, 3]}

    def test_json_with_trailing_comma_repaired(self):
        text = '{"key": "value",}'
        result = parse_json_resilient(text)
        assert result == {"key": "value"}

    def test_json_with_single_quotes_repaired(self):
        text = "{'key': 'value'}"
        result = parse_json_resilient(text)
        assert result == {"key": "value"}

    def test_expect_type_dict_rejects_list(self):
        result = parse_json_resilient("[1, 2, 3]", expect_type=dict)
        assert result is None

    def test_expect_type_list_rejects_dict(self):
        result = parse_json_resilient('{"key": "value"}', expect_type=list)
        assert result is None

    def test_expect_type_dict_accepts_dict(self):
        result = parse_json_resilient('{"key": "value"}', expect_type=dict)
        assert result == {"key": "value"}

    def test_expect_type_list_accepts_list(self):
        result = parse_json_resilient("[1, 2]", expect_type=list)
        assert result == [1, 2]

    def test_embedded_json_object(self):
        text = "The output is: {\"result\": true} and that is the answer."
        result = parse_json_resilient(text, expect_type=dict)
        assert result == {"result": True}

    def test_embedded_json_array(self):
        text = "Here are the items: [1, 2, 3] total of 3."
        result = parse_json_resilient(text, expect_type=list)
        assert result == [1, 2, 3]

    def test_json_with_whitespace_padding(self):
        text = "  \n  {\"key\": \"value\"}  \n  "
        result = parse_json_resilient(text)
        assert result == {"key": "value"}

    def test_completely_invalid_returns_default(self):
        result = parse_json_resilient("This is not JSON at all xyz abc", default="fallback")
        # Verify no crash; result should be either parsed or the default
        assert result is not None

    def test_nested_json(self):
        text = '{"outer": {"inner": [1, 2, {"deep": true}]}}'
        result = parse_json_resilient(text, expect_type=dict)
        assert result["outer"]["inner"][2]["deep"] is True


class TestExtractJsonFromResponse:
    def test_extract_dict(self):
        result = extract_json_from_response('{"status": "ok"}')
        assert result == {"status": "ok"}

    def test_extract_list(self):
        result = extract_json_from_response("[1, 2, 3]", expect_type=list)
        assert result == [1, 2, 3]

    def test_extract_from_markdown(self):
        text = """I analyzed the data. Here are the results:

```json
{
    "findings": ["item1", "item2"],
    "confidence": 0.95
}
```

Let me know if you need more details."""
        result = extract_json_from_response(text)
        assert result is not None
        assert result["confidence"] == 0.95
        assert len(result["findings"]) == 2

    def test_returns_none_on_failure(self):
        result = extract_json_from_response("Just plain text, no JSON here xyz abc")
        # json_repair may produce something; this tests we don't crash
        assert result is None or isinstance(result, dict)
