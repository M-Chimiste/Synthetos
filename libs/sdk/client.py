"""Sync and async orchestrator client implementations."""

from __future__ import annotations

from typing import Any

import httpx

from libs.sdk.exceptions import (
    SynthetoAPIError,
    SynthetoAuthError,
    SynthetoNotFoundError,
    SynthetoValidationError,
)

_ERROR_MAP: dict[int, type[SynthetoAPIError]] = {
    401: SynthetoAuthError,
    403: SynthetoAuthError,
    404: SynthetoNotFoundError,
    422: SynthetoValidationError,
}


def _raise_for_status(response: httpx.Response) -> None:
    if response.is_success:
        return
    detail = response.text
    try:
        body = response.json()
        detail = body.get("detail", detail)
    except Exception:
        pass
    exc_class = _ERROR_MAP.get(response.status_code, SynthetoAPIError)
    if exc_class == SynthetoAPIError:
        raise SynthetoAPIError(response.status_code, detail)
    raise exc_class(detail)


class AsyncSynthetoClient:
    """Async orchestrator client using httpx.AsyncClient."""

    def __init__(
        self,
        base_url: str = "http://127.0.0.1:8000",
        token: str = "lab-local-admin",
        timeout: float = 30.0,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._token = token
        self._client = httpx.AsyncClient(
            base_url=self._base_url,
            timeout=timeout,
            headers={
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/json",
            },
        )

    async def close(self) -> None:
        await self._client.aclose()

    async def __aenter__(self) -> AsyncSynthetoClient:
        return self

    async def __aexit__(self, *args: Any) -> None:
        await self.close()

    async def _get(self, path: str) -> dict[str, Any]:
        resp = await self._client.get(path)
        _raise_for_status(resp)
        return resp.json()

    async def _post(self, path: str, json: dict[str, Any] | None = None) -> dict[str, Any]:
        resp = await self._client.post(path, json=json or {})
        _raise_for_status(resp)
        return resp.json()

    # -- Cycles --

    async def list_cycles(self) -> dict[str, Any]:
        return await self._get("/api/v1/cycles")

    async def create_cycle(self, charter: dict[str, Any]) -> dict[str, Any]:
        return await self._post("/api/v1/cycles", json=charter)

    async def get_cycle(self, cycle_id: str) -> dict[str, Any]:
        return await self._get(f"/api/v1/cycles/{cycle_id}")

    async def cycle_command(self, cycle_id: str, command: str, **payload: Any) -> dict[str, Any]:
        return await self._post(
            f"/api/v1/cycles/{cycle_id}/commands",
            json={"command": command, **payload},
        )

    # -- Runs --

    async def list_runs(self, cycle_id: str) -> dict[str, Any]:
        return await self._get(f"/api/v1/cycles/{cycle_id}/runs")

    async def create_run(
        self, spec_id: str, execution_profile: str = "cpu-small", force_start: bool = False,
    ) -> dict[str, Any]:
        return await self._post(
            f"/api/v1/experiment-specs/{spec_id}/runs",
            json={"execution_profile": execution_profile, "force_start": force_start},
        )

    async def get_run(self, run_id: str) -> dict[str, Any]:
        return await self._get(f"/api/v1/runs/{run_id}")

    async def run_command(self, run_id: str, command: str) -> dict[str, Any]:
        return await self._post(f"/api/v1/runs/{run_id}/commands", json={"command": command})

    # -- Reports --

    async def list_reports(self) -> dict[str, Any]:
        return await self._get("/api/v1/reports")

    async def get_report(self, report_id: str) -> dict[str, Any]:
        return await self._get(f"/api/v1/reports/{report_id}")

    # -- Skills --

    async def list_skills(self) -> dict[str, Any]:
        return await self._get("/api/v1/skills")

    async def get_skill(self, skill_id: str) -> dict[str, Any]:
        return await self._get(f"/api/v1/skills/{skill_id}")

    # -- Verification --

    async def get_verification_summary(self, cycle_id: str) -> dict[str, Any]:
        return await self._get(f"/api/v1/cycles/{cycle_id}/verification")

    async def get_verification_report(self, report_id: str) -> dict[str, Any]:
        return await self._get(f"/api/v1/verification-reports/{report_id}")

    async def get_postmortem(self, postmortem_id: str) -> dict[str, Any]:
        return await self._get(f"/api/v1/postmortems/{postmortem_id}")

    async def get_historical_comparison(self, run_id: str) -> dict[str, Any]:
        return await self._get(f"/api/v1/runs/{run_id}/historical-comparison")

    # -- Timeline --

    async def get_timeline(self, cycle_id: str) -> dict[str, Any]:
        return await self._get(f"/api/v1/cycles/{cycle_id}/timeline")

    # -- Literature --

    async def list_papers(self, cycle_id: str, status: str | None = None) -> dict[str, Any]:
        path = f"/api/v1/cycles/{cycle_id}/papers"
        if status:
            path += f"?status={status}"
        return await self._get(path)

    async def get_literature_triage(self, cycle_id: str) -> dict[str, Any]:
        return await self._get(f"/api/v1/cycles/{cycle_id}/literature")

    # -- Evidence & Hypotheses --

    async def list_evidence(self, cycle_id: str) -> dict[str, Any]:
        return await self._get(f"/api/v1/cycles/{cycle_id}/evidence")

    async def list_hypotheses(self, cycle_id: str) -> dict[str, Any]:
        return await self._get(f"/api/v1/cycles/{cycle_id}/hypotheses")

    async def get_portfolio(self, cycle_id: str) -> dict[str, Any]:
        return await self._get(f"/api/v1/cycles/{cycle_id}/hypotheses/portfolio")

    # -- Health --

    async def health(self) -> dict[str, Any]:
        return await self._get("/api/v1/healthz")


class SynthetoClient:
    """Sync orchestrator client using httpx.Client."""

    def __init__(
        self,
        base_url: str = "http://127.0.0.1:8000",
        token: str = "lab-local-admin",
        timeout: float = 30.0,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._token = token
        self._client = httpx.Client(
            base_url=self._base_url,
            timeout=timeout,
            headers={
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/json",
            },
        )

    def close(self) -> None:
        self._client.close()

    def __enter__(self) -> SynthetoClient:
        return self

    def __exit__(self, *args: Any) -> None:
        self.close()

    def _get(self, path: str) -> dict[str, Any]:
        resp = self._client.get(path)
        _raise_for_status(resp)
        return resp.json()

    def _post(self, path: str, json: dict[str, Any] | None = None) -> dict[str, Any]:
        resp = self._client.post(path, json=json or {})
        _raise_for_status(resp)
        return resp.json()

    # -- Cycles --

    def list_cycles(self) -> dict[str, Any]:
        return self._get("/api/v1/cycles")

    def create_cycle(self, charter: dict[str, Any]) -> dict[str, Any]:
        return self._post("/api/v1/cycles", json=charter)

    def get_cycle(self, cycle_id: str) -> dict[str, Any]:
        return self._get(f"/api/v1/cycles/{cycle_id}")

    def cycle_command(self, cycle_id: str, command: str, **payload: Any) -> dict[str, Any]:
        return self._post(
            f"/api/v1/cycles/{cycle_id}/commands",
            json={"command": command, **payload},
        )

    # -- Runs --

    def list_runs(self, cycle_id: str) -> dict[str, Any]:
        return self._get(f"/api/v1/cycles/{cycle_id}/runs")

    def create_run(
        self, spec_id: str, execution_profile: str = "cpu-small", force_start: bool = False,
    ) -> dict[str, Any]:
        return self._post(
            f"/api/v1/experiment-specs/{spec_id}/runs",
            json={"execution_profile": execution_profile, "force_start": force_start},
        )

    def get_run(self, run_id: str) -> dict[str, Any]:
        return self._get(f"/api/v1/runs/{run_id}")

    def run_command(self, run_id: str, command: str) -> dict[str, Any]:
        return self._post(f"/api/v1/runs/{run_id}/commands", json={"command": command})

    # -- Reports --

    def list_reports(self) -> dict[str, Any]:
        return self._get("/api/v1/reports")

    def get_report(self, report_id: str) -> dict[str, Any]:
        return self._get(f"/api/v1/reports/{report_id}")

    # -- Skills --

    def list_skills(self) -> dict[str, Any]:
        return self._get("/api/v1/skills")

    def get_skill(self, skill_id: str) -> dict[str, Any]:
        return self._get(f"/api/v1/skills/{skill_id}")

    # -- Verification --

    def get_verification_summary(self, cycle_id: str) -> dict[str, Any]:
        return self._get(f"/api/v1/cycles/{cycle_id}/verification")

    def get_verification_report(self, report_id: str) -> dict[str, Any]:
        return self._get(f"/api/v1/verification-reports/{report_id}")

    def get_postmortem(self, postmortem_id: str) -> dict[str, Any]:
        return self._get(f"/api/v1/postmortems/{postmortem_id}")

    def get_historical_comparison(self, run_id: str) -> dict[str, Any]:
        return self._get(f"/api/v1/runs/{run_id}/historical-comparison")

    # -- Timeline --

    def get_timeline(self, cycle_id: str) -> dict[str, Any]:
        return self._get(f"/api/v1/cycles/{cycle_id}/timeline")

    # -- Literature --

    def list_papers(self, cycle_id: str, status: str | None = None) -> dict[str, Any]:
        path = f"/api/v1/cycles/{cycle_id}/papers"
        if status:
            path += f"?status={status}"
        return self._get(path)

    def get_literature_triage(self, cycle_id: str) -> dict[str, Any]:
        return self._get(f"/api/v1/cycles/{cycle_id}/literature")

    # -- Evidence & Hypotheses --

    def list_evidence(self, cycle_id: str) -> dict[str, Any]:
        return self._get(f"/api/v1/cycles/{cycle_id}/evidence")

    def list_hypotheses(self, cycle_id: str) -> dict[str, Any]:
        return self._get(f"/api/v1/cycles/{cycle_id}/hypotheses")

    def get_portfolio(self, cycle_id: str) -> dict[str, Any]:
        return self._get(f"/api/v1/cycles/{cycle_id}/hypotheses/portfolio")

    # -- Health --

    def health(self) -> dict[str, Any]:
        return self._get("/api/v1/healthz")
