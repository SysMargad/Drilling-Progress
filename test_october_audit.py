"""October 2026 audit of the published data: the critical cases checked against the Drive sources on 2026-11-05,
updated on 2026-11-06 after the owner entered eight missing reports and confirmed two rigs.

These assertions describe the sources as they were audited. When a missing report is later added to Drive
(e.g. C-1800 on 2026-10-18 day), the expectation here changes on purpose; this module is therefore run by
hand and in review, not by the scheduled Drive sync (test_shift_audit holds the invariants that always apply).
"""
import json
import unittest
from pathlib import Path

from drilling_sync import correct_holes
from shift_audit import build_audit, load_confirmations, load_foreman_reports

ROOT = Path(__file__).resolve().parent
DATA = json.loads((ROOT / 'dist' / 'data.json').read_text(encoding='utf-8'))
# The sync files the owner's hole corrections (2026-11-05) as it reads the sheets; a published row already
# under its corrected hole is left as it is.
correct_holes(DATA['shifts'], load_confirmations()['holes'])
# Later reports (e.g. the first UGDH2601 shift on 1 November) decide October's last slots, so audit through the data.
AUDIT = build_audit(DATA, ('C-1800', 'CSD-1300'), max(s['date'] for s in DATA['shifts']), load_confirmations(), load_foreman_reports())


def slot(rig, day, name):
    return next(s for s in AUDIT['slots'] if (s['rig'], s['date'], s['shift']) == (rig, f'2026-10-{day:02d}', name))


def texts(s):
    return ' | '.join(i['text'] for i in s['issues'])


class OctoberAuditTests(unittest.TestCase):
    def test_calendar_has_124_rig_shift_slots(self):
        october = AUDIT['months'][0]
        self.assertEqual(october['month'], '2026-10')
        self.assertEqual(october['expected'], 124)
        self.assertEqual(sum(october['counts'].values()), 124)

    def test_zhdh2601_c1800_starts_on_1_october_with_its_reports(self):
        for name, (top, bottom) in (('Өдөр', (0, 15)), ('Шөнө', (15, 45))):
            s = slot('C-1800', 1, name)
            self.assertEqual(s['status'], 'VERIFIED_DRILLING')
            self.assertEqual([(r['hole'], r['from'], r['to']) for r in s['records']], [('ZHDH2601', top, bottom)])
            self.assertTrue(s['records'][0]['reports'])

    def test_c1800_moves_from_zhdh2601_to_dtdh2603_on_10_october(self):
        closing, opening = slot('C-1800', 10, 'Өдөр'), slot('C-1800', 10, 'Шөнө')
        self.assertEqual(closing['meters'], 0)
        self.assertIn('374 м, collar-ын эцсийн гүн 377 м', texts(closing))
        self.assertEqual(opening['status'], 'VERIFIED_DRILLING')
        self.assertEqual([(r['hole'], r['from'], r['to']) for r in opening['records']], [('DTDH2603', 0, 11)])

    def test_csd1300_has_no_report_before_5_october(self):
        for day in range(1, 5):
            for name in ('Өдөр', 'Шөнө'):
                s = slot('CSD-1300', day, name)
                self.assertEqual((s['status'], s['meters']), ('UNVERIFIED', None))
        self.assertEqual(slot('CSD-1300', 5, 'Өдөр')['records'][0]['hole'], 'DTDH2602')

    def test_dtdh2603_night_of_14_october_is_reported_under_15_october(self):
        self.assertEqual(slot('C-1800', 14, 'Шөнө')['status'], 'MISSING_REPORT')
        self.assertEqual(slot('C-1800', 15, 'Шөнө')['status'], 'SOURCE_CONFLICT')
        self.assertIn('нэг ээлжээр зөрсөн', texts(slot('C-1800', 15, 'Шөнө')))

    def test_zhdh2612_and_c1800_dtdh2602_rows_are_zhdh2602_by_owner_decision(self):
        # 2026-11-05: the ZHDH2612 rows (16-17 Oct) and the C-1800 DTDH2602 row (18 Oct night) are ZHDH2602.
        for day, name, sheet_hole in ((16, 'Шөнө', 'ZHDH2612'), (17, 'Өдөр', 'ZHDH2612'), (17, 'Шөнө', 'ZHDH2612'), (18, 'Шөнө', 'DTDH2602')):
            s = slot('C-1800', day, name)
            self.assertEqual([r['hole'] for r in s['records']], ['ZHDH2602'])
            self.assertIn(f'эх хүснэгтэд {sheet_hole} → ZHDH2602', texts(s))
            self.assertNotEqual(s['status'], 'SOURCE_CONFLICT')
        # 2026-11-06: the 0-74 m row (rig "Баталгаажаагүй") is C-1800's; 74-110 and 221-266 m came in.
        start = slot('C-1800', 15, 'Өдөр')
        self.assertIn(('ZHDH2602', 0, 74), [(r['hole'], r['from'], r['to']) for r in start['records']])
        self.assertIn('Өрөм засагдсан: эх хүснэгтэд «Баталгаажаагүй» → C-1800', texts(start))
        for day, depths in ((16, (74, 110)), (18, (221, 266))):
            self.assertEqual([(r['hole'], r['from'], r['to']) for r in slot('C-1800', day, 'Өдөр')['records']], [('ZHDH2602', *depths)])
        self.assertNotIn('0–266', texts(slot('C-1800', 19, 'Өдөр')))
        self.assertFalse(any(r['hole'] == 'ZHDH2612' for s in AUDIT['slots'] for r in s['records']))

    def test_18_october_day_shifts_were_reported_on_6_november(self):
        for rig, hole, depths in (('C-1800', 'ZHDH2602', (221, 266)), ('CSD-1300', 'DTDH2606', (107.4, 134.4))):
            s = slot(rig, 18, 'Өдөр')
            self.assertEqual((s['status'], [(r['hole'], r['from'], r['to']) for r in s['records']]), ('VERIFIED_DRILLING', [(hole, *depths)]))

    def test_dtdh2605_15_october_parts_join_and_16_october_is_reported(self):
        # The 08-14 and 14-20 forms of 15 Oct day are one shift: 59.4-107.4 m (18 + 30 m).
        day = slot('CSD-1300', 15, 'Өдөр')
        self.assertEqual((day['status'], [(r['from'], r['to'], r['meters']) for r in day['records']], day['inferred']),
                         ('VERIFIED_DRILLING', [(59.4, 107.4, 48)], []))
        self.assertEqual(len(day['records'][0]['reports']), 2)
        # 16 Oct starts at 158.4 m, the night before ended at 158 m: the 0.4 m stays a conflict to check.
        later = slot('CSD-1300', 16, 'Өдөр')
        self.assertEqual([(r['from'], r['to']) for r in later['records']], [(158.4, 200.4)])
        self.assertIn('158–158.4 м (0.4 м) тайлангүй', texts(later))

    def test_zhdh2604_night_of_29_october_and_the_gaps_after_it(self):
        night = slot('C-1800', 29, 'Шөнө')
        self.assertEqual([(r['hole'], r['from'], r['to']) for r in night['records']], [('ZHDH2604', 395, 428)])
        self.assertEqual([(r['from'], r['to']) for r in slot('C-1800', 30, 'Өдөр')['records']], [(428, 431)])
        self.assertEqual(slot('C-1800', 31, 'Шөнө')['status'], 'MISSING_REPORT')

    def test_zhdh2604_reports_of_30_and_31_october_received_by_the_owner(self):
        # 2026-11-05: the 30 Oct night (ffff5.jpg) and 31 Oct day (ffff6.jpg) reports reached the owner; on 2026-11-06
        # their photos are in Drive too. Depth runs 428 -> 431 -> 446 -> 461 m; the 31 Oct night is still without one.
        chain = [slot('C-1800', 30, 'Шөнө'), slot('C-1800', 31, 'Өдөр')]
        self.assertEqual([(r['from'], r['to'], bool(r['reports'])) for s in chain for r in s['records']], [(431, 446, True), (446, 461, True)])
        self.assertEqual([s['status'] for s in chain], ['VERIFIED_DRILLING'] * 2)
        self.assertIn('Эзэмшигч баталгаажуулсан эх тайлан: ZHDH2604 446–461 м (ffff6.jpg)', texts(chain[1]))
        # The tab without times takes ST 3, DT 6.5 from the tab that states them.
        self.assertEqual([(s['st'], s['dt'], s['hours']) for s in DATA['shifts'] if (s['rig'], s['date'], s['shift'], s['hole'])
                          == ('C-1800', '2026-10-31', 'Өдөр', 'ZHDH2604')], [(3, 6.5, 12)])
        self.assertIn('ZHDH2604: 461–500 м (39 м) тайлангүй', texts(slot('C-1800', 31, 'Шөнө')))

    def test_csd1300_end_of_month_move_and_ugdh2601_start(self):
        for day, name in ((29, 'Шөнө'), (30, 'Өдөр'), (30, 'Шөнө')):
            self.assertIn('нүүлт байж болзошгүй', texts(slot('CSD-1300', day, name)))
        # UGDH2601 starts on 31 Oct; the day form says "C-1600", the owner confirmed CSD-1300 (2026-11-06).
        day, night = slot('CSD-1300', 31, 'Өдөр'), slot('CSD-1300', 31, 'Шөнө')
        self.assertEqual([(r['hole'], r['from'], r['to']) for s in (day, night) for r in s['records']], [('UGDH2601', 0, 8.4), ('UGDH2601', 8.4, 38.4)])
        self.assertIn('эх хүснэгтэд «C-1600» → CSD-1300', texts(day))
        self.assertFalse(any(r['hole'] == 'UGDH2601' for r in slot('C-1800', 31, 'Өдөр')['records']))

    def test_metres_inferred_from_depth_for_unreported_shifts(self):
        exact = [(s['rig'], s['date'][5:], s['shift'], i['hole'], i['from'], i['to']) for s in AUDIT['slots']
                 if s['date'].startswith('2026-10') for i in s['inferred'] if i['exact']]
        # After the 2026-11-06 reports only one October gap is pinned to a shift.
        self.assertEqual(exact, [('CSD-1300', '10-24', 'Шөнө', 'ZHDH2605', 0, 26.4)])
        october = AUDIT['months'][0]
        self.assertEqual(october['inferredMeters'], 26.4)
        # The owner kept the 15 Oct night report's date (2026-11-05), so the gap it fills on 14 Oct is not inferred.
        self.assertEqual(slot('C-1800', 14, 'Шөнө')['inferred'], [], 'the 15 Oct night report fills it')
        self.assertEqual([(u['hole'], u['meters'], u['shifts'], u['inMonth']) for u in october['unallocated']],
                         [('ZHDH2604', 39, 2, 1)])

    def test_zhdh2603_reports_overlap_by_one_metre(self):
        for day, name in ((19, 'Шөнө'), (20, 'Өдөр')):
            self.assertIn('59.4–60.4 м давхардсан', texts(slot('CSD-1300', day, name)))


class ForemanReportTests(unittest.TestCase):
    """The drilling foreman's October metre report (ммм1_1.xlsx, received 2026-11-05) against the shift reports."""
    report, = AUDIT['foreman']
    rows = {(r['rig'], r['hole']): r for r in report['rows']}

    def test_rig_totals_are_the_foremans_and_the_dashboards(self):
        self.assertEqual(self.report['rigs'], [{'rig': 'C-1800', 'foreman': 1552.7, 'reported': 1582.7},
                                               {'rig': 'CSD-1300', 'foreman': 1477.4, 'reported': 1655.0}])

    def test_c1800_drilled_zhdh2602_from_15_to_23_october(self):
        row = self.rows[('C-1800', 'ZHDH2602')]
        self.assertEqual((row['status'], row['foreman'], row['reached'], row['reported']), ('agree', 489.3, 489.3, 489.3))
        self.assertNotIn('ахлахын жагсаалтад үгүй', ' '.join(row['notes']), 'the corrected rows are ZHDH2602')

    def test_csd1300_hole_of_14_to_16_october_is_dtdh2605_in_the_shift_reports(self):
        row = self.rows[('CSD-1300', 'DTDH2603')]
        self.assertEqual((row['status'], row['reported']), ('differs', None))
        self.assertIn('DTDH2605 200 м (collar 200.4 м)', row['notes'][0])

    def test_large_differences(self):
        self.assertEqual((self.rows[('CSD-1300', 'ZHDH2606')]['foreman'], self.rows[('CSD-1300', 'ZHDH2606')]['reached']), (70, 233.4))
        self.assertEqual(self.rows[('CSD-1300', 'ZHDH2606')]['status'], 'differs')
        self.assertIn('collar-ын эцсийн гүнтэй (377 м)', ' '.join(self.rows[('C-1800', 'ZHDH2601')]['notes']))
        zhdh2604 = self.rows[('C-1800', 'ZHDH2604')]
        self.assertEqual(zhdh2604['holeText'], '')
        self.assertIn('2026-10-29 Шөнө-ийн гүнээр (428 м) тасарсан', ' '.join(zhdh2604['notes']))

    def test_whole_metre_rows(self):
        self.assertEqual([r['hole'] for r in self.report['rows'] if r['status'] == 'rounded'], ['DTDH2602', 'DTDH2601', 'ZHDH2603'])


if __name__ == '__main__':
    unittest.main()
