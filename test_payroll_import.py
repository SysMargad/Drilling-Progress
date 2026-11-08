import json
import tempfile
import unittest
import urllib.error
from pathlib import Path
from unittest.mock import MagicMock, patch

from drilling_sync import FINANCE_FOLDER_ID, FINANCE_SHEET_MIME, FOLDER_MIME, XLSX_MIME, drive_finance_aggregates
from payroll_import import SNAPSHOT, apply_payroll, load_payrolls, parse_pay_workbook, parse_payroll, validate_snapshot
from validate_data import validate_finance

# A pay-period workbook in the source layout, with made-up people and amounts: a master (100,000/day, 50 m at
# 20,000 = 1,000,000 bonus, 30,000 other additions) and an assistant (80,000/day, two days, 240,000 additions).
SUMMARY = [['Д/д', 'Албан тушаалын нэрс', 'Албан тушаалын тоо', 'Гарт авах цалин', 'Гар авах цалингийн дүн', 'Нэмэгдэл цалингийн мэдээлэл'],
           ['1', 'Өрөмдлөгийн өдрийн ээлжийн мастер', '1', '3000000', '3000000', '1 метр тутамд 20,000 төгрөгийн нэмэгдэл цалин олгоно'],
           ['2', 'Өрөмдлөгийн өдрийн ээлжийн туслах', '1', '2400000', '2400000', ''],
           ['', 'Нийт дүн', '2', '', '5400000', '']]
HEADER = ['№', 'Нэр', 'Регистрийн дугаар', 'Албан тушаал', 'Гарт авах цалин /30 хоног/', '10-р сар 16–19', '', '', '',
          'Нийт ажилласан\nхоног', 'Тооцсон цалин', 'Өрөмдсөн метр, илүү цаг, нэмэгдэл өдөр',
          'Нэмэгдэл цалин, цалингийн зөрүү, татвар', 'Ажлын хувцас, сэлбэгийн суутгал', 'Гарт олгох цалин']


def pay_rows():
    return [['Өрмийн багийн 2026.10.16–2026.10.19 хүртэл хугацааны ажилласан өдрийн бүртгэл'], HEADER,
            ['', '', '', '', '', 'Ба', 'Бя', 'Ня', 'Да'],
            ['', '', '', '', '', '16', '17', '18', '19'],
            ['1', 'PRIVATE_MASTER', 'PRIVATE_REGISTER', 'Өрмийн мастер', '3000000', '1', '1', '1', '1', '4', '400000', '50', '1030000', '', '1430000'],
            ['2', 'PRIVATE_ASSISTANT', 'PRIVATE_REGISTER', 'Өрмийн туслах', '2400000', '1', '1', '', '', '2', '160000', '3', '240000', '50000', '350000'],
            [],
            ['Нийт дүн', '', '', '', '', '', '', '', '', '6', '560000', '53', '1270000', '50000', '1780000'],
            ['', '', 'Өвчтэй']]


def workbook(rows=None):
    return [('10.16-19', rows or pay_rows()), ('Албан тушаал орон тоо', SUMMARY)]


def model_finance():
    rows = [{'date': f'2026-10-{day}', 'rig': rig, 'shift': shift, 'laborCost': 1000.0, 'foodCost': 500.0,
             'bonusCost': 300.0 if (day, rig, shift) == ('15', 'C-1800', 'Өдөр') else 0.0, 'incentiveCost': 0.0}
            for day in ('15', '16', '17') for rig in ('C-1800', 'CSD-1300') for shift in ('Өдөр', 'Шөнө')]
    daily = [{'date': f'2026-10-{day}', 'laborCost': 4000.0, 'foodCost': 2000.0,
              'bonusCost': 300.0 if day == '15' else 0.0, 'incentiveCost': 0.0} for day in ('15', '16', '17')]
    return {'period': '2026-10', 'daily': daily, 'rigShifts': rows}


SHIFTS = [{'date': '2026-10-15', 'rig': 'C-1800', 'shift': 'Өдөр', 'meters': 30.0},
          {'date': '2026-10-16', 'rig': 'CSD-1300', 'shift': 'Шөнө', 'meters': 10.0},
          {'date': '2026-10-16', 'rig': 'KVM', 'shift': 'Өдөр', 'meters': 99.0}]


class ParsePayrollTests(unittest.TestCase):
    def test_date_totals_split_the_metre_bonus_from_other_additions(self):
        parsed = parse_payroll(workbook(), 'pay.xlsx')
        self.assertEqual((parsed['start'], parsed['end'], parsed['people']), ('2026-10-16', '2026-10-19', 2))
        self.assertEqual(parsed['daily'], [
            {'date': '2026-10-16', 'base': 180000.0, 'incentive': 127500.0},
            {'date': '2026-10-17', 'base': 180000.0, 'incentive': 127500.0},
            {'date': '2026-10-18', 'base': 100000.0, 'incentive': 7500.0},
            {'date': '2026-10-19', 'base': 100000.0, 'incentive': 7500.0}])
        # The assistant's "3" in the metres column is extra days: no metre rate, so it stays an addition.
        self.assertEqual(parsed['bonus'], {'month': '2026-10', 'amount': 1000000.0, 'meters': 50.0})
        self.assertEqual(parsed['totals'], {'days': 6.0, 'base': 560000.0, 'additions': 1270000.0, 'deductions': 50000.0})
        self.assertNotIn('PRIVATE', json.dumps(parsed, ensure_ascii=False))

    def test_the_workbook_total_row_and_day_marks_are_checked(self):
        rows = pay_rows()
        rows[7][10] = '560500'
        with self.assertRaisesRegex(ValueError, 'base do not add up'):
            parse_payroll(workbook(rows))
        rows = pay_rows()
        rows[5][7] = '1'
        with self.assertRaisesRegex(ValueError, 'day marks'):
            parse_payroll(workbook(rows))
        rows = pay_rows()
        del rows[7]
        with self.assertRaisesRegex(ValueError, 'total row'):
            parse_payroll(workbook(rows))
        with self.assertRaisesRegex(ValueError, 'role summary'):
            parse_payroll([('10.16-19', pay_rows())])
        rows = pay_rows()
        rows[0] = ['Өрмийн багийн ажилласан өдрийн бүртгэл']
        with self.assertRaisesRegex(ValueError, 'names no period'):
            parse_payroll(workbook(rows), 'pay.xlsx')
        self.assertEqual(parse_payroll(workbook(rows), 'Цалин 2026.10.16-2026.10.19.xlsx')['end'], '2026-10-19')


class ApplyPayrollTests(unittest.TestCase):
    def setUp(self):
        self.payroll = {**parse_payroll(workbook(), 'Pay 2026.10.16-19.xlsx'), 'source': 'drive'}

    def test_actual_pay_replaces_the_model_on_its_dates_and_the_bonus_for_the_month(self):
        finance = apply_payroll(model_finance(), [self.payroll], SHIFTS)
        rows = {(r['date'], r['rig'], r['shift']): r for r in finance['rigShifts']}
        # 15 October is outside the pay period: the attendance model stays, the bonus is the month's actual one.
        self.assertEqual(rows[('2026-10-15', 'CSD-1300', 'Шөнө')]['laborCost'], 1000.0)
        self.assertEqual(rows[('2026-10-15', 'C-1800', 'Өдөр')]['bonusCost'], 847500.0)  # 1,000,000 × 1.13 × 30/40 m
        self.assertEqual(rows[('2026-10-16', 'CSD-1300', 'Шөнө')]['bonusCost'], 282500.0)
        # Each covered day's pay is split evenly over 2 rigs × 2 shifts; food is left to the model.
        for rig in ('C-1800', 'CSD-1300'):
            for shift in ('Өдөр', 'Шөнө'):
                self.assertEqual(rows[('2026-10-16', rig, shift)]['laborCost'], 50850.0)
                self.assertEqual(rows[('2026-10-16', rig, shift)]['incentiveCost'], 36018.75)
                self.assertEqual(rows[('2026-10-16', rig, shift)]['foodCost'], 500.0)
                self.assertEqual(rows[('2026-10-19', rig, shift)]['laborCost'], 28250.0)
        self.assertEqual(sum(r['bonusCost'] for r in finance['rigShifts']), 1130000.0)
        self.assertAlmostEqual(sum(r['laborCost'] for r in finance['rigShifts']) - 4000, 560000 * 1.13, places=2)
        self.assertEqual(finance['payPeriods'], [{'file': 'Pay 2026.10.16-19.xlsx', 'start': '2026-10-16',
                                                  'end': '2026-10-19', 'source': 'drive', 'bonus': True}])
        validate_finance(finance)
        self.assertEqual(apply_payroll(finance, [self.payroll], SHIFTS), finance, 'idempotent')

    def test_other_months_and_bonusless_periods_leave_the_model(self):
        finance = model_finance()
        self.assertIs(apply_payroll(finance, [{**self.payroll, 'start': '2026-11-01'}], SHIFTS), finance)
        no_bonus = {**self.payroll, 'bonus': {'month': '2026-10', 'amount': 0.0, 'meters': 0.0}}
        applied = apply_payroll(finance, [no_bonus], SHIFTS)
        self.assertEqual(sum(r['bonusCost'] for r in applied['rigShifts']), 300.0)
        self.assertFalse(applied['payPeriods'][0]['bonus'])
        self.assertIsNone(apply_payroll(None, [self.payroll], SHIFTS))


class LoadPayrollTests(unittest.TestCase):
    def snapshot(self, folder, entries):
        path = Path(folder) / 'payroll.json'
        path.write_text(json.dumps({'about': '', 'payrolls': entries}, ensure_ascii=False), encoding='utf-8')
        return path

    def test_drive_failure_falls_back_to_the_verified_totals(self):
        parsed = parse_payroll(workbook(), 'Pay A.xlsx')
        verified = {'id': 'A' * 33, 'name': 'Pay A.xlsx', 'modifiedTime': '2026-11-05T09:25:09Z',
                    **{k: parsed[k] for k in ('start', 'end', 'people', 'daily', 'bonus', 'totals')}}
        listed = {'id': 'B' * 33, 'name': 'Pay B.xlsx'}
        with tempfile.TemporaryDirectory() as folder:
            path = self.snapshot(folder, [verified, listed])
            drive = MagicMock()
            drive.download.side_effect = lambda file: (_ for _ in ()).throw(
                urllib.error.HTTPError('u', 404, 'x', {}, None)) if file['id'] == 'A' * 33 else b'B'
            payrolls, note = load_payrolls(drive, lambda content, suffix: workbook(), path)
            self.assertEqual([(p['name'], p['source']) for p in payrolls], [('Pay A.xlsx', 'snapshot'), ('Pay B.xlsx', 'drive')])
            self.assertEqual(note, 'Pay-period workbook refresh failed; verified snapshot used: Pay A.xlsx (HTTPError)')
            payrolls, note = load_payrolls(path=path)
            self.assertEqual(([p['source'] for p in payrolls], note), (['snapshot'], ''))
            with self.assertRaisesRegex(ValueError, 'date totals only'):
                load_payrolls(path=self.snapshot(folder, [{**verified, 'employee': 'PRIVATE'}]))

    def test_a_pay_workbook_in_the_finance_folder_is_not_read_as_attendance(self):
        attendance = [('attendance', [['Өрмийн багийн 2026.09.01-2026.09.30 бүртгэл'], ['10-р сар'], ['', 'Нэр', 'Албан тушаал'],
                                      ['', '', '', '', *[str(day) for day in range(1, 32)]]])]
        sheets = {b'pay': workbook(), b'attendance': attendance,
                  b'salary': [('salary', [['Албан тушаал', 'Ажилтны тоо', 'Нэрлэсэн цалин'], ['Өрмийн мастер', '1', '3100000']])],
                  b'products': [('products', [['Бүтээгдэхүүн', 'Тоо хэмжээ', 'Нэгж', 'Үнэ'], ['Mud', '25', 'кг', '330000']]),
                                ('usage', [['Нийт тооцооны шуудай', '0'], ['Огноо', 'Өрөм', 'Цооног', 'Ээлж', 'Mud тооцоо (шуудай)']])],
                  b'fuel': [('ledger', [['Огноо', 'Зарлага (өрөм) (л)', 'Өрөмийн Зардал (Төгрөг)'], ['2026-10-01', '0', '0']])]}
        files = [{'id': 'pay', 'mimeType': XLSX_MIME, 'modifiedTime': '2026-11-05'},
                 {'id': 'fuel', 'mimeType': FINANCE_SHEET_MIME, 'modifiedTime': '2026-10-04'},
                 {'id': 'products', 'mimeType': XLSX_MIME, 'modifiedTime': '2026-10-03'},
                 {'id': 'salary', 'mimeType': XLSX_MIME, 'modifiedTime': '2026-10-02'},
                 {'id': 'attendance', 'mimeType': FINANCE_SHEET_MIME, 'modifiedTime': '2026-10-01'}]
        with (patch('drilling_sync.Drive') as drive,
              patch('drilling_sync.workbook_rows', side_effect=lambda content, _: sheets[content]),
              patch('drilling_sync.mud_aggregates', return_value={}), patch('drilling_sync.fuel_aggregates', return_value={}),
              patch('drilling_sync.finance_aggregates', return_value={'period': '2026-10'}) as aggregate):
            drive.return_value.files.side_effect = lambda folder: (
                [{'id': 'nested', 'mimeType': FOLDER_MIME}] if folder == FINANCE_FOLDER_ID else files if folder == 'nested' else [])
            drive.return_value.download.side_effect = lambda file: file['id'].encode()
            drive_finance_aggregates(None, [], salary_source_id=None)
        self.assertIs(aggregate.call_args.args[1], attendance)


# A contract-fee workbook (Даалгаварын гэрээгээр ажиллагсадын хөлс) in the source layout, made-up people: a geology
# section (not read), a factory section that also pays two crew people, and the drill-crew section.
FEE_HEADER = ['№', 'Нэр', 'Регистрийн дугаар', 'Ажлын байр', 'Нөхцөл', 'Хөлс', 'Эхлэх огноо', '10-р сар', '', '',
              'Ажилласан өдөр', ' Ажилласан өдөрт ногдох цалин ', 'Дансны мэдээлэл', 'Татвар 1%', 'Цалингийн зөрүү, суутгал']


def fee_section(title, people, days, base):
    return [[title], FEE_HEADER, ['', '', '', '', '', '', '', 'Пү', 'Ба', 'Бя'], ['', '', '', '', '', '', '', '1', '2', '3'],
            *people, ['', 'Нийт дүн', '', '', '', '', '', '', '', '', str(days), f'  {base:,.2f} ']]


def fee_rows(crew_total=500000):
    return [['Гэрээгээр ажиллагсадын 2026.10.01 - 2026.10.03-г дуустал хугацааны хөлсний тооцоо'], [],
            *fee_section('Ховд аймаг Геологи, Дроны багийн гэрээт ажилчид',
                         [['1', 'PRIVATE_A', '', 'Геологийн туслах', '', '', '', '1', '1', '1', '3', '300000']], 3, 300000), [],
            *fee_section(' NGM-Үйлдвэр, өрмийн багийн гэрээт ажилчид',
                         [['1', 'PRIVATE_CARPENTER', '', 'Мужаан', '', '', '', '1', '1', '1', '3', '600000'],
                          ['2', 'Д.Мастер', '', 'Өрмийн мастер', '', '', '', '1', '', '', '1', '100000'],
                          ['3', 'Хабэа', '', 'ХАБЭА мэргэжилтэн', '', '', '', '1', '', '', '1', '100000']], 5, 800000), [],
            *fee_section('Дорнод аймаг NGM- Нэргүй өндөр талбай-Өрмийн баг',
                         [['1', 'Мастер', '', 'Өрмийн мастер', '', '', '', '', '1', '1', '2', '200000'],
                          ['2', 'Х.Хабэа', '', 'ХАБЭА', '', '', '', '', '1', '1', '2', '200000'],
                          ['3', 'PRIVATE_COOK', '', 'Туслах тогооч', '', '', '', '2', '', '', '2', '100000', '', '', '  (25,000.00)']],
                         6, crew_total)]


class ContractFeeTests(unittest.TestCase):
    def test_the_crew_section_counts_whole_and_a_mixed_section_only_its_crew_people(self):
        fees = parse_pay_workbook([('2026-10-03', fee_rows())], 'Хөлс-2026.10.03')
        self.assertEqual((fees['start'], fees['end'], fees['people']), ('2026-10-01', '2026-10-03', 3))
        # Day 1: the factory section's master and safety officer (also in the crew section by name) and the cook's
        # double day; the carpenter and the geology section are not crew.
        self.assertEqual(fees['daily'], [{'date': '2026-10-01', 'base': 300000.0}, {'date': '2026-10-02', 'base': 200000.0},
                                         {'date': '2026-10-03', 'base': 200000.0}])
        self.assertEqual(fees['totals'], {'days': 8.0, 'base': 700000.0, 'additions': 0.0, 'deductions': 25000.0})
        self.assertEqual(fees['bonus']['amount'], 0.0)
        self.assertNotIn('PRIVATE', json.dumps(fees, ensure_ascii=False))

    def test_a_section_total_that_does_not_add_up_is_rejected(self):
        with self.assertRaisesRegex(ValueError, 'base do not add up'):
            parse_pay_workbook([('2026-10-03', fee_rows(crew_total=600000))], 'Хөлс')

    def test_a_fee_period_replaces_pay_and_keeps_the_modelled_incentive_and_bonus(self):
        finance = model_finance()
        for row in finance['rigShifts']:
            row['incentiveCost'] = 70.0
        fees = {'name': 'Хөлс', 'start': '2026-10-15', 'end': '2026-10-15', 'people': 1, 'source': 'snapshot',
                'daily': [{'date': '2026-10-15', 'base': 400000.0}],
                'bonus': {'month': '2026-10', 'amount': 0.0, 'meters': 0.0},
                'totals': {'days': 1.0, 'base': 400000.0, 'additions': 0.0, 'deductions': 0.0}}
        applied = apply_payroll(finance, [fees], SHIFTS)
        rows = {(r['date'], r['rig'], r['shift']): r for r in applied['rigShifts']}
        self.assertEqual(rows[('2026-10-15', 'C-1800', 'Шөнө')]['laborCost'], 113000.0)  # 400,000 × 1.13 / 4
        self.assertEqual(rows[('2026-10-15', 'C-1800', 'Шөнө')]['incentiveCost'], 70.0)
        self.assertEqual(rows[('2026-10-15', 'C-1800', 'Өдөр')]['bonusCost'], 300.0)
        self.assertEqual(rows[('2026-10-16', 'C-1800', 'Шөнө')]['laborCost'], 1000.0)
        validate_finance(applied)


class PublishedSnapshotTests(unittest.TestCase):
    def test_the_snapshot_holds_verified_date_totals_only(self):
        snapshot = json.loads(SNAPSHOT.read_text(encoding='utf-8'))
        validate_snapshot(snapshot)
        for entry in snapshot['payrolls']:
            if 'daily' not in entry:
                continue
            self.assertEqual(set(entry['totals']), {'days', 'base', 'additions', 'deductions'})
            self.assertAlmostEqual(sum(row['base'] for row in entry['daily']), entry['totals']['base'], delta=1)
            self.assertLessEqual(entry['bonus']['amount'] + sum(row.get('incentive', 0) for row in entry['daily']),
                                 entry['totals']['additions'] + 1)


if __name__ == '__main__':
    unittest.main()
