import unittest

from app.shipping import shipping_cost


class ShippingTests(unittest.TestCase):
    def test_below_threshold_has_standard_shipping(self):
        self.assertEqual(shipping_cost(4999), 599)

    def test_exact_threshold_has_free_shipping(self):
        self.assertEqual(shipping_cost(5000), 0)

    def test_above_threshold_has_free_shipping(self):
        self.assertEqual(shipping_cost(5001), 0)

    def test_negative_subtotal_is_rejected(self):
        with self.assertRaises(ValueError):
            shipping_cost(-1)


if __name__ == "__main__":
    unittest.main()
