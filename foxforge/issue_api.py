"""Bounded GitHub issue operations with targeted, verified label changes."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from urllib.parse import quote, urlencode
import re

from .github_app import GitHubApp, GitHubAppError
from .issue_tasks import IssueError, IssueTask, ISSUE_LABELS, READY, RUNNING, timestamp
from .security import redact
from .state import RunState
from .actor_authorization import ActorPolicy


class IssueAPI:
    def __init__(self, app: GitHubApp):
        if not app.issues:
            raise IssueError("Issue access requires an explicit Issues App client")
        self.app = app
        self.repository = app.repository
        self.prefix = f"/repos/{self.repository}"
        self._bot = None

    def pages(self, endpoint: str, **filters) -> list:
        result = []
        for page in range(1, 101):
            data = self.app.api("GET", endpoint + "?" + urlencode({**filters, "per_page": 100, "page": page}))
            if not isinstance(data, list) or len(data) > 100:
                raise IssueError("Invalid paginated GitHub response; intervention required")
            result.extend(data)
            if len(data) < 100:
                return result
        raise IssueError("GitHub response exceeds intake scan limit; intervention required")

    def get(self, number: int) -> IssueTask:
        try:
            data = self.app.api("GET", f"{self.prefix}/issues/{number}")
        except GitHubAppError as exc:
            if exc.status == 404:
                raise IssueError("Issue is missing or inaccessible") from None
            raise
        return IssueTask.from_api(self.repository, number, data)

    def list_label(self, label: str) -> list[IssueTask]:
        rows = self.pages(f"{self.prefix}/issues", state="open", labels=label, sort="created", direction="asc")
        result = []
        for row in rows:
            if not isinstance(row, dict):
                raise IssueError("Invalid issue listing")
            if "pull_request" in row:
                continue
            task = IssueTask.from_api(self.repository, row.get("number"), row)
            if task.state == "open" and label in task.labels:
                result.append(task)
            else:
                raise IssueError("Issue listing changed during intake; retry the poll")
        return sorted(result, key=lambda task: (timestamp(task.created_at), task.number))

    def list_open(self) -> list[IssueTask]:
        rows = self.pages(f"{self.prefix}/issues", state="open", sort="created", direction="asc")
        result = []
        for row in rows:
            if not isinstance(row, dict):
                raise IssueError("Invalid issue listing")
            if "pull_request" in row:
                continue
            task = IssueTask.from_api(self.repository, row.get("number"), row)
            if task.state != "open":
                raise IssueError("Issue listing changed during discovery; retry the poll")
            result.append(task)
        return sorted(result, key=lambda task: (timestamp(task.created_at), task.number))

    def ready_approval(self, number: int, policy: ActorPolicy) -> tuple[int, str, int] | None:
        return self.approval_for_label(number, READY, policy)

    def approval_for_label(self, number: int, label_name: str, policy: ActorPolicy, *,
                           not_before: str | None = None, max_age_hours: int | None = None) -> tuple[int, str, int] | None:
        if not isinstance(label_name, str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9:._-]{0,99}", label_name):
            raise IssueError("Invalid approval label")
        relevant = []
        for event in self.pages(f"{self.prefix}/issues/{number}/events"):
            if not isinstance(event, dict):
                raise IssueError("Invalid issue approval history")
            label = event.get("label") or {}
            if not isinstance(label, dict):
                raise IssueError("Invalid issue approval label")
            if event.get("event") in {"labeled", "unlabeled"} and label.get("name") == label_name:
                if type(event.get("id")) is not int or event["id"] <= 0:
                    raise IssueError("Invalid issue approval identity")
                relevant.append(event)
        if not relevant:
            return None
        latest = max(relevant, key=lambda row: (timestamp(row.get("created_at")), row["id"]))
        approved_at = timestamp(latest.get("created_at"))
        if not_before is not None and approved_at < timestamp(not_before):
            return None
        if max_age_hours is not None:
            if type(max_age_hours) is not int or not 1 <= max_age_hours <= 24 * 30:
                raise IssueError("Invalid approval freshness limit")
            if approved_at < datetime.now(timezone.utc) - timedelta(hours=max_age_hours):
                return None
        actor = latest.get("actor")
        if latest["event"] != "labeled" or not isinstance(actor, dict) or actor.get("type") != "User" or type(actor.get("id")) is not int or actor["id"] <= 0:
            return None
        if not policy.allows(actor["id"]):
            return None
        login = actor.get("login")
        if not isinstance(login, str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9-]{0,38}", login):
            raise IssueError("Invalid approval actor")
        if login.casefold() == self.repository.split("/")[0].casefold():
            return latest["id"], login, actor["id"]
        try:
            permission = self.app.api("GET", f"{self.prefix}/collaborators/{quote(login, safe='')}/permission")
        except GitHubAppError as exc:
            if exc.status == 404:
                return None
            raise
        try:
            if permission["user"]["id"] != actor["id"] or permission["user"]["login"].casefold() != login.casefold():
                raise ValueError
            if permission["permission"] in {"write", "maintain", "admin"}:
                return latest["id"], login, actor["id"]
        except (KeyError, TypeError, ValueError, AttributeError):
            raise IssueError("Invalid approval permission metadata") from None
        return None

    def transition(self, number: int, target: str) -> IssueTask:
        if not self.app.publishing:
            raise IssueError("Issue mutation requires an explicit Issues-write App client")
        if target not in ISSUE_LABELS or target == READY:
            raise IssueError("Invalid automatic label transition")
        current = self.get(number)
        # Add destination first, so a partial claim still makes running visible.
        self.app.api("POST", f"{self.prefix}/issues/{number}/labels", {"labels": [target]})
        for label in sorted((set(current.labels) & ISSUE_LABELS) - {target}):
            self.app.api("DELETE", f"{self.prefix}/issues/{number}/labels/{quote(label, safe='')}")
        updated = self.get(number)
        if set(updated.labels) & ISSUE_LABELS != {target}:
            raise IssueError("Issue labels did not reach the expected state; intervention required")
        return updated

    def comment(self, state: RunState, body: str, kind: str) -> int:
        if not self.app.publishing:
            raise IssueError("Issue mutation requires an explicit Issues-write App client")
        if kind not in {"claim", "result"} or redact(body) != body:
            raise IssueError("Unsafe issue comment")
        marker = f"<!-- foxforge-issue:{self.repository.casefold()}:{state.github_issue_number}:{state.run_id}:{kind} -->"
        body += "\n\n" + marker
        if self._bot is None:
            self._bot = self.app.bot_identity()
        existing = self.pages(f"{self.prefix}/issues/{state.github_issue_number}/comments")
        matches = [row for row in existing if isinstance(row, dict) and isinstance(row.get("user"), dict)
                   and type(row["user"].get("id")) is int and row["user"]["id"] == self._bot.user_id
                   and row["user"].get("login") == self._bot.login and marker in str(row.get("body", ""))]
        if len(matches) > 1:
            raise IssueError("Ambiguous existing FoxForge comments")
        row = matches[0] if matches else self.app.api("POST", f"{self.prefix}/issues/{state.github_issue_number}/comments", {"body": body})
        try:
            number = row["id"]
            if type(number) is not int or number <= 0 or row["body"] != body or row["user"]["id"] != self._bot.user_id or row["user"]["login"] != self._bot.login:
                raise ValueError
            if row["html_url"].casefold() != f"https://github.com/{self.repository}/issues/{state.github_issue_number}#issuecomment-{number}".casefold():
                raise ValueError
        except (KeyError, TypeError, ValueError, AttributeError):
            raise IssueError("Issue comment ownership or returned facts did not match") from None
        return number

    def remote_conflicts(self, number: int) -> None:
        prefix = f"foxforge/{number}-"
        refs = self.app.api("GET", f"{self.prefix}/git/matching-refs/heads/{prefix}")
        if not isinstance(refs, list):
            raise IssueError("Invalid matching branch response")
        if refs:
            raise IssueError("Existing issue task branch on GitHub; intervention required")
        # No base filter: an existing issue PR to main must also block intake.
        for pr in self.pages(f"{self.prefix}/pulls", state="open"):
            try:
                if not isinstance(pr, dict):
                    raise ValueError
                body = pr.get("body") or ""
                branch = pr["head"]["ref"]
                if not isinstance(body, str) or not isinstance(branch, str):
                    raise ValueError
                linked = (re.escape(f"FoxForge-Issue: {self.repository}#{number}"), re.escape(f"https://github.com/{self.repository}/issues/{number}"))
                if branch.startswith(prefix) or any(re.search(value + r"(?![0-9])", body, re.IGNORECASE) for value in linked):
                    raise IssueError("Existing open PR associated with this issue; intervention required")
            except (KeyError, TypeError, ValueError):
                raise IssueError("Ambiguous pull request listing") from None
        # Timeline captures GitHub's own cross-references, including PRs whose
        # branch/body do not follow FoxForge conventions.
        for event in self.pages(f"{self.prefix}/issues/{number}/timeline"):
            if not isinstance(event, dict):
                raise IssueError("Invalid issue timeline")
            source = event.get("source") or {}
            if not isinstance(source, dict):
                raise IssueError("Invalid cross-reference metadata")
            source = source.get("issue") or {}
            if not isinstance(source, dict):
                raise IssueError("Invalid cross-reference metadata")
            if source.get("pull_request") and source.get("state") == "open":
                raise IssueError("Existing open PR cross-references this issue; intervention required")

    def require_running(self, snapshot: IssueTask) -> IssueTask:
        current = self.get(snapshot.number)
        ActorPolicy.from_env().require(current.author_id)
        if current.revision != snapshot.revision or current.author_id != snapshot.author_id:
            raise IssueError("ISSUE_CHANGED")
        if current.state != "open" or set(current.labels) & ISSUE_LABELS != {RUNNING}:
            raise IssueError("CLAIM_LOST")
        return current
