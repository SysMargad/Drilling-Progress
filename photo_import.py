"""Owner-verified photograph records, retained across automatic Drive refreshes."""
import copy
import json
from pathlib import Path

PATH = Path(__file__).resolve().parent / 'input' / 'photo-records.json'


def apply_photos(data, path=PATH):
    if not Path(path).exists():
        return data
    config = json.loads(Path(path).read_text(encoding='utf-8'))
    data = copy.deepcopy(data)
    for hole in config['collar']:
        if not any(h['id'] == hole['id'] for h in data['collar']):
            data['collar'].append(hole)
    for row in config['shifts']:
        key = tuple(row[k] for k in ('date', 'rig', 'shift', 'hole'))
        existing = next((s for s in data['shifts'] if tuple(s[k] for k in ('date', 'rig', 'shift', 'hole')) == key), None)
        # Drive may later acquire the original report; prefer that authoritative row.
        if existing is None:
            data['shifts'].append(row)
    data['shifts'].sort(key=lambda s: (s['date'], s['rig'], s['shift']))
    dates = [s['date'] for s in data['shifts']]
    data['period'] = min(dates) + ' – ' + max(dates)
    return data


def apply_daily_water(data, path=PATH):
    config = json.loads(Path(path).read_text(encoding='utf-8'))
    if not data.get('finance'):
        return data
    data = copy.deepcopy(data)
    water = data['finance'].setdefault('water', {'records': []})
    water.update(litresPerTrip=5000, estimated=False)
    water['dailyRecords'] = [r for r in config['waterDaily'] if r['date'].startswith(data['finance']['period'] + '-')]
    covered = {(r['date'], r['rig']) for r in water['dailyRecords']}
    water['records'] = [r for r in water['records'] if (r['date'], r['rig']) not in covered]
    return data
