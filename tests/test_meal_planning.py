"""Behavior tests for executable meals, not template text assertions."""
from copy import deepcopy
from decimal import Decimal, localcontext, Inexact
import json
import tempfile
import unittest

from nutrition_core.__main__ import dispatch
from nutrition_core.catalog import load_catalog
from nutrition_core.common import NutritionError
from nutrition_core.meal_planning import generate_day_plan, find_foods
from nutrition_core.targets import derive_targets, review_targets
from nutrition_core.plans import record_actual
from nutrition_core.storage import save_record, load_record, archive_record
from nutrition_core.workflow import validate_document

TODAY = '2026-10-06'


def profile():
    return {'id':'synthetic','age':34,'goals':['fat_loss'],
            'measurements':{'height_cm':'175','weight_kg':'84','measured_on':TODAY},
            'preferences':{'cuisine':'chinese','effort':'lazy','scenario':'home','dislikes':[]},
            'health':{'allergens':[],'conditions':[],'medications':[],'pregnancy_lactation':False,
                      'eating_disorder_risk':False,'malnutrition_risk':False},'storage':'local'}


class MealPlanningTests(unittest.TestCase):
    def setUp(self):
        self.profile = profile()
        self.inputs = {'sex_for_equation':'male','activity':'inactive','resistance_training':False}
        self.target = derive_targets(self.profile, self.inputs, TODAY)

    def plan(self, **kwargs):
        return generate_day_plan(self.profile, self.target, TODAY, **kwargs)

    def test_meal_generation_really_matches_daily_targets(self):
        for cuisine in ('chinese','western','mixed'):
            for goal in ('fat_loss','muscle_gain','wellbeing'):
                with self.subTest(cuisine=cuisine,goal=goal):
                    self.profile['preferences']['cuisine']=cuisine
                    self.profile['goals']=[goal]
                    self.inputs['resistance_training']=goal=='muscle_gain'
                    self.target=derive_targets(self.profile,self.inputs,TODAY)
                    before=deepcopy(self.target)
                    plan=self.plan()
                    self.assertEqual(plan['status'],'ok',plan['issues'])
                    self.assertEqual(self.target,before)
                    self.assertEqual(plan['state']['actuals'],{})
                    self.assertTrue(plan['check']['plan_complete'])
                    totals=plan['check']['calculation']['totals']
                    for key in ('energy_kcal','protein_g'):
                        self.assertLessEqual(Decimal(self.target[key]['min']),Decimal(totals[key]['amount']))
                        self.assertLessEqual(Decimal(totals[key]['amount']),Decimal(self.target[key]['max']))
                    self.assertEqual(len(plan['cards']),3)

    def test_four_meal_no_cook_and_budget_filters(self):
        self.profile['preferences']['scenario']='no_cook'
        plan=self.plan(options={'meal_ids':['breakfast','lunch','dinner','snack'],'budget':'ordinary'})
        self.assertEqual(plan['status'],'ok',plan['issues'])
        recipes={r['id']:r for r in dispatch({'operation':'list_recipes'})['recipes']}
        for card in plan['cards']:
            self.assertIn('none',recipes[card['recipe_id']]['kitchens'])
        self.profile['preferences']['scenario']='home'
        plan=self.plan(options={'budget':'economy'})
        self.assertEqual(plan['status'],'ok',plan['issues'])
        for card in plan['cards']:
            self.assertEqual(recipes[card['recipe_id']]['budget'],'economy')

    def test_fixed_breakfast_and_recorded_lunch_remain_identical_on_regeneration(self):
        first=self.plan()['state']
        first['meals'][0]['locked']=True
        first=record_actual(first,'lunch',{'status':'confirmed','items':first['meals'][1]['items']},load_catalog())['state']
        before=deepcopy(first)
        after=self.plan(state=first,options={'variant':4})
        self.assertEqual(after['status'],'ok',after['issues'])
        self.assertEqual(first,before)
        self.assertEqual(after['state']['meals'][:2],first['meals'][:2])
        self.assertEqual(after['state']['actuals'],first['actuals'])
        self.assertEqual(after['state']['revision'],first['revision']+1)

    def test_single_meal_swap_preserves_other_meals_and_checks_whole_day(self):
        first=self.plan()
        state=first['state']
        rid=first['cards'][1]['recipe_id']
        changed=self.plan(state=state,options={'replace_meal_id':'lunch','excluded_recipe_ids':[rid]})
        self.assertEqual(changed['status'],'ok',changed['issues'])
        self.assertEqual(changed['state']['meals'][0],state['meals'][0])
        self.assertEqual(changed['state']['meals'][2],state['meals'][2])
        self.assertNotEqual(changed['state']['meals'][1],state['meals'][1])
        self.assertEqual(changed['check']['status'],'ok')
        state['meals'][1]['locked']=True
        self.assertEqual(self.plan(state=state,options={'replace_meal_id':'lunch'})['status'],'conflict')

    def test_impossible_restrictions_do_not_change_state(self):
        state=self.plan()['state']
        before=deepcopy(state)
        for kwargs in ({'options':{'available_food_ids':[]}},
                       {'constraints':{'limits':[{'nutrient':'sodium_mg','max':'1','source':'Synthetic impossible limit'}]}}):
            result=self.plan(state=state,**kwargs)
            self.assertEqual(result['status'],'conflict')
            self.assertEqual(result['state'],before)
        self.assertEqual(state,before)

    def test_new_dislike_invalidates_locked_food_without_unlocking(self):
        state=self.plan()['state']
        state['meals'][0]['locked']=True
        food=state['meals'][0]['items'][0]['food_id']
        result=self.plan(state=state,options={'excluded_food_ids':[food]})
        self.assertEqual(result['status'],'conflict')
        self.assertEqual(result['state'],state)

    def test_health_and_target_member_changes_cannot_use_stale_plan(self):
        for health in ({'allergens':['milk']},{'conditions':['kidney disease']},{'pregnancy_lactation':True}):
            self.profile=profile();self.profile['health'].update(health)
            self.assertEqual(self.plan()['status'],'needs_information')
        self.profile=profile();self.profile['measurements']['weight_kg']='70'
        self.assertEqual(self.plan()['issues'],['target_refresh_required'])
        self.profile=profile();self.profile['id']='someone_else'
        with self.assertRaises(NutritionError): self.plan()

    def test_takeaway_stays_qualitative_without_inventing_oil_or_brand(self):
        self.profile['preferences']['scenario']='takeaway'
        result=self.plan()
        self.assertEqual(result['status'],'needs_information')
        self.assertIsNone(result['state'])
        self.assertEqual(result['qualitative_help']['validation'],'qualitative_only')

    def test_input_shape_and_options_are_strict(self):
        for options in ([],False,{'kitchen':[]},{'budget':[]},{'meal_ids':['lunch']},{'variant':True},{'meal_shares':{}},
                        {'available_food_ids':['not-a-food']},{'recipe_ids':{'lunch':'fake'}},
                        {'max_prep_minutes':0},{'unrelated':True}):
            with self.subTest(options=options), self.assertRaises(NutritionError):
                self.plan(options=options)

    def test_food_search_requires_confirmation_and_preserves_raw_cooked(self):
        result=find_foods('chicken')
        self.assertGreaterEqual(len(result['candidates']),2)
        self.assertEqual({c['state'] for c in result['candidates']},{'raw','cooked'})
        self.assertTrue(result['confirmation_required'])
        self.assertEqual(find_foods('not-a-food-999')['status'],'needs_information')

    def test_custom_decimal_context_does_not_change_output(self):
        baseline=self.plan()
        with localcontext() as context:
            context.prec=3
            context.traps[Inexact]=True
            self.assertEqual(self.plan(),baseline)

    def test_cli_targets_plan_document_save_archive_and_readback(self):
        target=dispatch({'operation':'automatic_targets','profile':self.profile,'inputs':self.inputs,'as_of':TODAY})
        plan=dispatch({'operation':'generate_day_plan','profile':self.profile,'target':target,'as_of':TODAY})
        document={'schema_version':'m3-1','profile':self.profile,'planning':{'inputs':target['inputs'],'target':target},
                  'days':{TODAY:plan['state']},'target_reviews':[]}
        self.assertEqual(validate_document(document),document)
        with tempfile.TemporaryDirectory() as root:
            import os
            data_dir=os.path.join(os.path.realpath(root),'records')
            saved=save_record(data_dir,'synthetic',document,0,True)
            self.assertEqual(saved['status'],'ok')
            archived=archive_record(data_dir,'synthetic',saved['revision'],True,saved['record_id'])
            self.assertEqual(archived['status'],'ok')
            loaded=load_record(data_dir,'synthetic')
            self.assertEqual(loaded['document'],document)
        wrong=deepcopy(document);wrong['planning']['inputs']['activity']='active'
        with self.assertRaises(NutritionError): validate_document(wrong)


if __name__=='__main__': unittest.main()


class ReviewedMealRegressionTests(unittest.TestCase):
    def test_review_date_refresh_and_small_weight_change_still_generate(self):
        from tests.test_targets import profile as old_profile, inputs, observations
        p = old_profile()
        target = derive_targets(p, inputs(), '2026-10-01')
        p['measurements']['measured_on'] = '2026-10-15'
        review = review_targets(p, target, observations(), '2026-10-15')
        self.assertEqual(review['action'], 'adjust')
        p['measurements']['weight_kg'] = '79.8'
        result = generate_day_plan(p, review['target'], '2026-10-15')
        self.assertEqual(result['status'], 'ok', result['issues'])

    def test_no_cook_never_selects_uncooked_regular_oats(self):
        p = profile()
        p['preferences']['scenario'] = 'no_cook'
        target = derive_targets(p, {'sex_for_equation':'male','activity':'inactive','resistance_training':False}, TODAY)
        for variant in range(5):
            result = generate_day_plan(p, target, TODAY, {'variant':variant})
            self.assertEqual(result['status'], 'ok')
            for meal in result['state']['meals']:
                self.assertNotIn('usda:173904', {item['food_id'] for item in meal['items']})


class PersistentPreferencesTests(unittest.TestCase):
    def document(self):
        p=profile()
        inputs={'sex_for_equation':'male','activity':'inactive','resistance_training':False}
        target=derive_targets(p,inputs,TODAY)
        return {'schema_version':'m3-1','profile':p,'planning':{'inputs':inputs,'target':target,
                'options':{'kitchen':'microwave','budget':'economy','meal_ids':['breakfast','lunch','dinner'],
                           'meal_shares':{'breakfast':25,'lunch':35,'dinner':40}}},
                'strategy_state':{'fasting_stopped_for_symptoms':False,
                    'fasting_preferences':{'opt_in':True,'pattern':'14:10','eating_start':'08:00','wake_time':'07:00','sleep_time':'23:00','work_pattern':'day'},
                    'traditional_preferences':{'opt_in':True,'method':'boil'}}}

    def test_once_selected_preferences_round_trip_and_reuse(self):
        from pathlib import Path
        document=self.document()
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory).resolve()/'records'
            saved=save_record(root,'synthetic',document,0,True)
            archive_record(root,'synthetic',saved['revision'],True,saved['record_id'])
            loaded=load_record(root,'synthetic')['document']
            self.assertEqual(loaded,document)
            plan=generate_day_plan(loaded['profile'],loaded['planning']['target'],TODAY,loaded['planning']['options'])
            self.assertEqual(plan['status'],'ok')

    def test_traditional_preferences_do_not_invent_fasting_history(self):
        document = self.document()
        document["strategy_state"] = {"traditional_preferences": {"opt_in": True, "method": "boil"}}
        validated = validate_document(document)
        self.assertNotIn("fasting_stopped_for_symptoms", validated["strategy_state"])
        document["strategy_state"]["fasting_stopped_for_symptoms"] = None
        with self.assertRaises(NutritionError):
            validate_document(document)

    def test_temporary_inventory_and_current_symptoms_cannot_be_saved_as_defaults(self):
        for field,value in [('available_food_ids',[]),('replace_meal_id','lunch'),('variant',2)]:
            document=self.document();document['planning']['options'][field]=value
            with self.assertRaises(NutritionError):validate_document(document)
        for field,value in [('symptoms',[]),('can_meet_daily_needs',True),('previously_stopped_for_symptoms',False)]:
            document=self.document();document['strategy_state']['fasting_preferences'][field]=value
            with self.assertRaises(NutritionError):validate_document(document)

    def test_invalid_saved_preferences_and_ids_rejected(self):
        document=self.document();document['planning']['options']['excluded_food_ids']=['unknown']
        with self.assertRaises(NutritionError):validate_document(document)
        document=self.document();document['strategy_state']['fasting_preferences']['eating_start']='29:00'
        with self.assertRaises(NutritionError):validate_document(document)
        document=self.document();document['planning']['options']['recipe_ids']={'lunch':'fake'}
        with self.assertRaises(NutritionError):validate_document(document)
