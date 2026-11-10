# Where to get the environment values

For the direct GitHub-to-trigger v0, copy `.env.example` to a private `.env` and
set `GITHUB_REPOSITORY`, `DEFAULT_BRANCH`, `GITHUB_ACTOR`, `DOCTL_CONTEXT`,
`HARNESS_INFERENCE_API_KEY` and `SLACK_WEBHOOK_URL` for your own accounts. Authorize
the GitHub OAuth connection as described below. The other credentials are needed
only for the relay/deployment stages. If `.env` exists, edit it instead of copying
over it. The
[demo walkthrough](demo.md) follows the tested OpenCode path; the
[setup FAQ](setup-faq.md) covers expired links, UI imports and local hosting.

| Credential | What it authorizes |
| --- | --- |
| Saved doctl API credential | Managing DO resources in its selected authentication context |
| Model access key | Model inference calls |
| Agent GitHub OAuth connection | Private-repo access, branch pushes and PR creation from the remote sandbox |
| Slack incoming webhook URL | Posting the execution summary to its chosen channel |
| Relay labeler-lookup PAT | Checking repository collaborator access, when the relay needs that lookup |

These credentials are separate. A local `gh` login does not populate the remote
agent's OAuth slot, and the model key does not authenticate GitHub operations.

## DOCTL_CONTEXT

Use `doctl auth list` to find the saved authentication context for the same team
you have selected in the Control Panel. Set `DOCTL_CONTEXT` in `.env` to that name;
the setup and sandbox-probe scripts pass it explicitly without switching your
global CLI context. Leave it blank only when the current CLI context is intended.
Context names are local to your configuration; no special context name is required.
For model or sandbox credential failures, use the
[authentication troubleshooting guide](authentication.md).

For manual `doctl` commands in the tutorial, add `--context "$DOCTL_CONTEXT"`
after `doctl`. A UI session returning 404 in the CLI can indicate a context mismatch.

## HARNESS_INFERENCE_API_KEY

1. Open DigitalOcean's [Model Access Keys page](https://cloud.digitalocean.com/model-studio/manage-keys)
   in the team you use for Harness Runtime.
2. Choose **Create model access key** and name it `issue-to-pr-demo`.
3. Under model scope, select `openai-gpt-oss-120b` for the tested OpenCode path.
   For the Claude Code variant, also select `anthropic-claude-5-sonnet`.
4. Continue and select **No VPC network**. Harness Runtime currently does not
   support VPC-scoped model keys.
5. Create the key, copy the secret shown once, and paste it after
   `HARNESS_INFERENCE_API_KEY=` in `.env`.

This is the model credential; `doctl` uses its separately configured DigitalOcean
API credential to create triggers. No Anthropic API key is needed for this spec.
See [model key instructions](https://docs.digitalocean.com/products/inference/how-to/manage-model-access-keys/)
and [Harness Runtime limits](https://docs.digitalocean.com/products/managed-agents/agent-harness-runtime/details/limits/).

## SLACK_WEBHOOK_URL

1. Open [Slack's app dashboard](https://api.slack.com/apps), choose **Create New App
   → From a manifest**, select your workspace, and paste [slack/manifest.yaml](../slack/manifest.yaml)
   in the **YAML** tab. Review and create the app. See the [manifest setup steps](../slack/README.md).
2. In its settings, open **Incoming Webhooks**; the manifest enables this feature.
   If using an existing app instead, enable **Activate Incoming Webhooks** manually.
3. Choose **Add New Webhook to Workspace**, select the demo channel, then **Authorize**.
   For a private channel, you must already be a member.
4. Copy the resulting URL into `SLACK_WEBHOOK_URL` in `.env`. It normally starts
   with `https://hooks.slack.com/services/`.

The full URL is a credential. A Slack channel URL or bot token is not the value
this setting expects. See [Slack's incoming webhook guide](https://docs.slack.dev/messaging/sending-messages-using-incoming-webhooks/).

## GitHub OAuth connection for the agent

`GITHUB_ACTOR` is a stable DO connection identifier, not a token. Choose your own
actor name, then load the file and start authorization from the project root:

```bash
set -a
source .env
set +a
bash scripts/create-connection.sh
```

Approve in the browser as the GitHub account that should access your demo copy.
DO brokers the sandbox's `GITHUB_TOKEN`; you do not paste that token into `.env`.
Verify the connection with:

```bash
doctl --context "$DOCTL_CONTEXT" harness-runtime connections list --actor "$GITHUB_ACTOR"
```

Then follow [README step 2](../README.md#2-prove-v0-github-directly-to-harness-runtime)
to create the direct trigger. The GitHub webhook for v0 uses the URL and secret
returned by that trigger. See [DO's GitHub connection guide](https://docs.digitalocean.com/products/managed-agents/agent-harness-runtime/how-to/connect-github/).

## Values needed when adding the relay

| Variable | Where it comes from |
| --- | --- |
| `GITHUB_REPOSITORY` | Your copied demo repository in `owner/repo` form |
| `DEFAULT_BRANCH` | Your repository's default branch, normally `main` for this demo |
| `GITHUB_ACTOR` | Your actor-scoped GitHub connection, authorized as above |
| `AGENT_LABEL` | Your chosen label, normally `agent`; create it in your repository |
| `GITHUB_WEBHOOK_SECRET` | Generate a new secret and use it for GitHub → relay |
| `RELAY_GITHUB_TOKEN` | Create the GitHub PAT described below; used only to check labeler access |
| `HARNESS_TRIGGER_URL` | Copy from `bash scripts/create-trigger.sh relay --opencode` output |
| `HARNESS_TRIGGER_SECRET` | Copy the one-time secret from that same **custom** trigger response |
| `DATABASE_PATH` | Local SQLite location, used only when `DATABASE_URL` is empty |
| `DATABASE_URL` | PostgreSQL connection URL; App Platform binds `${relay-db.DATABASE_URL}` at runtime and this takes precedence over `DATABASE_PATH` |
| `APP_PLATFORM` | Set to `true` by the app spec; startup requires PostgreSQL when present |

For `RELAY_GITHUB_TOKEN`, in GitHub open **Settings → Developer settings → Personal
access tokens → Fine-grained tokens → Generate new token**. Select your repository's
resource owner, give it an expiration, choose **Only select repositories**, and
select your demo copy. The collaborator-check endpoint requires **Metadata:
read** repository permission, which is included automatically. Copy the generated
token into `.env`. See [GitHub's PAT guide](https://docs.github.com/en/authentication/keeping-your-account-and-data-secure/managing-your-personal-access-tokens)
and the [collaborator endpoint's permissions](https://docs.github.com/en/rest/collaborators/collaborators#check-if-a-user-is-a-repository-collaborator).

For a fresh checkout, generate `GITHUB_WEBHOOK_SECRET` yourself with
`openssl rand -hex 32`. It must differ from `HARNESS_TRIGGER_SECRET`. The direct
v0 trigger and relay custom trigger also have different secrets; do not mix them.

Save credentials only in the gitignored `.env`, never in `.env.example`. Reload
the environment after edits before running setup scripts. Existing triggers keep
their captured credentials until you update or recreate them.

For hosted deployment, use [the App Platform guide](../README.md#4-deploy-the-optional-relay-on-app-platform).
Set relay secrets as runtime Secret values. App Platform supplies the HTTPS domain
and database URL. No `RELAY_DOMAIN` is needed. Use a direct PostgreSQL endpoint,
not transaction pooling, so the worker's session advisory lock stays attached to
its connection. The demo spec includes a development database; use Managed
PostgreSQL for production. Database URLs are credentials too.
