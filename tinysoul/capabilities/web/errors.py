"""Web capability failures."""

from __future__ import annotations

from enum import StrEnum

from tinysoul.infra import JsonObject, to_json_object


class WebFailureDisposition(StrEnum):
    """Model-facing recovery direction for one Web action failure."""

    RETRY_SAME = "retry_same"
    CHANGE_REQUEST = "change_request"
    USE_FALLBACK = "use_fallback"
    STOP = "stop"


_CHANGE_REQUEST_REASONS = frozenset(
    {
        "discovery_scope_violation",
        "invalid_expected_target_digest",
        "invalid_overwrite",
        "invalid_path_globs",
        "invalid_query",
        "invalid_redirect",
        "invalid_start_url",
        "invalid_target_link",
        "invalid_url",
        "invalid_visit_depth",
        "private_network_target",
        "query_chars_limit_exceeded",
        "redirect_limit_exceeded",
        "result_chars_limit_exceeded",
        "search_token_limit_exceeded",
        "seed_disallowed_by_robots",
        "source_bytes_limit_exceeded",
        "staged_result_bytes_limit_exceeded",
        "tool_round_limit_exceeded",
        "unsupported_content_type",
        "unsupported_url_scheme",
        "url_chars_limit_exceeded",
        "visit_depth_limit_exceeded",
        "output_chars_limit_exceeded",
    }
)
_RETRY_SAME_REASONS = frozenset(
    {
        "dns_resolution_failed",
        "network_request_failed",
    }
)
_USE_FALLBACK_REASONS = frozenset(
    {
        "extractor_failed",
        "extractor_protocol_invalid",
        "invalid_html",
        "no_usable_output",
        "page_visit_failed",
        "process_timeout",
        "provider_output_incomplete",
        "provider_protocol_invalid",
        "seed_fetch_failed",
    }
)
_STOP_REASONS = frozenset(
    {
        "credential_unavailable",
        "dependency_unavailable",
        "process_start_failed",
        "staging_failed",
        "web_discovery_failed",
        "web_fetch_failed",
        "web_search_failed",
        "worker_failed",
        "worker_protocol_invalid",
    }
)
_TRANSIENT_PROVIDER_ERROR_TYPES = frozenset(
    {
        "APIConnectionError",
        "APITimeoutError",
        "InternalServerError",
        "RateLimitError",
    }
)
_STOP_PROVIDER_ERROR_TYPES = frozenset(
    {
        "AuthenticationError",
        "PermissionDeniedError",
    }
)


class WebError(Exception):
    """Base Web capability error."""


class WebContractError(WebError):
    """Raised when a caller violates the Web service contract."""


class WebWorkerProtocolError(WebError):
    """Raised when staged Web worker output violates the host protocol."""


class WebProcessingError(WebError):
    """A stable Web failure suitable for ActionResult mapping."""

    def __init__(
        self,
        message: str,
        *,
        reason: str,
        payload: JsonObject | None = None,
    ) -> None:
        super().__init__(message)
        self.reason = reason
        self.payload = payload or {}


class WebProcessTimeout(WebError):
    """Raised when a controlled Web worker times out or is cancelled."""

    def __init__(self, message: str, *, reason: str) -> None:
        super().__init__(message)
        self.reason = reason


def web_failure_disposition(
    reason: str,
    facts: JsonObject | None = None,
) -> WebFailureDisposition:
    """Classify one stable Web failure without exposing implementation errors."""

    normalized = reason.strip() if isinstance(reason, str) else ""
    safe_facts = facts or {}
    if normalized == "http_status_error":
        status_code = safe_facts.get("status_code")
        if (
            isinstance(status_code, int)
            and not isinstance(status_code, bool)
            and (status_code in {408, 425, 429} or 500 <= status_code <= 599)
        ):
            return WebFailureDisposition.RETRY_SAME
        return WebFailureDisposition.CHANGE_REQUEST
    if normalized == "provider_request_failed":
        error_type = safe_facts.get("error_type")
        if (
            isinstance(error_type, str)
            and error_type in _TRANSIENT_PROVIDER_ERROR_TYPES
        ):
            return WebFailureDisposition.RETRY_SAME
        if isinstance(error_type, str) and error_type in _STOP_PROVIDER_ERROR_TYPES:
            return WebFailureDisposition.STOP
        return WebFailureDisposition.USE_FALLBACK
    if normalized in _RETRY_SAME_REASONS:
        return WebFailureDisposition.RETRY_SAME
    if normalized in _CHANGE_REQUEST_REASONS:
        return WebFailureDisposition.CHANGE_REQUEST
    if normalized in _USE_FALLBACK_REASONS:
        return WebFailureDisposition.USE_FALLBACK
    if normalized in _STOP_REASONS:
        return WebFailureDisposition.STOP
    return WebFailureDisposition.STOP


def web_failure_payload(
    reason: str,
    facts: JsonObject | None = None,
) -> JsonObject:
    """Return the compact model-visible failure and recovery protocol."""

    normalized = (
        reason.strip()
        if isinstance(reason, str) and reason.strip()
        else "web_failure"
    )
    return to_json_object(
        {
            "failure": {
                "reason": normalized,
                "disposition": web_failure_disposition(normalized, facts).value,
            }
        }
    )
