import sys
import types
import unittest

# These deterministic math/range tests do not issue HTTP requests. Keep them
# runnable even on a fresh machine before the engine's runtime dependency is
# installed.
sys.modules.setdefault("requests", types.SimpleNamespace(HTTPError=Exception, Session=object))

from gumsdk import GumroadSDK


class GumroadMoneyAndRangeTests(unittest.TestCase):
    def sdk_with_sales(self):
        sdk = object.__new__(GumroadSDK)
        sdk.list_all_sales = lambda: [
            {"price": 2500, "currency": "usd", "created_at": "2026-07-07T12:00:00Z", "product_id": "a"},
            {"price": 999, "currency": "usd", "created_at": "2026-07-10T12:00:00Z", "product_id": "a"},
            {"price": 100, "currency": "usd", "created_at": "2026-06-30T12:00:00Z", "product_id": "b"},
        ]
        return sdk

    def test_prices_are_normalized_from_cents(self):
        summary = self.sdk_with_sales().get_sales_summary()
        self.assertEqual(summary["total_revenue"], 35.99)
        self.assertEqual(summary["currency"], "USD")
        self.assertFalse(summary["refunds"]["available"])

    def test_range_summary_has_an_explicit_inclusive_scope(self):
        summary = self.sdk_with_sales().get_sales_summary_for_range("2026-07-07", "2026-07-13")
        self.assertEqual(summary["total_sales"], 2)
        self.assertEqual(summary["total_revenue"], 34.99)
        self.assertEqual(summary["date_range"], {"start": "2026-07-07", "end": "2026-07-13", "inclusive": True})


if __name__ == "__main__":
    unittest.main()
