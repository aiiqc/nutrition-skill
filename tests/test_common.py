import unittest
from decimal import Decimal, Inexact, localcontext

from nutrition_core.common import NutritionError, decimal_text, exact_context, number, require_keys


class DecimalBoundaryTests(unittest.TestCase):
    def test_rejects_ambiguous_or_unbounded_values(self):
        for value in (True, False, 0.1, float("nan"), "NaN", "Infinity", "-1", "1_0",
                      " 1", "1e2", "", "0.0000000000001", "10000000000000",
                      "123456789012.1234567", {}, []):
            with self.subTest(value=value), self.assertRaises(NutritionError):
                number(value)

    def test_exact_mass_conversion_and_output(self):
        with exact_context():
            self.assertEqual(decimal_text(number("0.043") * Decimal(1000)), "43")
            self.assertEqual(decimal_text(number("1.200") * Decimal("1.5")), "1.8")
        self.assertEqual(number(0), Decimal(0))
        with self.assertRaises(NutritionError):
            number("0", positive=True)

    def test_context_isolation(self):
        with localcontext() as outer:
            outer.prec = 2
            outer.traps[Inexact] = True
            with exact_context():
                self.assertEqual(Decimal("31.02") * Decimal("1.8"), Decimal("55.836"))
            self.assertEqual(outer.prec, 2)

    def test_fields_are_not_silently_ignored(self):
        for value in ([], {"amout": 2}, {1: "x"}):
            with self.assertRaises(NutritionError):
                require_keys(value, {"amount"}, {"amount"}, "quantity")
