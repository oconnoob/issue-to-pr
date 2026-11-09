# Shipping Quote API

A reproducible, intentionally buggy FastAPI target for trying issue-to-PR.
Copy this entire directory, including `.gitignore`, into a fresh directory and
give it its own Git repository. Keep this source template buggy for future trials.

Orders below $50 pay $5.99 shipping. Orders at $50 or above should ship free.
The initial code incorrectly charges shipping at exactly $50.

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
.venv/bin/python -m uvicorn app.main:app --host 127.0.0.1 --port 8001
```

In another terminal, from this directory:

```bash
curl --fail --silent --show-error 'http://127.0.0.1:8001/quote?subtotal_cents=5000'
python3 -m unittest discover -s tests -v
```

Initially the response has `shipping_cents: 599` and `total_cents: 5599`, and one
of four tests fails. After the agent's fix, those values become `0` and `5000`,
and all four tests should pass. Stop and restart the API after switching commits
so the curl result reflects the checked-out code. No API deployment is
required; this server runs only on your laptop.

## License

MIT. See [LICENSE](LICENSE).
