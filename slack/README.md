# Slack app manifest

`manifest.yaml` defines the app's display name, bot identity and incoming webhook
permission. It contains no credentials. The only requested OAuth scope is
`incoming-webhook`, which lets the installer choose a channel for summaries.

## Create the app

1. Open [Your Slack Apps](https://api.slack.com/apps).
2. Choose **Create New App → From a manifest**, then select your workspace.
3. Choose **YAML** and paste the contents of [manifest.yaml](manifest.yaml).
4. Review the configuration and create the app.
5. Open **Incoming Webhooks → Add New Webhook to Workspace**.
6. Select the demo channel and authorize the installation. For a private channel,
   you must already belong to it.
7. Copy the generated URL into `SLACK_WEBHOOK_URL` in the project's gitignored
   `.env`. If installation already generated a webhook, use that URL.

The manifest configures the app; Slack generates the secret webhook URL during
installation. The channel is selected there rather than hardcoded in the manifest.
This demo posts summaries through that URL and needs no event subscriptions,
slash commands or Slack request endpoint.

## Can it post after execution? Does it need chat:write?

Yes. Harness Runtime sends the agent's final response to the incoming webhook
configured on the trigger with `--output-mode slack --output-slack-webhook`.
The `incoming-webhook` scope already authorizes that channel-specific posting;
`chat:write` and a bot token are not needed for this flow. The agent sandbox does
not need the Slack webhook or Slack egress access.

The app does not listen for messages, mentions or thread replies. Adding those
features would require a separate Slack interaction flow and the matching event
subscriptions/scopes. There is no "what it can respond to" configuration to add
for the current final-summary behavior.

If no summary appears, inspect the DO execution's status and output, confirm the
selected Slack channel and webhook, and check the trigger's output configuration.
Editing `.env` alone does not update an existing trigger. Incoming webhooks cannot
read channel history, so verify message receipt in Slack itself.

References: [Slack app manifests](https://docs.slack.dev/app-manifests/),
[manifest fields](https://docs.slack.dev/reference/app-manifest/),
[`incoming-webhook` scope](https://docs.slack.dev/reference/scopes/incoming-webhook/),
[incoming webhook setup](https://docs.slack.dev/messaging/sending-messages-using-incoming-webhooks/).
