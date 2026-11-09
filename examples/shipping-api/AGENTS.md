# Working on this demo

This is a small FastAPI shipping quote service. Monetary amounts are integer cents.
Shipping is 599 cents below 5000 cents and free at 5000 cents or more.
Negative subtotals are invalid.

Run the regression suite with:

```bash
python3 -m unittest discover -s tests -v
```

The tests use only the standard library. Installing API dependencies is not
required to run them. Keep fixes small. Do not change prices, the threshold,
test expectations or the API contract. Do not add dependencies or CI workflows.
