import copy
import unittest
from consumption_model import apply_corrections, load_corrections, parse_corrections, validate_config
from validate_data import validate_fuel


class ConsumptionTests(unittest.TestCase):
    def setUp(self):
        self.config={'pricePerLitre':5400,'litresPerTrip':5000,
                     'fuelIssues':[{'date':'2026-10-23','rig':'C-1800','shift':'Өдөр','litres':100},
                                   {'date':'2026-10-23','rig':'CSD-1300','shift':'Шөнө','litres':200}],
                     'waterTrips':[{'date':'2026-10-23','rig':'C-1800','shift':'Өдөр','hole':'X','trips':1}]}
        self.data={'finance':{'period':'2026-10','fuel':{
            'daily':[{'date':'2026-10-22','litres':400,'cost':2160000},{'date':'2026-10-23','litres':999,'cost':5394600}],
            'allocations':[{'date':'2026-10-22','rig':'C-1800','shift':'Өдөр','hole':'X','litres':400,'cost':2160000},
                           {'date':'2026-10-23','rig':'C-1800','shift':'Өдөр','hole':'X','litres':999,'cost':5394600}]}},
            'shifts':[{'date':'2026-10-23','rig':'C-1800','shift':'Өдөр','hole':'X','waterUsageM3':None}]}

    def test_authoritative_slots_replace_old_daily_allocation_and_are_idempotent(self):
        original=copy.deepcopy(self.data)
        result=apply_corrections(self.data,self.config)
        fuel=result['finance']['fuel']
        self.assertEqual(sum(r['litres'] for r in fuel['daily']),700)
        self.assertEqual(sum(r['cost'] for r in fuel['allocations']),700*5400)
        self.assertEqual(fuel['coverage'][0]['recordedShifts'],2)
        self.assertEqual(len([r for r in fuel['allocations'] if r['date']=='2026-10-23']),2)
        validate_fuel(fuel,'2026-10')
        self.assertEqual(result,apply_corrections(result,self.config))
        self.assertEqual(self.data,original)
        self.assertTrue(result['shifts'][0]['waterUsageEstimated'])

    def test_measured_water_and_deliberate_zero_preserved(self):
        for measured in [0,2.5]:
            self.data['shifts'][0]['waterUsageM3']=measured
            result=apply_corrections(self.data,self.config)
            self.assertEqual(result['shifts'][0]['waterUsageM3'],measured)
            self.assertNotIn('waterUsageEstimated',result['shifts'][0])

    def test_future_month_excludes_prior_month_entries(self):
        self.data['finance']['period']='2026-11'
        result=apply_corrections(self.data,self.config)
        self.assertEqual(result['finance']['water']['records'],[])
        self.assertEqual(result['finance']['fuel']['coverage'],[])

    def test_sheet_parser_obeys_status_and_editable_assumptions(self):
        sheets=[('fuel',[['Үнэ ₮/л','6000'],['Огноо','Өрөм','Ээлж','Олгосон түлш (л)','Төлөв'],
                        ['46318','C-1800','Өдөр','100','Баталгаатай'],
                        ['46319','Усны машин','Өдөр','200','Хассан']]),
                ('water',[['Литр / рейс (таамаг)','4000'],['Огноо','Өрөм','Ээлж','Цооног','Рейс','Тооцоот ус (л)','Төлөв'],
                          ['2026-10-23','C-1800','Өдөр','X','2','8000','Таамаг']])]
        config=parse_corrections(sheets)
        self.assertEqual(config['pricePerLitre'],6000)
        self.assertEqual(len(config['fuelIssues']),1)
        result=apply_corrections(self.data,config)
        self.assertEqual(result['finance']['water']['records'][0]['litres'],8000)
        self.assertEqual(result['finance']['fuel']['daily'][-1]['cost'],600000)

    def test_duplicate_keys_and_non_drilling_equipment_rejected(self):
        self.config['fuelIssues'].append(dict(self.config['fuelIssues'][0]))
        with self.assertRaisesRegex(ValueError,'Duplicate'):
            validate_config(self.config)
        self.config['fuelIssues'].pop()
        self.config['fuelIssues'][0]['rig']='Усны машин'
        with self.assertRaisesRegex(ValueError,'invalid'):
            validate_config(self.config)

    def test_verified_photo_snapshot(self):
        config=load_corrections()
        self.assertEqual(len(config['fuelIssues']),32)
        self.assertAlmostEqual(sum(r['litres'] for r in config['fuelIssues']),4093.23)
        self.assertEqual(sum(r['trips'] for r in config['waterTrips']),5)


if __name__=='__main__':
    unittest.main()
