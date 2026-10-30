import json
import re
import unittest
from pathlib import Path
from unittest.mock import patch

from chat_report import build_message, new_shifts, post

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

    def test_only_shifts_added_since_previous_sync_are_reported(self):
        corrected = {**self.old[1], 'to': 161.0}
        self.assertEqual(new_shifts({'shifts': self.old}, {'shifts': [self.old[0], corrected] + self.added}),
                         self.added)
        self.assertEqual(new_shifts({'shifts': self.old + self.added}, self.data), [])

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
