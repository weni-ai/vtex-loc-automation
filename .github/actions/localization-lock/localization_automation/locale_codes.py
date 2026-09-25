"""Jira language codes, Crowdin ids, and repo file-token aliases."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Literal

SourceKind = Literal["EN", "PT", "ES"]

# Basename is only a locale token: en.json, pt-BR.yaml, pt_br.json, fr.po
_BASENAME_LOCALE = re.compile(
    r"^(?P<locale>[A-Za-z]{2}(?:[-_][A-Za-z]{2})?)\."
    r"(?:json|ya?ml|po|properties|tsx?|jsx?|xml)$",
    re.IGNORECASE,
)
# Resource with culture suffix: CheckoutMessages.pt-BR.resx / .pt_br.resx
_SUFFIX_LOCALE = re.compile(
    r"\.(?P<locale>[A-Za-z]{2}(?:[-_][A-Za-z]{2})?)\.(?:resx|restext)$",
    re.IGNORECASE,
)
# Fallback: .pt-BR. / .pt_br. before final extension
_DOT_LOCALE_BEFORE_EXT = re.compile(
    r"\.(?P<locale>[A-Za-z]{2}(?:[-_][A-Za-z]{2})?)\.[^.]+$",
    re.IGNORECASE,
)
_PATH_SEGMENT_LOCALE = re.compile(
    r"^(?P<locale>[A-Za-z]{2}(?:[-_][A-Za-z]{2})?)$",
    re.IGNORECASE,
)

IN_HOUSE = frozenset({"EN", "PT", "ES"})

JIRA_TO_CROWDIN: dict[str, str] = {
    "EN": "en",
    "PT": "pt-BR",
    "ES": "es-MX",
    "AR": "ar",
    "BG": "bg",
    "CA": "ca",
    "CS": "cs",
    "DA": "da",
    "DE": "de",
    "EE": "et",
    "EL": "el",
    "FI": "fi",
    "FR": "fr",
    "HU": "hu",
    "ID": "id",
    "IT": "it",
    "JA": "ja",
    "KO": "ko",
    "LT": "lt",
    "LV": "lv",
    "NL": "nl",
    "NN": "nn",
    "PL": "pl",
    "RO": "ro",
    "RU": "ru",
    "SK": "sk",
    "SL": "sl",
    "SR": "sr",
    "SV": "sv",
    "TH": "th",
    "UK": "uk",
}

# Longest-key-first when matching file tokens (see loc-jira-crowdin-setup reference).
FILE_TOKEN_TO_JIRA: dict[str, str] = {
    "en-us": "EN",
    "en-gb": "EN",
    "en": "EN",
    "pt-br": "PT",
    "pt": "PT",
    # pt-pt intentionally omitted — not Jira PT
    "es-mx": "ES",
    "es-es": "ES",
    "es-ar": "ES",
    "es-co": "ES",
    "es": "ES",
    "ar-sa": "AR",
    "ar": "AR",
    "de-de": "DE",
    "de-at": "DE",
    "de": "DE",
    "fr-fr": "FR",
    "fr-ca": "FR",
    "fr": "FR",
    "nl-nl": "NL",
    "nl-be": "NL",
    "nl": "NL",
    "pl-pl": "PL",
    "pl": "PL",
    "ro-ro": "RO",
    "ro": "RO",
    "ru-ru": "RU",
    "ru": "RU",
    "it-it": "IT",
    "it": "IT",
    "ja-jp": "JA",
    "ja": "JA",
    "ko-kr": "KO",
    "ko": "KO",
    "sv-se": "SV",
    "sv": "SV",
    "th-th": "TH",
    "th": "TH",
    "uk-ua": "UK",
    "ua": "UK",
    "uk": "UK",
    "et": "EE",
    "ee": "EE",
    "nb": "NN",
    "no": "NN",
    "nn": "NN",
    "bg": "BG",
    "ca": "CA",
    "cs": "CS",
    "da": "DA",
    "el": "EL",
    "fi": "FI",
    "hu": "HU",
    "id": "ID",
    "in": "ID",
    "lt": "LT",
    "lv": "LV",
    "sk": "SK",
    "sl": "SL",
    "sr": "SR",
}

JIRA_TO_REVIEW_NAME: dict[str, str] = {
    "EN": "English",
    "PT": "Portuguese",
    "ES": "Spanish",
    "AR": "Arabic",
    "BG": "Bulgarian",
    "CA": "Catalan",
    "CS": "Czech",
    "DA": "Danish",
    "DE": "German",
    "EE": "Estonian",
    "EL": "Greek",
    "FI": "Finnish",
    "FR": "French",
    "HU": "Hungarian",
    "ID": "Indonesian",
    "IT": "Italian",
    "JA": "Japanese",
    "KO": "Korean",
    "LT": "Lithuanian",
    "LV": "Latvian",
    "NL": "Dutch",
    "NN": "Norwegian",
    "PL": "Polish",
    "RO": "Romanian",
    "RU": "Russian",
    "SK": "Slovak",
    "SL": "Slovenian",
    "SR": "Serbian",
    "SV": "Swedish",
    "TH": "Thai",
    "UK": "Ukrainian",
}

_SOURCE_ALIASES: dict[str, SourceKind] = {
    "en": "EN",
    "en-us": "EN",
    "en-gb": "EN",
    "pt": "PT",
    "pt-br": "PT",
    "es": "ES",
    "es-mx": "ES",
    "es-es": "ES",
}


def normalize_locale_token(token: str) -> str:
    return token.strip().lower().replace("_", "-")


def map_file_token_to_jira(token: str) -> str | None:
    """Map a repo filename/key locale token to a Jira Languages code, or None."""
    normalized = normalize_locale_token(token)
    if not normalized or normalized == "pt-pt":
        return None
    # Longest alias first
    for alias in sorted(FILE_TOKEN_TO_JIRA.keys(), key=len, reverse=True):
        if normalized == alias:
            return FILE_TOKEN_TO_JIRA[alias]
    return None


def crowdin_id_for_file_token(token: str) -> str | None:
    """Map a repo filename locale token to a Crowdin language id via Jira aliases."""
    jira = map_file_token_to_jira(token)
    if not jira:
        return None
    return JIRA_TO_CROWDIN.get(jira)


def extract_locale_token_from_path(relative_path: str) -> str | None:
    """Best-effort locale token from a source or translation path."""
    name = Path(relative_path).name
    for pattern in (_BASENAME_LOCALE, _SUFFIX_LOCALE, _DOT_LOCALE_BEFORE_EXT):
        match = pattern.search(name)
        if match:
            return normalize_locale_token(match.group("locale"))

    parts = Path(relative_path).parts
    for part in reversed(parts[:-1]):
        match = _PATH_SEGMENT_LOCALE.match(part)
        if match:
            return normalize_locale_token(match.group("locale"))
    return None


def classify_source_language(source_language: str) -> SourceKind:
    """Map a locale token (from path or Crowdin id) to EN/PT/ES or raise."""
    normalized = normalize_locale_token(source_language)
    kind = _SOURCE_ALIASES.get(normalized)
    if kind is None:
        raise ValueError(
            f"Unsupported source language {source_language!r}; "
            "expected EN (en/en-US), PT (pt-BR), or ES (es-MX/es) "
            "inferred from crowdin.yml files[].source paths"
        )
    return kind


def crowdin_id_for_source(kind: SourceKind) -> str:
    return JIRA_TO_CROWDIN[kind]
