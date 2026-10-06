#!/usr/bin/env python3
"""Run a synthetic product journey, with no network or retained personal records."""
from copy import deepcopy
from datetime import date, timedelta
import json
from pathlib import Path
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
from nutrition_core.__main__ import dispatch


def run():
    day='2026-10-01'
    profile={'id':'demo_adult','age':34,'goals':['fat_loss'],'storage':'local',
             'measurements':{'height_cm':'175','weight_kg':'84','measured_on':day},
             'preferences':{'cuisine':'chinese','effort':'lazy','scenario':'home','dislikes':[]},
             'health':{'allergens':[],'conditions':[],'medications':[],'pregnancy_lactation':False,
                       'eating_disorder_risk':False,'malnutrition_risk':False}}
    inputs={'sex_for_equation':'male','activity':'inactive','resistance_training':False}
    target=dispatch({'operation':'automatic_targets','profile':profile,'inputs':inputs,'as_of':day})
    assert target['status']=='ok'
    plan=dispatch({'operation':'generate_day_plan','profile':profile,'target':target,'as_of':day})
    assert plan['status']=='ok'
    state=deepcopy(plan['state'])
    state['meals'][0]['locked']=True;state['revision']+=1
    state=dispatch({'operation':'record_actual','state':state,'meal_id':'breakfast',
                    'actual':{'status':'confirmed','items':state['meals'][0]['items']}})['state']
    swap=dispatch({'operation':'generate_day_plan','profile':profile,'target':target,'as_of':day,'state':state,
                   'options':{'replace_meal_id':'lunch','excluded_recipe_ids':[plan['cards'][1]['recipe_id']]}})
    assert swap['status']=='ok'
    assert swap['state']['meals'][0]==state['meals'][0] and swap['state']['actuals']==state['actuals']
    assert swap['state']['meals'][2]==state['meals'][2]
    start=date(2026,10,2)
    feedback={'window_start':'2026-10-02','window_end':'2026-10-15',
              'weigh_ins':[{'date':(start+timedelta(days=d)).isoformat(),'weight_kg':'84'} for d in (0,2,4,7,9,11)],
              'adherent_days':14,'comparable_conditions':True,'health_changed':False,'appetite_declined':False,
              'unintentional_weight_loss':False,'returning_after_gap':False,'activity_changed':False,
              'energy':'normal','hunger':'comfortable'}
    profile['measurements']['measured_on']='2026-10-15'
    review=dispatch({'operation':'weekly_adjustment','profile':profile,'target':target,'feedback':feedback,'as_of':'2026-10-15'})
    assert review['action']=='adjust'
    next_plan=dispatch({'operation':'generate_day_plan','profile':profile,'target':review['target'],'as_of':'2026-10-15'})
    assert next_plan['status']=='ok'
    label=dispatch({'operation':'calculate_label','label':{'name':'Synthetic yogurt','source_note':'Synthetic per 150 g label',
                    'basis_g':'150','nutrients':{'energy_kcal':'100','protein_g':'12'}},'amount_g':'75','confirmed':True})
    assert label['totals']['energy_kcal']['amount']=='50' and not label['intake_recorded']
    fasting=dispatch({'operation':'fasting','profile':profile,'as_of':'2026-10-15','request':{
        'opt_in':True,'pattern':'14:10','eating_start':'08:00','wake_time':'07:00','sleep_time':'23:00',
        'work_pattern':'day','symptoms':[],'previously_stopped_for_symptoms':False,'can_meet_daily_needs':True}})
    assert fasting['status']=='ok'
    traditional=dispatch({'operation':'tcm','profile':profile,'as_of':'2026-10-15','request':{
        'opt_in':True,'purpose':'ordinary_food','method':'porridge'}})
    assert traditional['status']=='ok'
    document={'schema_version':'m3-1','profile':profile,'planning':{'inputs':inputs,'target':review['target']},
              'days':{day:swap['state'],'2026-10-15':next_plan['state']},'target_reviews':[review],
              'strategy_state':{'fasting_stopped_for_symptoms':False}}
    with tempfile.TemporaryDirectory() as directory:
        data_dir=str(Path(directory).resolve()/'records')
        saved=dispatch({'operation':'save_record','data_dir':data_dir,'member_id':profile['id'],'document':document,
                        'expected_revision':0,'consent':True})
        assert saved['status']=='ok'
        archived=dispatch({'operation':'archive_record','data_dir':data_dir,'member_id':profile['id'],
                           'expected_revision':saved['revision'],'expected_record_id':saved['record_id'],'consent':True})
        assert archived['status']=='ok'
        loaded=dispatch({'operation':'load_record','data_dir':data_dir,'member_id':profile['id']})
        assert loaded['document']==document
        exported=dispatch({'operation':'export_record','data_dir':data_dir,'member_id':profile['id']})
        assert exported['export_complete']
    return {'status':'ok','data':'synthetic_only','target_energy_kcal':target['energy_kcal'],
            'initial_plan_kcal':plan['check']['calculation']['totals']['energy_kcal']['amount'],
            'meals':[{'meal':c['meal_id'],'title':c['title'],'portions':[(p['name'],p['grams']) for p in c['portions']]} for c in plan['cards']],
            'checks':['targets','quantified_day','fixed_and_eaten_preserved','single_meal_swap','bounded_weekly_adjustment',
                      'adjusted_day','confirmed_package_label','fasting_window','ordinary_traditional_foods',
                      'private_save','long_term_archive','new_readback','complete_export'],
            'temporary_records_removed':True}


if __name__=='__main__':
    print(json.dumps(run(),ensure_ascii=False,indent=2))
