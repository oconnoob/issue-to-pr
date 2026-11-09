import os
import json
from pathlib import Path
import subprocess
import sys

import pytest


def test_trigger_command_failure_does_not_dump_slack_webhook(tmp_path):
    executable = tmp_path / "doctl"
    executable.write_text("#!/bin/sh\nexit 9\n")
    executable.chmod(0o700)
    env = os.environ | {
        "PATH": str(tmp_path) + os.pathsep + os.environ["PATH"],
        "GITHUB_REPOSITORY": "demo/project", "DEFAULT_BRANCH": "main",
        "GITHUB_ACTOR": "demo", "HARNESS_INFERENCE_API_KEY": "private-model-key",
        "SLACK_WEBHOOK_URL": "https://hooks.slack.com/services/private-webhook",
    }
    root = Path(__file__).resolve().parents[2]
    result = subprocess.run([sys.executable, str(root / "scripts/create_trigger.py"), "relay"],
                            env=env, capture_output=True, text=True)
    assert result.returncode == 9
    assert "private-webhook" not in result.stdout + result.stderr
    assert "private-model-key" not in result.stdout + result.stderr
    assert "CalledProcessError" not in result.stderr


@pytest.mark.parametrize("command", [
    ["scripts/create_trigger.py", "direct", "--opencode"],
    ["scripts/create_trigger.py", "direct", "--opencode", "--name", "shipping-api-demo-02"],
    ["scripts/create-connection.sh"],
    ["scripts/probe-sandbox.sh", "demo-session"],
])
def test_setup_commands_use_selected_do_context(tmp_path, command):
    executable = tmp_path / "doctl"
    call_log = tmp_path / "doctl-call.json"
    executable.write_text(f"#!{sys.executable}\n"
                          "import json, os, pathlib, sys\n"
                          "pathlib.Path(os.environ['DOCTL_CALL_LOG']).write_text(json.dumps(sys.argv[1:]))\n")
    executable.chmod(0o700)
    env = os.environ | {
        "PATH": str(tmp_path) + os.pathsep + os.environ["PATH"],
        "DOCTL_CONTEXT": "correct-team", "DOCTL_CALL_LOG": str(call_log),
        "GITHUB_REPOSITORY": "demo/project", "DEFAULT_BRANCH": "main",
        "GITHUB_ACTOR": "demo", "HARNESS_INFERENCE_API_KEY": "test-key",
        "SLACK_WEBHOOK_URL": "https://hooks.slack.com/services/test-webhook",
    }
    root = Path(__file__).resolve().parents[2]
    interpreter = sys.executable if command[0].endswith(".py") else "bash"
    result = subprocess.run([interpreter] + command, cwd=root, env=env,
                            capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    arguments = json.loads(call_log.read_text())
    assert arguments[:3] == ["--context", "correct-team", "harness-runtime"]
    if command[0] == "scripts/create_trigger.py":
        expected_name = command[command.index("--name") + 1] if "--name" in command else "issue-to-pr-direct"
        assert arguments[arguments.index("--name") + 1] == expected_name


@pytest.mark.parametrize("name", ["", "-demo", "demo-", "x" * 65, "demo 01"])
def test_invalid_trigger_name_is_rejected_before_creation(name):
    root = Path(__file__).resolve().parents[2]
    result = subprocess.run(
        [sys.executable, str(root / "scripts/create_trigger.py"), "direct", f"--name={name}"],
        capture_output=True, text=True,
    )
    assert result.returncode == 2
    assert "Trigger name must be" in result.stderr


@pytest.mark.parametrize("spec", ["issue-to-pr.yaml", "issue-to-pr-opencode.yaml"])
def test_git_helper_authenticates_without_storing_token(tmp_path, spec):
    root = Path(__file__).resolve().parents[2]
    source = (root / "spec" / spec).read_text()
    helper = source.split("  GIT_CONFIG_VALUE_0: >-\n", 1)[1].splitlines()[0].strip()
    env = os.environ | {
        "HOME": str(tmp_path), "GIT_CONFIG_GLOBAL": os.devnull,
        "GIT_CONFIG_NOSYSTEM": "1", "GIT_TERMINAL_PROMPT": "0",
        "GITHUB_TOKEN": "fake-token-for-credential-test",
        "GIT_CONFIG_COUNT": "1",
        "GIT_CONFIG_KEY_0": "credential.https://github.com/demo/project.git.helper",
        "GIT_CONFIG_VALUE_0": helper,
    }
    result = subprocess.run(["git", "credential", "fill"],
                            input="url=https://github.com/demo/project.git\n\n",
                            env=env, capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    fields = dict(line.split("=", 1) for line in result.stdout.splitlines())
    assert fields["username"] == "x-access-token"
    assert fields["password"] == env["GITHUB_TOKEN"]
    assert env["GITHUB_TOKEN"] not in result.stderr
    assert not (tmp_path / ".git-credentials").exists()
    unrelated = subprocess.run(["git", "credential", "fill"],
                               input="url=https://github.com/other/repository.git\n\n",
                               env=env, capture_output=True, text=True)
    assert unrelated.returncode != 0
    assert env["GITHUB_TOKEN"] not in unrelated.stdout + unrelated.stderr
