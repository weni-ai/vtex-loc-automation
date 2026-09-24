#!/usr/bin/env python3
"""CLI for Crowdin-based localization lock checks."""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from localization_automation.crowdin_globs import (  # noqa: E402
    check_paths,
    derive_translation_globs,
    filter_source_files,
    infer_source_language,
)
from localization_automation.locale_bundle import (  # noqa: E402
    check_locale_bundles,
    is_locale_bundle_path,
)
from localization_automation.locale_codes import classify_source_language  # noqa: E402
from localization_automation.locale_inventory import discover_jira_languages  # noqa: E402
from localization_automation.ticket_graph import (  # noqa: E402
    SHORT_WORD_THRESHOLD,
    build_ticket_plan,
)

LOCALIZATION_README_URL = (
    "https://github.com/vtex/localization-tools/blob/main/"
    "localization-automation/README.md#1-locale-config-crowdinyml"
)


def _crowdin_path(repo_root: Path) -> Path:
    return repo_root / "crowdin.yml"


def _git_changed_paths(repo_root: Path, base_sha: str, head_sha: str) -> list[str]:
    result = subprocess.run(
        ["git", "diff", "--name-only", f"{base_sha}..{head_sha}"],
        cwd=repo_root,
        check=True,
        capture_output=True,
        text=True,
    )
    return [line for line in result.stdout.splitlines() if line]


def _git_tracked_paths(repo_root: Path) -> list[str]:
    result = subprocess.run(
        ["git", "ls-files"],
        cwd=repo_root,
        check=True,
        capture_output=True,
        text=True,
    )
    return [line for line in result.stdout.splitlines() if line]



def _git_show(repo_root: Path, sha: str, relative_path: str) -> str | None:
    result = subprocess.run(
        ["git", "show", f"{sha}:{relative_path}"],
        cwd=repo_root,
        check=False,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        return None
    return result.stdout


def _read_working_tree(repo_root: Path, relative_path: str) -> str | None:
    path = repo_root / relative_path
    if not path.is_file():
        return None
    return path.read_text(encoding="utf-8")


def _short_sha(sha: str | None) -> str | None:
    if not sha:
        return None
    return sha[:7] if len(sha) >= 7 else sha


def _safe_source_language(crowdin: Path) -> str | None:
    try:
        return infer_source_language(crowdin)
    except (OSError, ValueError):
        return None


def _format_pass_summary(
    *,
    repo_root: Path,
    crowdin: Path,
    paths: list[str],
    source_language: str | None,
    base_sha: str | None,
    head_sha: str | None,
) -> str:
    try:
        sources = set(filter_source_files(paths, crowdin))
    except (OSError, ValueError):
        sources = set()

    repository = os.environ.get("GITHUB_REPOSITORY") or repo_root.name
    event = os.environ.get("GITHUB_EVENT_NAME")

    lines = ["localization-lock: passed", ""]
    if event:
        lines.append(f"  event:           {event}")
    lines.append(f"  repository:      {repository}")
    short_base = _short_sha(base_sha)
    short_head = _short_sha(head_sha)
    if short_base:
        lines.append(f"  base_sha:        {short_base}")
    if short_head:
        lines.append(f"  head_sha:        {short_head}")
    if source_language:
        lines.append(f"  source_language: {source_language}")
    lines.append("")
    lines.append(f"  changed_files ({len(paths)}):")
    if paths:
        for path in paths:
            if path in sources:
                if is_locale_bundle_path(path, crowdin):
                    note = "allowed (source block only)"
                else:
                    note = "allowed (source)"
            else:
                note = "not a crowdin source (ignored by lock)"
            lines.append(f"    - {path}  {note}")
    else:
        lines.append("    (none)")
    lines.append("")
    lines.append("  blocked_files: 0")
    lines.append("")
    return "\n".join(lines)


def _format_fail_pr_comment(
    blocked: list[dict],
    source_language: str | None,
) -> str:
    path_blocks = [entry for entry in blocked if entry.get("reason") != "locale_bundle"]
    bundle_blocks = [entry for entry in blocked if entry.get("reason") == "locale_bundle"]

    lines = [
        f"> ### [:no_entry: Localization lock failed]({LOCALIZATION_README_URL})",
        ">",
    ]

    if path_blocks and bundle_blocks:
        lines.append(
            "> This PR changes translation content that must not be committed directly."
        )
    elif path_blocks:
        lines.append(
            "> This PR changes files managed by the Localization team via Crowdin. "
            "Direct commits to translation locales are blocked in CI."
        )
    else:
        lines.append(
            "> This PR changes non-source locale blocks in a locale bundle. "
            "Only the source-language object may change."
        )

    lines.extend([">", "> **Blocked files**"])
    for entry in path_blocks:
        lines.append(
            f"> - `{entry['path']}` — translation glob (`{entry['matchedGlob']}`)"
        )
    for entry in bundle_blocks:
        keys = ", ".join(entry.get("touched_keys") or [])
        src = entry.get("source_language") or source_language or "unknown"
        lines.append(
            f"> - `{entry['path']}` — source language `{src}`; touched keys: `{keys}`"
        )

    lines.extend([">", "> **What to do**"])
    if path_blocks:
        src = source_language or "the source locale"
        lines.append(f"> - Edit only the **source** locale (inferred: `{src}`)")
        lines.append(
            "> - Remove translation-file changes from this PR; the Localization team "
            "own these and will update them as needed"
        )
    if bundle_blocks:
        src = bundle_blocks[0].get("source_language") or source_language or "the source locale"
        if path_blocks:
            lines.append(">")
        lines.append(f"> - Edit only the `{src}` block in locale-bundle files")
        lines.append(
            "> - Other locale blocks are owned by the Localization team; "
            "they will update them as needed"
        )

    return "\n".join(lines)


def _cmd_lock(args: argparse.Namespace) -> int:
    repo_root = Path(args.repo_root).resolve()
    crowdin = _crowdin_path(repo_root)

    if not crowdin.is_file():
        if args.require_crowdin:
            sys.stdout.write(
                f"localization-lock: crowdin.yml not found at {crowdin}\n"
            )
            return 1
        return 0

    if args.files is not None:
        paths = list(args.files)
    else:
        if not args.base_sha or not args.head_sha:
            sys.stderr.write(
                "lock: provide --files or both --base-sha and --head-sha\n"
            )
            return 2
        paths = _git_changed_paths(repo_root, args.base_sha, args.head_sha)

    base_sha = args.base_sha
    head_sha = args.head_sha
    if args.files is not None and not (base_sha and head_sha):
        # Pre-commit / explicit files: compare working tree vs HEAD.
        base_sha = base_sha or "HEAD"
        head_sha = None  # working tree

    try:
        blocked = check_paths(paths, crowdin)

        def read_base(relative_path: str) -> str | None:
            return _git_show(repo_root, base_sha or "HEAD", relative_path)

        def read_head(relative_path: str) -> str | None:
            if head_sha:
                return _git_show(repo_root, head_sha, relative_path)
            return _read_working_tree(repo_root, relative_path)

        blocked.extend(
            check_locale_bundles(
                paths,
                crowdin,
                read_base=read_base,
                read_head=read_head,
            )
        )
    except (OSError, ValueError) as err:
        sys.stdout.write(f"localization-lock: unexpected error — {err}\n")
        return 1

    source_language = _safe_source_language(crowdin)

    if not blocked:
        sys.stdout.write(
            _format_pass_summary(
                repo_root=repo_root,
                crowdin=crowdin,
                paths=paths,
                source_language=source_language,
                base_sha=base_sha,
                head_sha=head_sha,
            )
        )
        return 0

    if args.comment_file:
        comment_path = Path(args.comment_file)
        comment_path.write_text(
            _format_fail_pr_comment(blocked, source_language),
            encoding="utf-8",
        )

    msg = "localization-lock: check failed.\n\n"
    path_blocks = [e for e in blocked if e.get("reason") != "locale_bundle"]
    bundle_blocks = [e for e in blocked if e.get("reason") == "locale_bundle"]

    if path_blocks:
        msg += (
            "The following files are translation files managed by the Localization team:\n\n"
        )
        for entry in path_blocks:
            msg += f"  {entry['path']}  (matched: {entry['matchedGlob']})\n"
        msg += (
            "\nTranslation files are managed via Crowdin. Do not commit them directly.\n"
        )

    if bundle_blocks:
        if path_blocks:
            msg += "\n"
        msg += (
            "The following locale-bundle files changed non-source locale blocks "
            "(only the inferred source-language object may change):\n\n"
        )
        for entry in bundle_blocks:
            keys = ", ".join(entry.get("touched_keys") or [])
            msg += (
                f"  {entry['path']}  (source_language={entry.get('source_language')}; "
                f"touched: {keys})\n"
            )
        msg += (
            "\nEdit only the source-language object (e.g. pt-BR). "
            "Other locale blocks are managed via Crowdin.\n"
        )

    msg += f"\nSee: {LOCALIZATION_README_URL}\n"
    sys.stdout.write(msg)
    return 1


def _cmd_list_sources(args: argparse.Namespace) -> int:
    repo_root = Path(args.repo_root).resolve()
    crowdin = _crowdin_path(repo_root)
    if not crowdin.is_file():
        # Early-gate policy: missing crowdin.yml → exit 0 (no sources).
        return 0

    if args.files is not None:
        paths = list(args.files)
    elif args.base_sha and args.head_sha:
        paths = _git_changed_paths(repo_root, args.base_sha, args.head_sha)
    else:
        paths = _git_tracked_paths(repo_root)

    try:
        sources = filter_source_files(paths, crowdin)
    except (OSError, ValueError) as err:
        sys.stderr.write(f"list-sources: {err}\n")
        return 1

    for path in sources:
        print(path)
    return 0


def _cmd_show_globs(args: argparse.Namespace) -> int:
    repo_root = Path(args.repo_root).resolve()
    crowdin = _crowdin_path(repo_root)
    if not crowdin.is_file():
        sys.stderr.write(f"show-globs: crowdin.yml not found at {crowdin}\n")
        return 1

    try:
        pairs = derive_translation_globs(crowdin)
    except (OSError, ValueError) as err:
        sys.stderr.write(f"show-globs: {err}\n")
        return 1

    for pair in pairs:
        print(f"source:      {pair.source_glob}")
        print(f"translation: {pair.translation_glob}")
        print()
    return 0


def _cmd_show_source_language(args: argparse.Namespace) -> int:
    repo_root = Path(args.repo_root).resolve()
    crowdin = _crowdin_path(repo_root)

    if not crowdin.is_file():
        return 0

    try:
        value = infer_source_language(crowdin)
        classify_source_language(value)
    except (OSError, ValueError) as err:
        sys.stderr.write(f"show-source-language: {err}\n")
        return 1

    print(value)
    return 0


def _cmd_inventory_locales(args: argparse.Namespace) -> int:
    repo_root = Path(args.repo_root).resolve()
    crowdin = _crowdin_path(repo_root)
    if not crowdin.is_file():
        sys.stderr.write("inventory-locales: crowdin.yml missing\n")
        return 1
    try:
        payload = discover_jira_languages(repo_root)
        if not payload.get("source_language"):
            raise ValueError(
                "Cannot infer source language from crowdin.yml files[].source paths"
            )
        classify_source_language(str(payload["source_language"]))
    except (OSError, ValueError) as err:
        sys.stderr.write(f"inventory-locales: {err}\n")
        return 1
    print(json.dumps(payload, indent=2 if args.pretty else None))
    return 0


def _cmd_ticket_plan(args: argparse.Namespace) -> int:
    repo_root = Path(args.repo_root).resolve()
    crowdin = _crowdin_path(repo_root)
    if not crowdin.is_file():
        sys.stderr.write("ticket-plan: crowdin.yml missing\n")
        return 1
    try:
        inventory = discover_jira_languages(repo_root)
        source = inventory.get("source_language")
        if not source:
            raise ValueError(
                "Cannot infer source language from crowdin.yml files[].source paths"
            )
        plan = build_ticket_plan(
            str(source),
            vendor_codes=list(inventory.get("vendors") or []),
            word_count=args.word_count,
        )
    except (OSError, ValueError) as err:
        sys.stderr.write(f"ticket-plan: {err}\n")
        return 1
    print(json.dumps(plan.to_dict(), indent=2 if args.pretty else None))
    return 0


def _add_repo_root(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--repo-root",
        default=".",
        help="Repository root (default: current directory)",
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="lock_cli.py")
    subparsers = parser.add_subparsers(dest="command", required=True)

    lock_parser = subparsers.add_parser("lock", help="Block translation file changes")
    _add_repo_root(lock_parser)
    lock_parser.add_argument(
        "--files",
        nargs="*",
        default=None,
        help="Explicit paths to check (default: use git diff)",
    )
    lock_parser.add_argument("--base-sha", help="Git base ref for changed files")
    lock_parser.add_argument("--head-sha", help="Git head ref for changed files")
    lock_parser.add_argument(
        "--require-crowdin",
        action="store_true",
        help="Fail if crowdin.yml is missing (default: skip check)",
    )
    lock_parser.add_argument(
        "--comment-file",
        help="When the lock fails, write a PR comment body to this path",
    )

    list_parser = subparsers.add_parser(
        "list-sources",
        help="Filter paths to crowdin.yml source globs (files, git range, or all tracked)",
    )
    _add_repo_root(list_parser)
    list_parser.add_argument(
        "--files",
        nargs="*",
        default=None,
        help="Explicit paths to filter",
    )
    list_parser.add_argument("--base-sha", help="Git base ref for changed files")
    list_parser.add_argument("--head-sha", help="Git head ref for changed files")

    globs_parser = subparsers.add_parser(
        "show-globs", help="Print derived source/translation globs from crowdin.yml"
    )
    _add_repo_root(globs_parser)

    lang_parser = subparsers.add_parser(
        "show-source-language",
        help="Infer source language from crowdin.yml files[].source paths",
    )
    _add_repo_root(lang_parser)

    inventory_parser = subparsers.add_parser(
        "inventory-locales",
        help="List in-house + vendor Jira language codes found in the repo",
    )
    _add_repo_root(inventory_parser)
    inventory_parser.add_argument(
        "--pretty",
        action="store_true",
        help="Pretty-print JSON",
    )

    plan_parser = subparsers.add_parser(
        "ticket-plan",
        help="Build LOC subtask summaries + Blocks pairs for crowdin.yml source",
    )
    _add_repo_root(plan_parser)
    plan_parser.add_argument(
        "--word-count",
        type=int,
        default=None,
        help=(
            "Crowdin parent word count; when set and below "
            f"SHORT_WORD_THRESHOLD ({SHORT_WORD_THRESHOLD}; 0 = short plan off), "
            "emit the short single-week language-name subtask plan"
        ),
    )
    plan_parser.add_argument(
        "--pretty",
        action="store_true",
        help="Pretty-print JSON",
    )

    args = parser.parse_args(argv)

    if args.command == "lock":
        return _cmd_lock(args)
    if args.command == "list-sources":
        return _cmd_list_sources(args)
    if args.command == "show-globs":
        return _cmd_show_globs(args)
    if args.command == "show-source-language":
        return _cmd_show_source_language(args)
    if args.command == "inventory-locales":
        return _cmd_inventory_locales(args)
    if args.command == "ticket-plan":
        return _cmd_ticket_plan(args)

    parser.print_help()
    return 2


if __name__ == "__main__":
    sys.exit(main())
