from copy import deepcopy
from decimal import Decimal, localcontext, Inexact
import unittest
from nutrition_core.__main__ import dispatch
from nutrition_core.common import NutritionError
from nutrition_core.labels import calculate_label


class PackageLabelTests(unittest.TestCase):
    def setUp(self):
        self.label={'name':'Fictional yogurt','source_note':'Synthetic label, per 150 g cup',
                    'basis_g':'150','nutrients':{'energy_kcal':'100','protein_g':'12','sodium_mg':'60'}}

    def test_confirmed_partial_pack_and_missing_nutrients(self):
        original=deepcopy(self.label)
        result=calculate_label(self.label,'75',True)
        self.assertEqual(result['totals']['energy_kcal']['amount'],'50')
        self.assertEqual(result['totals']['protein_g']['amount'],'6')
        self.assertIsNone(result['totals']['potassium_mg']['amount'])
        self.assertEqual(result['totals']['energy_kcal']['status'],'label_rounded')
        self.assertFalse(result['intake_recorded'])
        self.assertFalse(result['allergens_verified'])
        self.assertEqual(self.label,original)

    def test_unconfirmed_ocr_cannot_produce_confirmed_totals(self):
        self.assertIsNone(calculate_label(self.label,'75',False)['totals'])

    def test_kj_and_context_are_exact(self):
        self.label['nutrients']={'energy_kj':'418.4'}
        with localcontext() as context:
            context.prec=2;context.traps[Inexact]=True
            result=calculate_label(self.label,'150',True)
        self.assertEqual(result['totals']['energy_kcal']['amount'],'100')

    def test_ambiguous_energy_and_invalid_grams_rejected(self):
        for amount in ('0', True, [], '-1', '10001'):
            with self.assertRaises(NutritionError): calculate_label(self.label,amount,True)
        self.label['nutrients']['energy_kj']='418.4'
        with self.assertRaises(NutritionError): calculate_label(self.label,'150',True)

    def test_cli_preserves_label_precision_and_no_storage(self):
        result=dispatch({'operation':'calculate_label','label':self.label,'amount_g':'150','confirmed':True})
        self.assertEqual(result['status'],'ok')
        self.assertEqual(result['totals']['energy_kcal']['amount'],'100')
        self.assertFalse(result['intake_recorded'])
