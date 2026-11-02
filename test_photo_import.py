import copy
import unittest
from drilling_sync import load_json
from photo_import import PATH, apply_photos, apply_daily_water
from validate_data import validate


class PhotoImportTests(unittest.TestCase):
    def test_photos_are_idempotent_and_preserve_later_drive_records(self):
        data=load_json(PATH.parent.parent / 'dist/data.json')
        result=apply_photos(data)
        self.assertEqual(result,apply_photos(result))
        shift=next(s for s in result['shifts'] if s['date']=='2026-11-01' and s['rig']=='C-1800')
        self.assertEqual((shift['meters'],shift['dt'],shift['hours']),(3,12,12))
        shift['dt']=10
        again=apply_photos(result)
        self.assertEqual(next(s['dt'] for s in again['shifts'] if s['date']=='2026-11-01' and s['rig']=='C-1800'),10)
        self.assertEqual(next(h['targetArea'] for h in result['collar'] if h['id']=='UGDH2601'),'Уртын гол')

    def test_daily_journal_replaces_overlapping_shift_water(self):
        data=load_json(PATH.parent.parent / 'dist/data.json')
        result=apply_daily_water(data)
        water=result['finance']['water']
        self.assertEqual(sum(r['trips'] for r in water['dailyRecords']),36)
        self.assertEqual(sum(r['litres'] for r in water['dailyRecords']),180000)
        self.assertFalse(water['estimated'])
        self.assertEqual(water['records'],[])
        self.assertEqual(result,apply_daily_water(result))
        validate(result)


if __name__=='__main__':
    unittest.main()
