"""Drill-crew pay-period workbooks (the actual pay for, say, 2026.10.16-2026.10.31) for the finance aggregates.

A pay-period workbook lists each person's marked work days, the pay computed for them (Тооцсон цалин) and their
additions (Нэмэгдэл цалин): the drilling masters' metre bonus and the rest (overtime, one-assistant extra, ...).
Only date totals leave this module. Names, register, bank and phone columns and each person's amounts stay in memory;
input/payroll.json keeps the verified date totals for when Drive cannot be read.
"""
import json
import math
import re
from collections import defaultdict
from datetime import date, timedelta
from pathlib import Path

from drilling_sync import (ATTENDANCE_ROLE_ALIASES, FINANCE_RIGS, PAYROLL_HEADERS, XLSX_MIME, _calendar_day_cell,
                           _finance_cell, _finance_has_headers, _finance_number, _find_finance_table, _salary_table, norm)

ROOT = Path(__file__).resolve().parent
SNAPSHOT = ROOT / 'input' / 'payroll.json'
LOADING = 1.13  # the owner's 13% loading on every pay component, as in finance_aggregates
AMOUNTS = ('laborCost', 'foodCost', 'bonusCost', 'incentiveCost')
SHIFTS = ('Өдөр', 'Шөнө')
PERIOD = re.compile(r'(20\d{2})\.(\d{1,2})\.(\d{1,2})\s*[-–—]\s*(20\d{2})\.(\d{1,2})\.(\d{1,2})')
SUMMARY_HEADERS = ('албан тушаалын нэрс', 'албан тушаалын тоо', 'гарт авах цалин')


def _period(rows, header_index, name):
    text = ' '.join([' '.join(str(cell) for row in rows[:header_index + 1] for cell in row), name])
    match = PERIOD.search(text)
    if not match:
        raise ValueError('Pay-period workbook names no period (YYYY.MM.DD-YYYY.MM.DD)')
    start, end = date(*map(int, match.groups()[:3])), date(*map(int, match.groups()[3:]))
    if end < start or (start.year, start.month) != (end.year, end.month):
        raise ValueError('Pay period must lie within one month')
    return start, end


def _day_columns(rows, header_index, days):
    """The row under the header that numbers the period's days in consecutive columns (16, 17, ... 31)."""
    for index in range(header_index, min(header_index + 5, len(rows))):
        row = rows[index]
        for start in range(len(row)):
            if all(_calendar_day_cell(row, start + offset) == day.day for offset, day in enumerate(days)):
                return index, [start + offset for offset in range(len(days))]
    raise ValueError('Pay-period workbook has no day columns for its period')


def parse_payroll(sheets, name=''):
    """Date totals of one pay-period workbook: base pay and the non-bonus additions on each marked work day, and
    the masters' metre bonus, which is paid on the month's metres and so belongs to the month, not to days."""
    summary = [sheet for sheet in sheets if _finance_has_headers([sheet], SUMMARY_HEADERS)]
    if not summary:
        raise ValueError('Pay-period workbook has no role summary with the metre rate')
    rates = _salary_table(summary)
    _, rows, header_index, headers = _find_finance_table(sheets, ('нэр', 'албан тушаал', *PAYROLL_HEADERS))
    start, end = _period(rows, header_index, name)
    days = [start + timedelta(n) for n in range((end - start).days + 1)]
    column = lambda test: next((i for i, h in enumerate(headers) if test(h)), -1)
    role_col = column(lambda h: h == 'албан тушаал')
    worked_col = column(lambda h: h == 'нийт ажилласан хоног')
    base_col = column(lambda h: h == 'тооцсон цалин')
    meters_col = column(lambda h: h.startswith('өрөмдсөн метр'))
    extra_col = column(lambda h: h.startswith('нэмэгдэл цалин'))
    deduction_col = column(lambda h: 'суутгал' in h)
    if min(role_col, worked_col, base_col, extra_col) < 0:
        raise ValueError('Pay-period workbook is missing a pay column')
    day_row, day_cols = _day_columns(rows, header_index, days)
    daily = {day: {'base': 0.0, 'incentive': 0.0} for day in days}
    totals = {'days': 0.0, 'base': 0.0, 'additions': 0.0, 'deductions': 0.0}
    bonus = bonus_meters = 0.0
    people, check = 0, None
    for row in rows[day_row + 1:]:
        if any(norm(cell).startswith('нийт дүн') for cell in row[:role_col + 1]):
            check = row
            break
        role, base = _finance_cell(row, role_col), _finance_number(_finance_cell(row, base_col))
        if not role or base is None:
            continue
        marks = [(day, _finance_number(_finance_cell(row, col)) or 0.0) for day, col in zip(days, day_cols)]
        if any(mark < 0 or mark > 1 for _, mark in marks):
            raise ValueError('Pay-period day mark outside 0-1')
        worked = sum(mark for _, mark in marks)
        if not math.isclose(worked, _finance_number(_finance_cell(row, worked_col)) or 0.0, abs_tol=0.01):
            raise ValueError('Pay-period day marks do not add up to the worked days')
        extra = _finance_number(_finance_cell(row, extra_col)) or 0.0
        meters = (_finance_number(_finance_cell(row, meters_col)) or 0.0) if meters_col >= 0 else 0.0
        rate = (rates.get(ATTENDANCE_ROLE_ALIASES.get(norm(role), norm(role))) or {}).get('bonusPerMeter')
        # The metres column also holds overtime hours and extra days; only a role with a metre rate earns per metre.
        earned = meters * rate if rate and meters > 0 else 0.0
        other = extra - earned
        if other < -1:
            raise ValueError('Pay-period metre bonus exceeds the additions paid')
        if not worked:
            if base or extra:
                raise ValueError('Pay-period pay without marked work days')
            continue
        for day, mark in marks:
            daily[day]['base'] += base * mark / worked
            daily[day]['incentive'] += max(other, 0.0) * mark / worked
        bonus, bonus_meters = bonus + earned, bonus_meters + (meters if earned else 0.0)
        totals['days'] += worked
        totals['base'] += base
        totals['additions'] += extra
        totals['deductions'] += (_finance_number(_finance_cell(row, deduction_col)) or 0.0) if deduction_col >= 0 else 0.0
        people += 1
    # The workbook's own total row is the check that every person was read.
    if check is None:
        raise ValueError('Pay-period workbook has no total row')
    for key, col in (('days', worked_col), ('base', base_col), ('additions', extra_col)):
        if not math.isclose(totals[key], _finance_number(_finance_cell(check, col)) or 0.0, abs_tol=1.0):
            raise ValueError(f'Pay-period {key} do not add up to the workbook total')
    return {'name': name, 'start': start.isoformat(), 'end': end.isoformat(), 'people': people,
            'daily': [{'date': day.isoformat(), 'base': round(value['base'], 2), 'incentive': round(value['incentive'], 2)}
                      for day, value in daily.items()],
            'bonus': {'month': start.strftime('%Y-%m'), 'amount': round(bonus, 2), 'meters': round(bonus_meters, 2)},
            'totals': {key: round(value, 2) for key, value in totals.items()}}


FEE_HEADERS = ('нэр', 'ажлын байр', 'ажилласан өдөр', 'ажилласан өдөрт ногдох цалин')
CREW = 'өрмийн баг'


def _person(name):
    """The given name of a 'Д.Мөнхтөр'-style entry: the same person is written with or without the initial."""
    return norm(name).split('.')[-1].strip()


def parse_contract_fees(sheets, name=''):
    """Date totals of the drill crew in a contract-fee workbook (Даалгаварын гэрээгээр ажиллагсадын хөлс): one
    sheet with a section per site and team, each with its own header, day columns and total row. The crew
    section (title naming the drill crew alone) counts whole; a section that mixes the crew with other work
    (factory, carpentry) counts only the crew's people: a crew role or a person also listed in the crew section.
    These workbooks pay the fee for the marked days; they carry no metre bonus and no additions."""
    sections = []
    for _, rows in sheets:
        text = ' '.join(str(cell) for row in rows[:3] for cell in row)
        for index, row in enumerate(rows):
            headers = [norm(cell) for cell in row]
            if not all(h in headers for h in FEE_HEADERS):
                continue
            title = next((norm(' '.join(str(c) for c in rows[i] if str(c).strip())) for i in range(index - 1, max(index - 4, -1), -1)
                          if sum(1 for c in rows[i] if str(c).strip()) == 1), '')
            sections.append((title, rows, index, headers, text))
    if not sections:
        raise ValueError('Contract-fee workbook has no section with a fee table')
    match = PERIOD.search(' '.join([sections[0][4], name]))
    if not match:
        raise ValueError('Contract-fee workbook names no period (YYYY.MM.DD-YYYY.MM.DD)')
    start, end = date(*map(int, match.groups()[:3])), date(*map(int, match.groups()[3:]))
    if end < start or (start.year, start.month) != (end.year, end.month):
        raise ValueError('Pay period must lie within one month')
    days = [start + timedelta(n) for n in range((end - start).days + 1)]
    read = []
    for title, rows, index, headers, _ in sections:
        if CREW not in title:
            continue
        col = {key: headers.index(key) for key in ('нэр', 'ажлын байр', 'ажилласан өдөр', 'ажилласан өдөрт ногдох цалин')}
        deduction_col = next((i for i, h in enumerate(headers) if 'суутгал' in h), -1)
        day_row, day_cols = _day_columns(rows, index, days)
        people, check = [], None
        for row in rows[day_row + 1:]:
            if norm(_finance_cell(row, col['нэр'])).startswith('нийт дүн'):
                check = row
                break
            person, role = _finance_cell(row, col['нэр']), _finance_cell(row, col['ажлын байр'])
            base = _finance_number(_finance_cell(row, col['ажилласан өдөрт ногдох цалин']))
            if not person or base is None:
                continue
            marks = [(day, _finance_number(_finance_cell(row, c)) or 0.0) for day, c in zip(days, day_cols)]
            if any(mark < 0 or mark > 2 for _, mark in marks):
                raise ValueError('Contract-fee day mark outside 0-2')
            worked = sum(mark for _, mark in marks)
            if not math.isclose(worked, _finance_number(_finance_cell(row, col['ажилласан өдөр'])) or 0.0, abs_tol=0.01):
                raise ValueError('Contract-fee day marks do not add up to the worked days')
            if base and not worked:
                raise ValueError('Contract-fee pay without marked work days')
            deduction = abs(_finance_number(_finance_cell(row, deduction_col).strip('()')) or 0.0) if deduction_col >= 0 else 0.0
            people.append({'person': _person(person), 'role': norm(role), 'base': base, 'worked': worked,
                           'marks': marks, 'deduction': deduction})
        # The section's own total row is the check that every person in it was read.
        if check is None:
            raise ValueError('Contract-fee section has no total row')
        for key, column in (('worked', 'ажилласан өдөр'), ('base', 'ажилласан өдөрт ногдох цалин')):
            if not math.isclose(sum(p[key] for p in people), _finance_number(_finance_cell(check, col[column])) or 0.0, abs_tol=1.0):
                raise ValueError(f'Contract-fee section {key} do not add up to its total')
        read.append((title, people))
    crew = [people for title, people in read if title.endswith(CREW)]
    if not crew:
        raise ValueError('Contract-fee workbook has no drill-crew section')
    roles = {p['role'] for people in crew for p in people}
    names = {p['person'] for people in crew for p in people}
    daily = {day: 0.0 for day in days}
    totals = {'days': 0.0, 'base': 0.0, 'additions': 0.0, 'deductions': 0.0}
    count = set()
    for title, people in read:
        mixed = not title.endswith(CREW)
        for p in people:
            if mixed and p['role'] not in roles and p['person'] not in names:
                continue
            for day, mark in p['marks']:
                if p['worked']:
                    daily[day] += p['base'] * mark / p['worked']
            totals['days'] += p['worked']
            totals['base'] += p['base']
            totals['deductions'] += p['deduction']
            count.add(p['person'])
    return {'name': name, 'start': start.isoformat(), 'end': end.isoformat(), 'people': len(count),
            'daily': [{'date': day.isoformat(), 'base': round(value, 2)} for day, value in daily.items()],
            'bonus': {'month': start.strftime('%Y-%m'), 'amount': 0.0, 'meters': 0.0},
            'totals': {key: round(value, 2) for key, value in totals.items()}}


def parse_pay_workbook(sheets, name=''):
    """A pay-period workbook with the role summary and metre rates, or a contract-fee workbook."""
    if any(_finance_has_headers([sheet], SUMMARY_HEADERS) for sheet in sheets):
        return parse_payroll(sheets, name)
    return parse_contract_fees(sheets, name)


def validate_snapshot(snapshot):
    if set(snapshot) != {'about', 'payrolls'} or not isinstance(snapshot['payrolls'], list):
        raise ValueError('Unexpected pay-period snapshot fields')
    for entry in snapshot['payrolls']:
        if not re.fullmatch(r'[A-Za-z0-9_-]{20,}', str(entry.get('id', ''))) or not str(entry.get('name', '')).strip():
            raise ValueError('Pay-period snapshot entry needs a Drive id and a file name')
        if 'daily' not in entry:
            continue  # a file to read from Drive that has no verified totals yet
        if set(entry) - {'mimeType'} != {'id', 'name', 'modifiedTime', 'start', 'end', 'people', 'daily', 'bonus', 'totals'}:
            raise ValueError('Pay-period snapshot must hold date totals only')
        start, end = date.fromisoformat(entry['start']), date.fromisoformat(entry['end'])
        dates = [row['date'] for row in entry['daily']]
        if dates != [(start + timedelta(n)).isoformat() for n in range((end - start).days + 1)]:
            raise ValueError('Pay-period snapshot must list every date of its period')
        for row in entry['daily']:
            # A contract-fee period has no additions: it leaves the date's modelled incentive as it was.
            if set(row) - {'incentive'} != {'date', 'base'} or min(row['base'], row.get('incentive', 0)) < 0:
                raise ValueError('Invalid pay-period date total')
        if not math.isclose(sum(row['base'] for row in entry['daily']), entry['totals']['base'], abs_tol=1.0):
            raise ValueError('Pay-period snapshot base pay does not add up')
        if entry['bonus']['month'] != entry['start'][:7] or entry['bonus']['amount'] < 0:
            raise ValueError('Invalid pay-period metre bonus')


def load_payrolls(drive=None, workbook_reader=None, path=SNAPSHOT):
    """Date totals of the listed pay periods, read from Drive when a client is given. A file Drive cannot read or
    parse falls back to its verified totals in the snapshot. Returns (payrolls, note for the data log)."""
    snapshot = json.loads(Path(path).read_text(encoding='utf-8'))
    validate_snapshot(snapshot)
    result, failed = [], []
    for entry in snapshot['payrolls']:
        if drive is not None:
            try:
                sheets = workbook_reader(drive.download({'id': entry['id'], 'mimeType': entry.get('mimeType', XLSX_MIME)}), '.xlsx')
                result.append({**parse_pay_workbook(sheets, entry['name']), 'source': 'drive'})
                continue
            except Exception as error:  # Drive access or a changed layout: the verified totals stand in
                failed.append(f"{entry['name']} ({type(error).__name__})")
        if 'daily' in entry:
            result.append({**entry, 'source': 'snapshot'})
    note = ('Pay-period workbook refresh failed; verified snapshot used: ' + ', '.join(failed)) if failed else ''
    return result, note


def apply_payroll(finance, payrolls, shifts):
    """Actual pay replaces the attendance model on the dates a pay period covers: each day's pay split evenly over
    the 2 rigs x 2 shifts, since the workbook names no rig or shift. A period's metre bonus replaces the month's
    modelled bonus and is shared over the month's rig-shifts by the metres each drilled. Re-applying gives the same."""
    if finance is None:
        return finance
    period = finance['period']
    mine = [p for p in payrolls if p['start'][:7] == period]
    if not mine:
        return finance
    rows = {(r['date'], r['rig'], r['shift']): {**dict.fromkeys(AMOUNTS, 0.0), **r} for r in finance['rigShifts']}
    blank = lambda key: {'date': key[0], 'rig': key[1], 'shift': key[2], **dict.fromkeys(AMOUNTS, 0.0)}
    for payroll in mine:
        for day in payroll['daily']:
            keys = [(day['date'], rig, shift) for rig in sorted(FINANCE_RIGS) for shift in SHIFTS]
            for key in keys:
                row = rows.setdefault(key, blank(key))
                row['laborCost'] = round(day['base'] * LOADING / len(keys), 2)
                if 'incentive' in day:  # a contract-fee period keeps the modelled incentive
                    row['incentiveCost'] = round(day['incentive'] * LOADING / len(keys), 2)
    bonus = sum(p['bonus']['amount'] for p in mine)
    if bonus > 0:
        meters = defaultdict(float)
        for shift in shifts:
            if shift['rig'] in FINANCE_RIGS and shift['date'].startswith(period + '-'):
                meters[(shift['date'], shift['rig'], shift['shift'])] += shift.get('meters') or 0.0
        drilled = sum(meters.values())
        if drilled <= 0:
            raise ValueError('No drilled metres to share the pay-period metre bonus over')
        for key in meters:
            rows.setdefault(key, blank(key))
        for key, row in rows.items():
            row['bonusCost'] = round(bonus * LOADING * meters.get(key, 0.0) / drilled, 2)
    daily = {}
    for key in sorted(rows):
        row = rows[key]
        day = daily.setdefault(row['date'], {'date': row['date'], **dict.fromkeys(AMOUNTS, 0.0)})
        for amount in AMOUNTS:
            day[amount] = round(day[amount] + row[amount], 2)
    return {**finance, 'daily': [daily[key] for key in sorted(daily)], 'rigShifts': [rows[key] for key in sorted(rows)],
            'payPeriods': [{'file': p['name'], 'start': p['start'], 'end': p['end'], 'source': p['source'],
                            'bonus': p['bonus']['amount'] > 0} for p in mine]}
