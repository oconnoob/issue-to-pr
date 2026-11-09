# Troubleshoot managed-agent authentication

The workflow uses separate credentials for DigitalOcean resource management,
model inference, GitHub access and Slack delivery. Identify the failing stage
before replacing a credential; see the [environment guide](environment.md).

## Model provider: `401 invalid trusted identity`

This error comes from the model provider inside the agent run. Check that the
CLI authentication context and the Control Panel use the intended account/team,
and that the model access key covers the selected model.

```bash
doctl auth list
doctl --context "$DOCTL_CONTEXT" harness-runtime connections list \
  --actor "$GITHUB_ACTOR"
```

A UI session returning 404 through the CLI can indicate a context mismatch.
Also check funding and feature availability. A successful direct inference API
call alone does not verify the managed-agent request path. Switching agent
adapters does not fix an account/team or credential mismatch.

To isolate inference, use the [minimal UI auth-test spec](../spec/ui-opencode-auth-test.yaml)
with your model key supplied privately, and ask:

```text
Reply with exactly OK. Do not use tools or change files.
```

The browser does not read your shell environment. Supply values in its secret
fields or a resolved, gitignored `spec/*.local.yaml` file. Keep that file private.
This test has no GitHub workflow or Slack output, and creating a separate
environment does not update an existing trigger.

## GitHub: clone, push or PR creation fails

Confirm that the GitHub connection is active in the selected DO context and was
authorized by an account with write access to the target repository. Local `gh`
authentication does not supply the remote sandbox's `GITHUB_TOKEN`. For expired
authorization links, follow the [setup FAQ](setup-faq.md#what-if-the-authorization-link-expires).

Both workflow specs configure a repository-scoped git credential helper. Check
the resolved repository URL and helper configuration without printing the token.
During an active session, inspect tool availability with:

```bash
bash scripts/probe-sandbox.sh SESSION_ID
```

Check the specific failed host against spec egress rules. A download fallback
may use a different host from `github.com`; failure of that fallback does not
establish that git access is blocked. After correcting a spec or credential,
update or recreate the trigger: edits to local files do not change its captured
configuration.

## Protect credentials during diagnosis

Check credential presence with a boolean. Do not print environment variables,
enable shell tracing around secrets, put tokens in clone URLs or share raw logs.
Command deny patterns are guardrails, not a complete disclosure boundary.

If a GitHub credential is exposed, revoke it at GitHub and replace the connection
before retrying. Removing a DO connection alone does not revoke the GitHub OAuth
grant; follow [DO's revocation guidance](https://docs.digitalocean.com/products/managed-agents/agent-harness-runtime/how-to/connect-github/).
Exclude credentials from support reports.

Fresh-trigger sandboxes are torn down after completion. Inspect retained results
using your own IDs:

```bash
doctl --context "$DOCTL_CONTEXT" harness-runtime triggers get-execution \
  TRIGGER_ID EXECUTION_ID
```
