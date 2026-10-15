"""Validate the generated dataset before publishing public GitHub Pages."""
import math
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
        for key in ('from', 'to', 'meters', 'dt', 'st', 'rt', 'hours'):
            if not isinstance(s[key], (int, float)) or not math.isfinite(s[key]) or s[key] < 0:
                raise ValueError('Invalid shift number')
        if abs(s['to'] - s['from'] - s['meters']) > 0.05 or s['dt'] + s['st'] + s['rt'] > s['hours'] + 0.01:
            raise ValueError('Shift depth or hours mismatch')
    for key in ('driveUrl', 'collarUrl', 'shiftUrl'):
        url = data.get(key, '')
        if url and (urlparse(url).scheme != 'https' or urlparse(url).hostname not in {'drive.google.com', 'docs.google.com'}):
            raise ValueError('Unexpected source URL')
    return len(ids), len(seen)

if __name__ == '__main__':
    holes, shifts = validate(load_json(Path(__file__).parent / 'dist' / 'data.json'))
    print(f'Validated {holes} holes and {shifts} shifts')
