import io
import json
import re
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from chat_report import build_message, main, post, shift_key

ROOT = Path(__file__).resolve().parent


def shift(date, name, rig, hole, start, end, dt=10, **extra):
    return {'date': date, 'shift': name, 'rig': rig, 'hole': hole, 'from': start, 'to': end,
            'meters': end - start, 'dt': dt, 'st': None, 'rt': None, 'hours': 12,
            'driller': 'Бат', 'notes': '', 'reports': [], **extra}


def card_text(message):
    widgets = [w for s in message['cardsV2'][0]['card']['sections'] for w in s['widgets']]
    texts = [w['textParagraph']['text'] for w in widgets if 'textParagraph' in w]
    return [re.sub(r'<[^>]+>', '', text.replace('<br>', '\n')) for text in texts]


class ChatReportTests(unittest.TestCase):
    def setUp(self):
        self.old = [shift('2026-10-28', 'Өдөр', 'C-1800', 'ZHDH2604', 293, 338),
                    shift('2026-10-28', 'Өдөр', 'CSD-1300', 'ZHDH2606', 134.4, 161.4)]
        self.added = [shift('2026-10-28', 'Шөнө', 'C-1800', 'ZHDH2604', 338, 365, dt=6),
                      shift('2026-10-29', 'Өдөр', 'C-1800', 'ZHDH2604', 365, 395,
                            reports=[{'url': 'https://drive.google.com/file/d/x/view'}])]
        self.data = {'period': '2026-10-01 – 2026-10-29', 'shifts': self.old + self.added, 'collar': [
            {'id': 'ZHDH2604', 'targetArea': 'Замт Хөндий', 'plan': 450, 'start': '2026-10-24', 'finish': ''},
            {'id': 'ZHDH2606', 'targetArea': 'Замт Хөндий', 'plan': 230, 'start': '2026-10-26', 'finish': ''},
            {'id': 'ZHDH2605', 'targetArea': 'Замт Хөндий', 'plan': 160, 'collarDepth': 170.4,
             'start': '2026-10-24', 'finish': '2026-10-26', 'recovery': None, 'boxes': 49},
            {'id': 'ZHDH2612', 'targetArea': 'Замт Хөндий', 'plan': None, 'start': '', 'finish': ''}],
            'finance': {'daily': [{'date': '2026-10-29', 'laborCost': 1731451.62}]}}

    def run_report(self, folder, *args, fail=False):
        data, ledger = Path(folder) / 'data.json', Path(folder) / 'chat-posted.json'
        data.write_text(json.dumps(self.data, ensure_ascii=False), encoding='utf-8')
        argv = ['chat_report.py', '--data', str(data), '--ledger', str(ledger), *args]
        with patch('sys.argv', argv), patch.dict('os.environ', {'GOOGLE_CHAT_WEBHOOK_URL': 'https://chat.googleapis.com/x'}), \
                patch('chat_report.post', side_effect=OSError('HTTP 500') if fail else None) as sent, \
                patch('sys.stdout', io.StringIO()):
            try:
                main()
            except OSError:
                pass
        posted = json.loads(ledger.read_text(encoding='utf-8'))['posted'] if ledger.exists() else None
        return sent, posted

    def test_the_evening_card_shows_each_rigs_latest_date(self):
        with tempfile.TemporaryDirectory() as folder:
            sent, posted = self.run_report(folder)
            sent.assert_not_called()  # First run records history instead of flooding the space.
            self.assertEqual(len(posted), 4)
            ledger = Path(folder) / 'chat-posted.json'
            ledger.write_text(json.dumps({'posted': [list(shift_key(row)) for row in self.old]}), encoding='utf-8')
            sent, posted = self.run_report(folder, fail=True)
            self.assertEqual(len(posted), 2, 'a failed post records nothing')
            # C-1800's latest date is 29 Oct, CSD-1300's 28 Oct. The 28 Oct night of C-1800 came in late: it is in
            # the totals but not on the card, and no longer waits to be posted.
            sent, posted = self.run_report(folder)
            card = sent.call_args.args[1]['cardsV2'][0]['card']
            self.assertEqual(card['header']['subtitle'], 'Нэргүй Өндөр · C-1800 10-29 · CSD-1300 10-28 · 1 шинэ ээлж')
            text = '\n'.join(card_text(sent.call_args.args[1]))
            self.assertIn('10-29 Өдөр : 365 – 395 м', text)
            self.assertIn('10-28 Өдөр : 134.4 – 161.4 м', text)
            self.assertNotIn('10-28 Шөнө', text)
            self.assertIn('C-1800 : 102 м · 3 ээлж', text)
            self.assertEqual(len(posted), 4)
            # Nothing new: the card still goes out with the same latest dates.
            sent, unchanged = self.run_report(folder)
            self.assertEqual(sent.call_args.args[1]['cardsV2'][0]['card']['header']['subtitle'],
                             'Нэргүй Өндөр · C-1800 10-29 · CSD-1300 10-28 · шинэ ээлж ороогүй')
            self.assertEqual(unchanged, posted)
            sent, _ = self.run_report(folder, '--date', '2026-10-30')
            sent.assert_not_called()
            sent, _ = self.run_report(folder, '--date', '2026-10-29')
            self.assertIn('1 шинэ ээлж', sent.call_args.args[1]['cardsV2'][0]['card']['header']['subtitle'])
            del self.data['shifts'][0]
            _, posted = self.run_report(folder, '--date', '2026-10-29')
            self.assertNotIn(['C-1800', '2026-10-28', 'Өдөр', 'ZHDH2604'], posted)

    def test_a_shift_refiled_under_a_corrected_hole_is_not_posted_again(self):
        with tempfile.TemporaryDirectory() as folder:
            self.run_report(folder)
            ledger = Path(folder) / 'chat-posted.json'
            self.data['shifts'][0] = {**self.old[0], 'hole': 'ZHDH2602', 'correction': {'hole': 'ZHDH2604'}}
            sent, posted = self.run_report(folder)
            self.assertTrue(sent.call_args.args[1]['cardsV2'][0]['card']['header']['subtitle'].endswith('шинэ ээлж ороогүй'))
            self.assertIn(['C-1800', '2026-10-28', 'Өдөр', 'ZHDH2604'], posted, 'the key under the old hole is kept')
            self.assertTrue(ledger.exists())

    def test_card_starts_with_hole_progress_and_leaves_out_finance(self):
        message = build_message(self.data, list(reversed(self.added)))
        card = message['cardsV2'][0]['card']
        self.assertEqual(card['header']['subtitle'], 'Нэргүй Өндөр · 2026-10-28 – 2026-10-29 · 2 шинэ ээлж')
        hole, daily, progress, performance = card_text(message)
        self.assertTrue(hole.startswith('ZHDH2604 · Замт Хөндий · C-1800\n'))
        self.assertIn('Гүн : 395 / 450 м (88%)', hole)
        self.assertLess(hole.index('10-28 Шөнө : 338 – 365 м · 27 м'), hole.index('10-29 Өдөр : 365 – 395 м · 30 м'))
        self.assertIn('DT 6 ц · ROP 4.5 м/ц · Бат', hole)
        self.assertIn('Нийт : 57 м', hole)
        self.assertIn('<a href="https://drive.google.com/file/d/x/view">тайлан</a>',
                      card['sections'][0]['widgets'][0]['textParagraph']['text'])
        self.assertIn('C-1800 : 72 м\nCSD-1300 : 27 м · Шөнө мэдээ ороогүй\n', daily)
        self.assertIn('C-1800 : 30 м · Шөнө мэдээ ороогүй\nCSD-1300 : мэдээ ороогүй', daily)
        self.assertEqual(progress.splitlines()[1:], [
            'ZHDH2604 · Өрөмдөж байна · 395 / 450 м · 88%', 'ZHDH2606 · Өрөмдөж байна · 161.4 / 230 м · 70%',
            'ZHDH2612 · Төлөвлөсөн', 'ZHDH2605 · Дууссан 10-26 · 170.4 м'])
        self.assertIn('Өрөмдсөн : 129 м', performance)
        self.assertIn('C-1800 : 102 м · 3 ээлж', performance)
        self.assertNotIn('₮', json.dumps(message, ensure_ascii=False))
        self.assertNotIn('1731451', json.dumps(message))

    def test_corrected_rig_is_aggregated_under_c1800(self):
        added = shift('2026-10-29', 'Шөнө', 'C-1800', 'STDH2601', 0, 18)
        self.data['shifts'].append(added)
        *_, daily, _, performance = card_text(build_message(self.data, [added, self.added[0]]))
        self.assertNotIn('C-1600', daily.split('2026-10-29')[0])
        self.assertNotIn('C-1600', daily + performance)
        self.assertIn('C-1800 : 48 м', daily)
        self.assertIn('C-1800 : 120 м · 4 ээлж', performance)

    def test_finished_hole_shows_core_summary_and_escapes_text(self):
        self.data['shifts'].append(shift('2026-10-26', 'Өдөр', 'CSD-1300', 'ZHDH2605', 128.4, 170, driller='<b>x</b>'))
        hole = card_text(build_message(self.data, self.data['shifts'][-1:]))[0]
        self.assertIn('Төлөв : Дууссан', hole)
        self.assertIn('Дууссан 2026-10-26 : Collar 170.4 м · 49 хайрцаг', hole)
        self.assertIn('&lt;b&gt;x&lt;/b&gt;', json.dumps(build_message(self.data, self.data['shifts'][-1:])))

    def test_live_data_builds_a_card_within_chat_limits(self):
        data = json.loads((ROOT / 'dist' / 'data.json').read_text(encoding='utf-8'))
        latest = max(row['date'] for row in data['shifts'])
        message = build_message(data, [row for row in data['shifts'] if row['date'] == latest])
        self.assertLess(len(json.dumps(message, ensure_ascii=False).encode('utf-8')), 32000)
        self.assertNotIn('₮', json.dumps(message, ensure_ascii=False))

    def test_post_sends_utf8_json_only_to_google_chat(self):
        with patch('urllib.request.urlopen') as urlopen:
            post('https://chat.googleapis.com/v1/spaces/X/messages?key=k&token=t', {'text': 'Өрөм'})
        request = urlopen.call_args.args[0]
        self.assertEqual(request.get_header('Content-type'), 'application/json; charset=UTF-8')
        self.assertEqual(json.loads(request.data.decode('utf-8')), {'text': 'Өрөм'})
        with self.assertRaises(ValueError):
            post('https://example.com/hook', {'text': 'x'})


if __name__ == '__main__':
    unittest.main()
