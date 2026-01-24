import json
from typing import Any

from app.settings import get_settings

_ALLOWED_REASONING_EFFORT = {"none", "minimal", "low", "medium", "high", "xhigh"}
_ALLOWED_TEXT_VERBOSITY = {"low", "medium", "high"}


def _strip_inline_comment(text: str) -> str:
    return text.split("#", 1)[0].strip()


def _supports_reasoning(model: str) -> bool:
    normalized = model.strip().casefold()
    return normalized.startswith(("gpt-5", "o"))


def _supports_temperature(model: str) -> bool:
    normalized = model.strip().casefold()
    return not normalized.startswith(("gpt-5", "o"))


def _find_json_object_span(text: str) -> tuple[int, int] | None:
    start = text.find("{")
    if start < 0:
        return None

    depth = 0
    in_string = False
    escaped = False

    for index, char in enumerate(text[start:], start=start):
        if in_string:
            if escaped:
                escaped = False
                continue
            if char == "\\":
                escaped = True
                continue
            if char == '"':
                in_string = False
            continue

        if char == '"':
            in_string = True
            continue

        if char == "{":
            depth += 1
            continue
        if char == "}":
            depth -= 1
            if depth == 0:
                return start, index + 1

    return None


def extract_json_object(text: str) -> dict:
    stripped = text.strip()
    if not stripped:
        raise ValueError("Empty response")

    try:
        parsed = json.loads(stripped)
    except json.JSONDecodeError:
        parsed = None

    if isinstance(parsed, dict):
        return parsed

    span = _find_json_object_span(stripped)
    if not span:
        raise ValueError("No JSON object found in response")

    start, end = span
    return json.loads(stripped[start:end])


def build_responses_create_kwargs(
    *, model: str, force_json: bool = True
) -> dict[str, Any]:
    settings = get_settings()
    kwargs: dict[str, Any] = {}

    if settings.openai_max_output_tokens is not None:
        kwargs["max_output_tokens"] = settings.openai_max_output_tokens

    if settings.openai_temperature is not None and _supports_temperature(model):
        kwargs["temperature"] = settings.openai_temperature

    if settings.openai_reasoning_effort and _supports_reasoning(model):
        effort = _strip_inline_comment(settings.openai_reasoning_effort).casefold()
        if effort not in _ALLOWED_REASONING_EFFORT:
            raise ValueError(
                "OPENAI_REASONING_EFFORT must be one of "
                + ", ".join(sorted(_ALLOWED_REASONING_EFFORT))
            )
        kwargs["reasoning"] = {"effort": effort}

    text_config: dict[str, Any] = {}
    if settings.openai_text_verbosity:
        verbosity = _strip_inline_comment(settings.openai_text_verbosity).casefold()
        if verbosity not in _ALLOWED_TEXT_VERBOSITY:
            raise ValueError(
                "OPENAI_TEXT_VERBOSITY must be one of "
                + ", ".join(sorted(_ALLOWED_TEXT_VERBOSITY))
            )
        text_config["verbosity"] = verbosity

    if force_json and settings.openai_json_mode:
        text_config["format"] = {"type": "json_object"}

    if text_config:
        kwargs["text"] = text_config

    return kwargs
