"""Unit tests for libs.adapters.llm.json_utils."""

from __future__ import annotations

import pytest

from libs.adapters.llm.json_utils import extract_json_from_text, parse_json_lenient


class TestExtractJsonFromText:
    def test_clean_json_object(self):
        text = '{"key": "value"}'
        assert extract_json_from_text(text) == '{"key": "value"}'

    def test_clean_json_array(self):
        text = '[1, 2, 3]'
        assert extract_json_from_text(text) == '[1, 2, 3]'

    def test_json_with_markdown_fences(self):
        text = "Here is the result:\n```json\n{\"key\": \"value\"}\n```\nDone."
        assert extract_json_from_text(text) == '{"key": "value"}'

    def test_json_embedded_in_prose(self):
        text = 'The answer is {"decision": "advance", "score": 0.8} and that is all.'
        result = extract_json_from_text(text)
        assert result == '{"decision": "advance", "score": 0.8}'

    def test_no_json_found(self):
        text = "This is just plain text with no JSON."
        assert extract_json_from_text(text) is None

    def test_json_with_uppercase_fence(self):
        text = "```JSON\n[1, 2]\n```"
        assert extract_json_from_text(text) == "[1, 2]"


class TestParseJsonLenient:
    def test_clean_json_object(self):
        result = parse_json_lenient('{"key": "value"}')
        assert result == {"key": "value"}

    def test_clean_json_array(self):
        result = parse_json_lenient('[1, 2, 3]')
        assert result == [1, 2, 3]

    def test_json_in_markdown_fences(self):
        text = "```json\n{\"decision\": \"advance\", \"score\": 0.8}\n```"
        result = parse_json_lenient(text)
        assert result["decision"] == "advance"
        assert result["score"] == 0.8

    def test_json_with_trailing_comma(self):
        text = '{"key": "value", "other": 42,}'
        result = parse_json_lenient(text)
        assert result["key"] == "value"
        assert result["other"] == 42

    def test_json_with_single_quotes(self):
        text = "{'key': 'value', 'num': 42}"
        result = parse_json_lenient(text)
        assert result["key"] == "value"

    def test_json_embedded_in_prose(self):
        text = (
            "Here is my analysis:\n"
            '{"novelty_score": 0.7, "feasibility_score": 0.8, "impact_score": 0.6}\n'
            "That concludes the critique."
        )
        result = parse_json_lenient(text)
        assert result["novelty_score"] == 0.7

    def test_array_embedded_in_prose(self):
        text = 'Evidence items:\n[{"claim": "test"}]\nDone.'
        result = parse_json_lenient(text)
        assert isinstance(result, list)
        assert result[0]["claim"] == "test"

    def test_completely_unparseable_raises(self):
        with pytest.raises(ValueError, match="Failed to parse"):
            parse_json_lenient("This is not JSON at all.")

    def test_empty_string_raises(self):
        with pytest.raises(ValueError, match="Empty text"):
            parse_json_lenient("")

    def test_whitespace_only_raises(self):
        with pytest.raises(ValueError, match="Empty text"):
            parse_json_lenient("   \n  ")
