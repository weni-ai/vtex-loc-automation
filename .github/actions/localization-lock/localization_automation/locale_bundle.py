"""Guard multi-locale JSON bundles (source path == translation path)."""

from __future__ import annotations

import json
from typing import Any, Callable

from .crowdin_globs import (
    GlobPair,
    derive_translation_globs,
    infer_source_language,
    is_source_file,
)

ReadText = Callable[[str], str | None]


def is_locale_bundle_pair(pair: GlobPair) -> bool:
    """True when crowdin.yml maps a file to itself (all locales in one JSON)."""
    return pair.source_glob.lstrip("/") == pair.translation_glob.lstrip("/")


def locale_bundle_globs(crowdin_yml_path) -> list[GlobPair]:
    return [
        pair
        for pair in derive_translation_globs(crowdin_yml_path)
        if is_locale_bundle_pair(pair)
    ]


def is_locale_bundle_path(relative_path: str, crowdin_yml_path) -> bool:
    pairs = locale_bundle_globs(crowdin_yml_path)
    if not pairs:
        return False
    return is_source_file(relative_path, pairs)


def _parse_object(text: str | None, label: str) -> dict[str, Any]:
    if text is None or text.strip() == "":
        return {}
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError as err:
        raise ValueError(f"Invalid JSON in {label}: {err}") from err
    if not isinstance(parsed, dict):
        raise ValueError(f"Expected JSON object at root of {label}")
    return parsed


def non_source_locale_keys_changed(
    base_obj: dict[str, Any],
    head_obj: dict[str, Any],
    source_language: str,
) -> list[str]:
    """Top-level keys outside source_language whose values differ (add/change/remove)."""
    base_other = {k: v for k, v in base_obj.items() if k != source_language}
    head_other = {k: v for k, v in head_obj.items() if k != source_language}
    changed: list[str] = []
    for key in sorted(set(base_other) | set(head_other)):
        if base_other.get(key) != head_other.get(key):
            changed.append(key)
    return changed


def check_locale_bundle_content(
    relative_path: str,
    *,
    base_text: str | None,
    head_text: str | None,
    source_language: str,
) -> dict[str, Any] | None:
    """If non-source locale blocks changed, return a block dict; else None."""
    base_obj = _parse_object(base_text, f"{relative_path}@base")
    head_obj = _parse_object(head_text, f"{relative_path}@head")
    touched = non_source_locale_keys_changed(base_obj, head_obj, source_language)
    if not touched:
        return None
    return {
        "blocked": True,
        "path": relative_path,
        "reason": "locale_bundle",
        "source_language": source_language,
        "touched_keys": touched,
        "matchedGlob": relative_path,
    }


def check_locale_bundles(
    paths: list[str],
    crowdin_yml_path,
    *,
    read_base: ReadText,
    read_head: ReadText,
) -> list[dict[str, Any]]:
    if not locale_bundle_globs(crowdin_yml_path):
        return []

    source_language = infer_source_language(crowdin_yml_path)

    blocked: list[dict[str, Any]] = []
    seen: set[str] = set()
    for relative_path in paths:
        normalized = relative_path.replace("\\", "/").lstrip("/")
        if normalized in seen:
            continue
        seen.add(normalized)
        if not is_locale_bundle_path(normalized, crowdin_yml_path):
            continue
        result = check_locale_bundle_content(
            normalized,
            base_text=read_base(normalized),
            head_text=read_head(normalized),
            source_language=source_language,
        )
        if result:
            blocked.append(result)
    return blocked
