import io
import unittest
import tempfile
from unittest.mock import patch
from subprocess import CompletedProcess
import zipfile
from pathlib import Path
from drilling_sync import append_data_log, assemble, load_json, local_sources, parse_shifts, publish, signature, workbook_rows

ROOT = Path(__file__).resolve().parent

class PipelineTests(unittest.TestCase):
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
