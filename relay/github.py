"""GitHub-specific verification, filtering, authorization and normalization."""

import hashlib
import hmac
import json
import re
from uuid import UUID

from fastapi import HTTPException
import httpx

TRUSTED = {"OWNER", "MEMBER", "COLLABORATOR"}


class Skip(Exception):
    pass


class GitHub:
    def __init__(self, settings, client):
        self.settings = settings
        self.client = client

    def verify(self, body, headers):
        expected = "sha256=" + hmac.new(
            self.settings.github_secret.encode(), body, hashlib.sha256
        ).hexdigest()
        received = headers.get("x-hub-signature-256", "")
        if not hmac.compare_digest(expected.encode(), received.encode()):
            raise HTTPException(401, "Invalid GitHub signature")

    def delivery_id(self, headers):
        try:
            return str(UUID(headers.get("x-github-delivery", "")))
        except ValueError:
            raise HTTPException(400, "X-GitHub-Delivery must be a UUID") from None

    def prepare(self, body, headers):
        if headers.get("x-github-event") != "issues":
            raise Skip("not_issues")
        try:
            event = json.loads(body)
            if event["action"] != "labeled":
                raise Skip("not_labeled")
            if event.get("label", {}).get("name") != self.settings.label:
                raise Skip("different_label")
            repo, issue = event["repository"], event["issue"]
            if repo["full_name"].lower() != self.settings.repository.lower():
                raise Skip("different_repository")
            if "pull_request" in issue:
                raise Skip("pull_request")
            if issue.get("state") != "open":
                raise Skip("issue_not_open")
            number = issue["number"]
            if type(number) is not int or number <= 0:
                raise ValueError("Invalid issue number")
            title, text = issue["title"], issue.get("body") or ""
            branch, sender = repo["default_branch"], event["sender"]["login"]
            if not all(isinstance(x, str) for x in [title, text, branch, sender]):
                raise ValueError("Invalid text fields")
            if not title.strip() or not branch or not re.fullmatch(r"[A-Za-z0-9-]{1,39}", sender):
                raise ValueError("Invalid title, branch or sender")
            # Canonical URLs prevent payload URLs from becoming arbitrary destinations.
            full_name = self.settings.repository
            clone = f"https://github.com/{full_name}.git"
            issue_url = f"https://github.com/{full_name}/issues/{number}"
            if repo["clone_url"].lower() != clone.lower() or issue["html_url"].lower() != issue_url.lower():
                raise ValueError("Unexpected GitHub URLs")
            payload = {
                "repository": {"full_name": full_name, "clone_url": clone,
                               "default_branch": branch},
                "issue": {"number": number, "title": title, "body": text,
                          "html_url": issue_url},
            }
            return {"payload": payload, "sender": sender,
                    "author_trusted": issue.get("author_association") in TRUSTED}
        except (KeyError, TypeError, ValueError, AttributeError, RecursionError):
            raise HTTPException(400, "Malformed GitHub issue event") from None

    async def authorized(self, candidate):
        if candidate["author_trusted"]:
            return True
        owner = self.settings.repository.split("/")[0]
        if candidate["sender"].lower() == owner.lower():
            return True
        # sender has no author_association. Never infer membership from its login.
        response = await self.client.get(
            f"https://api.github.com/repos/{self.settings.repository}/collaborators/{candidate['sender']}",
            headers={"Authorization": f"Bearer {self.settings.github_token}",
                     "Accept": "application/vnd.github+json"},
        )
        if response.status_code == 204:
            return True
        if response.status_code == 404:
            return False
        response.raise_for_status()
        # Fail closed even on an unexpected successful response.
        raise httpx.HTTPError("Unexpected collaborator response")
