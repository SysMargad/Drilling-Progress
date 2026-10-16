"""Validate the generated dataset before publishing public GitHub Pages."""
import math
import re
from datetime import date
from pathlib import Path
from urllib.parse import urlparse
from drilling_sync import load_json

def validate(data):
    if not data.get('collar') or not data.get('shifts'):
        raise ValueError('Collar and shift records are required')
    ids = set()
    for h in data['collar']:
        if h.get('site') != 'Нэргүй Өндөр':
            raise ValueError('All holes must belong to Нэргүй Өндөр')
        if h.get('targetArea') not in {'Дорнын Төмөр', 'Замт Хөндий'}:
            raise ValueError('Unknown drilling area')
        if h['id'] in ids:
            raise ValueError('Duplicate hole ID')
        ids.add(h['id'])
        for key in ('e', 'n', 'z', 'az', 'dip', 'plan', 'collarDepth', 'recovery', 'boxes'):
            value = h[key]
            if value is not None and (not isinstance(value, (int, float)) or not math.isfinite(value) or value < 0):
                raise ValueError('Invalid collar number')
    seen = set()
    for s in data['shifts']:
        key = (s['rig'], s['date'], s['shift'], s['hole'])
        if key in seen or s['hole'] not in ids:
            raise ValueError('Duplicate shift or unknown hole')
        seen.add(key)
        date.fromisoformat(s['date'])
        for report in s.get('reports', []):
            url = urlparse(report['url'])
            if url.scheme != 'https' or url.hostname != 'drive.google.com' or not url.path.startswith('/file/d/'):
                raise ValueError('Unexpected report URL')
            if any(report.get(k) != s[k] for k in ('hole', 'rig', 'date', 'shift')):
                raise ValueError('Report provenance does not match shift')
        for key in ('from', 'to', 'meters', 'dt', 'st', 'rt', 'hours'):
            if key in {'st', 'rt'} and s[key] is None:
                continue
            if not isinstance(s[key], (int, float)) or not math.isfinite(s[key]) or s[key] < 0:
                raise ValueError('Invalid shift number')
        if abs(s['to'] - s['from'] - s['meters']) > 0.05 or s['dt'] + (s['st'] or 0) + (s['rt'] or 0) > s['hours'] + 0.01:
            raise ValueError('Shift depth or hours mismatch')
    for key in ('driveUrl', 'collarUrl', 'shiftUrl'):
        url = data.get(key, '')
        if url and (urlparse(url).scheme != 'https' or urlparse(url).hostname not in {'drive.google.com', 'docs.google.com'}):
            raise ValueError('Unexpected source URL')
    if 'finance' in data:
        validate_finance(data['finance'])
    return len(ids), len(seen)


def validate_finance(finance):
    if set(finance) != {'period', 'daily', 'rigShifts'}:
        raise ValueError('Finance data must contain aggregate fields only')
    if not isinstance(finance['period'], str) or not re.fullmatch(r'\d{4}-\d{2}', finance['period']):
        raise ValueError('Invalid finance period')
    daily = {}
    for row in finance['daily']:
        if set(row) != {'date', 'laborCost', 'foodCost'}:
            raise ValueError('Finance daily rows must not contain employee-level fields')
        date.fromisoformat(row['date'])
        if row['date'][:7] != finance['period'] or row['date'] in daily:
            raise ValueError('Invalid or duplicate finance date')
        for key in ('laborCost', 'foodCost'):
            value = row[key]
            if not isinstance(value, (int, float)) or not math.isfinite(value) or value < 0:
                raise ValueError('Invalid aggregate finance amount')
        daily[row['date']] = row
    by_date = {}
    seen = set()
    for row in finance['rigShifts']:
        if set(row) != {'date', 'rig', 'shift', 'laborCost', 'foodCost'}:
            raise ValueError('Finance shift rows must contain aggregate fields only')
        date.fromisoformat(row['date'])
        key = (row['date'], row['rig'], row['shift'])
        if (row['date'][:7] != finance['period'] or row['rig'] not in {'C-1800', 'CSD-1300'} or
                row['shift'] not in {'Өдөр', 'Шөнө'} or key in seen):
            raise ValueError('Invalid or duplicate finance rig shift')
        seen.add(key)
        totals = by_date.setdefault(row['date'], {'laborCost': 0.0, 'foodCost': 0.0})
        for amount in ('laborCost', 'foodCost'):
            value = row[amount]
            if not isinstance(value, (int, float)) or not math.isfinite(value) or value < 0:
                raise ValueError('Invalid aggregate finance amount')
            totals[amount] += value
    if set(daily) != set(by_date):
        raise ValueError('Finance daily and rig-shift aggregates do not align')
    for date_key, totals in by_date.items():
        for amount in ('laborCost', 'foodCost'):
            if not math.isclose(totals[amount], daily[date_key][amount], abs_tol=0.05):
                raise ValueError('Finance aggregate allocation does not balance')


if __name__ == '__main__':
    holes, shifts = validate(load_json(Path(__file__).parent / 'dist' / 'data.json'))
    print(f'Validated {holes} holes and {shifts} shifts')
