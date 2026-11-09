"""Create the direct v0 or relay trigger; never write resolved secrets to disk."""

import argparse
import json
import os
from pathlib import Path
import re
import subprocess

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=["direct", "relay"])
    parser.add_argument("--name", help="Unique trigger name; defaults to issue-to-pr-<mode>")
    parser.add_argument("--opencode", action="store_true")
    parser.add_argument("--dry-run", action="store_true",
                        help="Validate inputs and show prompt/spec paths; do not create a trigger")
    args = parser.parse_args()
    trigger_name = args.name if args.name is not None else f"issue-to-pr-{args.mode}"
    if not re.fullmatch(r"[A-Za-z0-9](?:[A-Za-z0-9._-]{0,62}[A-Za-z0-9])?", trigger_name):
        parser.error("Trigger name must be 1-64 letters/digits/./_/- and start and end with a letter or digit")
    required = ["GITHUB_REPOSITORY", "DEFAULT_BRANCH", "GITHUB_ACTOR",
                "HARNESS_INFERENCE_API_KEY", "SLACK_WEBHOOK_URL"]
    for name in required:
        if not os.environ.get(name):
            parser.error(f"Set {name} in your environment first")
    repo = os.environ["GITHUB_REPOSITORY"]
    if not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", repo):
        parser.error("GITHUB_REPOSITORY must be owner/repo")
    branch = os.environ["DEFAULT_BRANCH"]
    # Also keeps branch names safe inside YAML command patterns and prompts.
    if not re.fullmatch(r"[A-Za-z0-9_./-]+", branch) or subprocess.run(
        ["git", "check-ref-format", "--branch", branch], capture_output=True
    ).returncode:
        parser.error("DEFAULT_BRANCH must be a valid branch using letters, digits, _, ., / or -")
    actor = os.environ["GITHUB_ACTOR"]
    if not re.fullmatch(r"[A-Za-z0-9_.-]{1,64}", actor):
        parser.error("Invalid GITHUB_ACTOR")
    label = os.environ.get("AGENT_LABEL", "agent")
    if not label.strip():
        parser.error("AGENT_LABEL cannot be empty")
    prompt = (ROOT / "spec/prompt.txt").read_text()
    if args.mode == "direct":
        prompt = (ROOT / "spec/direct-guard.txt").read_text() + prompt
    for key, value in {"TARGET_REPOSITORY": repo, "DEFAULT_BRANCH": branch,
                       "AGENT_LABEL": json.dumps(label)}.items():
        prompt = prompt.replace(f"@{key}@", value)
    spec = ROOT / ("spec/issue-to-pr-opencode.yaml" if args.opencode
                   else "spec/issue-to-pr.yaml")
    context = os.environ.get("DOCTL_CONTEXT", "").strip()
    doctl = ["doctl"] + (["--context", context] if context else [])
    if args.dry_run:
        print(f"Name: {trigger_name}\nSpec: {spec}\nProvider: {'github' if args.mode == 'direct' else 'custom'}")
        print(f"DO context: {context or '(current doctl context)'}")
        print(prompt)
        return
    result = subprocess.run(doctl + [
        "harness-runtime", "triggers", "create",
        "--kind", "webhook", "--name", trigger_name,
        "--session-mode", "fresh", "--spec", str(spec),
        "--provider", "github" if args.mode == "direct" else "custom",
        "--prompt", prompt, "--output-mode", "slack",
        "--output-slack-webhook", os.environ["SLACK_WEBHOOK_URL"],
    ])
    # CalledProcessError would print argv, including the Slack webhook, on failure.
    raise SystemExit(result.returncode)


if __name__ == "__main__":
    main()
