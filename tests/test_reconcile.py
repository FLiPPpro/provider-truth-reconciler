import json, os, sys, unittest
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from reconcile import reconcile

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

def load(name):
    with open(os.path.join(HERE, "samples", name)) as fh:
        return json.load(fh)

class TestReconcile(unittest.TestCase):
    def test_bundled_sample(self):
        r = reconcile(load("claims.json"), load("provider.json"), load("window.json"))
        self.assertEqual(r["verdict"], "NEEDS_ATTENTION")
        self.assertEqual((r["sent"], r["accepted"], r["delta"], r["unknown_count"]), (6, 2, 2, 3))

    def test_unreadable_provider_is_unknown_not_zero(self):
        r = reconcile(load("claims.json"), load("provider_unreadable.json"), load("window.json"))
        self.assertEqual(r["verdict"], "UNKNOWN")
        self.assertIsNone(r["delta"])

    def test_all_confirmed_reconciles(self):
        claims = {"statusCode": 200, "body": [{"idempotency_key": "k1"}]}
        provider = {"statusCode": 200, "body": [{"idempotency_key": "k1", "status": "delivered"}]}
        r = reconcile(claims, provider, {"provider_name": "p"})
        self.assertEqual(r["verdict"], "RECONCILED")

    def test_confirmed_but_stale_is_unknown(self):
        # Reported by DuskWatch: a provider deduping on the idempotency key hands a
        # re-run the first attempt's delivered record. Older than claimed_at -> UNKNOWN.
        claims = {"statusCode": 200, "body": [
            {"idempotency_key": "k1", "claimed_at": "2026-09-23T10:00:00Z"},
            {"idempotency_key": "k2", "claimed_at": "2026-09-23T10:00:00Z"},
            {"idempotency_key": "k3", "claimed_at": "2026-09-23T10:00:00Z"},
        ]}
        provider = {"statusCode": 200, "body": [
            {"idempotency_key": "k1", "status": "delivered", "created_at": "2026-09-22T09:00:00Z"},
            {"idempotency_key": "k2", "status": "delivered", "created_at": "2026-09-23T10:00:05Z"},
            {"idempotency_key": "k3", "status": "delivered"},
        ]}
        r = reconcile(claims, provider, {"provider_name": "p"})
        states = {rec["idempotency_key"]: rec["state"] for rec in r["records"]}
        self.assertEqual(states, {"k1": "UNKNOWN", "k2": "ACCEPTED", "k3": "UNKNOWN"})
        self.assertEqual(r["verdict"], "NEEDS_ATTENTION")
        self.assertEqual((r["accepted"], r["unknown_count"]), (1, 2))

if __name__ == "__main__":
    unittest.main()
