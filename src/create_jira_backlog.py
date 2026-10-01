"""Create the AOT Pulse epics and their stories in JIRA (project AUBM by default).

Sources: "AOTPulse Specs/AOT BidHub — Epics & User Stories.md" (15 epics and
their story tables) and every "AOTPulse Specs/<feature>/spec.md" (spec
context for each epic, plus the stories of the 002-012 enhancements).

    python src/create_jira_backlog.py --check     # verify credentials/project, list assignees
    python src/create_jira_backlog.py --dry-run   # write the request bodies, call nothing
    python src/create_jira_backlog.py             # create the issues (resumable)

JIRA URL, username and API token come from jira_config.toml (see
jira_config.example.toml) or the JIRA_URL / JIRA_USERNAME / JIRA_API_TOKEN
environment variables, which win over the file.
"""

import argparse
import json
import os
import sys
from collections.abc import Mapping
from pathlib import Path

from jira_backlog.application.publisher import DryRunCreator, PublishResult, publish
from jira_backlog.config import ConfigError, JiraConfig, load_config, load_issue_settings
from jira_backlog.domain.aot_pulse_links import AOT_PULSE_LINKS
from jira_backlog.domain.backlog import build_backlog
from jira_backlog.domain.models import BacklogEpic
from jira_backlog.jira.client import JiraClient, JiraError, open_client
from jira_backlog.jira.fields import IssueSettings
from jira_backlog.output.state_file import JsonStateStore
from jira_backlog.parsing.epics_markdown import parse_epics
from jira_backlog.parsing.spec_markdown import parse_spec

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_SPECS_DIR = PROJECT_ROOT / "AOTPulse Specs"
EPICS_FILE_NAME = "AOT BidHub — Epics & User Stories.md"
DEFAULT_CONFIG = PROJECT_ROOT / "jira_config.toml"
DEFAULT_STATE = PROJECT_ROOT / "output" / "jira_backlog_state.json"
DEFAULT_PREVIEW = PROJECT_ROOT / "output" / "jira_backlog_preview.json"


def main(argv=None, env: Mapping[str, str] = os.environ, transport=None) -> int:
    args = _parser().parse_args(argv)
    backlog = load_backlog(
        args.specs_dir, args.epics_file or args.specs_dir / EPICS_FILE_NAME, args.epic
    )
    if args.dry_run:
        return dry_run(backlog, load_issue_settings(_read(args.config), env), args.preview_file)
    try:
        config = load_config(_read(args.config), env)
        with open_client(config.url, config.username, config.api_token, transport) as client:
            if args.check:
                return check(client, config)
            return run(backlog, client, JsonStateStore(args.state_file), config.issues)
    except ConfigError as error:
        return _fail(f"{error} (set them in {args.config} or the JIRA_* environment variables)", 2)
    except JiraError as error:
        return _fail(str(error), 1)


def load_backlog(specs_dir: Path, epics_file: Path, only: list[int] | None) -> list[BacklogEpic]:
    epics = [e for e in parse_epics(epics_file.read_text()) if not only or e.number in only]
    specs = [
        parse_spec(path.parent.name, path.read_text())
        for path in sorted(specs_dir.glob("*/spec.md"))
    ]
    return build_backlog(epics, specs, AOT_PULSE_LINKS)


def dry_run(backlog: list[BacklogEpic], settings: IssueSettings, preview_file: Path) -> int:
    creator, state = DryRunCreator(), _MemoryState()
    results = publish(backlog, creator, state, settings)
    pairs = zip(results, creator.requests, strict=True)
    preview = [{"item_key": result.item_key, "fields": fields} for result, fields in pairs]
    preview_file.parent.mkdir(parents=True, exist_ok=True)
    preview_file.write_text(json.dumps(preview, indent=2, ensure_ascii=False) + "\n")
    counts = f"{len(backlog)} epics, {len(results) - len(backlog)} stories"
    print(f"dry run: {len(results)} issues ({counts}) -> {preview_file}")
    return 0


def check(client: JiraClient, config: JiraConfig) -> int:
    key = config.issues.project_key
    if key not in {project["key"] for project in client.projects()}:
        return _fail(f"project {key} not found among the projects {config.username} can see", 1)
    print(f"project {key} found at {config.url}; assignable users:")
    for user in client.assignable_users(key):
        print(f"  {user['accountId']}  {user.get('displayName', '')}")
    return 0


def run(backlog, client: JiraClient, state: JsonStateStore, settings: IssueSettings) -> int:
    results = publish(backlog, client, state, settings, report=_print_result)
    created = sum(result.created for result in results)
    print(f"{created} created, {len(results) - created} already existed")
    return 0


class _MemoryState(dict):
    def save(self) -> None:
        """A dry run remembers nothing between runs."""


def _print_result(result: PublishResult) -> None:
    verb = "created" if result.created else "exists "
    print(f"{verb} {result.jira_key}  {result.item_key}  {result.summary}")


def _read(path: Path) -> str | None:
    return path.read_text() if path.is_file() else None


def _fail(message: str, code: int) -> int:
    print(message, file=sys.stderr)
    return code


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--dry-run", action="store_true", help="write request bodies, call nothing")
    mode.add_argument("--check", action="store_true", help="verify access and list assignees")
    parser.add_argument(
        "--epic", type=int, action="append", help="only this epic number (repeatable)"
    )
    parser.add_argument("--specs-dir", type=Path, default=DEFAULT_SPECS_DIR)
    parser.add_argument("--epics-file", type=Path, help=f"default: <specs-dir>/{EPICS_FILE_NAME}")
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    parser.add_argument("--state-file", type=Path, default=DEFAULT_STATE)
    parser.add_argument("--preview-file", type=Path, default=DEFAULT_PREVIEW)
    return parser


if __name__ == "__main__":
    sys.exit(main())
