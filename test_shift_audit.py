import io
import json
import tempfile
import unittest
import zipfile
from datetime import datetime, timezone
from pathlib import Path

from drilling_sync import (assemble, attach_reports, canonical_rig, daily_file, date, hole_id, parse_shifts,
                           shift_changes, ulaanbaatar_date, workbook_rows)
from shift_audit import STATUSES, build_audit, foreman_check, load_confirmations, load_foreman_reports
from validate_data import validate

ROOT = Path(__file__).resolve().parent
RIGS = ('C-1800', 'CSD-1300')
REPORT = [{'name': 'r.jpg', 'url': 'https://drive.google.com/file/d/r/view'}]


def shift(rig, day, name, hole, start, end, **extra):
    return {'rig': rig, 'date': day, 'shift': name, 'hole': hole, 'from': start, 'to': end,
            'meters': round(end - start, 2), 'dt': 10, 'st': None, 'rt': None, 'hours': 12, 'driller': '',
            'notes': '', 'source': f'{day}_{hole}_{name}.jpg', 'reports': REPORT, **extra}


def hole(id, start='2026-10-01', finish='', depth=None, plan=300):
    return {'id': id, 'start': start, 'finish': finish, 'collarDepth': depth, 'plan': plan}


def audit(shifts, collar, through='2026-10-31', **data):
    return build_audit({'shifts': shifts, 'collar': collar, **data}, RIGS, through)


def slot(result, rig, day, name):
    return next(s for s in result['slots'] if (s['rig'], s['date'], s['shift']) == (rig, day, name))


class ShiftAuditTests(unittest.TestCase):
    def test_expected_slots_are_days_by_shifts_by_rigs_and_counts_add_up(self):
        result = audit([shift('C-1800', '2026-10-01', 'Өдөр', 'A', 0, 10)], [hole('A')], through='2026-11-02')
        october, november = result['months']
        self.assertEqual((october['month'], october['expected']), ('2026-10', 124))
        self.assertEqual((november['month'], november['expected']), ('2026-11', 8))
        for month in result['months']:
            self.assertEqual(sum(month['counts'].values()), month['expected'])
            self.assertEqual(set(month['counts']), set(STATUSES))

    def test_missing_report_is_never_zero_metres(self):
        result = audit([shift('C-1800', '2026-10-01', 'Өдөр', 'A', 0, 30),
                        shift('C-1800', '2026-10-02', 'Өдөр', 'A', 60, 90),
                        shift('C-1800', '2026-10-02', 'Шөнө', 'A', 90, 90)], [hole('A')])
        gap = slot(result, 'C-1800', '2026-10-01', 'Шөнө')
        self.assertEqual((gap['status'], gap['meters']), ('MISSING_REPORT', None))
        self.assertIn('A: 30–60 м (30 м) тайлангүй', gap['issues'][0]['text'])
        zero = slot(result, 'C-1800', '2026-10-02', 'Шөнө')
        self.assertEqual((zero['status'], zero['meters']), ('VERIFIED_NON_DRILLING', 0))
        self.assertEqual(result['months'][0]['missingMeters'], 30)
        self.assertTrue(all(s['meters'] is None for s in result['slots'] if not s['records']))

    def test_metres_of_an_unreported_shift_are_inferred_from_the_depths_around_it(self):
        shifts = [shift('C-1800', '2026-10-01', 'Өдөр', 'A', 0, 30), shift('C-1800', '2026-10-02', 'Өдөр', 'A', 72, 100),
                  shift('C-1800', '2026-10-02', 'Шөнө', 'A', 100, 150),
                  shift('CSD-1300', '2026-10-01', 'Өдөр', 'B', 0, 10, hours=6), shift('CSD-1300', '2026-10-01', 'Шөнө', 'B', 25, 40)]
        result = audit(shifts, [hole('A'), hole('B')])
        night = slot(result, 'C-1800', '2026-10-01', 'Шөнө')
        self.assertEqual((night['status'], night['meters']), ('MISSING_REPORT', None), 'inferred metres are never a report')
        self.assertEqual([(i['from'], i['to'], i['meters'], i['exact']) for i in night['inferred']], [(30, 72, 42, True)])
        partial = slot(result, 'CSD-1300', '2026-10-01', 'Өдөр')
        self.assertEqual((partial['status'], partial['meters']), ('MISSING_REPORT', 10))
        self.assertEqual([(i['from'], i['to'], i['exact']) for i in partial['inferred']], [(10, 25, True)], 'the rest of a part-shift report')
        self.assertEqual(result['months'][0]['inferredMeters'], 42 + 15)
        self.assertTrue(all(s['status'] == 'MISSING_REPORT' for s in result['slots'] if s['inferred']))

    def test_inferred_metres_are_not_pinned_when_they_cannot_be(self):
        shifts = [shift('C-1800', '2026-10-01', 'Өдөр', 'A', 0, 30), shift('C-1800', '2026-10-03', 'Өдөр', 'A', 90, 120),
                  shift('C-1800', '2026-10-04', 'Өдөр', 'A', 120, 150), shift('C-1800', '2026-10-05', 'Өдөр', 'A', 260, 270),
                  shift('C-1800', '2026-10-31', 'Өдөр', 'A', 270, 280), shift('C-1800', '2026-11-01', 'Шөнө', 'A', 300, 310),
                  shift('CSD-1300', '2026-10-14', 'Өдөр', 'B', 203, 248), shift('CSD-1300', '2026-10-15', 'Өдөр', 'B', 257, 258.4, hours=6),
                  shift('CSD-1300', '2026-10-15', 'Шөнө', 'B', 248, 257)]
        result = audit(shifts, [hole('A'), hole('B')], through='2026-11-02')
        across = slot(result, 'C-1800', '2026-10-01', 'Шөнө')['inferred'][0]
        self.assertEqual((across['meters'], across['exact'], across['shifts']), (60, False, 3), 'a gap over three shifts is known in total only')
        too_much = slot(result, 'C-1800', '2026-10-04', 'Шөнө')['inferred'][0]
        self.assertEqual((too_much['meters'], too_much['exact']), (110, False))
        self.assertIn('нэг ээлжид багтахгүй', too_much['note'])
        october, november = result['months']
        self.assertEqual(october['inferredMeters'], 0)
        self.assertIn({'rig': 'C-1800', 'hole': 'A', 'from': 280, 'to': 300, 'meters': 20, 'shifts': 2, 'inMonth': 1}, october['unallocated'])
        self.assertIn({'rig': 'C-1800', 'hole': 'A', 'from': 280, 'to': 300, 'meters': 20, 'shifts': 2, 'inMonth': 1}, november['unallocated'])
        late = slot(result, 'CSD-1300', '2026-10-14', 'Шөнө')
        self.assertEqual((late['status'], late['inferred']), ('MISSING_REPORT', []), 'a report dated a shift late fills the gap; not inferred twice')

    def test_open_hole_without_report_is_missing_but_a_rig_move_is_only_unverified(self):
        shifts = [shift('C-1800', '2026-10-01', 'Өдөр', 'A', 0, 30), shift('C-1800', '2026-10-02', 'Өдөр', 'A', 30, 60),
                  shift('C-1800', '2026-10-03', 'Өдөр', 'B', 0, 20)]
        result = audit(shifts, [hole('A', finish='2026-10-02', depth=60), hole('B')])
        self.assertEqual(slot(result, 'C-1800', '2026-10-01', 'Шөнө')['status'], 'MISSING_REPORT')
        move = slot(result, 'C-1800', '2026-10-02', 'Шөнө')
        self.assertEqual(move['status'], 'UNVERIFIED')
        self.assertIn('нүүлт байж болзошгүй', move['issues'][0]['text'])
        before = slot(result, 'CSD-1300', '2026-10-01', 'Өдөр')
        self.assertEqual(before['status'], 'UNVERIFIED')

    def test_owner_confirmation_verifies_non_drilling_but_cannot_hide_missing_metres(self):
        shifts = [shift('C-1800', '2026-10-01', 'Өдөр', 'A', 0, 30), shift('C-1800', '2026-10-02', 'Өдөр', 'A', 40, 60)]
        confirm = lambda day, name: {'rig': 'C-1800', 'date': day, 'shift': name, 'status': 'VERIFIED_NON_DRILLING',
                                     'reason': 'Өрөм засвар', 'evidence': 'WhatsApp зураг', 'confirmedBy': 'Owner', 'confirmedAt': '2026-11-05'}
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'shift-audit.json'
            path.write_text(json.dumps({'confirmed': [confirm('2026-10-01', 'Шөнө'), confirm('2026-10-03', 'Өдөр')]}), encoding='utf-8')
            confirmations = load_confirmations(path)
            path.write_text(json.dumps({'confirmed': [{**confirm('2026-10-01', 'Шөнө'), 'evidence': ''}]}), encoding='utf-8')
            with self.assertRaisesRegex(ValueError, 'evidence'):
                load_confirmations(path)
        result = build_audit({'shifts': shifts, 'collar': [hole('A')]}, RIGS, '2026-10-31', confirmations)
        hidden = slot(result, 'C-1800', '2026-10-01', 'Шөнө')
        self.assertEqual(hidden['status'], 'MISSING_REPORT', 'the 30–40 m without a report stays missing')
        self.assertTrue(any('зөрчилдөж' in i['text'] for i in hidden['issues']))
        # Hole A is open at 60 m, so an unreported shift is a missing report unless the owner says what happened.
        self.assertEqual(slot(result, 'C-1800', '2026-10-04', 'Өдөр')['status'], 'MISSING_REPORT')
        confirmed = slot(result, 'C-1800', '2026-10-03', 'Өдөр')
        self.assertEqual(confirmed['status'], 'VERIFIED_NON_DRILLING')
        self.assertIn('WhatsApp зураг (Owner, 2026-11-05)', confirmed['issues'][0]['text'])

    def test_report_received_by_the_owner_verifies_a_row_only_at_the_same_depths(self):
        report = lambda day, name, start, end, source: {'rig': 'C-1800', 'date': day, 'shift': name, 'hole': 'A', 'from': start, 'to': end,
                                                        'source': source, 'evidence': 'Зураг эзэмшигчид ирсэн', 'confirmedBy': 'Owner', 'confirmedAt': '2026-11-05'}
        shifts = [shift('C-1800', '2026-10-29', 'Шөнө', 'A', 395, 428), shift('C-1800', '2026-10-30', 'Шөнө', 'A', 431, 446, reports=[], source='ffff5.jpg'),
                  shift('C-1800', '2026-10-31', 'Өдөр', 'A', 446, 461, reports=[], source='ffff6.jpg'),
                  shift('C-1800', '2026-10-31', 'Шөнө', 'A', 461, 470, reports=[], source='ffff7.jpg')]
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'shift-audit.json'
            path.write_text(json.dumps({'reports': [report('2026-10-30', 'Шөнө', 431, 446, 'ffff5.jpg'), report('2026-10-31', 'Өдөр', 446, 461, 'ffff6.jpg'),
                                                    report('2026-10-31', 'Шөнө', 461, 475, 'ffff7.jpg'), report('2026-10-30', 'Өдөр', 428, 431, 'ffff4.jpg')]}), encoding='utf-8')
            confirmations = load_confirmations(path)
            path.write_text(json.dumps({'reports': [{**report('2026-10-30', 'Шөнө', 431, 446, 'x'), 'to': None}]}), encoding='utf-8')
            with self.assertRaisesRegex(ValueError, 'depths'):
                load_confirmations(path)
        result = build_audit({'shifts': shifts, 'collar': [hole('A')]}, RIGS, '2026-10-31', confirmations)
        for day, name in (('2026-10-30', 'Шөнө'), ('2026-10-31', 'Өдөр')):
            confirmed = slot(result, 'C-1800', day, name)
            self.assertEqual((confirmed['status'], confirmed['records'][0]['evidence']), ('VERIFIED_DRILLING', 'owner'))
        self.assertIn('хүснэгтэд 461–470 м', ' '.join(i['text'] for i in slot(result, 'C-1800', '2026-10-31', 'Шөнө')['issues']))
        self.assertEqual(slot(result, 'C-1800', '2026-10-31', 'Шөнө')['status'], 'SOURCE_CONFLICT')
        received = slot(result, 'C-1800', '2026-10-30', 'Өдөр')
        self.assertEqual((received['status'], received['meters']), ('MISSING_REPORT', None), 'a report never becomes metres without its sheet row')
        self.assertTrue(any('хүснэгтэд мөр алга' in i['text'] for i in received['issues']))

    def test_foreman_monthly_report_is_checked_hole_by_hole(self):
        shifts = [shift('C-1800', '2026-10-01', 'Өдөр', 'A', 0, 30), shift('C-1800', '2026-10-01', 'Шөнө', 'A', 30, 60),
                  shift('C-1800', '2026-10-02', 'Өдөр', 'B', 100, 150), shift('C-1800', '2026-10-02', 'Шөнө', 'X', 0, 20),
                  shift('C-1800', '2026-10-03', 'Өдөр', 'C', 0, 25), shift('C-1800', '2026-10-03', 'Шөнө', 'C', 25, 40),
                  shift('CSD-1300', '2026-10-01', 'Өдөр', 'D', 0, 50.4), shift('CSD-1300', '2026-10-02', 'Өдөр', 'E', 0, 10)]
        collar = {h['id']: h for h in (hole('A', finish='2026-10-01', depth=61), hole('B', finish='2026-10-02', depth=150), hole('C'),
                                         hole('D', finish='2026-10-01', depth=50.4), hole('E'), hole('F'))}
        row = lambda rig, hole_id, start, finish, metres: {'rig': rig, 'hole': hole_id, 'start': start, 'finish': finish, 'metres': metres, 'row': 5, 'raw': 'x'}
        report = {'month': '2026-10', 'title': 'T', 'from': 'Өрмийн ахлах', 'file': 'f.xlsx', 'received': '2026-11-05', 'totals': {'C-1800': 210},
                  'rows': [row('C-1800', 'A', '', '2026-10-01', 61), row('C-1800', 'B', '2026-10-02', '2026-10-02', 150),
                           row('C-1800', '', '2026-10-03', '', 25), row('CSD-1300', 'D', '', '2026-10-01', 50),
                           row('CSD-1300', 'F', '2026-10-02', '2026-10-02', 10)]}
        check = foreman_check(report, shifts, collar)
        a, b, c, d, f = check['rows']
        self.assertEqual((a['status'], a['reached']), ('differs', 60))
        self.assertIn('collar-ын эцсийн гүнтэй (61 м) таарч', ' '.join(a['notes']))
        self.assertEqual((b['status'], b['reported'], b['reached']), ('agree', 50, 150), 'the foreman agrees on depth; the shift reports miss 100 m')
        self.assertIn('тайлангүй интервал', ' '.join(b['notes']))
        self.assertEqual((c['hole'], c['holeText']), ('C', ''), 'a row without a hole takes the hole the rig collared that day')
        self.assertIn('2026-10-03 Өдөр-ийн гүнээр (25 м) тасарсан; ээлжийн тайлангаар 40 м', ' '.join(c['notes']))
        self.assertEqual(d['status'], 'rounded')
        self.assertEqual((f['status'], f['reported']), ('differs', None))
        self.assertIn('тайланд: E 10 м', ' '.join(f['notes']))
        self.assertEqual(check['rigs'], [{'rig': 'C-1800', 'foreman': 210, 'reported': 170}, {'rig': 'CSD-1300', 'foreman': None, 'reported': 60.4}])
        report['rows'] = report['rows'][1:2] + [row('C-1800', 'C', '2026-10-01', '2026-10-03', 40)]
        self.assertIn('ахлахын жагсаалтад үгүй цооногийн тайлан: X 20 м', ' '.join(foreman_check(report, shifts, collar)['rows'][1]['notes']))
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'foreman.json'
            path.write_text(json.dumps({'reports': [{**report, 'rows': [{**row('C-1800', 'A', '', '', 61), 'raw': ''}]}]}), encoding='utf-8')
            with self.assertRaisesRegex(ValueError, 'source cells'):
                load_foreman_reports(path)
        result = build_audit({'shifts': shifts, 'collar': list(collar.values())}, RIGS, '2026-10-31', None, [report])
        self.assertEqual(len(result['foreman']), 1)

    def test_hole_change_within_a_shift_is_a_transition_not_an_error(self):
        result = audit([shift('C-1800', '2026-10-10', 'Өдөр', 'A', 370, 374), shift('C-1800', '2026-10-10', 'Өдөр', 'B', 0, 5)],
                       [hole('A', start='2026-09-27', finish='2026-10-10', depth=374), hole('B', start='2026-10-10')])
        changed = slot(result, 'C-1800', '2026-10-10', 'Өдөр')
        self.assertEqual(changed['status'], 'VERIFIED_DRILLING')
        self.assertEqual(changed['meters'], 9)
        self.assertIn('A → B', next(i['text'] for i in changed['issues'] if i['kind'] == 'transition'))

    def test_overlaps_and_a_report_dated_one_shift_late(self):
        result = audit([shift('CSD-1300', '2026-10-19', 'Шөнө', 'A', 14.4, 60.4), shift('CSD-1300', '2026-10-20', 'Өдөр', 'A', 59.4, 107.4),
                        shift('C-1800', '2026-10-14', 'Өдөр', 'B', 203, 248), shift('C-1800', '2026-10-15', 'Өдөр', 'B', 257, 258.4, hours=6),
                        shift('C-1800', '2026-10-15', 'Шөнө', 'B', 248, 257)],
                       [hole('A', start='2026-10-19'), hole('B')])
        for day, name in (('2026-10-19', 'Шөнө'), ('2026-10-20', 'Өдөр')):
            self.assertEqual(slot(result, 'CSD-1300', day, name)['status'], 'SOURCE_CONFLICT')
        self.assertEqual(slot(result, 'C-1800', '2026-10-14', 'Шөнө')['status'], 'MISSING_REPORT')
        late = slot(result, 'C-1800', '2026-10-15', 'Шөнө')
        self.assertEqual(late['status'], 'SOURCE_CONFLICT')
        self.assertTrue(any('нэг ээлжээр зөрсөн' in i['text'] for i in late['issues']))

    def test_evidence_decides_verified(self):
        result = audit([shift('C-1800', '2026-10-01', 'Өдөр', 'A', 0, 10, reports=[]),
                        shift('C-1800', '2026-10-01', 'Шөнө', 'A', 10, 20, reports=[], source=''),
                        shift('C-1800', '2026-10-02', 'Өдөр', 'A', 20, 30, reports=[], source='', origin='photo-records'),
                        shift('C-1800', '2026-10-02', 'Шөнө', 'A', 30, 40, source='2026-10-02_A_n_DATE_CHECK.jpg')], [hole('A')])
        self.assertEqual(slot(result, 'C-1800', '2026-10-01', 'Өдөр')['status'], 'UNVERIFIED')
        self.assertIn('эх файлын нэр алга', slot(result, 'C-1800', '2026-10-01', 'Шөнө')['issues'][0]['text'])
        self.assertEqual(slot(result, 'C-1800', '2026-10-02', 'Өдөр')['status'], 'VERIFIED_DRILLING')
        self.assertEqual(slot(result, 'C-1800', '2026-10-02', 'Шөнө')['status'], 'UNVERIFIED')

    def test_hole_outside_its_collar_window_or_unregistered_is_a_conflict(self):
        result = audit([shift('C-1800', '2026-10-18', 'Шөнө', 'A', 266, 266), shift('C-1800', '2026-10-16', 'Шөнө', 'X', 0, 45)],
                       [hole('A', start='2026-10-04', finish='2026-10-10', depth=300), {'id': 'X', 'start': '', 'finish': '', 'collarDepth': None, 'plan': None}])
        self.assertIn('2026-10-10-нд дууссан', ' '.join(i['text'] for i in slot(result, 'C-1800', '2026-10-18', 'Шөнө')['issues']))
        self.assertEqual(slot(result, 'C-1800', '2026-10-16', 'Шөнө')['status'], 'SOURCE_CONFLICT')

    def test_collar_depth_beyond_the_last_report(self):
        result = audit([shift('C-1800', '2026-10-09', 'Өдөр', 'A', 359, 374), shift('C-1800', '2026-10-10', 'Өдөр', 'A', 374, 374),
                        shift('C-1800', '2026-10-10', 'Шөнө', 'B', 0, 11)],
                       [hole('A', finish='2026-10-10', depth=377), hole('B', start='2026-10-10')])
        closing = slot(result, 'C-1800', '2026-10-10', 'Өдөр')
        self.assertEqual(closing['status'], 'SOURCE_CONFLICT')
        self.assertIn('374 м, collar-ын эцсийн гүн 377 м', closing['issues'][0]['text'])

    def test_rows_without_a_known_rig_and_rejected_rows_reach_the_audit(self):
        data = {'shifts': [shift('C-1800', '2026-10-15', 'Өдөр', 'A', 0, 10)], 'collar': [hole('A')],
                'unassignedShifts': [{'rigText': 'Баталгаажаагүй', 'date': '2026-10-15', 'shift': 'Өдөр', 'hole': 'X', 'from': 0,
                                      'to': 74, 'meters': 74, 'source': 'x.jpg', 'row': 51, 'sheet': 'S', 'tab': 'T', 'url': ''}],
                'rejectedShifts': [{'rig': 'CSD-1300', 'date': '2026-10-16', 'shift': 'Шөнө', 'hole': 'Y', 'row': 7,
                                    'reason': 'Missing/invalid dt for Y on 2026-10-16', 'sheet': 'S', 'tab': 'T', 'url': ''}],
                'sourceConflicts': [{'rig': 'C-1800', 'date': '2026-10-15', 'shift': 'Өдөр', 'hole': 'A', 'kept': 'S / T мөр 3',
                                     'fields': {'to': [10, 12]}, 'others': ['S2 / T мөр 4']}]}
        result = build_audit(data, RIGS, '2026-10-31')
        both = [slot(result, rig, '2026-10-15', 'Өдөр') for rig in RIGS]
        self.assertTrue(all(any('Баталгаажаагүй' in i['text'] for i in s['issues']) for s in both))
        self.assertEqual(both[0]['status'], 'SOURCE_CONFLICT')
        rejected = slot(result, 'CSD-1300', '2026-10-16', 'Шөнө')
        self.assertEqual(rejected['status'], 'SOURCE_CONFLICT')
        self.assertIn('мөр 7', rejected['issues'][0]['text'])


SHIFT_HEADER = ['Rig', 'Source', 'Date', 'Shift', 'Driller', 'Hole ID', 'From', 'To', 'Drilled', 'ST', 'RT', 'DT', 'Total', 'Work notes']
COLLAR_HEADER = ['Hole ID', 'Plan Depth (m)', 'Drilled Depth (m)', 'Started Date', 'Finished Date']


def csv_source(name, rows, modified):
    text = '\n'.join(','.join(map(str, row)) for row in rows)
    return {'name': name, 'url': f'https://docs.google.com/spreadsheets/d/{name}', 'modified': modified,
            'content': text.encode('utf-8'), 'suffix': '.csv'}


class SourceReconciliationTests(unittest.TestCase):
    seed = {'driveUrl': 'https://drive.google.com/drive/folders/root', 'shifts': []}

    def test_identifiers_dates_and_shift_names_are_normalised(self):
        self.assertEqual(canonical_rig(' C-1600 '), 'C-1800')
        self.assertEqual(canonical_rig('CSD-1300'), 'CSD-1300')
        self.assertEqual([hole_id(v) for v in ('ZHDH-2601', 'zhdh2601 ', 'ZH-2601')], ['ZHDH2601', 'ZHDH2601', None])
        self.assertEqual([date(v) for v in ('2026-10-01T08:00', '46296', '2026.10.01', '01/10/2026')], ['2026-10-01'] * 4)
        with self.assertRaisesRegex(ValueError, 'Missing/invalid date or shift'):
            parse_shifts([SHIFT_HEADER, ['C-1800', 'a', '2026-10-01', 'Day', '', 'ZHDH2601', 0, 10, 10, '', '', 10, 12, '']])
        night = parse_shifts([SHIFT_HEADER, ['C-1800', 'a', '2026-10-01', ' Шөнө ', '', 'ZHDH2601', 0, 10, 10, '', '', 10, 12, '']])
        self.assertEqual([r['shift'] for r in night], ['Шөнө'])

    def test_ulaanbaatar_date_crosses_midnight_before_utc(self):
        self.assertEqual(ulaanbaatar_date(datetime(2026, 10, 31, 15, 59, tzinfo=timezone.utc)), '2026-10-31')
        self.assertEqual(ulaanbaatar_date(datetime(2026, 10, 31, 16, 0, tzinfo=timezone.utc)), '2026-11-01')

    def test_duplicate_sheets_numeric_conflicts_unassigned_and_rejected_rows(self):
        collar = csv_source('collar', [COLLAR_HEADER, ['DTDH9001', 300, '', '2026-10-01', ''], ['ZHDH9612', '', '', '', '']], '1')
        row = ['C-1800', '20261001_d', '2026-10-01', 'Өдөр', 'Bat', 'DTDH-9001', 0, 15, 15, '', '', 10, 12, 'note']
        newer = csv_source('new', [SHIFT_HEADER, row, ['Баталгаажаагүй', 'x.jpg', '2026-10-15', 'Өдөр', '', 'ZHDH-9612', 0, 74, 74, '', '', '', '', ''],
                                   ['CSD-1300', 'bad', '2026-10-02', 'Шөнө', '', 'DTDH9001', 10, 20, 15, '', '', 10, 12, '']], '3')
        copy = csv_source('copy', [SHIFT_HEADER, row[:13] + ['other note']], '2')
        older = csv_source('old', [SHIFT_HEADER, row[:7] + [16, 16] + row[9:]], '1')
        data = assemble([newer, copy, older, collar], {**self.seed, 'collar': []})
        self.assertEqual(len(data['shifts']), 1, 'a duplicate report is counted once')
        self.assertEqual(data['shifts'][0]['meters'], 15)
        self.assertEqual(data['shifts'][0]['sheet'], {'name': 'new', 'tab': '1', 'row': 2, 'url': 'https://docs.google.com/spreadsheets/d/new'})
        self.assertEqual(len(data['sourceConflicts']), 1, 'a notes-only difference is not a conflict')
        self.assertEqual(data['sourceConflicts'][0]['fields'], {'to': [15, 16], 'meters': [15, 16]})
        self.assertEqual([(r['rigText'], r['hole'], r['to'], r['row']) for r in data['unassignedShifts']], [('Баталгаажаагүй', 'ZHDH9612', 74, 3)])
        self.assertEqual([(r['hole'], r['date'], r['row']) for r in data['rejectedShifts']], [('DTDH9001', '2026-10-02', 4)])
        self.assertIn('Depth/meters mismatch', data['rejectedShifts'][0]['reason'])

    def test_raw_reports_link_by_cited_file_and_uncited_reports_are_listed(self):
        def file(id, name, mime='image/jpeg'):
            return {'id': id, 'name': name, 'mimeType': mime}
        self.assertEqual(daily_file(file('a', '2026-10-16_ZHDH2612_n.jpg'), 'ZHDH2612', 'C-1800', '')['rig'], 'C-1800')
        # A report left in the hole folder itself, outside the rig sub-folder: only its cited name links it.
        named = daily_file(file('a', '2026-10-18_DTDH2602_C1800_n.jpg'), 'DTDH2602', None, 'folder')
        self.assertEqual((named['date'], named['shift'], named['rig']), ('2026-10-18', 'Шөнө', ''))
        self.assertEqual(daily_file(file('b', '20261102_d_UGDH2601_CSD-1300.jpg'), 'UGDH2601', '', '')['shift'], 'Өдөр')
        self.assertEqual(daily_file(file('c', 'DATE_REVIEW_ZHDH2604_d_95-128_alt.jpg'), 'ZHDH2604', 'C-1800', '')['date'], '')
        self.assertIsNone(daily_file(file('d', 'Drilling log', 'application/vnd.ms-excel'), 'A', 'C-1800', ''))
        copy = daily_file(file('e', '2026-10-18_DTDH2602_C1800_n.jpg'), 'DTDH2601', 'C-1800', '')
        extra = daily_file(file('f', '2026-10-15_ZHDH2612_d.jpg'), 'ZHDH2612', 'C-1800', '')
        rows = [{'hole': 'DTDH2602', 'rig': 'C-1800', 'date': '2026-10-18', 'shift': 'Шөнө', 'source': '2026-10-18_DTDH2602_C1800_n.JPG'}]
        unlinked = attach_reports(rows, [copy, named, extra])
        self.assertEqual(rows[0]['reports'][0]['url'], named['url'], "the shift's own hole folder wins")
        self.assertEqual((rows[0]['reports'][0]['match'], rows[0]['reports'][0]['rig']), ('source', 'C-1800'))
        self.assertEqual([r['name'] for r in unlinked], ['2026-10-18_DTDH2602_C1800_n.jpg', '2026-10-15_ZHDH2612_d.jpg'])

    def test_workbook_rows_keep_sheet_row_numbers_and_tab_titles(self):
        buffer = io.BytesIO()
        ns = 'xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"'
        with zipfile.ZipFile(buffer, 'w') as z:
            z.writestr('xl/workbook.xml', f'<workbook {ns} xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">'
                                          '<sheets><sheet name="2_Ээлжийн_бүртгэл" sheetId="1" r:id="rId1"/></sheets></workbook>')
            z.writestr('xl/_rels/workbook.xml.rels', '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
                                                     '<Relationship Id="rId1" Target="worksheets/sheet1.xml"/></Relationships>')
            z.writestr('xl/worksheets/sheet1.xml', f'<worksheet {ns}><sheetData><row r="1"><c r="A1" t="inlineStr"><is><t>x</t></is></c></row>'
                                                   '<row r="4"><c r="B4"><v>7</v></c></row></sheetData></worksheet>')
        (title, rows), = workbook_rows(buffer.getvalue(), '.xlsx')
        self.assertEqual(title, '2_Ээлжийн_бүртгэл')
        self.assertEqual(rows[3], ['', '7'], 'row 4 of the sheet is rows[3]')

    def test_collection_log_records_added_removed_and_changed_shifts(self):
        a, b = shift('C-1800', '2026-10-01', 'Өдөр', 'A', 0, 10), shift('C-1800', '2026-10-01', 'Шөнө', 'A', 10, 20)
        trail = shift_changes({'shifts': [a, b]}, {'shifts': [{**a, 'to': 12, 'meters': 12}, shift('CSD-1300', '2026-10-02', 'Өдөр', 'B', 0, 5)]})
        self.assertEqual(trail, {'added': ['CSD-1300 / 2026-10-02 / Өдөр / B'], 'removed': ['C-1800 / 2026-10-01 / Шөнө / A'],
                                 'changed': ['C-1800 / 2026-10-01 / Өдөр / A']})


class PublishedAuditTests(unittest.TestCase):
    """Invariants of the published dataset; they hold whatever the sources add later."""

    def test_published_audit_classifies_every_slot_without_inventing_metres(self):
        data = json.loads((ROOT / 'dist' / 'data.json').read_text(encoding='utf-8'))
        result = build_audit(data, RIGS, max(s['date'] for s in data['shifts']))
        self.assertEqual(result['months'][0]['month'], min(s['date'] for s in data['shifts'])[:7])
        for s in result['slots']:
            self.assertIn(s['status'], STATUSES)
            if not s['records']:
                self.assertIsNone(s['meters'])
            if s['status'] == 'MISSING_REPORT':
                self.assertTrue(any(i['kind'] == 'gap' for i in s['issues']))
        total = sum(sum(m['meters'].values()) for m in result['months'])
        self.assertAlmostEqual(total, sum(s['meters'] for s in data['shifts'] if s['rig'] in RIGS), places=2)
        if 'shiftAudit' in data:
            validate(data)


if __name__ == '__main__':
    unittest.main()
