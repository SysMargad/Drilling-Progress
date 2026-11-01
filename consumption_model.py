"""Verified shift issues and explicitly estimated water; no vehicle-fuel costs."""
from collections import defaultdict
from datetime import datetime, timedelta
from pathlib import Path
import json
import math

SHEET_ID = '1xQTv-Hc7hpq2S7HmdMaPKHcg7IyGMkAAcWNK9OLk_QY'
ROOT = Path(__file__).resolve().parent
RIGS = {'C-1800', 'CSD-1300'}
SHIFTS = {'Өдөр', 'Шөнө'}


def day(value):
    value = str(value).strip()
    if value.replace('.', '', 1).isdigit():
        return (datetime(1899, 12, 30) + timedelta(days=float(value))).date().isoformat()
    return datetime.strptime(value[:10], '%Y-%m-%d').date().isoformat()


def positive(value, zero=False):
    result = float(str(value).replace(',', ''))
    if not math.isfinite(result) or result < 0 or (result == 0 and not zero):
        raise ValueError('Invalid consumption quantity')
    return result


def parse_corrections(sheets):
    result = {'fuelIssues': [], 'waterTrips': []}
    for _, rows in sheets:
        headers = None
        kind = None
        for row in rows:
            if row and row[0] == 'Үнэ ₮/л':
                result['pricePerLitre'] = positive(row[1])
            if row and row[0] == 'Литр / рейс (таамаг)':
                result['litresPerTrip'] = positive(row[1])
            if 'Олгосон түлш (л)' in row and 'Ээлж' in row:
                headers, kind = row, 'fuel'
                continue
            if 'Тооцоот ус (л)' in row and 'Рейс' in row:
                headers, kind = row, 'water'
                continue
            if not headers or not row or str(row[0]).startswith('НИЙТ'):
                continue
            def get(label):
                index = headers.index(label)
                return row[index] if index < len(row) else ''
            if not get('Огноо'):
                continue
            status = get('Төлөв')
            if status not in ('Баталгаатай', 'Таамаг'):
                continue
            item = {'date': day(get('Огноо')), 'rig': get('Өрөм'), 'shift': get('Ээлж')}
            if kind == 'fuel':
                item['litres'] = positive(get('Олгосон түлш (л)'), zero=True)
                result['fuelIssues'].append(item)
            else:
                item.update(hole=get('Цооног'), trips=positive(get('Рейс'), zero=True))
                result['waterTrips'].append(item)
    if not result['fuelIssues'] or not result['waterTrips'] or 'pricePerLitre' not in result or 'litresPerTrip' not in result:
        raise ValueError('Consumption correction tables or assumptions missing')
    validate_config(result)
    return result


def validate_config(config):
    positive(config['pricePerLitre'])
    positive(config['litresPerTrip'])
    for field in ('fuelIssues', 'waterTrips'):
        seen = set()
        for row in config[field]:
            day(row['date'])
            key = (row['date'], row['rig'], row['shift'])
            if key in seen or row['rig'] not in RIGS or row['shift'] not in SHIFTS:
                raise ValueError('Duplicate or invalid consumption shift')
            seen.add(key)
            positive(row['litres' if field == 'fuelIssues' else 'trips'], zero=True)


def load_corrections(drive=None, workbook_reader=None):
    """Read the editable Sheet; caller may report a failure and use the snapshot."""
    if drive is not None:
        content = drive.download({'id': SHEET_ID, 'mimeType': 'application/vnd.google-apps.spreadsheet'})
        return parse_corrections(workbook_reader(content, '.xlsx'))
    result = json.loads((ROOT / 'input' / 'consumption-corrections.json').read_text(encoding='utf-8'))
    validate_config(result)
    return result


def apply_corrections(data, config):
    validate_config(config)
    if data.get('finance') is None:
        return data
    data = {**data, 'finance': dict(data['finance']), 'shifts': [dict(row) for row in data['shifts']]}
    finance = data['finance']
    period = finance['period']
    issues = [row for row in config['fuelIssues'] if row['date'].startswith(period + '-')]
    by_date = defaultdict(list)
    for row in issues:
        by_date[row['date']].append(row)
    fuel = finance['fuel']
    daily = {row['date']: dict(row) for row in fuel['daily']}
    allocations = [dict(row) for row in fuel['allocations'] if row['date'] not in by_date]
    coverage = [dict(row) for row in fuel.get('coverage', []) if row['date'] not in by_date]
    for date, entries in sorted(by_date.items()):
        items = [{'date': date, 'rig': row['rig'], 'shift': row['shift'], 'hole': '',
                  'litres': row['litres'], 'cost': round(row['litres'] * config['pricePerLitre'], 2)} for row in entries]
        daily[date] = {'date': date, 'litres': round(sum(row['litres'] for row in items), 2),
                       'cost': round(sum(row['cost'] for row in items), 2)}
        allocations.extend(items)
        coverage.append({'date': date, 'recordedShifts': len(entries), 'expectedShifts': 4})
    finance['fuel'] = {'daily': sorted(daily.values(), key=lambda row: row['date']),
                       'allocations': allocations, 'coverage': sorted(coverage, key=lambda row: row['date'])}
    records = [{**{key: row[key] for key in ('date', 'rig', 'shift', 'hole', 'trips')},
                'litres': row['trips'] * config['litresPerTrip']} for row in config['waterTrips']
               if row['date'].startswith(period + '-')]
    finance['water'] = {'litresPerTrip': config['litresPerTrip'], 'estimated': True, 'records': records}
    for row in data['shifts']:
        matching = [r for r in records if all(r[key] == row[key] for key in ('date', 'rig', 'shift', 'hole'))]
        if matching and (row.get('waterUsageM3') is None or row.get('waterUsageEstimated')):
            # One delivery belongs to the shift; split-row handling is done in the browser.
            row['waterUsageM3'] = matching[0]['litres'] / 1000
            row['waterUsageEstimated'] = True
    return data
