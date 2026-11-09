# Run the shipping API issue-to-PR demo

Use your own private copy of the demo and your own DO/GitHub/Slack credentials.
The API runs locally for checking behavior; the coding agent runs on DO and
clones your committed GitHub source. You do not need a public API server, relay,
Droplet or tunnel for this direct-trigger exercise.

## Prepare a fresh target

Start in the tutorial repository and follow [environment setup](environment.md)
and [Slack installation](../slack/README.md). Configure your `.env` with the new
target repository, not the upstream example. Preserve an existing `.env` instead
of overwriting it. Then load your trusted settings:

```bash
export TUTORIAL_ROOT="$PWD"
set -a
source .env
set +a
export DEMO_DIR="$(dirname "$TUTORIAL_ROOT")/shipping-api-demo-01"
```

Choose a new local directory and a new `GITHUB_REPOSITORY` for each independent
trial. Copy only the included source template, which contains no credentials or
Git history:

```bash
(
  set -e
  test ! -e "$DEMO_DIR"
  mkdir -p "$DEMO_DIR"
  cp -R "$TUTORIAL_ROOT/examples/shipping-api/." "$DEMO_DIR/"
  git -C "$DEMO_DIR" init -b main
  git -C "$DEMO_DIR" add .
  git -C "$DEMO_DIR" commit -m "Add shipping API with boundary regression"
  gh repo create "$GITHUB_REPOSITORY" --private \
    --source "$DEMO_DIR" --remote origin --push
)
```

If Git requires an author identity, configure it for this local repository before
finishing the commit. Alternatively, use the separate demo repository's **Use this
template** button and include only its default branch. Do not include its example
fix branches. Clone your resulting repository locally and set `DEMO_DIR` to it.

## Start the API and reproduce the bug

In one terminal:

```bash
cd "$DEMO_DIR"
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
.venv/bin/python -m uvicorn app.main:app --host 127.0.0.1 --port 8001
```

In another terminal, run:

```bash
curl --fail --silent --show-error \
  'http://127.0.0.1:8001/quote?subtotal_cents=5000' | python3 -m json.tool
```

Initial response:

```json
{"subtotal_cents":5000,"shipping_cents":599,"total_cents":5599}
```

The order is exactly $50, so shipping should be free. At 4999 cents, shipping
should remain 599 cents; at 5001 cents, it should be zero. Negative subtotals
should return HTTP 422.

From the demo directory, run the regression tests:

```bash
python3 -m unittest discover -s tests -v
```

Expect exactly **one failure among four tests** at the threshold. These tests
use only Python's standard library; the local dependency install serves the API.
If all tests pass before the agent works, check that you started from the buggy
template rather than an existing fix branch.

## Create an issue and connect a trigger

Use the shell where `TUTORIAL_ROOT`, `GITHUB_REPOSITORY` and your DO settings are
loaded. Create the issue before connecting the webhook, and leave it unlabelled:

```bash
gh label create agent --repo "$GITHUB_REPOSITORY" \
  --description "Ready for the coding agent" --color 0080FF
ISSUE_URL="$(gh issue create --repo "$GITHUB_REPOSITORY" \
  --title 'Free shipping is incorrectly charged at exactly $50' \
  --body-file "$TUTORIAL_ROOT/docs/demo-issue.md")"
export ISSUE_NUMBER="${ISSUE_URL##*/}"
printf 'Issue %s: %s\n' "$ISSUE_NUMBER" "$ISSUE_URL"
```

Keep the actual issue number. Ensure the OAuth actor is active in your selected
DO context. From the tutorial directory, create a uniquely named OpenCode trigger:

```bash
cd "$TUTORIAL_ROOT"
bash scripts/create-trigger.sh direct --opencode --name shipping-api-demo-01 --dry-run
doctl --context "$DOCTL_CONTEXT" harness-runtime create \
  --spec spec/issue-to-pr-opencode.yaml --dry-run
bash scripts/create-trigger.sh direct --opencode --name shipping-api-demo-01
```

The first two commands create nothing. Run the final command once, then privately
save its trigger ID, webhook URL and one-time secret. Configure a webhook in your
new repository with that URL and secret, JSON, SSL verification and **Issues**
only. A setup ping can produce a skipped session. Trigger creation does not create
the GitHub webhook for you. Never publish the returned secret or Slack webhook.

Apply `agent` using the issue's label picker, or use this command instead:

```bash
gh issue edit "$ISSUE_NUMBER" --repo "$GITHUB_REPOSITORY" --add-label agent
```

Follow the execution with the returned IDs:

```bash
doctl --context "$DOCTL_CONTEXT" harness-runtime triggers list-executions TRIGGER_ID
doctl --context "$DOCTL_CONTEXT" harness-runtime triggers get-execution \
  TRIGGER_ID EXECUTION_ID
```

Inspect detailed logs privately. A completed turn does not prove it opened a PR;
read its final response and inspect the actual GitHub result. Fresh-trigger
sandboxes are removed after completion, so use retained execution records then.

## Verify the pushed PR and repeat the curl request

Find the proposed fix:

```bash
gh pr list --repo "$GITHUB_REPOSITORY" --state open \
  --head "agent/issue-$ISSUE_NUMBER"
```

Review its diff, issue reference and reported test result. Stop your local API
with **Ctrl+C before switching code**. From a clean demo checkout, use the actual
PR number you inspected:

```bash
git status --short
gh pr checkout PR_NUMBER
git rev-parse --short HEAD
python3 -m unittest discover -s tests -v
```

Continue only when the checkout is clean; do not discard local work with
`--force`. Expect **all four tests to pass** with unchanged expectations. Restart
the API using the same server command, then repeat the exact 5000-cent request.
The corrected result should be:

```json
{"subtotal_cents":5000,"shipping_cents":0,"total_cents":5000}
```

Restarting avoids serving code still loaded by the previous Python process.
Checking out the PR locally does not merge it or change remote `main`; pulling
`main` alone will not apply an unmerged PR's fix. Check the actual Slack channel
for the final summary and leave the PR for human review.

## Repeat or stop

Pause your trial trigger, disable its GitHub webhook and stop the local API when
finished. Use a new repository, directory and trigger name for a fresh trial.
Keep the upstream source template buggy so new copies reproduce the initial
behavior. Re-labeling an issue with an existing agent PR should
return that PR; see [duplicate handling](../README.md#duplicate-handling-when-issues-or-prs-change).

The template's before/after API behavior has been verified locally. Completing
the workflow requires your own authorized accounts and a successful live agent
run. The relay is a separate deployment stage; see the [setup FAQ](setup-faq.md).
