"""Independent logic audit (2026-11-09) of the shift chronology, depth continuity and metre attribution, run against
the real parse_shifts / assemble / build_audit with the KHDH2601 and STDH2601 depths of 7-8 November 2026.

Owner decisions of 2026-11-09 on the findings: a blank DT stays 12 h when the total is 12 h (test 09); the overview
keeps adding estimated metres and splitting multi-shift gaps evenly; a rejected row that states a depth bounds the
gap, and an owner-confirmed 0 m shift takes no gap metres (test 16).
"""
import unittest
from datetime import datetime, timedelta

from drilling_sync import assemble, parse_shifts
from shift_audit import build_audit

RIGS = ('C-1800', 'CSD-1300')
# The header of the hole sheets' 2_Ээлжийн_бүртгэл tab.
HEADER = ['Rig', 'Source', 'Date', 'Shift', 'Driller', 'Hole ID', 'From', 'To', 'Drilled', 'PT', 'DT', 'OT', 'ST', 'RT',
          'Total', 'Water consumption (m3)', 'DT source (hours)', 'Work notes', 'Source URL', 'RP (Run/Pull)']
REPORT = [{'name': 'r.pdf', 'url': 'https://drive.google.com/file/d/r/view'}]


def row(rig, day, shift, hole, start, end, drilled, pt='', dt='', ot='', st='', rt='', total='12', notes=''):
    return [rig, f'{day}_{hole}.pdf', day, shift, '', hole, start, end, drilled, pt, dt, ot, st, rt, total, '', '', notes, '', '']


def parse(*rows):
    rejected = []
    return parse_shifts([HEADER, *rows], rejected=rejected), rejected


def interval(day, shift):
    """Day 08:00-20:00; night 20:00-08:00 of the next day, filed under its start date."""
    start = datetime.fromisoformat(day) + timedelta(hours=8 if shift == 'Өдөр' else 20)
    return start, start + timedelta(hours=12)


def collar(*ids):
    return [{'id': i, 'start': '2026-11-01', 'finish': '', 'collarDepth': None, 'plan': 300} for i in ids]


def audit(shifts, holes, rejected=(), through='2026-11-08', confirmed=()):
    for s in shifts:
        s.setdefault('reports', REPORT)
    confirmations = {'confirmed': list(confirmed), 'reports': [], 'holes': [], 'rigs': []}
    return build_audit({'shifts': shifts, 'collar': collar(*holes), 'rejectedShifts': list(rejected)}, RIGS, through, confirmations)


def slot(result, rig, day, shift):
    return next(s for s in result['slots'] if (s['rig'], s['date'], s['shift']) == (rig, day, shift))


# KHDH2601 on CSD-1300 as the sheet holds it on 2026-11-09 (no 11-08 day report anywhere in Drive).
KHDH = [row('CSD-1300', '2026-11-07', 'Өдөр', 'KHDH2601', 59.4, 92.4, 33, pt='0.5', ot='0.5'),
        row('CSD-1300', '2026-11-07', 'Шөнө', 'KHDH2601', 92.4, 125.4, 33, pt='0.5', dt='7', ot='1'),
        row('CSD-1300', '2026-11-08', 'Шөнө', 'KHDH2601', 143.4, 164.4, 21, pt='0.5', dt='7', ot='1.5')]
# STDH2601 on C-1800: the 11-08 night form's Drilled cell is blank at source; the sheet writes 0.
STDH = [row('C-1800', '2026-11-07', 'Өдөр', 'STDH2601', 48, 51, 3, pt='0.5'),
        row('C-1800', '2026-11-07', 'Шөнө', 'STDH2601', 51, 60, 9),
        row('C-1800', '2026-11-08', 'Шөнө', 'STDH2601', 65, 65, 0, notes='PQ casing 30→48 м = 18 м')]


class ChronologyTests(unittest.TestCase):
    def test_01_normal_night_day_night_day_sequence(self):
        result = audit(parse(*KHDH)[0], ['KHDH2601'])
        order = [(s['date'], s['shift']) for s in result['slots'] if s['rig'] == 'CSD-1300' and s['date'] >= '2026-11-07']
        starts = [interval(*key)[0] for key in order]
        self.assertEqual(starts, sorted(starts), 'audit slots run in shift start order')
        self.assertEqual(order[:4], [('2026-11-07', 'Өдөр'), ('2026-11-07', 'Шөнө'), ('2026-11-08', 'Өдөр'), ('2026-11-08', 'Шөнө')])

    def test_02_night_shift_crosses_midnight_as_12_hours(self):
        start, end = interval('2026-11-07', 'Шөнө')
        self.assertEqual((start.isoformat(), end.isoformat()), ('2026-11-07T20:00:00', '2026-11-08T08:00:00'))
        self.assertLess(end, interval('2026-11-08', 'Өдөр')[1])
        self.assertEqual(interval('2026-11-08', 'Өдөр')[0], end, 'the next day shift starts when the night ends')

    def test_03_missing_day_shift_between_two_nights_is_detected(self):
        day = slot(audit(parse(*KHDH)[0], ['KHDH2601']), 'CSD-1300', '2026-11-08', 'Өдөр')
        self.assertEqual(day['status'], 'MISSING_REPORT')

    def test_04_depth_continuity_gap_is_measured(self):
        day = slot(audit(parse(*KHDH)[0], ['KHDH2601']), 'CSD-1300', '2026-11-08', 'Өдөр')
        self.assertEqual([(i['hole'], i['from'], i['to'], i['meters']) for i in day['inferred']], [('KHDH2601', 125.4, 143.4, 18.0)])

    def test_05_a_depth_gap_is_never_a_confirmed_report(self):
        result = audit(parse(*KHDH)[0], ['KHDH2601'])
        day = slot(result, 'CSD-1300', '2026-11-08', 'Өдөр')
        self.assertIsNone(day['meters'], 'no reported metres on the missing shift')
        self.assertFalse(any(r['hole'] == 'KHDH2601' for r in day['records']))
        self.assertTrue(day['inferred'][0]['exact'], 'one candidate shift: pinned, but still an estimate')


class RecordIntegrityTests(unittest.TestCase):
    def source(self, name, rows, header=HEADER):
        text = '\n'.join(','.join(map(str, r)) for r in [header, *rows])
        return {'name': name, 'url': f'https://docs.google.com/spreadsheets/d/{name}', 'modified': name,
                'content': text.encode('utf-8'), 'suffix': '.csv'}

    def test_06_duplicate_shift_key_is_counted_once_and_a_difference_is_a_conflict(self):
        seed = {'driveUrl': 'https://drive.google.com/drive/folders/x', 'shifts': [], 'collar': []}
        holes = self.source('0', [['KHDH2601', 300, '', '2026-11-04', '']],
                            ['Hole ID', 'Plan Depth (m)', 'Drilled Depth (m)', 'Started Date', 'Finished Date'])
        same = assemble([self.source('2', KHDH[1:2]), self.source('1', KHDH[1:2]), holes], seed)
        self.assertEqual(len(same['shifts']), 1)
        other = row('CSD-1300', '2026-11-07', 'Шөнө', 'KHDH2601', 92.4, 126.4, 34, pt='0.5', dt='7', ot='1')
        differing = assemble([self.source('2', KHDH[1:2]), self.source('1', [other]), holes], seed)
        self.assertEqual((len(differing['shifts']), len(differing['sourceConflicts'])), (1, 1))

    def test_07_continuity_is_not_computed_across_holes(self):
        shifts = parse(*STDH[:2], row('C-1800', '2026-11-08', 'Шөнө', 'XXDH2601', 0, 20, 20))[0]
        day = slot(audit(shifts, ['STDH2601', 'XXDH2601']), 'C-1800', '2026-11-08', 'Өдөр')
        self.assertFalse(any(i['hole'] != 'STDH2601' for i in day['inferred']))
        self.assertFalse(any(i['from'] == 60 and i['to'] == 0 for i in day['inferred']))

    def test_08_casing_metres_are_not_drilled_metres(self):
        night = parse(*STDH)[0][-1]
        self.assertEqual((night['from'], night['to'], night['meters']), (65, 65, 0))

    def test_09_a_blank_dt_with_a_12_hour_total_is_12_hours(self):
        # Owner decision (2026-10-27, kept 2026-11-09): a blank DT is 12 h when the total is 12 h, even beside
        # written PT/OT (KHDH 11-07 day: PT 0.5 + OT 0.5). The audit report records this as an assumption.
        day = parse(*KHDH)[0][0]
        self.assertEqual(day['dt'], 12)

    def test_10_blank_drilled_is_not_zero(self):
        shifts, rejected = parse(row('C-1800', '2026-11-08', 'Шөнө', 'STDH2601', 65, 65, ''))
        self.assertEqual(shifts, [])
        self.assertIn('Missing/invalid meters', rejected[0]['reason'])

    @unittest.skip('NOT TESTABLE: the 2_Ээлжийн_бүртгэл schema has no start/finish time columns; dates cannot be '
                   'checked against the report times by the code')
    def test_11_night_report_date_conflicting_with_its_times(self):
        pass

    def test_12_overlapping_depth_intervals_are_flagged(self):
        shifts = parse(*KHDH[:2], row('CSD-1300', '2026-11-08', 'Өдөр', 'KHDH2601', 120, 143.4, 23.4))[0]
        result = audit(shifts, ['KHDH2601'])
        texts = [i['text'] for s in result['slots'] for i in s['issues'] if s['date'] == '2026-11-08']
        self.assertTrue(any('давхардсан' in t for t in texts), texts)

    def test_13_a_zero_metre_shift_after_a_missing_one_keeps_the_gap(self):
        result = audit(parse(*STDH)[0], ['STDH2601'])
        day = slot(result, 'C-1800', '2026-11-08', 'Өдөр')
        self.assertEqual((day['status'], [(i['from'], i['to'], i['meters']) for i in day['inferred']]),
                         ('MISSING_REPORT', [(60, 65, 5)]))

    def test_14_reported_totals_exclude_inferred_metres(self):
        result = audit(parse(*KHDH)[0] + parse(*STDH)[0], ['KHDH2601', 'STDH2601'])
        november = result['months'][0]
        reported = sum(s['meters'] or 0 for s in result['slots'] if s['date'].startswith('2026-11'))
        self.assertEqual(reported, 33 + 33 + 21 + 3 + 9 + 0)
        self.assertEqual(november['inferredMeters'], 18 + 5)

    def test_15_parsing_and_assembling_twice_gives_the_same_records(self):
        first, second = parse(*KHDH, *STDH)[0], parse(*KHDH, *STDH)[0]
        self.assertEqual(first, second)
        self.assertEqual(len({(s['rig'], s['date'], s['shift'], s['hole']) for s in first}), len(first))


class FindingTests(unittest.TestCase):
    # STDH2601 30 -> 48 m (11-04 night To 30, 11-07 day From 48). The 11-05 day row (From/To blank, owner-confirmed
    # 0 m) and the 11-06 night row (From 48, To blank) are rejected by validation.
    ROWS = (row('C-1800', '2026-11-04', 'Шөнө', 'STDH2601', 27, 30, 3),
            row('C-1800', '2026-11-05', 'Өдөр', 'STDH2601', '', '', 0, pt='0.5', ot='2', rt='8'),
            row('C-1800', '2026-11-06', 'Шөнө', 'STDH2601', 48, '', '', total='0'),
            STDH[0])
    ZERO = {'rig': 'C-1800', 'date': '2026-11-05', 'shift': 'Өдөр', 'status': 'VERIFIED_NON_DRILLING',
            'reason': '0 м', 'evidence': 'мөр 7', 'confirmedBy': 'owner', 'confirmedAt': '2026-11-06'}

    def run_audit(self, confirmed=()):
        shifts, rejected = parse(*self.ROWS)
        for r in rejected:
            r.update(sheet='S', tab='T', url='')
        return audit(shifts, ['STDH2601'], rejected, confirmed=confirmed)

    def test_16_a_rejected_row_that_states_its_depth_limits_the_gap(self):
        # The 11-06 night started at 48 m, so it and the shifts after it cannot hold 30-48 m.
        result = self.run_audit()
        gap = slot(result, 'C-1800', '2026-11-05', 'Шөнө')['inferred'][0]
        self.assertEqual((gap['from'], gap['to'], gap['shifts']), (30, 48, 3))
        self.assertEqual(slot(result, 'C-1800', '2026-11-06', 'Шөнө')['inferred'], [])
        night = slot(result, 'C-1800', '2026-11-06', 'Шөнө')
        self.assertEqual(night['status'], 'UNVERIFIED', 'the next report starts at 48 m too: 0 m from the depths, not a conflict')
        self.assertTrue(any('To = 48 м, өрөмдсөн 0 м' in i['text'] for i in night['issues']))
        self.assertIsNone(night['meters'], 'never turned into a reported 0 m')

    def test_19_a_blank_to_stays_a_conflict_when_the_next_report_starts_elsewhere(self):
        shifts, rejected = parse(row('C-1800', '2026-11-06', 'Шөнө', 'STDH2601', 45, '', '', total='0'), STDH[0])
        for r in rejected:
            r.update(sheet='S', tab='T', url='')
        self.assertEqual(slot(audit(shifts, ['STDH2601'], rejected), 'C-1800', '2026-11-06', 'Шөнө')['status'], 'SOURCE_CONFLICT')

    def test_17_an_owner_confirmed_zero_metre_shift_takes_no_gap_metres(self):
        result = self.run_audit([self.ZERO])
        zero = slot(result, 'C-1800', '2026-11-05', 'Өдөр')
        self.assertEqual((zero['status'], zero['inferred']), ('VERIFIED_NON_DRILLING', []))
        gap = slot(result, 'C-1800', '2026-11-05', 'Шөнө')['inferred'][0]
        self.assertEqual((gap['shifts'], gap['exact']), (2, False))
        self.assertEqual(slot(result, 'C-1800', '2026-11-06', 'Өдөр')['status'], 'MISSING_REPORT')

    def test_18_a_rejected_row_ending_above_a_gap_comes_before_it(self):
        shifts, rejected = parse(row('C-1800', '2026-11-04', 'Шөнө', 'STDH2601', 27, 30, 3),
                                 row('C-1800', '2026-11-05', 'Өдөр', 'STDH2601', 30, 30, '', total='0'),
                                 STDH[0])
        for r in rejected:
            r.update(sheet='S', tab='T', url='')
        result = audit(shifts, ['STDH2601'], rejected)
        self.assertEqual(slot(result, 'C-1800', '2026-11-05', 'Өдөр')['inferred'], [])
        self.assertEqual(slot(result, 'C-1800', '2026-11-05', 'Шөнө')['inferred'][0]['shifts'], 3)


class FinishedHoleTests(unittest.TestCase):
    # Owner rule 2026-11-09: reports of a hole stop and the rig's later reports name another hole -> it is finished.
    def test_20_a_hole_no_later_report_names_is_finished_without_a_collar_date(self):
        shifts = parse(row('C-1800', '2026-11-01', 'Өдөр', 'ZHDH2611', 0, 30, 30),
                       row('C-1800', '2026-11-03', 'Өдөр', 'ZHDH2613', 0, 20, 20))[0]
        move = slot(audit(shifts, ['ZHDH2611', 'ZHDH2613']), 'C-1800', '2026-11-02', 'Өдөр')
        self.assertEqual(move['status'], 'UNVERIFIED', 'a rig move, not a missing report')
        self.assertTrue(any('дурдагдаагүй тул дууссан' in i['text'] for i in move['issues']))

    def test_21_a_hole_named_again_later_is_not_finished(self):
        shifts = parse(row('C-1800', '2026-11-01', 'Өдөр', 'ZHDH2611', 0, 30, 30),
                       row('C-1800', '2026-11-03', 'Өдөр', 'ZHDH2613', 0, 20, 20),
                       row('C-1800', '2026-11-04', 'Өдөр', 'ZHDH2611', 30, 40, 10))[0]
        gap = slot(audit(shifts, ['ZHDH2611', 'ZHDH2613']), 'C-1800', '2026-11-02', 'Өдөр')
        self.assertEqual(gap['status'], 'MISSING_REPORT')

    def test_22_the_rigs_latest_hole_is_still_being_drilled(self):
        latest = slot(audit(parse(*STDH)[0], ['STDH2601'], through='2026-11-12'), 'C-1800', '2026-11-10', 'Өдөр')
        self.assertEqual(latest['status'], 'MISSING_REPORT', 'no later report of another hole: not finished')


if __name__ == '__main__':
    unittest.main(verbosity=2)
