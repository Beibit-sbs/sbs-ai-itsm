from __future__ import annotations

import hashlib
import json
import math
import re
from typing import Any
import zlib
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from app.models.tenant_experience import TenantExperienceProfile


HEX_COLOR_PATTERN = re.compile(r"^#[0-9A-Fa-f]{6}$")
PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"
MAX_LOGO_BYTES = 512 * 1024
MIN_LOGO_DIMENSION = 32
MAX_LOGO_DIMENSION = 2048
MAX_BRAND_ASSETS_PER_TENANT = 20

ALLOWED_UI_LOCALES = ("ru-RU", "kk-KZ", "en-US")
ALLOWED_FORMAT_LOCALES = ("ru-RU", "kk-KZ", "en-US")
ALLOWED_CURRENCIES = ("KZT", "RUB", "USD", "EUR")
ALLOWED_DATE_STYLES = ("short", "medium", "long")
ALLOWED_HOUR_CYCLES = ("h23", "h12")
ALLOWED_FIRST_DAYS = (1, 7)

DEFAULT_TERMINOLOGY = {
    "incident_singular": "Инцидент",
    "incident_plural": "Инциденты",
    "request_singular": "Запрос услуги",
    "request_plural": "Запросы услуг",
    "asset_singular": "Актив",
    "asset_plural": "Активы",
    "service_singular": "Услуга",
    "service_plural": "Услуги",
    "knowledge_base": "База знаний",
}
TERMINOLOGY_KEYS = tuple(DEFAULT_TERMINOLOGY)

DEFAULT_EXPERIENCE = {
    "product_name": "SBS AI ITSM",
    "short_name": "SBS",
    "logo_asset_id": None,
    "primary_color": "#40A8FF",
    "accent_color": "#7FE2FF",
    "surface_color": "#07111F",
    "text_color": "#E8F0FA",
    "ui_locale": "ru-RU",
    "format_locale": "ru-RU",
    "timezone": "Asia/Qyzylorda",
    "currency_code": "KZT",
    "date_style": "medium",
    "hour_cycle": "h23",
    "first_day_of_week": 1,
    "terminology": DEFAULT_TERMINOLOGY,
}


def canonical_json(value: object) -> str:
    return json.dumps(
        value,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    )


def sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _channel(value: int) -> float:
    normalized = value / 255
    if normalized <= 0.04045:
        return normalized / 12.92
    return math.pow((normalized + 0.055) / 1.055, 2.4)


def relative_luminance(value: str) -> float:
    normalized = normalize_color(value)
    channels = [
        int(normalized[index : index + 2], 16)
        for index in (1, 3, 5)
    ]
    red, green, blue = [_channel(item) for item in channels]
    return 0.2126 * red + 0.7152 * green + 0.0722 * blue


def contrast_ratio(first: str, second: str) -> float:
    first_luminance = relative_luminance(first)
    second_luminance = relative_luminance(second)
    return (
        max(first_luminance, second_luminance) + 0.05
    ) / (
        min(first_luminance, second_luminance) + 0.05
    )


def normalize_color(value: str) -> str:
    normalized = str(value).strip().upper()
    if not HEX_COLOR_PATTERN.fullmatch(normalized):
        raise ValueError("Colors must use six-digit hexadecimal notation")
    return normalized


def best_foreground(background: str) -> str:
    dark = "#03121E"
    light = "#FFFFFF"
    return (
        dark
        if contrast_ratio(dark, background) >= contrast_ratio(light, background)
        else light
    )


def _safe_label(value: object, field: str, *, minimum: int, maximum: int) -> str:
    normalized = " ".join(str(value).split())
    if len(normalized) < minimum or len(normalized) > maximum:
        raise ValueError(f"{field} must contain {minimum}-{maximum} characters")
    if any(character in normalized for character in "<>{}"):
        raise ValueError(f"{field} contains unsupported markup characters")
    if any(ord(character) < 32 for character in normalized):
        raise ValueError(f"{field} contains control characters")
    return normalized


def _normalize_terminology(value: object) -> dict[str, str]:
    if not isinstance(value, dict):
        raise ValueError("terminology must be an object")
    unknown = sorted(set(value) - set(TERMINOLOGY_KEYS))
    missing = sorted(set(TERMINOLOGY_KEYS) - set(value))
    if unknown:
        raise ValueError(f"Unknown terminology keys: {', '.join(unknown)}")
    if missing:
        raise ValueError(f"Missing terminology keys: {', '.join(missing)}")
    return {
        key: _safe_label(value[key], key, minimum=2, maximum=40)
        for key in TERMINOLOGY_KEYS
    }


def validate_experience(value: dict[str, Any]) -> dict[str, Any]:
    product_name = _safe_label(
        value.get("product_name", ""),
        "product_name",
        minimum=2,
        maximum=80,
    )
    short_name = _safe_label(
        value.get("short_name", ""),
        "short_name",
        minimum=2,
        maximum=24,
    )
    primary_color = normalize_color(str(value.get("primary_color", "")))
    accent_color = normalize_color(str(value.get("accent_color", "")))
    surface_color = normalize_color(str(value.get("surface_color", "")))
    text_color = normalize_color(str(value.get("text_color", "")))

    if contrast_ratio(text_color, surface_color) < 4.5:
        raise ValueError("Text and surface colors must have at least 4.5:1 contrast")
    if contrast_ratio(primary_color, surface_color) < 3:
        raise ValueError("Primary and surface colors must have at least 3:1 contrast")
    if contrast_ratio(accent_color, surface_color) < 3:
        raise ValueError("Accent and surface colors must have at least 3:1 contrast")

    ui_locale = str(value.get("ui_locale", ""))
    if ui_locale not in ALLOWED_UI_LOCALES:
        raise ValueError(f"Unsupported UI locale: {ui_locale}")
    format_locale = str(value.get("format_locale", ""))
    if format_locale not in ALLOWED_FORMAT_LOCALES:
        raise ValueError(f"Unsupported format locale: {format_locale}")
    timezone = str(value.get("timezone", "")).strip()
    try:
        ZoneInfo(timezone)
    except (ValueError, ZoneInfoNotFoundError) as exc:
        raise ValueError(f"Unknown IANA timezone: {timezone}") from exc
    currency_code = str(value.get("currency_code", "")).upper()
    if currency_code not in ALLOWED_CURRENCIES:
        raise ValueError(f"Unsupported currency: {currency_code}")
    date_style = str(value.get("date_style", ""))
    if date_style not in ALLOWED_DATE_STYLES:
        raise ValueError(f"Unsupported date style: {date_style}")
    hour_cycle = str(value.get("hour_cycle", ""))
    if hour_cycle not in ALLOWED_HOUR_CYCLES:
        raise ValueError(f"Unsupported hour cycle: {hour_cycle}")
    first_day_of_week = int(value.get("first_day_of_week", 0))
    if first_day_of_week not in ALLOWED_FIRST_DAYS:
        raise ValueError("First day of week must be Monday (1) or Sunday (7)")

    logo_asset_id = value.get("logo_asset_id")
    if logo_asset_id is not None:
        logo_asset_id = str(logo_asset_id)

    return {
        "product_name": product_name,
        "short_name": short_name,
        "logo_asset_id": logo_asset_id,
        "primary_color": primary_color,
        "accent_color": accent_color,
        "surface_color": surface_color,
        "text_color": text_color,
        "ui_locale": ui_locale,
        "format_locale": format_locale,
        "timezone": timezone,
        "currency_code": currency_code,
        "date_style": date_style,
        "hour_cycle": hour_cycle,
        "first_day_of_week": first_day_of_week,
        "terminology": _normalize_terminology(value.get("terminology")),
    }


def default_experience() -> dict[str, Any]:
    return validate_experience(
        {
            **DEFAULT_EXPERIENCE,
            "terminology": dict(DEFAULT_TERMINOLOGY),
        }
    )


def profile_snapshot(profile: TenantExperienceProfile) -> dict[str, Any]:
    return validate_experience(
        {
            "product_name": profile.product_name,
            "short_name": profile.short_name,
            "logo_asset_id": profile.logo_asset_id,
            "primary_color": profile.primary_color,
            "accent_color": profile.accent_color,
            "surface_color": profile.surface_color,
            "text_color": profile.text_color,
            "ui_locale": profile.ui_locale,
            "format_locale": profile.format_locale,
            "timezone": profile.timezone,
            "currency_code": profile.currency_code,
            "date_style": profile.date_style,
            "hour_cycle": profile.hour_cycle,
            "first_day_of_week": profile.first_day_of_week,
            "terminology": json.loads(profile.terminology_json),
        }
    )


def apply_experience(
    profile: TenantExperienceProfile,
    value: dict[str, Any],
) -> dict[str, Any]:
    normalized = validate_experience(value)
    for field in (
        "product_name",
        "short_name",
        "logo_asset_id",
        "primary_color",
        "accent_color",
        "surface_color",
        "text_color",
        "ui_locale",
        "format_locale",
        "timezone",
        "currency_code",
        "date_style",
        "hour_cycle",
        "first_day_of_week",
    ):
        setattr(profile, field, normalized[field])
    profile.terminology_json = canonical_json(normalized["terminology"])
    return normalized


def snapshot_evidence(value: dict[str, Any]) -> tuple[str, str]:
    serialized = canonical_json(validate_experience(value))
    return serialized, sha256_text(serialized)


def png_dimensions(payload: bytes) -> tuple[int, int]:
    if len(payload) > MAX_LOGO_BYTES:
        raise ValueError(f"Logo exceeds {MAX_LOGO_BYTES} bytes")
    if len(payload) < 45 or not payload.startswith(PNG_SIGNATURE):
        raise ValueError("Only validated PNG logos are supported")
    offset = len(PNG_SIGNATURE)
    chunks: list[tuple[bytes, bytes]] = []
    while offset < len(payload):
        if len(chunks) >= 1_000 or offset + 12 > len(payload):
            raise ValueError("PNG logo has an invalid chunk structure")
        length = int.from_bytes(payload[offset : offset + 4], "big")
        chunk_type = payload[offset + 4 : offset + 8]
        chunk_end = offset + 12 + length
        if length > MAX_LOGO_BYTES or chunk_end > len(payload):
            raise ValueError("PNG logo has an invalid chunk length")
        chunk_data = payload[offset + 8 : offset + 8 + length]
        expected_crc = int.from_bytes(
            payload[offset + 8 + length : chunk_end],
            "big",
        )
        actual_crc = zlib.crc32(chunk_type + chunk_data) & 0xFFFFFFFF
        if expected_crc != actual_crc:
            raise ValueError("PNG logo failed its CRC integrity check")
        chunks.append((chunk_type, chunk_data))
        offset = chunk_end
        if chunk_type == b"IEND":
            break
    if offset != len(payload):
        raise ValueError("PNG logo contains trailing data")
    if not chunks or chunks[0][0] != b"IHDR" or len(chunks[0][1]) != 13:
        raise ValueError("PNG logo is missing its IHDR header")
    if chunks[-1] != (b"IEND", b""):
        raise ValueError("PNG logo is missing its IEND marker")
    if not any(chunk_type == b"IDAT" and data for chunk_type, data in chunks):
        raise ValueError("PNG logo is missing image data")

    ihdr = chunks[0][1]
    width = int.from_bytes(ihdr[0:4], "big")
    height = int.from_bytes(ihdr[4:8], "big")
    bit_depth = ihdr[8]
    color_type = ihdr[9]
    compression, filtering, interlace = ihdr[10:13]
    allowed_bit_depths = {
        0: {1, 2, 4, 8, 16},
        2: {8, 16},
        3: {1, 2, 4, 8},
        4: {8, 16},
        6: {8, 16},
    }
    if bit_depth not in allowed_bit_depths.get(color_type, set()):
        raise ValueError("PNG logo uses an unsupported color format")
    if compression != 0 or filtering != 0 or interlace not in {0, 1}:
        raise ValueError("PNG logo uses unsupported encoding parameters")
    if not (
        MIN_LOGO_DIMENSION <= width <= MAX_LOGO_DIMENSION
        and MIN_LOGO_DIMENSION <= height <= MAX_LOGO_DIMENSION
    ):
        raise ValueError(
            "Logo dimensions must be between "
            f"{MIN_LOGO_DIMENSION} and {MAX_LOGO_DIMENSION} pixels"
        )
    return width, height


def experience_contrast(value: dict[str, Any]) -> dict[str, float | str]:
    normalized = validate_experience(value)
    return {
        "text_on_surface": round(
            contrast_ratio(normalized["text_color"], normalized["surface_color"]),
            2,
        ),
        "primary_on_surface": round(
            contrast_ratio(normalized["primary_color"], normalized["surface_color"]),
            2,
        ),
        "accent_on_surface": round(
            contrast_ratio(normalized["accent_color"], normalized["surface_color"]),
            2,
        ),
        "on_primary_color": best_foreground(normalized["primary_color"]),
        "on_accent_color": best_foreground(normalized["accent_color"]),
    }
