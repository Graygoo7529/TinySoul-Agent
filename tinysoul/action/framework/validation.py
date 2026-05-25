"""
Lightweight structural validators for Action metadata and input parameters.

No external dependencies — implements a small hand-written validator
instead of pulling in ``jsonschema``.
"""

import json
from typing import Any

from tinysoul.trap import ActionExecutionError, ActionInputError


# Keys required at the top level of an ACTION_JSON object.
_REQUIRED_ACTION_JSON_TOP_KEYS = (
    "name",
    "description",
    "cluster",
    "profile",
    "contract",
    "detail",
)

# Keys required inside ``cluster``.
_REQUIRED_CLUSTER_KEYS = ("type", "domain")

# Keys required inside ``profile``.
_REQUIRED_PROFILE_KEYS = (
    "action_intention",
    "action_environment_effect",
    "action_mode",
    "llm_dependency",
)

# Keys required inside ``contract``.
_REQUIRED_CONTRACT_KEYS = ("applicability", "preconditions", "postconditions")

# Keys required inside ``contract.applicability``.
_REQUIRED_APPLICABILITY_KEYS = ("mode",)

# Keys required inside ``detail``.
_REQUIRED_DETAIL_KEYS = ("parameter_schema",)


def validate_action_metadata(action_json: str) -> dict[str, Any]:
    """
    Parse and validate an ACTION_JSON string for structural correctness.

    Checks performed:
    - Valid JSON that parses to a ``dict``.
    - All required top-level keys are present and non-empty.
    - ``cluster`` is a dict with ``type`` and ``domain``.
    - ``profile`` is a dict with the four required trait keys.
    - ``contract`` is a dict with ``applicability`` (which has ``mode``),
      ``preconditions``, and ``postconditions``.
    - ``detail`` is a dict with ``parameter_schema``.

    Args:
        action_json: Raw JSON string describing an action.

    Returns:
        The parsed ``dict`` on success.

    Raises:
        ActionExecutionError: If any structural check fails.
    """
    try:
        data = json.loads(action_json)
    except json.JSONDecodeError as exc:
        raise ActionExecutionError(
            f"ACTION_JSON is not valid JSON: {exc}"
        ) from exc

    if not isinstance(data, dict):
        raise ActionExecutionError(
            f"ACTION_JSON must be a JSON object, got {type(data).__name__}"
        )

    # Top-level keys
    for key in _REQUIRED_ACTION_JSON_TOP_KEYS:
        if key not in data:
            raise ActionExecutionError(
                f"ACTION_JSON missing required key: '{key}'"
            )
        if key == "description" and (not data[key] or not isinstance(data[key], str)):
            raise ActionExecutionError(
                f"ACTION_JSON '{key}' must be a non-empty string"
            )

    # cluster
    cluster = data.get("cluster", {})
    if not isinstance(cluster, dict):
        raise ActionExecutionError("ACTION_JSON 'cluster' must be an object")
    for key in _REQUIRED_CLUSTER_KEYS:
        if key not in cluster:
            raise ActionExecutionError(
                f"ACTION_JSON cluster missing required key: '{key}'"
            )

    # profile
    profile = data.get("profile", {})
    if not isinstance(profile, dict):
        raise ActionExecutionError("ACTION_JSON 'profile' must be an object")
    for key in _REQUIRED_PROFILE_KEYS:
        if key not in profile:
            raise ActionExecutionError(
                f"ACTION_JSON profile missing required key: '{key}'"
            )

    # contract
    contract = data.get("contract", {})
    if not isinstance(contract, dict):
        raise ActionExecutionError("ACTION_JSON 'contract' must be an object")
    for key in _REQUIRED_CONTRACT_KEYS:
        if key not in contract:
            raise ActionExecutionError(
                f"ACTION_JSON contract missing required key: '{key}'"
            )

    applicability = contract.get("applicability", {})
    if not isinstance(applicability, dict):
        raise ActionExecutionError(
            "ACTION_JSON contract.applicability must be an object"
        )
    for key in _REQUIRED_APPLICABILITY_KEYS:
        if key not in applicability:
            raise ActionExecutionError(
                f"ACTION_JSON contract.applicability missing required key: '{key}'"
            )

    # detail
    detail = data.get("detail", {})
    if not isinstance(detail, dict):
        raise ActionExecutionError("ACTION_JSON 'detail' must be an object")
    for key in _REQUIRED_DETAIL_KEYS:
        if key not in detail:
            raise ActionExecutionError(
                f"ACTION_JSON detail missing required key: '{key}'"
            )

    return data


def validate_action_input(action_name: str, schema: dict[str, Any], payload: dict[str, Any]) -> None:
    """
    Validate action input parameters against ``parameter_schema``.

    Checks performed:
    - ``payload`` is a ``dict``.
    - Every field listed in ``schema["required"]`` is present as a key in
      ``payload``.

    Args:
        action_name: Name of the action (for error messages).
        schema: The ``parameter_schema`` dict from the action's metadata.
        payload: The action input dict to validate.

    Raises:
        ActionInputError: If validation fails.
    """
    if not isinstance(payload, dict):
        raise ActionInputError(
            f"Action '{action_name}' input must be an object, got {type(payload).__name__}",
            action_name=action_name,
            action_input=payload,
        )

    required = schema.get("required", [])
    if not isinstance(required, list):
        required = []

    missing = [field for field in required if field not in payload]
    if missing:
        raise ActionInputError(
            f"Action '{action_name}' missing required parameter(s): {', '.join(missing)}",
            action_name=action_name,
            action_input=payload,
        )
