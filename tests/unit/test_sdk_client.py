"""Unit tests for the SDK client: error mapping, constructor, method existence."""

from __future__ import annotations

import httpx
import pytest

from libs.sdk.client import AsyncSynthetoClient, SynthetoClient, _raise_for_status
from libs.sdk.exceptions import (
    SynthetoAPIError,
    SynthetoAuthError,
    SynthetoNotFoundError,
    SynthetoValidationError,
)


class TestErrorMapping:
    def _make_response(self, status_code: int, json_body: dict | None = None) -> httpx.Response:
        content = b""
        if json_body:
            import json

            content = json.dumps(json_body).encode()
        return httpx.Response(
            status_code=status_code,
            content=content,
            headers={"content-type": "application/json"} if json_body else {},
            request=httpx.Request("GET", "http://test"),
        )

    def test_200_no_error(self) -> None:
        resp = self._make_response(200)
        _raise_for_status(resp)  # Should not raise

    def test_401_raises_auth_error(self) -> None:
        resp = self._make_response(401, {"detail": "Unauthorized"})
        with pytest.raises(SynthetoAuthError):
            _raise_for_status(resp)

    def test_403_raises_auth_error(self) -> None:
        resp = self._make_response(403, {"detail": "Forbidden"})
        with pytest.raises(SynthetoAuthError):
            _raise_for_status(resp)

    def test_404_raises_not_found(self) -> None:
        resp = self._make_response(404, {"detail": "Not found"})
        with pytest.raises(SynthetoNotFoundError):
            _raise_for_status(resp)

    def test_422_raises_validation_error(self) -> None:
        resp = self._make_response(422, {"detail": "Validation failed"})
        with pytest.raises(SynthetoValidationError):
            _raise_for_status(resp)

    def test_500_raises_generic_api_error(self) -> None:
        resp = self._make_response(500, {"detail": "Internal error"})
        with pytest.raises(SynthetoAPIError) as exc_info:
            _raise_for_status(resp)
        assert exc_info.value.status_code == 500

    def test_error_extracts_detail_from_json(self) -> None:
        resp = self._make_response(400, {"detail": "Bad request details"})
        with pytest.raises(SynthetoAPIError) as exc_info:
            _raise_for_status(resp)
        assert "Bad request details" in str(exc_info.value)


class TestSyncClientConstructor:
    def test_default_constructor(self) -> None:
        client = SynthetoClient()
        assert client._base_url == "http://127.0.0.1:8000"
        assert client._token == "lab-local-admin"
        client.close()

    def test_custom_constructor(self) -> None:
        client = SynthetoClient(
            base_url="http://custom:9000/",
            token="my-token",
            timeout=10.0,
        )
        assert client._base_url == "http://custom:9000"
        assert client._token == "my-token"
        client.close()

    def test_context_manager(self) -> None:
        with SynthetoClient() as client:
            assert client._base_url == "http://127.0.0.1:8000"


class TestAsyncClientConstructor:
    def test_default_constructor(self) -> None:
        client = AsyncSynthetoClient()
        assert client._base_url == "http://127.0.0.1:8000"
        assert client._token == "lab-local-admin"

    def test_custom_constructor(self) -> None:
        client = AsyncSynthetoClient(
            base_url="http://custom:9000",
            token="my-token",
        )
        assert client._base_url == "http://custom:9000"


class TestSyncClientMethods:
    """Verify all expected methods exist on the sync client."""

    def test_cycle_methods(self) -> None:
        client = SynthetoClient()
        assert callable(client.list_cycles)
        assert callable(client.create_cycle)
        assert callable(client.get_cycle)
        assert callable(client.cycle_command)
        client.close()

    def test_run_methods(self) -> None:
        client = SynthetoClient()
        assert callable(client.list_runs)
        assert callable(client.create_run)
        assert callable(client.get_run)
        assert callable(client.run_command)
        client.close()

    def test_report_methods(self) -> None:
        client = SynthetoClient()
        assert callable(client.list_reports)
        assert callable(client.get_report)
        client.close()

    def test_skill_methods(self) -> None:
        client = SynthetoClient()
        assert callable(client.list_skills)
        assert callable(client.get_skill)
        client.close()

    def test_verification_methods(self) -> None:
        client = SynthetoClient()
        assert callable(client.get_verification_summary)
        assert callable(client.get_verification_report)
        assert callable(client.get_postmortem)
        assert callable(client.get_historical_comparison)
        client.close()

    def test_timeline_method(self) -> None:
        client = SynthetoClient()
        assert callable(client.get_timeline)
        client.close()

    def test_literature_methods(self) -> None:
        client = SynthetoClient()
        assert callable(client.list_papers)
        assert callable(client.get_literature_triage)
        assert callable(client.list_evidence)
        assert callable(client.list_hypotheses)
        assert callable(client.get_portfolio)
        client.close()

    def test_health_method(self) -> None:
        client = SynthetoClient()
        assert callable(client.health)
        client.close()
