"""Validate the generated dataset before publishing public GitHub Pages."""
import math
import re
from datetime import date
from pathlib import Path
from urllib.parse import urlparse
from drilling_sync import load_json, RIGS

def validate(data):
    if not data.get('collar') or not data.get('shifts'):
        raise ValueError('Collar and shift records are required')
    ids = set()
    for h in data['collar']:
        if h.get('site') != 'Нэргүй Өндөр':
            raise ValueError('All holes must belong to Нэргүй Өндөр')
        # New areas (Сант, ...) come from the hole prefix or its Drive area folder.
        area = h.get('targetArea')
        if not isinstance(area, str) or not area.strip() or len(area) > 60:
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
        if s['rig'] not in RIGS:
            raise ValueError('Unknown drilling rig')
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
        water = s.get('waterUsageM3')
        if water is not None and (not isinstance(water, (int, float)) or not math.isfinite(water) or water < 0):
            raise ValueError('Invalid water consumption volume')
        if abs(s['to'] - s['from'] - s['meters']) > 0.05 or s['dt'] + (s['st'] or 0) + (s['rt'] or 0) > s['hours'] + 0.01:
            raise ValueError('Shift depth or hours mismatch')
    for key in ('driveUrl', 'collarUrl', 'shiftUrl'):
        url = data.get(key, '')
        if url and (urlparse(url).scheme != 'https' or urlparse(url).hostname not in {'drive.google.com', 'docs.google.com'}):
            raise ValueError('Unexpected source URL')
    for url in [s['sheet'].get('url', '') for s in data['shifts'] if s.get('sheet')] +                [r.get('url', '') for key in ('unassignedShifts', 'rejectedShifts') for r in data.get(key, [])]:
        if url and (urlparse(url).scheme != 'https' or urlparse(url).hostname not in {'drive.google.com', 'docs.google.com'}):
            raise ValueError('Unexpected source sheet URL')
    for report in data.get('unlinkedReports', []):
        drive_file(report['url'])
    if 'shiftAudit' in data:
        validate_audit(data['shiftAudit'], data)
    if 'finance' in data:
        validate_finance(data['finance'])
    return len(ids), len(seen)


def drive_file(url):
    parsed = urlparse(url)
    if parsed.scheme != 'https' or parsed.hostname != 'drive.google.com' or not parsed.path.startswith('/file/d/'):
        raise ValueError('Unexpected report URL')


def validate_audit(audit, data):
    """Every rig-shift slot classified once; a slot without a record never carries metres."""
    from shift_audit import STATUSES
    if set(audit['rigs']) - RIGS or not re.fullmatch(r'\d{4}-\d{2}-\d{2}', audit['through']):
        raise ValueError('Invalid shift audit header')
    seen, months = set(), {}
    for slot in audit['slots']:
        key = (slot['rig'], slot['date'], slot['shift'])
        if key in seen or slot['rig'] not in audit['rigs'] or slot['shift'] not in {'Өдөр', 'Шөнө'} or slot['status'] not in STATUSES:
            raise ValueError('Invalid or duplicate shift audit slot')
        seen.add(key)
        date.fromisoformat(slot['date'])
        if (slot['meters'] is None) != (not slot['records']):
            raise ValueError('An unreported shift cannot carry metres')
        # Metres inferred from depth belong to a shift without its report, never to a verified one.
        if slot.get('inferred') and (slot['status'] != 'MISSING_REPORT' or any(i['meters'] <= 0 or i['to'] - i['from'] - i['meters'] > 0.05 for i in slot['inferred'])):
            raise ValueError('Inferred metres only fill a missing report')
        for report in [x for r in slot['records'] for x in r['reports']] + slot.get('driveReports', []):
            drive_file(report['url'])
        if slot['folderUrl'] and urlparse(slot['folderUrl']).hostname != 'drive.google.com':
            raise ValueError('Unexpected audit folder URL')
        months[slot['date'][:7]] = months.get(slot['date'][:7], 0) + 1
    for month in audit['months']:
        if month['expected'] != months.get(month['month']) or sum(month['counts'].values()) != month['expected']:
            raise ValueError('Shift audit counts do not add up')
    for report in audit.get('foreman', []):
        if any(row['status'] not in {'agree', 'rounded', 'differs'} or row['rig'] not in RIGS for row in report['rows']):
            raise ValueError('Invalid foreman report check')
    recorded = {(s['rig'], s['date'], s['shift']) for s in data['shifts'] if s['rig'] in audit['rigs'] and s['date'] <= audit['through']}
    if recorded - seen:
        raise ValueError('Shift audit misses recorded shifts')


def validate_finance(finance):
    if set(finance) - {'diamond', 'water', 'payPeriods'} not in ({'period', 'daily', 'rigShifts'}, {'period', 'daily', 'rigShifts', 'mud'}, {'period', 'daily', 'rigShifts', 'mud', 'fuel'}):
        raise ValueError('Finance data must contain aggregate fields only')
    if not isinstance(finance['period'], str) or not re.fullmatch(r'\d{4}-\d{2}', finance['period']):
        raise ValueError('Invalid finance period')
    # Which dates the actual pay-period workbooks cover (payroll_import.py): file name and dates, no amounts.
    for item in finance.get('payPeriods', []):
        if (set(item) != {'file', 'start', 'end', 'source', 'bonus'} or not isinstance(item['file'], str)
                or item['source'] not in {'drive', 'snapshot'} or not isinstance(item['bonus'], bool)
                or not item['start'].startswith(finance['period'] + '-') or not item['end'].startswith(finance['period'] + '-')
                or date.fromisoformat(item['end']) < date.fromisoformat(item['start'])):
            raise ValueError('Invalid pay-period provenance')
    if 'fuel' in finance:
        validate_fuel(finance['fuel'], finance['period'])
    if 'water' in finance:
        water = finance['water']
        if set(water) - {'dailyRecords'} != {'litresPerTrip', 'estimated', 'records'} or not isinstance(water['estimated'], bool):
            raise ValueError('Water conversion must be explicitly estimated')
        if not isinstance(water['litresPerTrip'], (int, float)) or not math.isfinite(water['litresPerTrip']) or water['litresPerTrip'] <= 0:
            raise ValueError('Invalid water trip capacity')
        seen_water = set()
        for row in water.get('dailyRecords', []):
            key = (row['date'], row['rig'])
            if set(row) != {'date', 'rig', 'trips', 'litres'} or key in seen_water or row['rig'] not in {'C-1800','CSD-1300'} or not row['date'].startswith(finance['period'] + '-'):
                raise ValueError('Invalid daily water record')
            seen_water.add(key)
            date.fromisoformat(row['date'])
            if not all(isinstance(row[k], (int,float)) and math.isfinite(row[k]) and row[k] >= 0 for k in ('trips','litres')) or not math.isclose(row['litres'], row['trips'] * water['litresPerTrip'], abs_tol=0.01):
                raise ValueError('Daily water trips do not reconcile')
        for row in water['records']:
            if (row['date'],row['rig']) in seen_water:
                raise ValueError('Water daily and shift records overlap')
            key = (row['date'], row['rig'], row['shift'])
            if set(row) != {'date', 'rig', 'shift', 'hole', 'trips', 'litres'} or key in seen_water or not row['date'].startswith(finance['period'] + '-') or row['rig'] not in {'C-1800', 'CSD-1300'} or row['shift'] not in {'Өдөр', 'Шөнө'}:
                raise ValueError('Invalid water delivery record')
            seen_water.add(key)
            date.fromisoformat(row['date'])
            if not all(isinstance(row[k], (int, float)) and math.isfinite(row[k]) and row[k] >= 0 for k in ('trips', 'litres')) or not math.isclose(row['litres'], row['trips'] * water['litresPerTrip'], abs_tol=0.01):
                raise ValueError('Water trips and litres do not reconcile')
    if 'mud' in finance:
        validate_mud(finance['mud'])
    if 'diamond' in finance:
        diamond = finance['diamond']
        if set(diamond) != {'plannedMeters', 'totalBudget', 'ratePerMeter', 'sourceUrl'}:
            raise ValueError('Unexpected diamond budget fields')
        for key in ('plannedMeters', 'totalBudget', 'ratePerMeter'):
            if not isinstance(diamond[key], (int, float)) or not math.isfinite(diamond[key]) or diamond[key] <= 0:
                raise ValueError('Invalid diamond budget amount')
        if not math.isclose(diamond['ratePerMeter'] * diamond['plannedMeters'], diamond['totalBudget'], abs_tol=0.01):
            raise ValueError('Diamond unit rate does not reconcile')
        source = urlparse(diamond['sourceUrl'])
        if source.scheme != 'https' or source.hostname != 'docs.google.com' or not source.path.startswith('/spreadsheets/d/'):
            raise ValueError('Invalid diamond budget source')
    daily = {}
    for row in finance['daily']:
        if set(row) not in ({'date', 'laborCost', 'foodCost'}, {'date', 'laborCost', 'foodCost', 'bonusCost'}, {'date', 'laborCost', 'foodCost', 'bonusCost', 'incentiveCost'}):
            raise ValueError('Finance daily rows must not contain employee-level fields')
        date.fromisoformat(row['date'])
        if row['date'][:7] != finance['period'] or row['date'] in daily:
            raise ValueError('Invalid or duplicate finance date')
        for key in ('laborCost', 'foodCost', 'bonusCost', 'incentiveCost'):
            value = row.get(key, 0)
            if not isinstance(value, (int, float)) or not math.isfinite(value) or value < 0:
                raise ValueError('Invalid aggregate finance amount')
        daily[row['date']] = row
    by_date = {}
    seen = set()
    for row in finance['rigShifts']:
        if set(row) not in ({'date', 'rig', 'shift', 'laborCost', 'foodCost'}, {'date', 'rig', 'shift', 'laborCost', 'foodCost', 'bonusCost'}, {'date', 'rig', 'shift', 'laborCost', 'foodCost', 'bonusCost', 'incentiveCost'}):
            raise ValueError('Finance shift rows must contain aggregate fields only')
        date.fromisoformat(row['date'])
        key = (row['date'], row['rig'], row['shift'])
        if (row['date'][:7] != finance['period'] or row['rig'] not in {'C-1800', 'CSD-1300'} or
                row['shift'] not in {'Өдөр', 'Шөнө'} or key in seen):
            raise ValueError('Invalid or duplicate finance rig shift')
        seen.add(key)
        totals = by_date.setdefault(row['date'], {'laborCost': 0.0, 'foodCost': 0.0, 'bonusCost': 0.0, 'incentiveCost': 0.0})
        for amount in ('laborCost', 'foodCost', 'bonusCost', 'incentiveCost'):
            value = row.get(amount, 0)
            if not isinstance(value, (int, float)) or not math.isfinite(value) or value < 0:
                raise ValueError('Invalid aggregate finance amount')
            totals[amount] += value
    if set(daily) != set(by_date):
        raise ValueError('Finance daily and rig-shift aggregates do not align')
    for date_key, totals in by_date.items():
        for amount in ('laborCost', 'foodCost', 'bonusCost', 'incentiveCost'):
            if not math.isclose(totals[amount], daily[date_key].get(amount, 0), abs_tol=0.05):
                raise ValueError('Finance aggregate allocation does not balance')


def validate_mud(mud):
    if set(mud) != {'totalBags', 'bagKg', 'pricePerBag', 'allocations'}:
        raise ValueError('Unexpected mud fields')
    for key in ('totalBags', 'bagKg', 'pricePerBag'):
        if not isinstance(mud[key], (int, float)) or not math.isfinite(mud[key]) or mud[key] <= 0:
            raise ValueError('Invalid mud total or unit')
    seen = set()
    for row in mud['allocations']:
        if set(row) != {'date', 'rig', 'shift', 'hole', 'bags'}:
            raise ValueError('Unexpected mud allocation fields')
        date.fromisoformat(row['date'])
        key = (row['date'], row['rig'], row['shift'], row['hole'])
        if key in seen or row['rig'] not in {'C-1800', 'CSD-1300'} or row['shift'] not in {'Өдөр', 'Шөнө'} or not row['hole']:
            raise ValueError('Invalid mud allocation key')
        seen.add(key)
        if not isinstance(row['bags'], (int, float)) or not math.isfinite(row['bags']) or row['bags'] < 0:
            raise ValueError('Invalid mud allocation volume')
    if not math.isclose(sum(row['bags'] for row in mud['allocations']), mud['totalBags'], abs_tol=0.00001):
        raise ValueError('Mud allocations do not balance to total')


def validate_fuel(fuel, period):
    if set(fuel) - {'coverage'} != {'daily', 'allocations'}:
        raise ValueError('Unexpected fuel fields')
    coverage_dates = set()
    for row in fuel.get('coverage', []):
        if set(row) != {'date', 'recordedShifts', 'expectedShifts'} or row['date'] in coverage_dates or not row['date'].startswith(period + '-') or row['expectedShifts'] != 4 or not isinstance(row['recordedShifts'], int) or not 0 <= row['recordedShifts'] <= 4:
            raise ValueError('Invalid fuel coverage')
        coverage_dates.add(row['date'])
    daily = {}
    for row in fuel['daily']:
        if set(row) != {'date', 'litres', 'cost'} or row['date'] in daily or not row['date'].startswith(period+'-'):
            raise ValueError('Invalid fuel daily fields or duplicate date')
        date.fromisoformat(row['date'])
        if (row['litres'] is None) != (row['cost'] is None):
            raise ValueError('Fuel quantity and cost must be known together')
        for key in ('litres','cost'):
            if row[key] is not None and (not isinstance(row[key],(int,float)) or not math.isfinite(row[key]) or row[key]<0):
                raise ValueError('Invalid fuel amount')
        daily[row['date']] = row
    totals, seen = {}, set()
    for row in fuel['allocations']:
        if set(row) != {'date','rig','shift','hole','litres','cost'}:
            raise ValueError('Unexpected fuel allocation fields')
        key=(row['date'],row['rig'],row['shift'],row['hole'])
        if key in seen or row['date'] not in daily or daily[row['date']]['litres'] is None or row['rig'] not in {'C-1800','CSD-1300'} or row['shift'] not in {'Өдөр','Шөнө'}:
            raise ValueError('Invalid fuel allocation key')
        seen.add(key)
        total=totals.setdefault(row['date'],{'litres':0,'cost':0})
        for field in ('litres','cost'):
            if not isinstance(row[field],(int,float)) or not math.isfinite(row[field]) or row[field]<0:
                raise ValueError('Invalid allocated fuel amount')
            total[field]+=row[field]
    for day,row in daily.items():
        if row['litres'] is None:
            continue
        for field in ('litres','cost'):
            if not math.isclose(totals.get(day,{}).get(field,-1),row[field],abs_tol=0.005):
                raise ValueError('Fuel allocation does not balance to daily ledger')


if __name__ == '__main__':
    holes, shifts = validate(load_json(Path(__file__).parent / 'dist' / 'data.json'))
    print(f'Validated {holes} holes and {shifts} shifts')
