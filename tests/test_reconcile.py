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

if __name__ == "__main__":
    unittest.main()
