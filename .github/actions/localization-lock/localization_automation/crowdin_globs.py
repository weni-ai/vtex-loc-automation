"""Derive Crowdin translation globs and classify repository paths."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml
from wcmatch import glob as wglob

from localization_automation.locale_codes import (
    classify_source_language,
    crowdin_id_for_source,
    extract_locale_token_from_path,
    map_file_token_to_jira,
)

LOCALE_VARS = [
    "%two_letters_code%",
    "%locale%",
    "%locale_with_underscore%",
    "%language%",
    "%three_letters_code%",
    "%android_code%",
    "%osx_code%",
]

GLOB_CHARS = re.compile(r"[*?[\]{}/]")


@dataclass(frozen=True)
class GlobPair:
    translation_glob: str
    source_glob: str

    @property
    def translationGlob(self) -> str:
        return self.translation_glob

    @property
    def sourceGlob(self) -> str:
        return self.source_glob


def _has_glob_chars(segment: str) -> bool:
    return GLOB_CHARS.search(segment) is not None


def _glob_match(path: str, pattern: str) -> bool:
    return wglob.globmatch(
        path,
        pattern,
        flags=wglob.GLOBSTAR | wglob.DOTGLOB,
    )


def derive_glob_pair(entry: dict[str, Any], base_path: str) -> GlobPair:
    source = entry["source"]
    translation = entry["translation"]

    if base_path and base_path not in (".", ""):
        base = base_path.rstrip("/")
        source = f"{base}/{source.lstrip('/')}"
        translation = f"{base}/{translation.lstrip('/')}"

    segments = source.split("/")
    last_segment = segments[-1]

    if _has_glob_chars(last_segment):
        raise ValueError(
            "parse error: source glob's last segment must be a literal filename "
            f"(got: {last_segment})"
        )

    parent_segments = segments[:-1]
    original_path = "/".join(parent_segments)
    original_file_name = last_segment
    dot_index = original_file_name.rfind(".")
    file_extension = (
        original_file_name[dot_index + 1 :] if dot_index >= 0 else ""
    )
    file_name = (
        original_file_name[:dot_index] if dot_index >= 0 else original_file_name
    )

    translation_glob = translation
    translation_glob = translation_glob.replace("%original_path%", original_path)
    translation_glob = translation_glob.replace(
        "%original_file_name%", original_file_name
    )
    translation_glob = translation_glob.replace("%file_extension%", file_extension)
    translation_glob = translation_glob.replace("%file_name%", file_name)

    for locale_var in LOCALE_VARS:
        translation_glob = translation_glob.replace(locale_var, "*")

    translation_glob = re.sub(r"/+", "/", translation_glob)

    return GlobPair(translation_glob=translation_glob, source_glob=source)


def derive_translation_globs(crowdin_yml_path: str | Path) -> list[GlobPair]:
    path = Path(crowdin_yml_path)
    try:
        content = path.read_text(encoding="utf-8")
    except OSError as err:
        raise OSError(
            f"Failed to read crowdin.yml at {crowdin_yml_path}: {err}"
        ) from err

    try:
        parsed = yaml.safe_load(content)
    except yaml.YAMLError as err:
        raise ValueError(
            f"Failed to parse crowdin.yml at {crowdin_yml_path}: {err}"
        ) from err

    if not parsed or "files" not in parsed:
        raise ValueError(
            f"crowdin.yml at {crowdin_yml_path} is missing the required 'files' key"
        )

    files = parsed["files"]
    if not isinstance(files, list) or len(files) == 0:
        return []

    base_path = parsed.get("base_path") or "."
    effective_base = "" if base_path == "." else base_path

    return [derive_glob_pair(entry, effective_base) for entry in files]


def _first_locale_key_in_bundle(bundle_path: Path) -> str | None:
    """Return the first top-level JSON key that looks like a locale token."""
    try:
        data = json.loads(bundle_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, UnicodeDecodeError):
        return None
    if not isinstance(data, dict):
        return None
    for key in data:
        if not isinstance(key, str):
            continue
        if map_file_token_to_jira(key) is None:
            continue
        return key
    return None


def infer_source_language(crowdin_yml_path: str | Path) -> str:
    """
    Infer Crowdin source language id from files[].source paths.

    Examples: en.json → en, pt-br.json → pt-BR, Messages.resx (no locale) → en.
    Locale-bundle-only configs (source path == translation path): use the first
    top-level locale key in the JSON file on disk.
    Not a Crowdin crowdin.yml field — Loc automation only.
    """
    yml_path = Path(crowdin_yml_path)
    pairs = derive_translation_globs(yml_path)
    if not pairs:
        raise ValueError("crowdin.yml has no files entries")

    tokens: list[str] = []
    bundle_paths: list[str] = []
    for pair in pairs:
        source_path = pair.source_glob.lstrip("/")
        translation_path = pair.translation_glob.lstrip("/")
        token = extract_locale_token_from_path(source_path)
        if token is None:
            if source_path == translation_path:
                bundle_paths.append(source_path)
                continue
            # Culture-invariant source (e.g. Messages.resx) → English.
            token = "en"
        tokens.append(token)

    if not tokens:
        repo_root = yml_path.parent
        for relative in bundle_paths:
            bundle_file = repo_root / relative
            first_key = _first_locale_key_in_bundle(bundle_file)
            if first_key is None:
                continue
            return crowdin_id_for_source(classify_source_language(first_key))
        raise ValueError(
            "Cannot infer source language from crowdin.yml: no locale in "
            "files[].source paths and no locale block found in locale-bundle JSON"
        )

    kinds = {classify_source_language(token) for token in tokens}
    if len(kinds) != 1:
        raise ValueError(
            "Conflicting source languages in crowdin.yml files[].source paths: "
            + ", ".join(sorted(tokens))
        )
    return crowdin_id_for_source(next(iter(kinds)))


def is_source_file(path: str, glob_pairs: list[GlobPair]) -> bool:
    normalized_path = path.lstrip("/")
    for pair in glob_pairs:
        norm_source = pair.source_glob.lstrip("/")
        if _glob_match(normalized_path, norm_source):
            return True
    return False


def is_translation_file(
    file_path: str, glob_pairs: list[GlobPair]
) -> dict[str, Any]:
    normalized_path = file_path.lstrip("/")
    for pair in glob_pairs:
        norm_trans = pair.translation_glob.lstrip("/")
        norm_source = pair.source_glob.lstrip("/")
        if not _glob_match(normalized_path, norm_trans):
            continue
        if _glob_match(normalized_path, norm_source):
            continue
        return {"blocked": True, "matchedGlob": pair.translation_glob}
    return {"blocked": False}


def filter_source_files(paths: list[str], crowdin_yml_path: str | Path) -> list[str]:
    glob_pairs = derive_translation_globs(crowdin_yml_path)
    return [p for p in paths if is_source_file(p, glob_pairs)]


def check_paths(
    paths: list[str], crowdin_yml_path: str | Path
) -> list[dict[str, Any]]:
    glob_pairs = derive_translation_globs(crowdin_yml_path)
    blocked: list[dict[str, Any]] = []
    for p in paths:
        result = is_translation_file(p, glob_pairs)
        if result.get("blocked"):
            blocked.append({"path": p, **result})
    return blocked
