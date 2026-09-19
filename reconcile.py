#!/usr/bin/env python3
"""Provider-truth reconciliation.

Your automation says the run succeeded. The provider is the only thing that
knows whether it actually did. This compares the two and emits an exception
report.

Rule 0: UNKNOWN is never converted to SUCCESS.

Stdlib only. Python 3.8+.
"""

import argparse
import json
import sys
from datetime import datetime, timezone

ACCEPT_STATES = ["delivered", "accepted", "succeeded", "confirmed", "paid"]


def dig(obj, path):
    """Walk a dotted path. Returns None if any hop is missing."""
    if not path:
        return obj
    cur = obj
    for key in path.split("."):
        if cur is None:
            return None
        if isinstance(cur, dict):
            cur = cur.get(key)
        else:
            return None
    return cur


def as_rows(value):
    """Accept either a bare list or the common {"data": [...]} envelope."""
    if isinstance(value, list):
        return value
    if isinstance(value, dict) and isinstance(value.get("data"), list):
        return value["data"]
    return []


def reconcile(claim_response, provider_response, window,
              claim_path="body", provider_path="body",
              claim_key="idempotency_key", provider_key="idempotency_key",
              accept_states=None):
    """Return the exception report for one reconciliation window.

    claim_response   -- what YOUR system logged as a success
    provider_response -- what the PROVIDER will confirm
    window           -- {"window_start", "window_end", "provider_name"}
    """
    accept = [s.lower() for s in (accept_states or ACCEPT_STATES)]

    claim_status = claim_response.get("statusCode")
    provider_status = provider_response.get("statusCode")
    claim_ok = isinstance(claim_status, int) and 200 <= claim_status < 300
    provider_ok = isinstance(provider_status, int) and 200 <= provider_status < 300

    claims = as_rows(dig(claim_response, claim_path)) if claim_ok else []
    events = as_rows(dig(provider_response, provider_path)) if provider_ok else []

    evidence = {
        "window_start": window.get("window_start"),
        "window_end": window.get("window_end"),
        "provider": window.get("provider_name"),
        "claim_source_status": claim_status,
        "provider_source_status": provider_status,
        "claims_read": len(claims),
        "provider_events_read": len(events),
        "reconciled_at": datetime.now(timezone.utc)
        .isoformat(timespec="milliseconds")
        .replace("+00:00", "Z"),
    }

    # If either side could not be read, EVERYTHING in the window is UNKNOWN.
    # An unreadable provider is not a confirmation, and it is not a failure either.
    if not claim_ok or not provider_ok:
        if not claim_ok:
            reason = (
                "Could not read our own claimed-success log (HTTP %s). "
                "Nothing in this window can be asserted." % claim_status
            )
        else:
            reason = (
                "Could not read the provider (HTTP %s). Provider silence here is "
                "absence of evidence, not evidence of absence." % provider_status
            )
        return {
            "verdict": "UNKNOWN",
            "reason": reason,
            "sent": None,
            "accepted": None,
            "delta": None,
            "unknown_count": len(claims) or None,
            "records": [],
            "evidence": evidence,
        }

    by_key = {}
    for event in events:
        key = dig(event, provider_key)
        if key is not None:
            by_key[str(key)] = event

    records = []
    accepted = delta = unknown = 0

    for claim in claims:
        key = dig(claim, claim_key)

        # A claim with no key cannot be matched in EITHER direction -> UNKNOWN, not a delta.
        if key is None:
            unknown += 1
            records.append({
                "idempotency_key": None,
                "state": "UNKNOWN",
                "why": "Claim carries no %s, so provider truth cannot be looked up." % claim_key,
                "provider_evidence": None,
                "our_claim": claim,
            })
            continue

        event = by_key.get(str(key))
        if event is None:
            delta += 1
            records.append({
                "idempotency_key": key,
                "state": "DELTA",
                "why": "We reported success but the provider has no confirming event in this window.",
                "provider_evidence": None,
                "our_claim": claim,
            })
            continue

        raw_state = dig(event, "status")
        if raw_state is None:
            raw_state = dig(event, "state")
        state = str(raw_state).lower() if raw_state is not None else ""

        if state in accept:
            accepted += 1
            records.append({
                "idempotency_key": key,
                "state": "ACCEPTED",
                "why": 'Provider confirmed with status "%s".' % state,
                "provider_evidence": event,
                "our_claim": claim,
            })
        elif not state:
            # Provider returned a row but no interpretable status. Ambiguous != confirmed.
            unknown += 1
            records.append({
                "idempotency_key": key,
                "state": "UNKNOWN",
                "why": "Provider returned a matching record with no interpretable status "
                       "field. Ambiguity is not confirmation.",
                "provider_evidence": event,
                "our_claim": claim,
            })
        else:
            delta += 1
            records.append({
                "idempotency_key": key,
                "state": "DELTA",
                "why": 'We reported success but the provider status is "%s".' % state,
                "provider_evidence": event,
                "our_claim": claim,
            })

    # Provider events with no matching claim: the inverse blind spot.
    claim_keys = {str(dig(c, claim_key)) for c in claims}
    for event in events:
        if str(dig(event, provider_key)) in claim_keys:
            continue
        unknown += 1
        records.append({
            "idempotency_key": dig(event, provider_key),
            "state": "UNKNOWN",
            "why": "Provider has an event we never claimed. Possible duplicate send, "
                   "retry, or a run we lost the record of.",
            "provider_evidence": event,
            "our_claim": None,
        })

    return {
        "verdict": "NEEDS_ATTENTION" if (delta or unknown) else "RECONCILED",
        "sent": len(claims),
        "accepted": accepted,
        "delta": delta,
        "unknown_count": unknown,
        "records": records,
        "evidence": evidence,
    }


def render_text(report):
    ev = report["evidence"]
    lines = []
    lines.append("PROVIDER-TRUTH RECONCILIATION")
    lines.append("provider : %s" % ev.get("provider"))
    lines.append("window   : %s -> %s" % (ev.get("window_start"), ev.get("window_end")))
    lines.append("sources  : our log HTTP %s (%s rows) | provider HTTP %s (%s events)" % (
        ev.get("claim_source_status"), ev.get("claims_read"),
        ev.get("provider_source_status"), ev.get("provider_events_read")))
    lines.append("")
    lines.append("VERDICT  : %s" % report["verdict"])
    if report.get("reason"):
        lines.append("reason   : %s" % report["reason"])
    lines.append("sent=%s accepted=%s delta=%s unknown=%s" % (
        report["sent"], report["accepted"], report["delta"], report["unknown_count"]))

    exceptions = [r for r in report["records"] if r["state"] != "ACCEPTED"]
    if exceptions:
        lines.append("")
        lines.append("EXCEPTIONS (%d)" % len(exceptions))
        for rec in exceptions:
            lines.append("  [%s] %s" % (rec["state"], rec["idempotency_key"]))
            lines.append("      %s" % rec["why"])
    return "\n".join(lines)


def main(argv=None):
    parser = argparse.ArgumentParser(
        description="Reconcile what your automation claimed against what the provider confirms.")
    parser.add_argument("--claims", required=True,
                        help="JSON file: the response from your own claimed-success log")
    parser.add_argument("--provider", required=True,
                        help="JSON file: the response from the provider's events endpoint")
    parser.add_argument("--window", required=True,
                        help="JSON file: {window_start, window_end, provider_name}")
    parser.add_argument("--claim-path", default="body")
    parser.add_argument("--provider-path", default="body")
    parser.add_argument("--claim-key", default="idempotency_key")
    parser.add_argument("--provider-key", default="idempotency_key")
    parser.add_argument("--accept-states", default=",".join(ACCEPT_STATES))
    parser.add_argument("--json", action="store_true", help="emit the full report as JSON")
    args = parser.parse_args(argv)

    with open(args.claims) as fh:
        claims = json.load(fh)
    with open(args.provider) as fh:
        provider = json.load(fh)
    with open(args.window) as fh:
        window = json.load(fh)

    report = reconcile(
        claims, provider, window,
        claim_path=args.claim_path, provider_path=args.provider_path,
        claim_key=args.claim_key, provider_key=args.provider_key,
        accept_states=[s.strip() for s in args.accept_states.split(",") if s.strip()],
    )

    if args.json:
        print(json.dumps(report, indent=2, sort_keys=False))
    else:
        print(render_text(report))

    # 0 = everything confirmed. 1 = exceptions found. 2 = window unreadable.
    if report["verdict"] == "RECONCILED":
        return 0
    if report["verdict"] == "UNKNOWN":
        return 2
    return 1


if __name__ == "__main__":
    sys.exit(main())
