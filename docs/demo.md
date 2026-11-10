# Run the issue-to-PR demo

Use your own private copy of the [shipping API template](https://github.com/oconnoob/issue-to-pr-demo).
The API runs locally so you can check its behavior; the coding agent clones your
committed GitHub source and runs on DigitalOcean. This direct-trigger demo needs
no relay deployment, Droplet, or tunnel.

## 1. Copy the demo and configure access

You need Python 3.12+, authenticated `gh` and `doctl` CLIs, Harness Runtime
access, and a Slack channel for summaries. From the directory containing your
setup checkout, create a fresh target (replace `YOUR_OWNER`):

```bash
gh repo create YOUR_OWNER/shipping-api-demo-01 \
  --template oconnoob/issue-to-pr-demo --private --clone
cd issue-to-pr
export TUTORIAL_ROOT="$PWD"
export DEMO_DIR="$(dirname "$TUTORIAL_ROOT")/shipping-api-demo-01"
if [ ! -f .env ]; then cp .env.example .env; fi
chmod 600 .env
```

Alternatively, use **Use this template** in GitHub, copy only its default branch,
and clone your result. Set `DEMO_DIR` to that checkout. The source template
contains the bug, tests, and agent instructions.

Follow the [environment guide](environment.md) and [Slack installation](../slack/README.md).
Set `.env` to your new repository, actual default branch, GitHub actor, DO
context, model key, and Slack webhook. Then load it and authorize GitHub:

```bash
set -a
source .env
set +a
bash scripts/create-connection.sh
```

Complete the browser authorization before continuing. Reload `.env` after edits;
the scripts consume exported values.

## 2. Prepare the issue and webhook

Create an unlabelled issue before connecting the webhook:

```bash
gh label create agent --repo "$GITHUB_REPOSITORY" \
  --description "Ready for the coding agent" --color 0080FF
gh issue create --repo "$GITHUB_REPOSITORY" \
  --title 'Free shipping is incorrectly charged at exactly $50' \
  --body-file "$TUTORIAL_ROOT/docs/demo-issue.md"
```

Keep the returned issue number. From the setup checkout, preview the task and
create a uniquely named trigger:

```bash
bash scripts/create-trigger.sh direct --opencode --name shipping-api-demo-01 --dry-run
bash scripts/create-trigger.sh direct --opencode --name shipping-api-demo-01
```

Save the returned trigger ID, URL, and one-time secret privately. In your demo
repo's **Settings → Webhooks**, add that URL and secret, choose
`application/json`, keep SSL verification enabled, and select **Issues** only.
Trigger creation does not create this GitHub webhook. Let setup events finish;
even a skipped direct-trigger event can start a session.

## 3. Show the bug and start the agent

In one terminal, install dependencies and start the API:

```bash
cd "$DEMO_DIR"
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
.venv/bin/python -m uvicorn app.main:app --host 127.0.0.1 --port 8001
```

Open another terminal in that same demo checkout:

```bash
curl --fail --silent --show-error \
  'http://127.0.0.1:8001/quote?subtotal_cents=5000' | python3 -m json.tool
python3 -m unittest discover -s tests -v
```

Shipping is incorrectly **599** cents and the total is **5599**. Expect exactly
**one failing test among four**. At $50, shipping should be free. The tests use
only Python's standard library; installed dependencies serve the local API.

Apply `agent` to the prepared issue using GitHub's label picker. Follow the run
in Harness Runtime, or use your trigger ID from the setup shell:

```bash
doctl --context "$DOCTL_CONTEXT" harness-runtime triggers list-executions TRIGGER_ID
```

Check the final response and actual PR; execution success alone does not prove a
fix was created. Keep raw logs private. See the [setup FAQ](setup-faq.md) for errors.

## 4. Verify the pushed fix

Review the PR's diff, linked issue, and test report. Stop the local API with
**Ctrl+C before switching code**. In the demo checkout, run `git status --short`
and continue only when it is clean. Use the PR number you inspected:

```bash
gh pr checkout PR_NUMBER
python3 -m unittest discover -s tests -v
```

Expect **all four tests to pass**, with unchanged expectations. Restart the API
using the same server command, then repeat the identical curl request. Shipping
should be **0** and the total **5000**. Restarting makes the server load the PR's
code; pulling `main` does not apply an unmerged fix.

Check the actual Slack channel for the summary. Leave the PR open for human
review. When finished, stop the API, disable the GitHub webhook, and pause your
trigger from the setup shell:

```bash
doctl --context "$DOCTL_CONTEXT" harness-runtime triggers pause TRIGGER_ID
```

For another trial, use a fresh demo copy, issue, and trigger name. Re-labeling an
issue with an existing agent PR should return that PR. See
[duplicate handling](../README.md#duplicate-handling-when-issues-or-prs-change)
for closed PRs, deleted branches, and retries.

## Optional hosted relay

This walkthrough proves the direct GitHub-to-Harness Runtime path. The optional
relay is deployed separately on [App Platform with PostgreSQL](../README.md#4-deploy-the-optional-relay-on-app-platform).
Use the generated HTTPS domain. Before switching GitHub to it, disable the direct
webhook and pause its **Harness Runtime trigger**; use a separate custom trigger
behind the relay. Relay deployment and its Slack result require their own live
verification. Local tests do not establish that it has been deployed.
