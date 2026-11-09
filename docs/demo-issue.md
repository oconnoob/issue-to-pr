## Bug

Shipping should be free for orders of 5000 cents ($50) or more. At exactly 5000
cents, the API incorrectly charges 599 cents shipping.

## Reproduce

Run the API with:

```bash
.venv/bin/python -m uvicorn app.main:app --host 127.0.0.1 --port 8001
```

Then request:

```bash
curl 'http://127.0.0.1:8001/quote?subtotal_cents=5000'
```

Actual:

```json
{"subtotal_cents":5000,"shipping_cents":599,"total_cents":5599}
```

Expected:

```json
{"subtotal_cents":5000,"shipping_cents":0,"total_cents":5000}
```

## Acceptance criteria

- Make the smallest fix to the exact-threshold behavior.
- Keep the API, 5000-cent threshold and 599-cent shipping price unchanged.
- Preserve all regression tests and expected values; add no dependencies.
- Run `python3 -m unittest discover -s tests -v`; all four tests must pass.
- Open a PR with a standalone `Fixes #N`, using this issue's actual number,
  and describe the change and exact test command/result.
- Send the final summary through the configured Slack output. Do not post issue
  comments, change CI workflows or merge the PR.
