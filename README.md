# provider-truth-reconciler

Your automation says the run succeeded. The provider is the only thing that knows
whether it actually did.

This is a small, dependency-free diagnostic that reads two things — **what your
system claimed succeeded** and **what the provider will confirm** — and prints an
exception report for the rows where they disagree.

**Rule 0: UNKNOWN is never converted to SUCCESS.** An unreadable provider is not a
confirmation, and it is not a failure either. Most monitoring collapses that third
state into one of the other two, which is exactly how silent failures stay silent.

## Worked example (runs on the bundled synthetic data)

```
git clone https://github.com/FLiPPpro/provider-truth-reconciler
cd provider-truth-reconciler
python3 reconcile.py \
  --claims   samples/claims.json \
  --provider samples/provider.json \
  --window   samples/window.json
```

Output:

```
PROVIDER-TRUTH RECONCILIATION
provider : synthetic-email-provider
window   : 2026-09-18T00:00:00Z -> 2026-09-18T01:00:00Z
sources  : our log HTTP 200 (6 rows) | provider HTTP 200 (5 events)

VERDICT  : NEEDS_ATTENTION
sent=6 accepted=2 delta=2 unknown=3

EXCEPTIONS (5)
  [DELTA] run-1002
      We reported success but the provider status is "bounced".
  [DELTA] run-1003
      We reported success but the provider has no confirming event in this window.
  [UNKNOWN] run-1004
      Provider returned a matching record with no interpretable status field. Ambiguity is not confirmation.
  [UNKNOWN] None
      Claim carries no idempotency_key, so provider truth cannot be looked up.
  [UNKNOWN] run-0999
      Provider has an event we never claimed. Possible duplicate send, retry, or a run we lost the record of.
```

Six runs were logged as successes. Two of them were real. That gap is the product.

Now run it against a provider that was down:

```
python3 reconcile.py \
  --claims   samples/claims.json \
  --provider samples/provider_unreadable.json \
  --window   samples/window.json
```

```
VERDICT  : UNKNOWN
reason   : Could not read the provider (HTTP 503). Provider silence here is absence of evidence, not evidence of absence.
sent=None accepted=None delta=None unknown=6
```

It does not report zero failures. It reports that it does not know.

## The five states

| State | Meaning |
|---|---|
| `ACCEPTED` | Provider confirmed it with a status in the accept list. |
| `DELTA` | You claimed success; the provider says otherwise, or has no record of it. |
| `UNKNOWN` (no key) | The claim carries no idempotency key, so provider truth cannot be looked up in either direction. |
| `UNKNOWN` (ambiguous) | The provider returned a matching row with no interpretable status. Ambiguity is not confirmation. |
| `UNKNOWN` (orphan) | The provider has an event you never claimed — a duplicate send, a retry, or a run whose record you lost. |

Exit codes: `0` reconciled · `1` exceptions found · `2` the window could not be read.
Suitable for a cron job or a CI step.

## Using it on your own data

Point it at two JSON files, each shaped like an HTTP response you already have:

```json
{ "statusCode": 200, "body": [ { "idempotency_key": "run-1001", "...": "..." } ] }
```

A `{"data": [...]}` envelope inside `body` is also accepted. Flags for everything
that varies between stacks:

```
--claim-path / --provider-path   dotted path to the rows (default: body)
--claim-key  / --provider-key    the join key  (default: idempotency_key)
--accept-states                  comma list (default: delivered,accepted,succeeded,confirmed,paid)
--json                           emit the full machine-readable report
```

`reconcile.reconcile()` is importable if you would rather call it directly.

## Scope, stated plainly

This is the diagnostic, not the pipeline. It does not fetch from your provider, hold
credentials, schedule itself, or write anything back. You hand it two payloads you
already have; it tells you where they disagree, with the provider's own record
attached to every exception so you can trace it. Read-only by construction.

## If you want this run against your own environment

The hard part is rarely the comparison — it is working out which endpoint is
actually authoritative for your provider, what your real join key is, and which
provider statuses genuinely mean "done".

Done-for-you install, $99: I take one of your scheduled automations, wire this
against the right provider endpoint, tune the join key and accept-states to your
stack, and hand it back as a working diff plus the first exception report from your
real data.

https://jarvisai3.gumroad.com/l/pfygw

The same page has a $29 self-serve tier if you would rather do the wiring yourself.

## Origin

The comparison logic here is a direct port of the reconciliation step from a
scheduled n8n workflow built for the same job. This repository extracts it so it can
be run against anything, from a shell, with no platform at all.

## License

MIT — see [LICENSE](LICENSE).
