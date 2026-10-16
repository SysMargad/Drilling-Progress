import io
import json
import unittest
import tempfile
from unittest.mock import patch
from subprocess import CompletedProcess
import zipfile
from pathlib import Path
from drilling_sync import (FINANCE_FOLDER_ID, FINANCE_SHEET_MIME, FOLDER_MIME,
                           append_data_log, assemble, drive_finance_aggregates,
                           finance_aggregates, FinanceSourceError, load_json,
                           local_sources, parse_shifts, publish, signature,
                           workbook_rows, report_metadata, attach_reports, drive_sources,
                           XLSX_MIME)

ROOT = Path(__file__).resolve().parent

class PipelineTests(unittest.TestCase):
    def test_blank_optional_time_codes_remain_unknown(self):
        headers=['Rig','Source','Date','Shift','Driller','Hole ID','From','To','Drilled','ST','RT','DT','Total','Work notes']
        row=['CSD-1300','photo','2026-10-14','Өдөр','x','DTDH2605','0','8.4','8.4','','','2.5','12','']
        parsed=parse_shifts([headers,row])[0]
        self.assertIsNone(parsed['st'])
        self.assertIsNone(parsed['rt'])
        self.assertEqual(parsed['dt'],2.5)
        for index,value in [(9,'#REF!'),(9,'-1'),(11,''),(11,'13')]:
            bad=row.copy();bad[index]=value
            with self.assertRaises(ValueError):
                parse_shifts([headers,bad])
        data=self.seed.copy();data['shifts']=[parsed]
        from validate_data import validate
        validate(data)

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
        day_header = ['', '', '', '', *[str(day) for day in range(1, 32)]]
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
            {'date': '2026-10-01', 'laborCost': 1840000.0, 'foodCost': 210000.0}
        ])
        self.assertAlmostEqual(sum(row['laborCost'] for row in finance['rigShifts']), 1840000.0)
        self.assertAlmostEqual(sum(row['foodCost'] for row in finance['rigShifts']), 210000.0)
        day_shift = next(row for row in finance['rigShifts']
                         if row['rig'] == 'C-1800' and row['shift'] == 'Өдөр')
        self.assertEqual(day_shift['laborCost'], 1240000.0)
        self.assertEqual(day_shift['foodCost'], 140000.0)
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
        files = [
            {'id': 'attendance-file', 'mimeType': FINANCE_SHEET_MIME, 'modifiedTime': '2026-10-01'},
            {'id': 'salary-file', 'mimeType': XLSX_MIME, 'modifiedTime': '2026-10-02'},
        ]
        sheets_by_content = {b'salary': salary_sheets, b'attendance': attendance_sheets}
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
                b'salary' if file['id'] == 'salary-file' else b'attendance'
            )
            self.assertEqual(drive_finance_aggregates(None, []), expected)
        aggregate.assert_called_once_with(salary_sheets, attendance_sheets, [])

    def test_missing_finance_folder_source_reports_safe_source_name(self):
        with patch('drilling_sync.Drive') as drive:
            drive.return_value.files.return_value = []
            with self.assertRaises(FinanceSourceError) as caught:
                drive_finance_aggregates(None, [])
        self.assertEqual(caught.exception.source, 'salary workbook in shared finance folder')
        self.assertEqual(caught.exception.status, 404)
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
