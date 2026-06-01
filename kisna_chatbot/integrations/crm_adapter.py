"""
VTiger CRM adapter for the multi-client WhatsApp chatbot.

Provides async case management via ClientConfig vtiger_base and vtiger_token.
"""

from typing import Any

import httpx

from kisna_chatbot.config.base import ClientConfig
from kisna_chatbot.utils.logger_config import logger

_ALLOWED_UPDATE_FIELDS = frozenset({"status", "priority", "description", "notes"})


class CRMError(Exception):
    """Raised when a CRM API call fails."""

    def __init__(self, message: str, *, cause: Exception | None = None) -> None:
        super().__init__(message)
        self.cause = cause


class CRMAdapter:
    """
    Async VTiger CRM adapter for case create, read, and update operations.

    Constructed with ClientConfig; uses vtiger_base and vtiger_token for Bearer auth.
    """

    def __init__(self, config: ClientConfig) -> None:
        self._config = config
        self.client_id = config.client_id
        self.base_url = (config.vtiger_base or "").rstrip("/")
        self.token = config.vtiger_token or ""
        self._client = httpx.AsyncClient(timeout=30.0)

    async def aclose(self) -> None:
        """Close the underlying HTTP client."""
        await self._client.aclose()

    def _require_config(self) -> None:
        if not self.base_url:
            raise ValueError(
                f"vtiger_base is not configured for client {self.client_id}"
            )
        if not self.token:
            raise ValueError(
                f"vtiger_token is not configured for client {self.client_id}"
            )

    def _headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self.token}",
            "Content-Type": "application/json",
        }

    @staticmethod
    def _status_code(exc: httpx.HTTPError) -> int | None:
        response = getattr(exc, "response", None)
        return getattr(response, "status_code", None) if response is not None else None

    def _crm_error(self, method: str, url: str, exc: httpx.HTTPError) -> CRMError:
        status = self._status_code(exc)
        message = f"{method} {url} failed"
        if status is not None:
            message += f" with status {status}"
        return CRMError(message, cause=exc)

    def _normalize_create_case(self, payload: Any) -> dict:
        case_id = ""
        if isinstance(payload, dict):
            result = payload.get("result")
            if isinstance(result, dict):
                case_id = result.get("caseid") or result.get("id") or ""
            if not case_id:
                case_id = payload.get("caseid") or payload.get("id") or ""
        case_id = str(case_id) if case_id else ""
        return {
            "id": case_id,
            "url": f"{self.base_url}/case/{case_id}",
        }

    async def _patch_case(self, case_id: str, body: dict) -> dict:
        self._require_config()
        url = f"{self.base_url}/api/v1/cases/{case_id}"
        response = await self._client.patch(url, json=body, headers=self._headers())
        response.raise_for_status()
        return response.json()

    async def create_case(
        self,
        title: str,
        description: str,
        case_type: str,
        phone: str,
        customer_name: str,
        priority: str = "Medium",
        status: str = "Open",
    ) -> dict:
        """
        Create a CRM case.

        Args:
            title: Case title.
            description: Case description.
            case_type: Case type (sent as JSON field "type").
            phone: Customer phone number.
            customer_name: Customer display name.
            priority: Case priority.
            status: Initial case status.

        Returns:
            Normalized dict with id and url keys.

        Raises:
            ValueError: If vtiger_base or vtiger_token is not configured.
            CRMError: If the HTTP request fails.
        """
        self._require_config()
        url = f"{self.base_url}/api/v1/cases"
        body = {
            "title": title,
            "description": description,
            "type": case_type,
            "phone": phone,
            "customer_name": customer_name,
            "priority": priority,
            "status": status,
        }

        try:
            response = await self._client.post(url, json=body, headers=self._headers())
            response.raise_for_status()
            payload = response.json()
            result = self._normalize_create_case(payload)
            logger.info(
                "CRM case created",
                extra={
                    "client_id": self.client_id,
                    "case_id": result.get("id"),
                    "phone": phone,
                },
            )
            return result
        except httpx.HTTPError as e:
            logger.exception(
                "CRM case creation failed",
                extra={
                    "client_id": self.client_id,
                    "phone": phone,
                    "status_code": self._status_code(e),
                    "error": str(e),
                },
            )
            raise self._crm_error("POST", url, e) from e
        except Exception as e:
            logger.exception(
                "CRM case creation failed",
                extra={
                    "client_id": self.client_id,
                    "phone": phone,
                    "error": str(e),
                },
            )
            raise

    async def get_case(self, case_id: str) -> dict:
        """
        Fetch a CRM case by id.

        Args:
            case_id: Case identifier.

        Returns:
            Case data as returned by the API.

        Raises:
            ValueError: If vtiger_base or vtiger_token is not configured.
            CRMError: If the HTTP request fails.
        """
        self._require_config()
        url = f"{self.base_url}/api/v1/cases/{case_id}"

        try:
            response = await self._client.get(url, headers=self._headers())
            response.raise_for_status()
            result = response.json()
            logger.info(
                "CRM case fetched",
                extra={
                    "client_id": self.client_id,
                    "case_id": case_id,
                },
            )
            return result
        except httpx.HTTPError as e:
            logger.exception(
                "CRM case fetch failed",
                extra={
                    "client_id": self.client_id,
                    "case_id": case_id,
                    "status_code": self._status_code(e),
                    "error": str(e),
                },
            )
            raise self._crm_error("GET", url, e) from e
        except Exception as e:
            logger.exception(
                "CRM case fetch failed",
                extra={
                    "client_id": self.client_id,
                    "case_id": case_id,
                    "error": str(e),
                },
            )
            raise

    async def update_case(self, case_id: str, **kwargs: Any) -> dict:
        """
        Update fields on an existing CRM case.

        Args:
            case_id: Case identifier.
            **kwargs: Fields to update (status, priority, description, notes).

        Returns:
            Updated case data as returned by the API.

        Raises:
            ValueError: If vtiger_base or vtiger_token is not configured.
            CRMError: If the HTTP request fails.
        """
        body = {k: v for k, v in kwargs.items() if k in _ALLOWED_UPDATE_FIELDS}
        url = f"{self.base_url}/api/v1/cases/{case_id}"

        try:
            result = await self._patch_case(case_id, body)
            logger.info(
                "CRM case updated",
                extra={
                    "client_id": self.client_id,
                    "case_id": case_id,
                    "updated_fields": list(body.keys()),
                },
            )
            return result
        except httpx.HTTPError as e:
            logger.exception(
                "CRM case update failed",
                extra={
                    "client_id": self.client_id,
                    "case_id": case_id,
                    "status_code": self._status_code(e),
                    "error": str(e),
                },
            )
            raise self._crm_error("PATCH", url, e) from e
        except Exception as e:
            logger.exception(
                "CRM case update failed",
                extra={
                    "client_id": self.client_id,
                    "case_id": case_id,
                    "error": str(e),
                },
            )
            raise

    async def assign_case(self, case_id: str, assigned_to: str) -> dict:
        """
        Assign a CRM case to a user or team.

        Args:
            case_id: Case identifier.
            assigned_to: Assignee identifier.

        Returns:
            Updated case data as returned by the API.

        Raises:
            ValueError: If vtiger_base or vtiger_token is not configured.
            CRMError: If the HTTP request fails.
        """
        url = f"{self.base_url}/api/v1/cases/{case_id}"
        body = {"assigned_to": assigned_to}

        try:
            result = await self._patch_case(case_id, body)
            logger.info(
                "CRM case assigned",
                extra={
                    "client_id": self.client_id,
                    "case_id": case_id,
                    "assigned_to": assigned_to,
                },
            )
            return result
        except httpx.HTTPError as e:
            logger.exception(
                "CRM case assignment failed",
                extra={
                    "client_id": self.client_id,
                    "case_id": case_id,
                    "assigned_to": assigned_to,
                    "status_code": self._status_code(e),
                    "error": str(e),
                },
            )
            raise self._crm_error("PATCH", url, e) from e
        except Exception as e:
            logger.exception(
                "CRM case assignment failed",
                extra={
                    "client_id": self.client_id,
                    "case_id": case_id,
                    "assigned_to": assigned_to,
                    "error": str(e),
                },
            )
            raise
