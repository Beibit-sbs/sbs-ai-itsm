from __future__ import annotations

from datetime import date, datetime
import hashlib
import json
import math
import re
from typing import Any


FIELD_TYPES = {
    "text",
    "textarea",
    "integer",
    "number",
    "boolean",
    "date",
    "datetime",
    "email",
    "select",
    "multiselect",
}
FIELD_KEY_PATTERN = re.compile(r"^[a-z][a-z0-9_]{1,63}$")
EMAIL_PATTERN = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def canonical_json(value: object) -> str:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )


def schema_hash(schema: dict[str, Any]) -> str:
    return hashlib.sha256(canonical_json(schema).encode("utf-8")).hexdigest()


def normalize_schema(schema: dict[str, Any] | None) -> dict[str, Any]:
    candidate = schema or {"fields": []}
    if not isinstance(candidate, dict):
        raise ValueError("schema must be an object")
    fields = candidate.get("fields", [])
    if not isinstance(fields, list):
        raise ValueError("schema.fields must be an array")
    if len(fields) > 100:
        raise ValueError("a CI class can define at most 100 fields")

    normalized_fields: list[dict[str, Any]] = []
    keys: set[str] = set()
    for index, field in enumerate(fields):
        if not isinstance(field, dict):
            raise ValueError(f"fields[{index}] must be an object")
        key = str(field.get("key", "")).strip()
        label = str(field.get("label", "")).strip()
        field_type = str(field.get("type", "")).strip().lower()
        if not FIELD_KEY_PATTERN.fullmatch(key):
            raise ValueError(
                f"fields[{index}].key must use lowercase letters, numbers and _"
            )
        if key in keys:
            raise ValueError(f"duplicate field key: {key}")
        if not label or len(label) > 200:
            raise ValueError(f"fields[{index}].label is required")
        if field_type not in FIELD_TYPES:
            raise ValueError(f"fields[{index}].type is unsupported")
        description = str(field.get("description", "")).strip()
        if len(description) > 1_000:
            raise ValueError(f"fields[{index}].description is too long")
        keys.add(key)
        options = field.get("options", [])
        if field_type in {"select", "multiselect"}:
            if not isinstance(options, list) or not options:
                raise ValueError(f"fields[{index}].options are required")
            if len(options) > 200:
                raise ValueError(f"fields[{index}].options has too many entries")
            normalized_options: list[dict[str, str]] = []
            option_values: set[str] = set()
            for option_index, option in enumerate(options):
                if not isinstance(option, dict):
                    raise ValueError(
                        f"fields[{index}].options[{option_index}] must be an object"
                    )
                value = str(option.get("value", "")).strip()
                option_label = str(option.get("label", "")).strip()
                if not value or not option_label:
                    raise ValueError(
                        f"fields[{index}].options[{option_index}] is incomplete"
                    )
                if len(value) > 200 or len(option_label) > 200:
                    raise ValueError(
                        f"fields[{index}].options[{option_index}] is too long"
                    )
                if value in option_values:
                    raise ValueError(f"duplicate option value for {key}: {value}")
                option_values.add(value)
                normalized_options.append({"value": value, "label": option_label})
            options = normalized_options
        else:
            options = []
        normalized_fields.append(
            {
                "key": key,
                "label": label,
                "type": field_type,
                "required": bool(field.get("required", False)),
                "description": description,
                "options": options,
            }
        )
    return {"fields": normalized_fields}


def merge_schemas(
    inherited: dict[str, Any] | None,
    own: dict[str, Any] | None,
) -> dict[str, Any]:
    parent = normalize_schema(inherited)
    child = normalize_schema(own)
    parent_keys = {field["key"] for field in parent["fields"]}
    duplicates = [
        field["key"] for field in child["fields"] if field["key"] in parent_keys
    ]
    if duplicates:
        raise ValueError(
            "child schema cannot override inherited fields: "
            + ", ".join(sorted(duplicates))
        )
    if len(parent["fields"]) + len(child["fields"]) > 100:
        raise ValueError("effective CI schema can contain at most 100 fields")
    return {
        "fields": [
            *(
                {**field, "inherited": True}
                for field in parent["fields"]
            ),
            *(
                {**field, "inherited": False}
                for field in child["fields"]
            ),
        ]
    }


def _normalize_value(field: dict[str, Any], value: Any) -> Any:
    field_type = field["type"]
    if field_type in {"text", "textarea", "email", "select"}:
        if not isinstance(value, str):
            raise ValueError("must be a string")
        result = value.strip()
        maximum_length = 100_000 if field_type == "textarea" else 10_000
        if len(result) > maximum_length:
            raise ValueError(f"must contain at most {maximum_length} characters")
        if field_type == "email" and result and not EMAIL_PATTERN.fullmatch(result):
            raise ValueError("must be a valid email")
        if field_type == "select":
            allowed = {option["value"] for option in field["options"]}
            if result not in allowed:
                raise ValueError("must use an allowed option")
        return result
    if field_type == "integer":
        if isinstance(value, bool):
            raise ValueError("must be an integer")
        if isinstance(value, float) and not value.is_integer():
            raise ValueError("must be an integer")
        if isinstance(value, str) and not re.fullmatch(r"[+-]?\d+", value.strip()):
            raise ValueError("must be an integer")
        try:
            return int(value)
        except (TypeError, ValueError) as exc:
            raise ValueError("must be an integer") from exc
    if field_type == "number":
        if isinstance(value, bool):
            raise ValueError("must be a number")
        try:
            result = float(value)
        except (TypeError, ValueError) as exc:
            raise ValueError("must be a number") from exc
        if not math.isfinite(result):
            raise ValueError("must be a finite number")
        return result
    if field_type == "boolean":
        if not isinstance(value, bool):
            raise ValueError("must be boolean")
        return value
    if field_type == "date":
        if not isinstance(value, str):
            raise ValueError("must be an ISO date")
        try:
            return date.fromisoformat(value).isoformat()
        except ValueError as exc:
            raise ValueError("must be an ISO date") from exc
    if field_type == "datetime":
        if not isinstance(value, str):
            raise ValueError("must be an ISO datetime")
        if "T" not in value and " " not in value:
            raise ValueError("must be an ISO datetime")
        try:
            return datetime.fromisoformat(value.replace("Z", "+00:00")).isoformat()
        except ValueError as exc:
            raise ValueError("must be an ISO datetime") from exc
    if field_type == "multiselect":
        if not isinstance(value, list):
            raise ValueError("must be an array")
        if len(value) > 200:
            raise ValueError("must contain at most 200 options")
        allowed = {option["value"] for option in field["options"]}
        normalized = [str(entry).strip() for entry in value]
        if len(set(normalized)) != len(normalized) or any(
            entry not in allowed for entry in normalized
        ):
            raise ValueError("must contain unique allowed options")
        return normalized
    raise ValueError("uses an unsupported type")


def validate_attributes(
    schema: dict[str, Any],
    attributes: dict[str, Any] | None,
) -> tuple[dict[str, Any], dict[str, list[str]]]:
    definition = normalize_schema(schema)
    values = attributes or {}
    if not isinstance(values, dict):
        return {}, {"_attributes": ["attributes must be an object"]}
    fields = {field["key"]: field for field in definition["fields"]}
    errors: dict[str, list[str]] = {}
    normalized: dict[str, Any] = {}
    for key in values:
        if key not in fields:
            errors.setdefault(key, []).append("field is not defined by the CI class")
    for key, field in fields.items():
        value = values.get(key)
        if value in (None, "", []):
            if field["required"]:
                errors.setdefault(key, []).append("field is required")
            continue
        try:
            normalized[key] = _normalize_value(field, value)
        except ValueError as exc:
            errors.setdefault(key, []).append(str(exc))
    return normalized, errors
