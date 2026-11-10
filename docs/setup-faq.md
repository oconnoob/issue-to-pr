# Setup questions

## What is already working, and what is still a deployment exercise?

The direct GitHub-to-OpenCode path has been tested live through PR creation,
with all four demo regression tests passing independently on the pushed commit.
Slack output is configured, but receipt must be checked in the selected channel.

The relay supports SQLite locally and PostgreSQL on App Platform. Tests cover
both databases. To verify the hosted path, deploy the relay on App Platform and
run the example with your own webhook and custom trigger. The trigger setup
scripts alone do not deploy the relay.

## What do the setup scripts actually do?

| Action | Result |
| --- | --- |
| Load `.env` with `set -a; source .env; set +a` | Exports settings to commands in that shell |
| `scripts/create-connection.sh` | Starts GitHub OAuth authorization in the selected DO context |
| `scripts/create-trigger.sh direct --opencode --dry-run` | Checks inputs and prints the assembled prompt; creates nothing |
| `doctl harness-runtime create --spec … --dry-run` | Parses/resolves the environment spec without starting a session |
| `scripts/create-trigger.sh direct --opencode` | Creates a fresh-session GitHub trigger with Slack output |
| `scripts/create-trigger.sh relay --opencode` | Creates a separate custom-provider trigger for the relay |
| `doctl apps propose --spec deploy/app.yaml` | Validates an App Platform proposal without creating resources |
| Create a new app from the reviewed spec in App Platform | Deploys the relay and provisions its demo database; incurs charges |

Run the shell scripts with `bash`. They consume exported settings, not `.env`
automatically. Creating a DO trigger does not create a GitHub webhook, deploy the
relay, start a local server or establish a tunnel.

## Do I need a relay or a tunnel to test?

For the direct proof, no: GitHub calls DO's public trigger URL. Your laptop can
be offline after configuration. A fresh hosted agent session does the work.

For the relay path, GitHub must reach `POST /webhooks/github` on your relay over
public HTTPS. The README deploys it on App Platform with PostgreSQL and the
generated HTTPS address. No custom domain is required. For temporary local
testing, run the relay locally and expose its port 8000 through an HTTPS tunnel
such as ngrok; use `https://YOUR_TUNNEL_HOST/webhooks/github` as the GitHub payload
URL. Use the GitHub-to-relay secret there. The tunnel does not replace signature
verification or the separate custom DO trigger. A local health check alone does
not make the service reachable from GitHub.

## Can I apply the label in GitHub's UI?

For a fresh repository, before/after curl requests and independent PR tests, use
the [demo walkthrough](demo.md). It avoids deleting the original issue or PR.

Yes. Under the repository's **Issues → Labels**, create `agent` if needed. Open
the issue, click **Labels** in the right sidebar and select `agent`. This emits
the `issues` / `labeled` event. Configure the webhook first; an already-present
label is not a new event. Remove and reapply it if necessary.

Re-labeling an issue that already has an agent PR should find that PR. For another
fix, choose a small reproducible bug and a new issue. See
[duplicate handling](../README.md#duplicate-handling-when-issues-or-prs-change)
before retrying a task.

## Why is GitHub authorization needed if gh works locally?

Your local GitHub login is not the remote sandbox's credential. The DO OAuth
connection supplies the sandbox's `GITHUB_TOKEN`, which git and GitHub REST use
to read the private repo, push a feature branch and open the PR. The agent acts
through the GitHub account that approved the connection.

That connection is distinct from the DO API credential used by `doctl`, the
inference model access key, the Slack incoming webhook, and the relay's optional
labeler-lookup PAT. See the [credential guide](environment.md).

## What if the authorization link expires?

Generate links when you are ready to approve them; do not reuse links from old
messages. First check the connection in the intended context:

```bash
doctl --context "$DOCTL_CONTEXT" harness-runtime connections list \
  --actor "$GITHUB_ACTOR"
```

If it is active, no fresh authorization is required. If creating a connection for
an expired actor returns a conflict, replace only that expired connection, then
start the flow again:

```bash
doctl --context "$DOCTL_CONTEXT" harness-runtime connections revoke CONNECTION_ID
doctl --context "$DOCTL_CONTEXT" harness-runtime connections create \
  --actor "$GITHUB_ACTOR" --scopes repo,read:user --no-browser --no-wait
```

Open the newly printed URL promptly and check the connection becomes `active`.
Never put authorization URLs or verification codes in reusable documentation.
Revocation can be blocked by dependent Environment Configs; inspect the named
configs before removing anything. Do not delete unrelated configs to refresh a
link. For compromised credentials, removing the DO connection alone does not
revoke the GitHub OAuth grant. Follow
[DO's revocation guidance](https://docs.digitalocean.com/products/managed-agents/agent-harness-runtime/how-to/connect-github/)
and revoke the credential at GitHub too.

## Can I create the environment by importing YAML in the web UI?

Yes. Select the same team as your CLI context, open Harness Runtime's environment
creation flow, and use YAML import. The minimal
[`ui-opencode-auth-test.yaml`](../spec/ui-opencode-auth-test.yaml) tests model
access only. A session prompt of `Reply with exactly OK. Do not use tools or change
files.` should return `OK` when that path is working.

The browser does not read your shell's `.env`; replace `${…}` placeholders with
the intended values in the import/secret fields. A resolved YAML containing a key
must stay private. The working copy's `spec/*.local.yaml` pattern is gitignored
and Docker-excluded; do not commit or screenshot such a file. Any resolved local
auth-test import is a private artifact, not a reusable published example.

Importing a config or creating a session does not create or update the GitHub
trigger. The minimal auth-test spec also has no GitHub OAuth slot, repository,
task prompt or Slack output. After the test, use the full workflow spec and trigger
setup. A trigger captures its spec and secrets; updating a separate UI config or
editing local files does not update that trigger.

## Is 401 invalid trusted identity a doctl login problem?

That message comes from the model provider inside the agent run. Check the CLI
authentication context against the Control Panel team and verify the model key's
scope. A successful direct inference API call alone does not verify the managed
agent request path. Follow the [authentication troubleshooting guide](authentication.md)
to isolate model access from GitHub access. Changing adapters does not correct an
account/team or credential mismatch.

## What can the Slack app respond to?

It posts final summaries to the chosen incoming-webhook channel. It does not read
Slack messages or handle mentions or replies. The manifest needs only
`incoming-webhook` for this behavior; see the [Slack guide](../slack/README.md).

## What if the execution says succeeded but no PR appears?

That status means the agent turn completed. Read the final response: it may have
skipped an event or stopped because tests, authentication or a task requirement
failed. Inspect the actual PR, changed files, linked issue and test output. Fresh
trigger sessions are torn down, so use `triggers get-execution` after completion
and session logs while the session is still active.
