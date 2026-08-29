from __future__ import annotations

from datetime import date
import hashlib
import json
import re
from typing import Any


FIELD_TYPES = {
    "text",
    "textarea",
    "number",
    "boolean",
    "select",
    "multiselect",
    "date",
    "email",
}
VISIBILITY_OPERATORS = {"eq", "neq", "in", "truthy", "falsy"}
FIELD_KEY_PATTERN = re.compile(r"^[a-z][a-z0-9_]{1,63}$")
SECTION_ID_PATTERN = re.compile(r"^[a-z][a-z0-9_-]{1,63}$")
EMAIL_PATTERN = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def default_schema() -> dict[str, Any]:
    return {
        "title": "Данные запроса",
        "introduction": "Заполните сведения, необходимые для выполнения услуги.",
        "sections": [
            {
                "id": "request_details",
                "title": "Детали запроса",
                "description": "",
                "order": 10,
            }
        ],
        "fields": [],
    }


def default_attachment_rules() -> dict[str, Any]:
    return {
        "enabled": False,
        "required": False,
        "max_files": 3,
        "max_size_mb": 10,
        "allowed_extensions": ["pdf", "png", "jpg", "docx", "xlsx"],
    }


def canonical_json(value: object) -> str:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )


def schema_hash(schema: dict[str, Any], attachment_rules: dict[str, Any]) -> str:
    payload = canonical_json({"schema": schema, "attachment_rules": attachment_rules})
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _trimmed_string(value: object, *, max_length: int) -> str | None:
    if not isinstance(value, str):
        return None
    result = value.strip()
    if not result or len(result) > max_length:
        return None
    return result


def validate_form_definition(
    schema: dict[str, Any],
    attachment_rules: dict[str, Any],
) -> list[str]:
    errors: list[str] = []
    if not isinstance(schema, dict):
        return ["schema must be an object"]

    title = _trimmed_string(schema.get("title"), max_length=200)
    if title is None:
        errors.append("Form title is required and must not exceed 200 characters")
    introduction = schema.get("introduction", "")
    if not isinstance(introduction, str) or len(introduction) > 2_000:
        errors.append("Form introduction must be a string up to 2000 characters")

    sections = schema.get("sections")
    fields = schema.get("fields")
    if not isinstance(sections, list) or not sections:
        errors.append("At least one form section is required")
        sections = []
    if len(sections) > 10:
        errors.append("A form can contain at most 10 sections")
    if not isinstance(fields, list):
        errors.append("Form fields must be an array")
        fields = []
    if len(fields) > 50:
        errors.append("A form can contain at most 50 fields")

    section_ids: set[str] = set()
    for index, section in enumerate(sections):
        path = f"sections[{index}]"
        if not isinstance(section, dict):
            errors.append(f"{path} must be an object")
            continue
        section_id = section.get("id")
        if not isinstance(section_id, str) or not SECTION_ID_PATTERN.fullmatch(section_id):
            errors.append(f"{path}.id must use lowercase letters, numbers, _ or -")
        elif section_id in section_ids:
            errors.append(f"{path}.id must be unique")
        else:
            section_ids.add(section_id)
        if _trimmed_string(section.get("title"), max_length=160) is None:
            errors.append(f"{path}.title is required")
        description = section.get("description", "")
        if not isinstance(description, str) or len(description) > 1_000:
            errors.append(f"{path}.description must be a string up to 1000 characters")
        order = section.get("order", (index + 1) * 10)
        if not isinstance(order, int) or isinstance(order, bool) or not 0 <= order <= 10_000:
            errors.append(f"{path}.order must be an integer from 0 to 10000")

    field_keys: set[str] = set()
    for index, field in enumerate(fields):
        path = f"fields[{index}]"
        if not isinstance(field, dict):
            errors.append(f"{path} must be an object")
            continue
        key = field.get("key")
        field_type = field.get("type")
        if not isinstance(key, str) or not FIELD_KEY_PATTERN.fullmatch(key):
            errors.append(f"{path}.key must use lowercase letters, numbers and _")
        elif key in field_keys:
            errors.append(f"{path}.key must be unique")
        else:
            field_keys.add(key)
        if _trimmed_string(field.get("label"), max_length=200) is None:
            errors.append(f"{path}.label is required")
        if field_type not in FIELD_TYPES:
            errors.append(f"{path}.type is unsupported")
        if field.get("section_id") not in section_ids:
            errors.append(f"{path}.section_id references an unavailable section")
        if not isinstance(field.get("required", False), bool):
            errors.append(f"{path}.required must be boolean")
        for property_name, limit in (
            ("help_text", 1_000),
            ("placeholder", 300),
        ):
            value = field.get(property_name, "")
            if not isinstance(value, str) or len(value) > limit:
                errors.append(f"{path}.{property_name} must be a string up to {limit} characters")

        options = field.get("options", [])
        if field_type in {"select", "multiselect"}:
            if not isinstance(options, list) or not options:
                errors.append(f"{path}.options are required for {field_type}")
            elif len(options) > 100:
                errors.append(f"{path}.options can contain at most 100 entries")
            else:
                values: set[str] = set()
                for option_index, option in enumerate(options):
                    option_path = f"{path}.options[{option_index}]"
                    if not isinstance(option, dict):
                        errors.append(f"{option_path} must be an object")
                        continue
                    value = _trimmed_string(option.get("value"), max_length=100)
                    label = _trimmed_string(option.get("label"), max_length=200)
                    if value is None:
                        errors.append(f"{option_path}.value is required")
                    elif value in values:
                        errors.append(f"{option_path}.value must be unique")
                    else:
                        values.add(value)
                    if label is None:
                        errors.append(f"{option_path}.label is required")
        elif options not in (None, []):
            errors.append(f"{path}.options are only supported for choice fields")

        validations = field.get("validations", {})
        if not isinstance(validations, dict):
            errors.append(f"{path}.validations must be an object")
        else:
            min_length = validations.get("min_length")
            max_length = validations.get("max_length")
            if min_length is not None and (
                not isinstance(min_length, int)
                or isinstance(min_length, bool)
                or min_length < 0
                or min_length > 30_000
            ):
                errors.append(f"{path}.validations.min_length is invalid")
            if max_length is not None and (
                not isinstance(max_length, int)
                or isinstance(max_length, bool)
                or max_length < 1
                or max_length > 30_000
            ):
                errors.append(f"{path}.validations.max_length is invalid")
            if (
                isinstance(min_length, int)
                and isinstance(max_length, int)
                and min_length > max_length
            ):
                errors.append(f"{path}.validations min_length cannot exceed max_length")
            minimum = validations.get("min")
            maximum = validations.get("max")
            if minimum is not None and (
                not isinstance(minimum, (int, float)) or isinstance(minimum, bool)
            ):
                errors.append(f"{path}.validations.min must be numeric")
            if maximum is not None and (
                not isinstance(maximum, (int, float)) or isinstance(maximum, bool)
            ):
                errors.append(f"{path}.validations.max must be numeric")
            if (
                isinstance(minimum, (int, float))
                and not isinstance(minimum, bool)
                and isinstance(maximum, (int, float))
                and not isinstance(maximum, bool)
                and minimum > maximum
            ):
                errors.append(f"{path}.validations min cannot exceed max")
            pattern = validations.get("pattern")
            if pattern is not None:
                if not isinstance(pattern, str) or len(pattern) > 500:
                    errors.append(f"{path}.validations.pattern is invalid")
                else:
                    try:
                        re.compile(pattern)
                    except re.error:
                        errors.append(f"{path}.validations.pattern is not valid regex")

        visibility = field.get("visibility")
        if visibility is not None:
            if not isinstance(visibility, dict):
                errors.append(f"{path}.visibility must be an object")
            else:
                controller = visibility.get("field_key")
                operator = visibility.get("operator")
                if controller == key:
                    errors.append(f"{path}.visibility cannot reference itself")
                elif controller not in field_keys:
                    errors.append(
                        f"{path}.visibility must reference a field defined before it"
                    )
                if operator not in VISIBILITY_OPERATORS:
                    errors.append(f"{path}.visibility.operator is unsupported")
                if operator in {"eq", "neq", "in"} and "value" not in visibility:
                    errors.append(f"{path}.visibility.value is required")
                if operator == "in" and not isinstance(visibility.get("value"), list):
                    errors.append(f"{path}.visibility.value must be an array for in")

    errors.extend(validate_attachment_rules(attachment_rules))
    return errors


def validate_attachment_rules(rules: dict[str, Any]) -> list[str]:
    if not isinstance(rules, dict):
        return ["attachment_rules must be an object"]
    errors: list[str] = []
    enabled = rules.get("enabled", False)
    required = rules.get("required", False)
    if not isinstance(enabled, bool) or not isinstance(required, bool):
        errors.append("Attachment enabled and required flags must be boolean")
    if required and not enabled:
        errors.append("Required attachments must also be enabled")
    max_files = rules.get("max_files", 3)
    max_size_mb = rules.get("max_size_mb", 10)
    if not isinstance(max_files, int) or isinstance(max_files, bool) or not 1 <= max_files <= 20:
        errors.append("Attachment max_files must be from 1 to 20")
    if (
        not isinstance(max_size_mb, int)
        or isinstance(max_size_mb, bool)
        or not 1 <= max_size_mb <= 100
    ):
        errors.append("Attachment max_size_mb must be from 1 to 100")
    extensions = rules.get("allowed_extensions", [])
    if not isinstance(extensions, list) or len(extensions) > 30:
        errors.append("Attachment allowed_extensions must be an array of at most 30 values")
    else:
        for extension in extensions:
            if (
                not isinstance(extension, str)
                or not re.fullmatch(r"[a-z0-9]{1,12}", extension.lower())
            ):
                errors.append("Attachment extensions must contain only letters and numbers")
                break
    return errors


def is_visible(field: dict[str, Any], values: dict[str, Any]) -> bool:
    visibility = field.get("visibility")
    if not isinstance(visibility, dict):
        return True
    current = values.get(str(visibility.get("field_key")))
    operator = visibility.get("operator")
    expected = visibility.get("value")
    if operator == "eq":
        return current == expected
    if operator == "neq":
        return current != expected
    if operator == "in":
        return isinstance(expected, list) and current in expected
    if operator == "truthy":
        return bool(current)
    if operator == "falsy":
        return not bool(current)
    return False


def validate_submission(
    schema: dict[str, Any],
    attachment_rules: dict[str, Any],
    values: dict[str, Any],
    attachments: list[dict[str, Any]],
) -> tuple[dict[str, list[str]], dict[str, Any], list[str]]:
    errors: dict[str, list[str]] = {}
    normalized: dict[str, Any] = {}
    visible_fields: list[str] = []

    def add_error(key: str, message: str) -> None:
        errors.setdefault(key, []).append(message)

    fields = schema.get("fields", [])
    for field in fields if isinstance(fields, list) else []:
        if not isinstance(field, dict) or not is_visible(field, values):
            continue
        key = str(field.get("key", ""))
        visible_fields.append(key)
        value = values.get(key)
        empty = value is None or value == "" or value == []
        if field.get("required") and empty:
            add_error(key, "Обязательное поле")
            continue
        if empty:
            continue

        field_type = field.get("type")
        candidate: Any = value
        if field_type in {"text", "textarea", "email", "date", "select"}:
            if not isinstance(value, str):
                add_error(key, "Ожидается текстовое значение")
                continue
            candidate = value.strip()
        elif field_type == "number":
            if isinstance(value, bool):
                add_error(key, "Ожидается число")
                continue
            try:
                candidate = float(value)
                if candidate.is_integer():
                    candidate = int(candidate)
            except (TypeError, ValueError):
                add_error(key, "Ожидается число")
                continue
        elif field_type == "boolean":
            if not isinstance(value, bool):
                add_error(key, "Ожидается значение да/нет")
                continue
        elif field_type == "multiselect":
            if not isinstance(value, list) or any(not isinstance(item, str) for item in value):
                add_error(key, "Ожидается список значений")
                continue

        validations = field.get("validations", {})
        validations = validations if isinstance(validations, dict) else {}
        if isinstance(candidate, str):
            min_length = validations.get("min_length")
            max_length = validations.get("max_length")
            if isinstance(min_length, int) and len(candidate) < min_length:
                add_error(key, f"Минимальная длина: {min_length}")
            if isinstance(max_length, int) and len(candidate) > max_length:
                add_error(key, f"Максимальная длина: {max_length}")
            pattern = validations.get("pattern")
            if isinstance(pattern, str) and not re.fullmatch(pattern, candidate):
                add_error(key, "Значение не соответствует требуемому формату")
        if field_type == "number":
            minimum = validations.get("min")
            maximum = validations.get("max")
            if isinstance(minimum, (int, float)) and candidate < minimum:
                add_error(key, f"Минимальное значение: {minimum}")
            if isinstance(maximum, (int, float)) and candidate > maximum:
                add_error(key, f"Максимальное значение: {maximum}")
        if field_type == "email" and isinstance(candidate, str) and not EMAIL_PATTERN.fullmatch(candidate):
            add_error(key, "Укажите корректный email")
        if field_type == "date" and isinstance(candidate, str):
            try:
                date.fromisoformat(candidate)
            except ValueError:
                add_error(key, "Укажите корректную дату")
        if field_type in {"select", "multiselect"}:
            allowed = {
                option.get("value")
                for option in field.get("options", [])
                if isinstance(option, dict)
            }
            selected_values = candidate if isinstance(candidate, list) else [candidate]
            if any(selected not in allowed for selected in selected_values):
                add_error(key, "Выбрано недоступное значение")
        if key not in errors:
            normalized[key] = candidate

    rules = attachment_rules
    if rules.get("enabled"):
        if rules.get("required") and not attachments:
            add_error("_attachments", "Добавьте обязательное вложение")
        max_files = int(rules.get("max_files", 3))
        if len(attachments) > max_files:
            add_error("_attachments", f"Можно добавить не более {max_files} файлов")
        allowed_extensions = {
            str(extension).lower().lstrip(".")
            for extension in rules.get("allowed_extensions", [])
        }
        max_bytes = int(rules.get("max_size_mb", 10)) * 1024 * 1024
        for attachment in attachments:
            name = str(attachment.get("name", ""))
            extension = name.rsplit(".", 1)[-1].lower() if "." in name else ""
            size = attachment.get("size_bytes")
            if allowed_extensions and extension not in allowed_extensions:
                add_error("_attachments", f"Тип файла {name or 'без имени'} не разрешён")
            if not isinstance(size, int) or size < 0:
                add_error("_attachments", f"Не удалось определить размер файла {name}")
            elif size > max_bytes:
                add_error(
                    "_attachments",
                    f"Файл {name} превышает {rules.get('max_size_mb', 10)} МБ",
                )

    return errors, normalized, visible_fields
