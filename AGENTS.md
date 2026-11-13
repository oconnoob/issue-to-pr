# Guide users through issue-to-PR setup

This repository helps users set up a cloud coding agent on DigitalOcean
Harness Runtime. A GitHub issue labeled `agent` starts a hosted run that can
open a pull request for human review and post its final summary to Slack.
You are the setup guide in this checkout. The hosted agent's task instructions
live in `spec/prompt.txt`; setup guidance belongs here and in the linked docs.

## Start with the direct demo

1. Determine where the user is in the setup. Continue from any working
   configuration. Confirm the intended DigitalOcean team and `DOCTL_CONTEXT`,
   GitHub target repository, and default branch before making remote changes.
2. For a first run, follow the [demo walkthrough](docs/demo.md). Use a private
   copy of the shipping API template as the target. This checkout is the setup
   repository, not the target. Leave the demo bug in place for the hosted agent
   to fix.
3. Use the [environment guide](docs/environment.md) and [Slack setup](slack/README.md)
   to guide credential entry and GitHub OAuth. Have the user enter secrets in
   their local `.env` or the relevant provider UI and approve OAuth in their
   browser. Preserve an existing `.env`. Do not print secrets, resolved specs,
   or unredacted logs in chat or commit them.
4. Follow [the direct OpenCode setup](README.md#2-prove-v0-github-directly-to-harness-runtime).
   Start with the documented dry run. Explain which later steps create a trigger,
   add a GitHub webhook, or start a hosted run, and make those changes only within
   the user's authorized scope. Trigger creation does not install the webhook.
   The direct demo needs no relay or tunnel; keep it on a controlled issue tracker.
5. Verify the actual PR, its linked issue, the regression tests, and Slack receipt.
   A successful execution alone does not establish any of those. Use the
   [setup FAQ](docs/setup-faq.md) and [authentication guide](docs/authentication.md)
   to troubleshoot the step that failed. Leave the PR open for human review.

## Add the relay only when needed

Follow [the App Platform deployment guide](README.md#4-deploy-the-optional-relay-on-app-platform)
for PostgreSQL, the generated HTTPS address, and a separate custom trigger.
Preview the app proposal and explain the charges before creating resources. At
cutover, disable the direct GitHub webhook and pause its Harness Runtime trigger
before enabling the relay route. Keep the two routes from running in parallel.
