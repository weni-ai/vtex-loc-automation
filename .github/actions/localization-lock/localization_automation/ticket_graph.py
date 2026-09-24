"""Build LOC ticket subtask summaries and Blocks index pairs from source + vendors."""

from __future__ import annotations

from dataclasses import asdict, dataclass

from localization_automation.locale_codes import (
    IN_HOUSE,
    JIRA_TO_REVIEW_NAME,
    SourceKind,
    classify_source_language,
)


PREPARE = "Prepare file to be localized"
UPDATE_SOURCE = "Update source file"
HANDOFF = "Change Crowdin project"
CREATE_PR = "Create PR"
OTHER_LANGUAGES = "Other languages"

ENGLISH = "English"
PORTUGUESE = "Portuguese"
SPANISH = "Spanish"

# Crowdin parent word count below this → one subtask per language (no review chain).
# Set to 0 to disable the short plan (re-enable with e.g. 40 when ready).
SHORT_WORD_THRESHOLD = 0


def _chain(language_name: str) -> list[str]:
    return [
        f"{language_name} review",
        f"{language_name} review 2",
        f"{language_name} implementation",
    ]


def _vendor_summaries(vendor_codes: list[str]) -> list[str]:
    """Full-flow vendor labels: single → '{Name} review'; many → Other languages."""
    if not vendor_codes:
        return []
    if len(vendor_codes) == 1:
        code = vendor_codes[0]
        name = JIRA_TO_REVIEW_NAME.get(code, code)
        return [f"{name} review"]
    return [OTHER_LANGUAGES]


def _short_vendor_summaries(vendor_codes: list[str]) -> list[str]:
    """Short-flow vendor labels: single → language name only; many → Other languages."""
    if not vendor_codes:
        return []
    if len(vendor_codes) == 1:
        code = vendor_codes[0]
        return [JIRA_TO_REVIEW_NAME.get(code, code)]
    return [OTHER_LANGUAGES]


def _in_house_languages_by_summary() -> dict[str, list[str]]:
    return {
        "English review": ["EN"],
        "English review 2": ["EN"],
        "English implementation": ["EN"],
        ENGLISH: ["EN"],
        "Portuguese review": ["PT"],
        "Portuguese review 2": ["PT"],
        "Portuguese implementation": ["PT"],
        PORTUGUESE: ["PT"],
        "Spanish review": ["ES"],
        "Spanish review 2": ["ES"],
        "Spanish implementation": ["ES"],
        SPANISH: ["ES"],
    }


@dataclass(frozen=True)
class TicketPlan:
    source: SourceKind
    summaries: list[str]
    block_pairs: list[list[int]]
    parent_languages: list[str]
    languages_by_summary: dict[str, list[str]]
    primary_review_summary: str
    handoff_summary: str | None
    vendor_codes: list[str]
    # 1 = short (below SHORT_WORD_THRESHOLD; currently disabled at 0): single week.
    # 2 = source week + one parallel in-house target week (EN, or PT/ES with no vendors).
    # 3 = PT/ES source with vendors (serialized EN then second in-house + vendors).
    wave_count: int

    def to_dict(self) -> dict:
        return asdict(self)


def _build_short_ticket_plan(
    source: SourceKind,
    vendors: list[str],
) -> TicketPlan:
    """One language subtask each; Prepare/Create PR unchanged; dues = next week."""
    vendor_subs = _short_vendor_summaries(vendors)
    summaries: list[str] = [PREPARE]
    block_pairs: list[list[int]] = []

    def idx(summary: str) -> int:
        return summaries.index(summary)

    def link(blocker: str, blocked: str) -> None:
        block_pairs.append([idx(blocker), idx(blocked)])

    if source == "EN":
        # Prepare → English → Update → PT / ES / [vendor] → Create PR
        summaries.extend([ENGLISH, UPDATE_SOURCE, PORTUGUESE, SPANISH])
        summaries.extend(vendor_subs)
        summaries.append(CREATE_PR)

        link(PREPARE, ENGLISH)
        link(ENGLISH, UPDATE_SOURCE)
        link(UPDATE_SOURCE, PORTUGUESE)
        link(UPDATE_SOURCE, SPANISH)
        link(ENGLISH, CREATE_PR)
        link(PORTUGUESE, CREATE_PR)
        link(SPANISH, CREATE_PR)
        for vendor in vendor_subs:
            link(UPDATE_SOURCE, vendor)
            link(vendor, CREATE_PR)
        handoff = None
        primary = ENGLISH

    elif source == "PT":
        if not vendors:
            summaries.extend([PORTUGUESE, UPDATE_SOURCE, ENGLISH, SPANISH, CREATE_PR])
            link(PREPARE, PORTUGUESE)
            link(PORTUGUESE, UPDATE_SOURCE)
            link(UPDATE_SOURCE, ENGLISH)
            link(UPDATE_SOURCE, SPANISH)
            link(PORTUGUESE, CREATE_PR)
            link(ENGLISH, CREATE_PR)
            link(SPANISH, CREATE_PR)
            handoff = None
        else:
            # Prepare → Portuguese → Update (Mon) → Change project + English (Tue)
            # / ES+[vendor] (Fri)
            summaries.extend(
                [PORTUGUESE, UPDATE_SOURCE, HANDOFF, ENGLISH, SPANISH]
            )
            summaries.extend(vendor_subs)
            summaries.append(CREATE_PR)
            link(PREPARE, PORTUGUESE)
            link(PORTUGUESE, UPDATE_SOURCE)
            link(UPDATE_SOURCE, HANDOFF)
            link(UPDATE_SOURCE, ENGLISH)
            link(HANDOFF, SPANISH)
            link(PORTUGUESE, CREATE_PR)
            link(ENGLISH, CREATE_PR)
            link(SPANISH, CREATE_PR)
            for vendor in vendor_subs:
                link(HANDOFF, vendor)
                link(vendor, CREATE_PR)
            handoff = HANDOFF
        primary = PORTUGUESE

    else:  # ES
        if not vendors:
            summaries.extend([SPANISH, UPDATE_SOURCE, ENGLISH, PORTUGUESE, CREATE_PR])
            link(PREPARE, SPANISH)
            link(SPANISH, UPDATE_SOURCE)
            link(UPDATE_SOURCE, ENGLISH)
            link(UPDATE_SOURCE, PORTUGUESE)
            link(SPANISH, CREATE_PR)
            link(ENGLISH, CREATE_PR)
            link(PORTUGUESE, CREATE_PR)
            handoff = None
        else:
            # Prepare → Spanish → Update (Mon) → Change project + English (Tue)
            # / PT+[vendor] (Fri)
            summaries.extend(
                [SPANISH, UPDATE_SOURCE, HANDOFF, ENGLISH, PORTUGUESE]
            )
            summaries.extend(vendor_subs)
            summaries.append(CREATE_PR)
            link(PREPARE, SPANISH)
            link(SPANISH, UPDATE_SOURCE)
            link(UPDATE_SOURCE, HANDOFF)
            link(UPDATE_SOURCE, ENGLISH)
            link(HANDOFF, PORTUGUESE)
            link(SPANISH, CREATE_PR)
            link(ENGLISH, CREATE_PR)
            link(PORTUGUESE, CREATE_PR)
            for vendor in vendor_subs:
                link(HANDOFF, vendor)
                link(vendor, CREATE_PR)
            handoff = HANDOFF
        primary = SPANISH

    languages_by_summary = _in_house_languages_by_summary()
    if len(vendors) == 1:
        languages_by_summary[vendor_subs[0]] = [vendors[0]]
    elif len(vendors) >= 2:
        languages_by_summary[OTHER_LANGUAGES] = list(vendors)

    return TicketPlan(
        source=source,
        summaries=summaries,
        block_pairs=block_pairs,
        parent_languages=sorted(IN_HOUSE | set(vendors)),
        languages_by_summary=languages_by_summary,
        primary_review_summary=primary,
        handoff_summary=handoff,
        vendor_codes=vendors,
        wave_count=1,
    )


def build_ticket_plan(
    source_language: str,
    vendor_codes: list[str] | None = None,
    *,
    word_count: int | None = None,
) -> TicketPlan:
    source = classify_source_language(source_language)
    vendors = sorted({code for code in (vendor_codes or []) if code not in IN_HOUSE})

    if word_count is not None and 0 < word_count < SHORT_WORD_THRESHOLD:
        return _build_short_ticket_plan(source, vendors)

    en = _chain("English")
    pt = _chain("Portuguese")
    es = _chain("Spanish")
    vendor_subs = _vendor_summaries(vendors)

    summaries: list[str] = [PREPARE]
    block_pairs: list[list[int]] = []

    def idx(summary: str) -> int:
        return summaries.index(summary)

    def link(blocker: str, blocked: str) -> None:
        block_pairs.append([idx(blocker), idx(blocked)])

    def link_chain(chain: list[str]) -> None:
        for i in range(len(chain) - 1):
            link(chain[i], chain[i + 1])

    if source == "EN":
        # Prepare → EN* → Update → PT* / ES* → [vendor] → Create PR
        summaries.extend(en)
        summaries.append(UPDATE_SOURCE)
        summaries.extend(pt)
        summaries.extend(es)
        summaries.extend(vendor_subs)
        summaries.append(CREATE_PR)

        link(PREPARE, en[0])
        link_chain(en)
        link(en[-1], UPDATE_SOURCE)
        link(UPDATE_SOURCE, pt[0])
        link(UPDATE_SOURCE, es[0])
        link_chain(pt)
        link_chain(es)
        link(pt[-1], CREATE_PR)
        link(es[-1], CREATE_PR)
        link(en[-1], CREATE_PR)
        for vendor in vendor_subs:
            link(UPDATE_SOURCE, vendor)
            link(vendor, CREATE_PR)
        handoff = None
        primary = en[0]
        wave_count = 2

    elif source == "PT":
        if not vendors:
            # 2 waves: Prepare → PT* → Update → EN* / ES* → Create PR (no project handoff)
            summaries.extend(pt)
            summaries.append(UPDATE_SOURCE)
            summaries.extend(en)
            summaries.extend(es)
            summaries.append(CREATE_PR)

            link(PREPARE, pt[0])
            link_chain(pt)
            link(pt[-1], UPDATE_SOURCE)
            link(UPDATE_SOURCE, en[0])
            link(UPDATE_SOURCE, es[0])
            link_chain(en)
            link_chain(es)
            link(en[-1], CREATE_PR)
            link(es[-1], CREATE_PR)
            handoff = None
            wave_count = 2
        else:
            # 3 waves: Prepare → PT* → Update → EN* → handoff → ES* / [vendor] → Create PR
            summaries.extend(pt)
            summaries.append(UPDATE_SOURCE)
            summaries.extend(en)
            summaries.append(HANDOFF)
            summaries.extend(es)
            summaries.extend(vendor_subs)
            summaries.append(CREATE_PR)

            link(PREPARE, pt[0])
            link_chain(pt)
            link(pt[-1], UPDATE_SOURCE)
            link(UPDATE_SOURCE, en[0])
            link_chain(en)
            link(pt[-1], HANDOFF)
            link(en[-1], HANDOFF)
            link(HANDOFF, es[0])
            link_chain(es)
            link(es[-1], CREATE_PR)
            link(en[-1], CREATE_PR)
            for vendor in vendor_subs:
                link(HANDOFF, vendor)
                link(vendor, CREATE_PR)
            handoff = HANDOFF
            wave_count = 3
        primary = pt[0]

    else:  # ES
        if not vendors:
            # 2 waves: Prepare → ES* → Update → EN* / PT* → Create PR (no project handoff)
            summaries.extend(es)
            summaries.append(UPDATE_SOURCE)
            summaries.extend(en)
            summaries.extend(pt)
            summaries.append(CREATE_PR)

            link(PREPARE, es[0])
            link_chain(es)
            link(es[-1], UPDATE_SOURCE)
            link(UPDATE_SOURCE, en[0])
            link(UPDATE_SOURCE, pt[0])
            link_chain(en)
            link_chain(pt)
            link(en[-1], CREATE_PR)
            link(pt[-1], CREATE_PR)
            handoff = None
            wave_count = 2
        else:
            # 3 waves: Prepare → ES* → Update → EN* → handoff → PT* / [vendor] → Create PR
            summaries.extend(es)
            summaries.append(UPDATE_SOURCE)
            summaries.extend(en)
            summaries.append(HANDOFF)
            summaries.extend(pt)
            summaries.extend(vendor_subs)
            summaries.append(CREATE_PR)

            link(PREPARE, es[0])
            link_chain(es)
            link(es[-1], UPDATE_SOURCE)
            link(UPDATE_SOURCE, en[0])
            link_chain(en)
            link(es[-1], HANDOFF)
            link(en[-1], HANDOFF)
            link(HANDOFF, pt[0])
            link_chain(pt)
            link(pt[-1], CREATE_PR)
            link(en[-1], CREATE_PR)
            for vendor in vendor_subs:
                link(HANDOFF, vendor)
                link(vendor, CREATE_PR)
            handoff = HANDOFF
            wave_count = 3
        primary = es[0]

    languages_by_summary = _in_house_languages_by_summary()
    if len(vendors) == 1:
        languages_by_summary[vendor_subs[0]] = [vendors[0]]
    elif len(vendors) >= 2:
        languages_by_summary[OTHER_LANGUAGES] = list(vendors)

    parent_languages = sorted(IN_HOUSE | set(vendors))

    return TicketPlan(
        source=source,
        summaries=summaries,
        block_pairs=block_pairs,
        parent_languages=parent_languages,
        languages_by_summary=languages_by_summary,
        primary_review_summary=primary,
        handoff_summary=handoff,
        vendor_codes=vendors,
        wave_count=wave_count,
    )
