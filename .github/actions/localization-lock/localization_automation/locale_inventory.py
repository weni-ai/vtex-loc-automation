"""Discover Jira language codes present in a consumer repo."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

from localization_automation.crowdin_globs import (
    _glob_match,
    derive_translation_globs,
    infer_source_language,
    is_source_file,
    is_translation_file,
)
from localization_automation.locale_bundle import is_locale_bundle_pair
from localization_automation.locale_codes import (
    IN_HOUSE,
    extract_locale_token_from_path,
    map_file_token_to_jira,
)


def _git_ls_files(repo_root: Path) -> list[str]:
    result = subprocess.run(
        ["git", "ls-files"],
        cwd=repo_root,
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        return []
    return [line for line in result.stdout.splitlines() if line]


def _bundle_locale_keys(repo_root: Path, relative_path: str) -> set[str]:
    path = repo_root / relative_path
    if not path.is_file():
        return set()
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return set()
    if not isinstance(data, dict):
        return set()
    codes: set[str] = set()
    for key in data:
        if not isinstance(key, str):
            continue
        jira = map_file_token_to_jira(key)
        if jira:
            codes.add(jira)
    return codes


def discover_jira_languages(repo_root: str | Path) -> dict[str, object]:
    """
    Inventory locales present in the repo via crowdin.yml globs + locale bundles.

    Returns:
      {
        "source_language": str | None,  # inferred from files[].source paths
        "all": ["EN", "PT", ...],
        "in_house": ["EN", "PT", "ES"],
        "vendors": ["RO", ...],
        "unknown_tokens": [...],
      }
    """
    root = Path(repo_root).resolve()
    crowdin = root / "crowdin.yml"
    source_language: str | None = None
    if crowdin.is_file():
        try:
            source_language = infer_source_language(crowdin)
        except ValueError:
            source_language = None

    found: set[str] = set()
    unknown: set[str] = set()

    if crowdin.is_file():
        pairs = derive_translation_globs(crowdin)
        bundle_pairs = [pair for pair in pairs if is_locale_bundle_pair(pair)]
        tracked = _git_ls_files(root)
        for relative in tracked:
            normalized = relative.lstrip("/")

            if bundle_pairs and is_source_file(normalized, bundle_pairs):
                found |= _bundle_locale_keys(root, normalized)
                continue

            matches_translation = is_translation_file(normalized, pairs).get(
                "blocked"
            )
            if not matches_translation:
                matches_translation = any(
                    _glob_match(normalized, pair.translation_glob.lstrip("/"))
                    for pair in pairs
                )
            if not matches_translation:
                continue

            token = extract_locale_token_from_path(normalized)
            if not token:
                continue
            jira = map_file_token_to_jira(token)
            if jira:
                found.add(jira)
            else:
                unknown.add(token)

    in_house = sorted(IN_HOUSE)
    vendors = sorted(code for code in found if code not in IN_HOUSE)
    all_codes = sorted(set(in_house) | found)

    return {
        "source_language": source_language,
        "all": all_codes,
        "in_house": in_house,
        "vendors": vendors,
        "unknown_tokens": sorted(unknown),
    }
