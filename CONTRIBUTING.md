# Contributing

Use an issue for a reproducible problem or a focused pull request for a change.
Do not include credentials, resolved local specs, raw agent transcripts or private
issue content. If a credential is exposed, revoke it rather than just deleting
the text.

Run the tutorial checks from this repository's root:

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -r relay/requirements-dev.txt
.venv/bin/python -m pytest -q
```

The separate shipping demo intentionally fails its exact-threshold test. Do not
fix the bug or weaken its expected values on the template's default branch; the
agent should propose that fix in each participant's own copied repository.
Keep the local template and separate demo consistent when changing their API or
instructions. Agent PRs are reviewed by people and are not merged automatically.

For a live reproduction, use your own private copy, account, connection, model
key and Slack webhook. The upstream repositories are source examples, not a
shared agent service.
