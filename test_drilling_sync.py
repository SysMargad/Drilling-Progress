import io
import json
import unittest
import tempfile
import urllib.error
from types import SimpleNamespace
from unittest.mock import patch
from subprocess import CompletedProcess
import zipfile
from pathlib import Path
from drilling_sync import (FINANCE_FOLDER_ID, FINANCE_SHEET_MIME, FOLDER_MIME,
                           append_data_log, assemble, drive_finance_aggregates, apply_uploaded_fuel,
                           finance_aggregates, mud_aggregates, fuel_aggregates, FinanceSourceError, load_json,
                           local_sources, parse_shifts, publish, signature,
                           workbook_rows, report_metadata, attach_reports, drive_sources,
                           XLSX_MIME, Drive)

ROOT = Path(__file__).resolve().parent

class PipelineTests(unittest.TestCase):
    def test_uploaded_fuel_survives_stale_drive_without_double_counting(self):
        finance = {'period': '2026-10', 'fuel': {'daily': [
            {'date': '2026-10-16', 'litres': 620, 'cost': 3348000},
            {'date': '2026-10-19', 'litres': None, 'cost': None}], 'allocations': []}}
        shifts = [{'date': '2026-10-19', 'rig': 'C-1800', 'shift': 'Өдөр', 'hole': 'X', 'hours': 12}]
        supplement = {'period': '2026-10', 'daily': [
            {'date': '2026-10-16', 'litres': 620, 'cost': 3348000},
            {'date': '2026-10-19', 'litres': 500, 'cost': 2700000}]}
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'fuel.json'
            path.write_text(json.dumps(supplement), encoding='utf-8')
            result = apply_uploaded_fuel(finance, shifts, path)
            self.assertEqual(sum(row['litres'] for row in result['fuel']['daily']), 1120)
            self.assertEqual(result, apply_uploaded_fuel(result, shifts, path))
            self.assertIsNone(finance['fuel']['daily'][1]['litres'])
            changed = apply_uploaded_fuel(result, [{**shifts[0], 'rig': 'CSD-1300'}], path)
            allocation = next(row for row in changed['fuel']['allocations'] if row['date'] == '2026-10-19')
            self.assertEqual(allocation['rig'], 'CSD-1300')
            self.assertEqual(allocation['litres'], 500)
            self.assertEqual(apply_uploaded_fuel({**finance, 'period': '2026-11'}, shifts, path)['period'], '2026-11')

    def test_blank_optional_time_codes_remain_unknown(self):
        headers=['Rig','Source','Date','Shift','Driller','Hole ID','From','To','Drilled','ST','RT','DT','Total','Work notes']
        row=['CSD-1300','photo','2026-10-14','Өдөр','x','DTDH2605','0','8.4','8.4','','','2.5','12','']
        parsed=parse_shifts([headers,row])[0]
        self.assertIsNone(parsed['st'])
        self.assertIsNone(parsed['rt'])
        self.assertEqual(parsed['dt'],2.5)
        for index,value in [(9,'#REF!'),(9,'-1'),(11,'13')]:
            bad=row.copy();bad[index]=value
            with self.assertRaises(ValueError):
                parse_shifts([headers,bad])
        data=self.seed.copy();data['shifts']=[parsed]
        from validate_data import validate
        validate(data)

    def test_total_code_hours_header_keeps_reported_value(self):
        headers=['Rig','Source','Date','Shift','Hole ID','From','To','Drilled','ST','RT','DT','Total code hrs']
        row=['C-1800','photo','2026-10-20','Өдөр','ZHDH2603','59.4','107.4','48','','','10','12']
        self.assertEqual(parse_shifts([headers,row])[0]['hours'],12)
        self.assertEqual(parse_shifts([headers,[*row[:-1],'']])[0]['hours'],12)

    def test_source_shift_duration_precedes_partial_code_subtotal(self):
        headers=['Rig','Source','Date','Shift','Hole ID','From','To','Drilled','DT','Total code hrs','Shift hours (source)']
        row=['C-1800','photo','2026-10-23','Шөнө','ZHDH2604','0','11','11','','6','12']
        result=parse_shifts([headers,row])[0]
        self.assertEqual((result['dt'],result['hours']),(12,12))
        row[-1]='0';row[-3]='0'
        self.assertEqual(parse_shifts([headers,row])[0]['hours'],0)

    def test_owner_correction_only_applies_to_designated_shift(self):
        headers=['Rig','Source','Date','Shift','Hole ID','From','To','Drilled','DT','Total code hrs','Work notes']
        row=['C-1800','photo','2026-10-19','Шөнө','ZHDH2602','287','326','39','','','маягтын нийт хугацаа 12ц']
        parsed=parse_shifts([headers,row])[0]
        self.assertEqual((parsed['meters'],parsed['dt'],parsed['hours']),(39,0,12))
        actual=row.copy();actual[8:10]=['8','11']
        self.assertEqual((parse_shifts([headers,actual])[0]['dt'],parse_shifts([headers,actual])[0]['hours']),(8,11))
        other=row.copy();other[2]='2026-10-20'
        parsed_other = parse_shifts([headers,other])[0]
        self.assertEqual((parsed_other['dt'],parsed_other['hours']),(12,12))

    def test_zero_metre_incident_shift_requires_fully_accounted_hours(self):
        headers=['Rig','Source','Date','Shift','Hole ID','From','To','Drilled','DT','Total','PT','OT']
        row=['C-1800','photo','2026-10-18','Шөнө','DTDH2602','266','266','0','','12','0.5','11.5']
        self.assertEqual(parse_shifts([headers,row])[0]['dt'],0)
        incomplete=row.copy();incomplete[-1]='10'
        self.assertEqual(parse_shifts([headers,incomplete])[0]['dt'],12)

    def test_blank_required_hours_use_owner_default_without_replacing_zero(self):
        headers=['Rig','Source','Date','Shift','Hole ID','From','To','Drilled','ST','RT','DT','Total']
        row=['CSD-1300','photo','2026-10-25','Шөнө','ZHDH2605','59.4','128.4','69','','','','']
        parsed=parse_shifts([headers,row])[0]
        self.assertEqual((parsed['dt'],parsed['hours']),(12,12))
        self.assertIsNone(parsed['st'])
        self.assertIsNone(parsed['rt'])
        self.assertIn('source blank; estimated',parsed['notes'])
        zero=row.copy();zero[10:12]=['0','0']
        self.assertEqual((parse_shifts([headers,zero])[0]['dt'],parse_shifts([headers,zero])[0]['hours']),(0,0))
        malformed=row.copy();malformed[10]='#REF!'
        with self.assertRaisesRegex(ValueError,'dt'):
            parse_shifts([headers,malformed])
        conflict=row.copy();conflict[8]='1'
        with self.assertRaisesRegex(ValueError,'hours mismatch'):
            parse_shifts([headers,conflict])

    def test_drive_read_retries_transient_errors_only(self):
        drive=object.__new__(Drive)
        drive.credentials=SimpleNamespace(valid=True,token='unit-test-placeholder')
        def error(status):
            return urllib.error.HTTPError('https://www.googleapis.com/unit-test',status,'test',{},None)
        with patch('drilling_sync.urllib.request.urlopen',side_effect=[error(500),io.BytesIO(b'ok')]) as request, patch('drilling_sync.time.sleep') as sleep:
            self.assertEqual(drive.request('https://www.googleapis.com/unit-test'),b'ok')
            self.assertEqual(request.call_count,2)
            sleep.assert_called_once_with(1)
        for status,attempts in [(500,3),(403,1)]:
            with patch('drilling_sync.urllib.request.urlopen',side_effect=error(status)) as request, patch('drilling_sync.time.sleep'):
                with self.assertRaises(urllib.error.HTTPError):
                    drive.request('https://www.googleapis.com/unit-test')
                self.assertEqual(request.call_count,attempts)

    def test_water_volume_is_not_a_cost_and_preserves_missing_values(self):
        headers=['Rig','Source','Date','Shift','Hole ID','From','To','Drilled','ST','RT','DT','Total','Water consumption (L)']
        row=['C-1800','photo','2026-10-14','Өдөр','DTDH2605','0','8','8','','','2','12','2500']
        self.assertEqual(parse_shifts([headers,row])[0]['waterUsageM3'],2.5)
        self.assertEqual(parse_shifts([headers,[*row[:-1],'0']])[0]['waterUsageM3'],0)
        self.assertIsNone(parse_shifts([headers,[*row[:-1],'']])[0]['waterUsageM3'])
        self.assertEqual(parse_shifts([[*headers[:-1],'Усны хэрэглээ (м³)'],row])[0]['waterUsageM3'],2500)
        with self.assertRaisesRegex(ValueError,'water consumption'):
            parse_shifts([headers,[*row[:-1],'-1']])

    def test_drive_report_folder_traversal(self):
        def folder(id,name):
            return {'id':id,'name':name,'mimeType':'application/vnd.google-apps.folder'}
        tree={'root':[folder('hole','DTDH2603')], 'hole':[folder('daily','02. Daily report')],
              'daily':[folder('rig','C-1800'),folder('skip','Duplicates_To_Delete')],
              'rig':[{'id':'photo','name':'Daily_report_20261015_n.JPG','mimeType':'image/jpeg'}]}
        with patch('drilling_sync.Drive') as drive:
            drive.return_value.files.side_effect=lambda id:tree[id]
            records,folders,reports=drive_sources('root',None)
        self.assertEqual(records,[])
        self.assertIn('DTDH2603',folders)
        self.assertEqual([(r['hole'],r['rig'],r['date'],r['shift']) for r in reports],
                         [('DTDH2603','C-1800','2026-10-15','Шөнө')])

    def test_report_matching_and_provenance(self):
        image={'id':'photo','name':'DTDH2603_Daily_report_20261015_n.JPG.jpg','mimeType':'image/jpeg'}
        report=report_metadata(image,'DTDH2603','C-1800','https://drive.google.com/drive/folders/test')
        self.assertEqual((report['date'],report['shift']),('2026-10-15','Шөнө'))
        self.assertEqual(report_metadata({**image,'name':'Daily_report_20261014_d'},'DTDH2603','C-1800','')['shift'],'Өдөр')
        self.assertIsNone(report_metadata({**image,'name':'20261399_d.JPG'},'DTDH2603','C-1800',''))
        self.assertIsNone(report_metadata({**image,'mimeType':'text/plain'},'DTDH2603','C-1800',''))
        self.assertIsNone(report_metadata(image,'DTDH2603','unknown',''))
        rows=[{k:report[k] for k in ('date','shift','rig','hole')}]
        rows += [{**rows[0],'rig':'CSD-1300'},{**rows[0],'hole':'OTHER'},{**rows[0],'shift':'Өдөр'}]
        attach_reports(rows,[report,report])
        self.assertEqual([len(r['reports']) for r in rows],[1,0,0,0])

    def test_all_current_shifts_have_exact_report(self):
        data=assemble(self.records,self.seed,report_index=load_json(ROOT/'input'/'report-index.json'))
        self.assertEqual(len(data['shifts']),44)
        for row in data['shifts']:
            self.assertEqual(len(row['reports']),1)
            self.assertTrue(all(row[k]==row['reports'][0][k] for k in ('hole','rig','date','shift')))

    def setUp(self):
        self.records = local_sources(ROOT / 'input')
        self.seed = load_json(ROOT / 'dist' / 'data.json')

    def test_real_sources_and_duplicate_reports(self):
        data = assemble(self.records + self.records, self.seed)
        self.assertEqual(len(data['collar']), 6)
        self.assertEqual(len(data['shifts']), 44)
        self.assertAlmostEqual(sum(s['meters'] for s in data['shifts']), 1103.8)
        self.assertAlmostEqual(sum(s['dt'] for s in data['shifts']), 366)
        self.assertEqual(sum(s['hours'] for s in data['shifts']), 528)
        self.assertEqual({h['site'] for h in data['collar']}, {'Нэргүй Өндөр'})
        self.assertEqual({h['targetArea'] for h in data['collar']}, {'Дорнын Төмөр', 'Замт Хөндий'})
        h = next(h for h in data['collar'] if h['id'] == 'DTDH2603')
        self.assertIsNone(h['collarDepth'])
        self.assertEqual(max(s['to'] for s in data['shifts'] if s['hole'] == h['id']), 203)

    def test_invalid_shift_rejected(self):
        rows = [['Rig','Source','Date','Shift','Driller','Hole ID','From','To','Drilled','ST','RT','DT','Total','Work notes'],
                ['C-1800','a','2026-10-13','Өдөр','x','DTDH2603','10','20','30','0','0','10','12','']]
        with self.assertRaisesRegex(ValueError, 'Depth/meters mismatch'):
            parse_shifts(rows)

    def test_xlsx_sparse_cells_and_shared_strings(self):
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, 'w') as z:
            z.writestr('xl/sharedStrings.xml', '<sst xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"><si><t>Hole Id</t></si></sst>')
            z.writestr('xl/worksheets/sheet1.xml', '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"><sheetData><row r="1"><c r="B1" t="s"><v>0</v></c><c r="D1" t="inlineStr"><is><t>Plan Depth, m</t></is></c></row><row r="2"><c r="B2" t="inlineStr"><is><t>DTDH2603</t></is></c><c r="D2"><v>280</v></c></row></sheetData></worksheet>')
        sheets = workbook_rows(buf.getvalue(), '.xlsx')
        self.assertEqual(sheets[0][1][0], ['', 'Hole Id', '', 'Plan Depth, m'])
        self.assertEqual(sheets[0][1][1][3], '280')

    def test_finance_aggregates_map_roles_and_exclude_private_rows(self):
        salary_rows = [
            ['№', 'Албан тушаал', 'Ажилтны тоо', 'Нэрлэсэн цалин',
             'Бонус (1 хүн - 1 метр тутам)', 'Өдрийн', 'НДШ', 'Бодит цалин'],
            ['1', 'Өрмийн мастер', '4', '3100000', '10000', '120000', '', ''],
            ['2', 'Тогоочийн туслах', '1', '3100000', '', '', '', ''],
            ['3', 'Туслах угаагч', '1', '3100000', '', '', '', ''],
            ['4', 'ХАБ, Кемп менежер', '1', '3100000', '', '', '', ''],
            ['5', 'Кемп бой', '1', '3100000', '', '', '', ''],
            ['6', 'Усны жолооч', '3', '6200000', '', '', '', ''],
        ]
        day_header = ['', '', '', '', *[str(float(day)) for day in range(1, 32)]]
        attendance_rows = [
            ['Өрмийн багийн 2026.09.01-2026.09.30 бүртгэл'],
            ['', '', '', '', '10-р сар 1-31'],
            [],
            ['№', 'Нэр', 'Албан тушаал', 'Ажилтны төрөл', 'Тайлант сар'],
            [],
            day_header,
            ['1', 'PRIVATE_MASTER_1', 'Өрмийн мастер', '', 'C18D'],
            ['2', 'PRIVATE_MASTER_2', '', '', 'C18D'],
            ['3', 'PRIVATE_COOK_HELPER', 'Туслах тогооч', '', 'W'],
            ['4', 'PRIVATE_WASHER', 'Угаагч', '', 'P'],
            ['5', 'PRIVATE_HSE', 'ХАБЭА мэргэжилтэн', '', 'W'],
            ['6', 'PRIVATE_CAMP_WORKER', 'Аж ахуйн ажилтан', '', 'W'],
            ['7', 'PRIVATE_DRIVER_1', 'Жолооч', '', 'W'],
            ['8', 'PRIVATE_DRIVER_2', '', '', 'P'],
            ['9', 'PRIVATE_DRIVER_3', '', '', 'P'],
            ['10', 'PRIVATE_DRIVER_4', '', '', 'P'],
        ]
        finance = finance_aggregates(
            [('salary.xlsx', salary_rows)],
            [('attendance.xlsx', attendance_rows)],
            [
                {'date': '2026-10-01', 'rig': 'C-1800', 'shift': 'Өдөр', 'meters': 12},
                {'date': '2026-10-01', 'rig': 'C-1800', 'shift': 'Өдөр', 'meters': 8},
            ],
        )
        self.assertEqual(finance['period'], '2026-10')
        self.assertEqual(finance['daily'], [
            {'date': '2026-10-01', 'laborCost': 791000.0, 'foodCost': 735000.0, 'bonusCost': 452000.0, 'incentiveCost': 271200.0}
        ])
        self.assertAlmostEqual(sum(row['laborCost'] for row in finance['rigShifts']), 791000.0)
        self.assertAlmostEqual(sum(row['foodCost'] for row in finance['rigShifts']), 735000.0)
        day_shift = next(row for row in finance['rigShifts']
                         if row['rig'] == 'C-1800' and row['shift'] == 'Өдөр')
        self.assertEqual(day_shift['laborCost'], 367250.0)
        self.assertEqual(day_shift['foodCost'], 183750.0)
        self.assertEqual(day_shift['bonusCost'],452000.0)
        self.assertEqual(day_shift['incentiveCost'],271200.0)
        # Two active masters, four shared field staff; factory attendance is excluded.
        self.assertAlmostEqual(finance['daily'][0]['laborCost'] + finance['daily'][0]['bonusCost'] + finance['daily'][0]['incentiveCost'], (700000 + 400000 + 240000) * 1.13)
        absent_rows = [r.copy() for r in attendance_rows]
        absent_rows[6][4] = ''
        absent = finance_aggregates([('rates', salary_rows)], [('days', absent_rows)], [{'date':'2026-10-01','rig':'C-1800','shift':'Өдөр','meters':20}])
        self.assertEqual(absent['daily'][0]['laborCost'],678000.0)
        self.assertEqual(absent['daily'][0]['bonusCost'],226000.0)
        self.assertEqual(absent['daily'][0]['incentiveCost'],135600.0)
        self.assertEqual(absent['daily'][0]['foodCost'],735000.0)
        changed=finance_aggregates([('rates', salary_rows)],[('days', attendance_rows)],[{'date':'2026-10-01','rig':'C-1800','shift':'Өдөр','meters':40}])
        self.assertEqual(changed['daily'][0]['laborCost'],finance['daily'][0]['laborCost'])
        self.assertEqual(changed['daily'][0]['foodCost'],finance['daily'][0]['foodCost'])
        self.assertEqual(changed['daily'][0]['bonusCost'],904000.0)
        values = json.loads(json.dumps(finance, ensure_ascii=False))
        def leaves(value):
            if isinstance(value, dict):
                return [leaf for child in value.values() for leaf in leaves(child)]
            if isinstance(value, list):
                return [leaf for child in value for leaf in leaves(child)]
            return [value]
        public_values = leaves(values)
        self.assertFalse(any(isinstance(value, str) and 'PRIVATE_' in value for value in public_values))
        for individual_amount in (3100000, 6200000, 120000, 10000):
            self.assertNotIn(individual_amount, public_values)
        from validate_data import validate
        validate({**self.seed, 'finance': finance})
        unsafe = {**finance, 'daily': [{**finance['daily'][0], 'employeeName': 'PRIVATE_MASTER_1'}]}
        with self.assertRaisesRegex(ValueError, 'employee-level'):
            validate({**self.seed, 'finance': unsafe})

    def test_finance_sources_are_discovered_from_shared_folder_headers(self):
        salary_sheets = [('salary', [
            ['Албан тушаал', 'Ажилтны тоо', 'Нэрлэсэн цалин'],
            ['Өрмийн мастер', '1', '3100000'],
        ])]
        attendance_sheets = [('attendance', [
            ['Өрмийн багийн 2026.09.01-2026.09.30 бүртгэл'],
            ['10-р сар'],
            ['', 'Нэр', 'Албан тушаал'],
            ['', '', '', '', *[str(day) for day in range(1, 32)]],
        ])]
        products_sheets = [('products', [['Бүтээгдэхүүн','Тоо хэмжээ','Нэгж','Үнэ'], ['Mud','25','кг','330000']]), ('usage', [['Нийт тооцооны шуудай','17'], ['Огноо','Өрөм','Цооног','Ээлж','Mud тооцоо (шуудай)'], ['2026-10-01','C-1800','DTDH2601','Өдөр','17']])]
        fuel_sheets=[('ledger',[['Огноо','Зарлага (өрөм) (л)','Өрөмийн Зардал (Төгрөг)'],['2026-10-01','200','1080000']])]
        files = [
            {'id':'fuel-file','mimeType':FINANCE_SHEET_MIME,'modifiedTime':'2026-10-04'},
            {'id':'products-file','mimeType':XLSX_MIME,'modifiedTime':'2026-10-03'},
            {'id': 'attendance-file', 'mimeType': FINANCE_SHEET_MIME, 'modifiedTime': '2026-10-01'},
            {'id': 'salary-file', 'mimeType': XLSX_MIME, 'modifiedTime': '2026-10-02'},
        ]
        sheets_by_content = {b'salary': salary_sheets, b'attendance': attendance_sheets, b'products': products_sheets, b'fuel':fuel_sheets}
        expected = {'period': '2026-10'}
        with (patch('drilling_sync.Drive') as drive,
              patch('drilling_sync.workbook_rows',
                    side_effect=lambda content, _: sheets_by_content[content]),
              patch('drilling_sync.finance_aggregates', return_value=expected) as aggregate):
            drive.return_value.files.side_effect = lambda folder: (
                [{'id': 'nested', 'mimeType': FOLDER_MIME}] if folder == FINANCE_FOLDER_ID
                else files if folder == 'nested' else []
            )
            drive.return_value.download.side_effect = lambda file: (
                b'salary' if file['id'] == 'salary-file' else b'products' if file['id']=='products-file' else b'fuel' if file['id']=='fuel-file' else b'attendance'
            )
            result=drive_finance_aggregates(None, [])
            self.assertEqual(result['mud']['totalBags'],17)
            self.assertEqual(result['mud']['totalBags']*result['mud']['bagKg'],425)
        aggregate.assert_called_once_with(salary_sheets, attendance_sheets, [])

    def test_fuel_ledger_actual_issues_cost_and_missing_values(self):
        sheets=[('ledger',[['Огноо','Зарлага (өрөм) (л)','Өрөмийн Зардал (Төгрөг)'],
                          ['2026-09-30','100','540000'],['2026-10-01','','0'],
                          ['2026-10-02','200','1080000'],['2026-10-03','0','0'],
                          ['2026-10-04','600','3240000']])]
        shifts=[{'date':'2026-10-02','rig':'C-1800','shift':'Өдөр','hole':'X','hours':9},
                {'date':'2026-10-02','rig':'CSD-1300','shift':'Шөнө','hole':'Y','hours':3}]
        fuel=fuel_aggregates(sheets,shifts,'2026-10')
        self.assertEqual(len(fuel['daily']),4)
        self.assertIsNone(fuel['daily'][0]['litres'])
        self.assertEqual(fuel['daily'][2]['litres'],0)
        items=[r for r in fuel['allocations'] if r['date']=='2026-10-02']
        self.assertEqual([r['litres'] for r in items],[150,50])
        self.assertEqual(sum(r['cost'] for r in items),1080000)
        self.assertEqual(sum(r['litres'] for r in fuel['allocations']),800)
        from validate_data import validate_fuel
        validate_fuel(fuel,'2026-10')
        fuel['allocations'][0]['cost']+=100
        with self.assertRaisesRegex(ValueError,'balance'):
            validate_fuel(fuel,'2026-10')

    def test_mud_source_total_and_allocation_must_balance(self):
        sheets=[('products', [['Бүтээгдэхүүн','Тоо хэмжээ','Нэгж','Үнэ'],['Mud','25','кг','330000']]),
                ('usage', [['Нийт тооцооны шуудай','17'],['Огноо','Өрөм','Цооног','Ээлж','Mud тооцоо (шуудай)'],
                           ['2026-10-01','C-1800','DTDH2601','Өдөр','9'],['2026-10-01','CSD-1300','DTDH2602','Шөнө','8']])]
        mud=mud_aggregates(sheets)
        self.assertEqual(sum(r['bags'] for r in mud['allocations']),17)
        self.assertEqual(mud['totalBags']*mud['pricePerBag'],5610000)
        from validate_data import validate_mud
        validate_mud(mud)
        sheets[1][1][-1][-1]='9'
        with self.assertRaisesRegex(ValueError,'balance'):
            mud_aggregates(sheets)

    def test_missing_finance_folder_source_reports_safe_source_name(self):
        with patch('drilling_sync.Drive') as drive:
            drive.return_value.files.return_value = []
            with self.assertRaises(FinanceSourceError) as caught:
                drive_finance_aggregates(None, [])
        self.assertEqual(caught.exception.source, 'finance folder contents not visible to sync account')
        self.assertEqual(caught.exception.status, 403)
        self.assertNotIn(FINANCE_FOLDER_ID, str(caught.exception))

    def test_empty_sources_cannot_overwrite_data(self):
        with self.assertRaises(ValueError):
            assemble([], self.seed)

    def test_browser_json_numbers_and_timestamp_are_equivalent(self):
        self.assertEqual(signature({'meters': 305.0, 'updatedAt': 'a'}),
                         signature({'meters': 305, 'updatedAt': 'b'}))

    def test_publisher_rejects_another_repository(self):
        responses = [CompletedProcess([], 0, str(ROOT)+'\n', ''),
                     CompletedProcess([], 0, 'main\n', ''),
                     CompletedProcess([], 0, 'https://github.com/SysMargad/Mapping.git\n', '')]
        with patch('drilling_sync.subprocess.run', side_effect=responses) as run:
            with self.assertRaisesRegex(RuntimeError, 'origin must be'):
                publish({}, ROOT)
            self.assertEqual(run.call_count, 3)

    def test_collection_log_keeps_real_attempts_and_failure(self):
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / 'data-log.json'
            append_data_log(target, {'id': 'one', 'status': 'updated', 'source': 'local'})
            append_data_log(target, {'id': 'two', 'status': 'failed', 'source': 'drive', 'error': 'HTTP 403'})
            history = load_json(target)['entries']
            self.assertEqual([row['id'] for row in history], ['one', 'two'])
            self.assertEqual(history[-1]['error'], 'HTTP 403')

    def test_publisher_preserves_other_staged_files(self):
        responses = [CompletedProcess([], 0, str(ROOT)+'\n', ''),
                     CompletedProcess([], 0, 'main\n', ''),
                     CompletedProcess([], 0, 'https://github.com/SysMargad/Drilling-Progress.git\n', ''),
                     CompletedProcess([], 0, 'README.md\n', '')]
        with patch('drilling_sync.subprocess.run', side_effect=responses) as run:
            with self.assertRaisesRegex(RuntimeError, 'Other staged files'):
                publish({}, ROOT)
            self.assertEqual(run.call_count, 4)

if __name__ == '__main__':
    unittest.main()
