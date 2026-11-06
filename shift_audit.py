"""Rig-shift calendar audit.

Every day and night shift of each rig is one slot (October: 31 days x 2 shifts x 2 rigs = 124).
A slot is classified from evidence only: its shift records and their raw Drive reports, the depth
continuity of each hole and the collar register. A slot without a record is never 0 m drilled:
it is a missing report when depth or the rig's open hole shows work, otherwise unverified until a
report or an owner confirmation (input/shift-audit.json) says what the rig did.
"""
from __future__ import annotations

import json
import re
from datetime import date as Date, timedelta
from pathlib import Path

from drilling_sync import report_stem

STATUSES = ('VERIFIED_DRILLING', 'VERIFIED_NON_DRILLING', 'MISSING_REPORT', 'SOURCE_CONFLICT', 'UNVERIFIED')
SHIFTS = ('Өдөр', 'Шөнө')
TOLERANCE = 0.05
CONFIG = Path(__file__).resolve().parent / 'input' / 'shift-audit.json'
FOREMAN = Path(__file__).resolve().parent / 'input' / 'foreman-reports.json'


def m(value):
    return f'{value:g}'


def months_between(first, last):
    months, year, month = [], first.year, first.month
    while (year, month) <= (last.year, last.month):
        months.append(f'{year:04d}-{month:02d}')
        year, month = (year + 1, 1) if month == 12 else (year, month + 1)
    return months


def load_confirmations(path=CONFIG):
    """Owner confirmations, each with its evidence: `confirmed` slots without a report (rig move, standby)
    and `reports` that reached the owner but not the hole's Drive folder, with the depths they state."""
    if not Path(path).exists():
        return {'confirmed': [], 'reports': [], 'holes': [], 'rigs': []}
    config = json.loads(Path(path).read_text(encoding='utf-8'))
    confirmed, reports, holes = config.get('confirmed', []), config.get('reports', []), config.get('holes', [])
    rigs = config.get('rigs', [])
    for row in confirmed:
        if row.get('status') != 'VERIFIED_NON_DRILLING' or row.get('shift') not in SHIFTS:
            raise ValueError('Shift audit confirmations may only record verified non-drilling shifts')
        if not all(str(row.get(key, '')).strip() for key in ('rig', 'date', 'reason', 'evidence', 'confirmedBy', 'confirmedAt')):
            raise ValueError('Shift audit confirmation needs rig, date, reason, evidence, confirmedBy and confirmedAt')
        Date.fromisoformat(row['date'])
    for row in reports:
        if row.get('shift') not in SHIFTS or not all(str(row.get(key, '')).strip() for key in
                                                     ('rig', 'date', 'hole', 'source', 'evidence', 'confirmedBy', 'confirmedAt')):
            raise ValueError('A confirmed report needs rig, date, shift, hole, source, evidence, confirmedBy and confirmedAt')
        if not all(isinstance(row.get(key), (int, float)) for key in ('from', 'to')) or row['to'] < row['from']:
            raise ValueError('A confirmed report states the depths it covers (from <= to)')
        Date.fromisoformat(row['date'])
    for row in holes:
        # A sheet row filed under the wrong hole number: identified by rig ('' = a row with no known rig),
        # date, shift, hole and depths; only its hole changes.
        if row.get('shift') not in SHIFTS or not all(str(row.get(key, '')).strip() for key in
                                                     ('date', 'hole', 'correctHole', 'reason', 'evidence', 'confirmedBy', 'confirmedAt')):
            raise ValueError('A hole correction needs date, shift, hole, correctHole, reason, evidence, confirmedBy and confirmedAt')
        if not isinstance(row.get('rig'), str) or not all(isinstance(row.get(key), (int, float)) for key in ('from', 'to')):
            raise ValueError('A hole correction names the rig ("" for a row without one) and the depths of the row')
        if row['hole'] == row['correctHole']:
            raise ValueError('A hole correction must change the hole')
        Date.fromisoformat(row['date'])
    for row in rigs:
        # A sheet row whose rig text is wrong or missing: identified by that text, date, shift, hole (as the
        # sheet gives it) and depths; only its rig changes.
        if row.get('shift') not in SHIFTS or row.get('correctRig') not in ('C-1800', 'CSD-1300') or not all(
                str(row.get(key, '')).strip() for key in ('date', 'hole', 'reason', 'evidence', 'confirmedBy', 'confirmedAt')):
            raise ValueError('A rig correction needs date, shift, hole, correctRig (C-1800/CSD-1300), reason, evidence, confirmedBy and confirmedAt')
        if not isinstance(row.get('rig'), str) or not all(isinstance(row.get(key), (int, float)) for key in ('from', 'to')):
            raise ValueError('A rig correction names the rig text of the row ("" for none) and its depths')
        if row['rig'] == row['correctRig']:
            raise ValueError('A rig correction must change the rig')
        Date.fromisoformat(row['date'])
    return {'confirmed': confirmed, 'reports': reports, 'holes': holes, 'rigs': rigs}


def daily_folder(data, hole):
    folder = (data.get('folderMap') or {}).get(hole) or {}
    daily = next((f for f in folder.get('folders', []) if f['name'].startswith('02')), None)
    return (daily or folder).get('url', '')


def evidence(record):
    if record.get('reports'):
        return 'report'
    if record.get('origin') == 'photo-records' or record.get('ownerReport'):
        return 'owner'
    return 'sheet' if str(record.get('source', '')).strip() else ''


def build_audit(data, rigs, through, confirmations=None, foreman=()):
    """Classify every rig-shift slot from the first shift month through `through` (YYYY-MM-DD)."""
    shifts = [s for s in data['shifts'] if s['rig'] in rigs]
    through_day = Date.fromisoformat(through)
    first_day = Date.fromisoformat(min(s['date'] for s in shifts)).replace(day=1)
    collar = {h['id']: h for h in data['collar']}
    slots, by_rig = {}, {rig: [] for rig in rigs}
    day = first_day
    while day <= through_day:
        for index, shift in enumerate(SHIFTS):
            for rig in rigs:
                slot = {'rig': rig, 'date': day.isoformat(), 'shift': shift, 't': day.toordinal() * 2 + index,
                        'records': [], 'issues': [], 'status': None, 'holes': set()}
                slots[(rig, slot['date'], shift)] = slot
                by_rig[rig].append(slot)
        day += timedelta(days=1)

    records = []
    for s in shifts:
        slot = slots.get((s['rig'], s['date'], s['shift']))
        if slot is None:
            continue
        record = {**s, 't': slot['t'], 'slot': slot}
        slot['records'].append(record)
        records.append(record)

    def issue(slot, kind, text, status=None):
        if not any(i['text'] == text for i in slot['issues']):
            slot['issues'].append({'kind': kind, 'text': text})
        if status == 'SOURCE_CONFLICT' or (status == 'MISSING_REPORT' and slot['status'] != 'SOURCE_CONFLICT'):
            slot['status'] = status

    def rig_neighbours(rig, t):
        before = [r for r in records if r['rig'] == rig and r['t'] < t]
        after = [r for r in records if r['rig'] == rig and r['t'] > t]
        return (max(before, key=lambda r: (r['t'], r['to'])) if before else None,
                min(after, key=lambda r: (r['t'], r['from'])) if after else None)

    gaps = []

    def missing(hole, top, bottom, upper, lower):
        """Metres top-bottom of a hole have no report: put them on the rig's empty slots between its records."""
        rig = (lower or upper)['rig']
        if lower:
            previous, _ = rig_neighbours(rig, lower['t'])
            start, end = (previous['t'] if previous else -1), lower['t']
            if upper and upper['rig'] == rig:
                start = max(start, upper['t'])
        else:
            _, following = rig_neighbours(rig, upper['t'])
            start, end = upper['t'], following['t'] if following else float('inf')
        h = collar.get(hole, {})
        candidates = [s for s in by_rig[rig] if start < s['t'] < end and not s['records']
                      and (lower is None or not h.get('start') or s['date'] >= h['start'])
                      and (lower is not None or not h.get('finish') or s['date'] <= h['finish'])]
        text = f'{hole}: {m(top)}–{m(bottom)} м ({m(round(bottom - top, 2))} м) тайлангүй'
        gap = {'hole': hole, 'rig': rig, 'from': top, 'to': bottom, 'slots': candidates}
        gaps.append(gap)
        if candidates:
            for slot in candidates:
                slot['holes'].add(hole)
                issue(slot, 'gap', text + (f' — {len(candidates)} ээлжид' if len(candidates) > 1 else ''), 'MISSING_REPORT')
        elif upper and upper['rig'] == rig and lower and upper['hours'] < 11.99:
            gap['partial'] = upper['slot']
            issue(upper['slot'], 'gap', f'Хэсэгчилсэн тайлан ({m(upper["hours"])} ц); дараагийн тайлан '
                  f'{m(bottom)} м-ээс эхэлсэн — {text}', 'MISSING_REPORT')
        elif lower is None:
            issue(upper['slot'], 'collar', f'{hole}: тайлангийн эцсийн гүн {m(top)} м, collar-ын эцсийн гүн {m(bottom)} м '
                  f'({m(round(bottom - top, 2))} м зөрүү)', 'SOURCE_CONFLICT')
        else:
            issue(lower['slot'], 'gap', text + ' — тайлан оногдох хоосон ээлж алга', 'SOURCE_CONFLICT')

    backwards = []
    for hole in sorted({r['hole'] for r in records}):
        sequence = sorted((r for r in records if r['hole'] == hole), key=lambda r: (r['t'], r['from']))
        deepest = None
        for record in sequence:
            if deepest is None:
                if record['from'] > TOLERANCE:
                    missing(hole, 0, record['from'], None, record)
            elif record['from'] - deepest['to'] > TOLERANCE:
                missing(hole, deepest['to'], record['from'], deepest, record)
            elif deepest['to'] - record['from'] > TOLERANCE:
                if record['to'] <= deepest['from'] + TOLERANCE or record['to'] <= deepest['to'] - TOLERANCE:
                    backwards.append(record)
                    text = (f'{hole}: {m(record["from"])}–{m(record["to"])} м нь өмнөх {deepest["date"]} '
                            f'{deepest["shift"]} ({m(deepest["from"])}–{m(deepest["to"])} м)-ийн гүнээс дээш — огноо, ээлж эсвэл цооног буруу байж болзошгүй')
                    issue(record['slot'], 'overlap', text, 'SOURCE_CONFLICT')
                else:
                    text = (f'{hole}: {m(record["from"])}–{m(deepest["to"])} м давхардсан '
                            f'({m(round(deepest["to"] - record["from"], 2))} м), {deepest["date"]} {deepest["shift"]} ба {record["date"]} {record["shift"]}')
                    issue(record['slot'], 'overlap', text, 'SOURCE_CONFLICT')
                    issue(deepest['slot'], 'overlap', text, 'SOURCE_CONFLICT')
            # On a tie the later record (e.g. the 0 m shift that closed the hole) is the hole's last word.
            if deepest is None or record['to'] >= deepest['to']:
                deepest = record
        h = collar.get(hole, {})
        depth = h.get('collarDepth')
        if depth is not None and h.get('finish'):
            if depth - deepest['to'] > TOLERANCE:
                missing(hole, deepest['to'], depth, deepest, None)
            elif deepest['to'] - depth > TOLERANCE:
                issue(deepest['slot'], 'collar', f'{hole}: тайлангийн гүн {m(deepest["to"])} м, collar-ын эцсийн гүн {m(depth)} м', 'SOURCE_CONFLICT')

    for record in backwards:
        for gap in gaps:
            if gap['hole'] == record['hole'] and abs(gap['from'] - record['from']) <= TOLERANCE and abs(gap['to'] - record['to']) <= TOLERANCE:
                hint = (f'{record["date"]} {record["shift"]}-ийн тайлан ({m(record["from"])}–{m(record["to"])} м) энэ завсрыг яг нөхөж байна — '
                        'тайлангийн огноо/ээлж нэг ээлжээр зөрсөн байж болзошгүй')
                gap['filled'] = record
                for slot in gap['slots'] + [record['slot']]:
                    issue(slot, 'hint', hint)

    # The metres a gap must hold, from the depths before and after it. A gap is pinned to a shift only when
    # one shift is without a report and the metres fit one shift (no more than the most any reported shift
    # drilled); otherwise only its total is known. Inferred metres are never a report and never verified;
    # a gap another report fills exactly (a report dated a shift late) is not inferred, which would count it twice.
    most = max((r['meters'] for r in records), default=0)
    for gap in gaps:
        metres = round(gap['to'] - gap['from'], 2)
        targets = [gap['partial']] if gap.get('partial') else gap['slots']
        if gap.get('filled') or metres <= TOLERANCE or not targets:
            continue
        exact = len(targets) == 1 and metres <= most
        note = ('' if exact else f'{len(targets)} ээлжид хуваагдана; ээлж бүрийн метр тодорхойгүй' if len(targets) > 1
                else f'{m(metres)} м нэг ээлжид багтахгүй (тайлангаар нэг ээлжид хамгийн ихдээ {m(most)} м) — өөр тайлангүй ээлжтэй хуваагдана')
        gap['inferred'] = {'meters': metres, 'exact': exact, 'slots': targets}
        for slot in targets:
            slot.setdefault('inferred', []).append({'hole': gap['hole'], 'from': gap['from'], 'to': gap['to'], 'meters': metres,
                                                   'exact': exact, 'shifts': len(targets), 'note': note})

    for record in records:
        h = collar.get(record['hole'])
        if not h or (not h.get('start') and h.get('plan') is None):
            issue(record['slot'], 'hole', f'{record["hole"]}: collar-д төлөвлөгөө, эхэлсэн огноо бүртгэгдээгүй цооног — цооногийн дугаарыг эх тайлантай тулгах', 'SOURCE_CONFLICT')
            continue
        day = Date.fromisoformat(record['date'])
        if h.get('start') and day < Date.fromisoformat(h['start']) - timedelta(days=1):
            issue(record['slot'], 'hole', f'{record["hole"]}: collar-ын эхэлсэн огноо {h["start"]}-аас өмнөх тайлан', 'SOURCE_CONFLICT')
        if h.get('finish') and day > Date.fromisoformat(h['finish']) + timedelta(days=1):
            issue(record['slot'], 'hole', f'{record["hole"]}: цооног {h["finish"]}-нд дууссан (collar) — энэ тайлангийн цооногийн дугаарыг шалгах', 'SOURCE_CONFLICT')

    for conflict in data.get('sourceConflicts', []):
        slot = slots.get((conflict['rig'], conflict['date'], conflict['shift']))
        if slot:
            fields = ', '.join(f'{key}: {" / ".join(m(v) if isinstance(v, (int, float)) else str(v) for v in values)}'
                               for key, values in conflict['fields'].items())
            issue(slot, 'conflict', f'{conflict["hole"]}: эх хүснэгтүүд зөрүүтэй ({fields}); {conflict["kept"]}-ийн утгыг авсан', 'SOURCE_CONFLICT')

    for row in data.get('unassignedShifts', []):
        for rig in rigs:
            slot = slots.get((rig, row['date'], row['shift']))
            if slot:
                issue(slot, 'unassigned', f'Өрөм нь «{row["rigText"] or "хоосон"}» мөр: {row["hole"]} {m(row["from"])}–{m(row["to"])} м '
                      f'({row["source"] or row["sheet"]}) — аль өрөмд хамаарахыг баталгаажуулах')

    for row in data.get('rejectedShifts', []):
        for rig in ([row['rig']] if row.get('rig') in rigs else rigs):
            slot = slots.get((rig, row.get('date'), row.get('shift')))
            if slot:
                held = any(r['hole'] == row.get('hole') for r in slot['records'])
                issue(slot, 'rejected', f'Хүснэгтийн мөр татгалзсан ({row["sheet"]} / {row["tab"]} мөр {row["row"]}): {row["reason"]}'
                      + (' — өөр хүснэгтийн хүчинтэй мөрийг ашигласан' if held else ''),
                      None if held else 'SOURCE_CONFLICT')

    for record in records:
        if record.get('correction'):
            c = record['correction']
            issue(record['slot'], 'correction', f'Цооногийн дугаар засагдсан: эх хүснэгтэд {c["hole"]} → {record["hole"]} — {c["reason"]} ({c["confirmedBy"]}, {c["confirmedAt"]})')
        if record.get('rigCorrection'):
            c = record['rigCorrection']
            issue(record['slot'], 'correction', f'Өрөм засагдсан: эх хүснэгтэд «{c["rig"] or "хоосон"}» → {record["rig"]} — {c["reason"]} ({c["confirmedBy"]}, {c["confirmedAt"]})')
        names = [str(record.get('source', ''))] + [x.get('name', '') for x in record.get('reports', [])]
        if any(re.search(r'date[_\s-]?(check|review)', name, re.I) for name in names):
            record['dateCheck'] = True
            issue(record['slot'], 'evidence', f'{record["hole"]}: эх файлын нэрэнд огноог шалгах тэмдэглэгээтэй ({record.get("source", "")})')

    # Drive reports no shift cites: a copy of a cited file is a duplicate; any other report dated for a
    # slot without that hole's record is a raw report missing from the sheets.
    cited = {report_stem(x.get('name', '')) for r in records for x in r.get('reports', [])} | {report_stem(r.get('source', '')) for r in records}
    for report in data.get('unlinkedReports', []):
        if report_stem(report['name']) in cited or not report.get('date') or not report.get('shift'):
            continue
        for rig in ([report['rig']] if report.get('rig') in rigs else rigs):
            slot = slots.get((rig, report['date'], report['shift']))
            if slot and not any(r['hole'] == report['hole'] for r in slot['records']):
                slot['holes'].add(report['hole'])
                issue(slot, 'unlinked', f'Drive-д {report["hole"]}-ийн тайлан бий, хүснэгтэд ороогүй: {report["name"]}',
                      'SOURCE_CONFLICT' if slot['records'] else None)
                slot.setdefault('driveReports', []).append({'name': report['name'], 'url': report['url']})

    # A report the owner received is evidence for the sheet row only when the row states the same depths.
    for report in (confirmations or {}).get('reports', []):
        slot = slots.get((report['rig'], report['date'], report['shift']))
        if not slot:
            continue
        stated = f'{report["hole"]} {m(report["from"])}–{m(report["to"])} м ({report["source"]})'
        record = next((r for r in slot['records'] if r['hole'] == report['hole']), None)
        if record is None:
            slot['holes'].add(report['hole'])
            issue(slot, 'confirmation', f'Эзэмшигч тайлан ирснийг баталсан: {stated} — хүснэгтэд мөр алга', 'MISSING_REPORT')
        elif abs(record['from'] - report['from']) <= TOLERANCE and abs(record['to'] - report['to']) <= TOLERANCE:
            record['ownerReport'] = report
            issue(slot, 'confirmation', f'Эзэмшигч баталгаажуулсан эх тайлан: {stated} — {report["evidence"]} '
                  f'({report["confirmedBy"]}, {report["confirmedAt"]})')
        else:
            issue(slot, 'confirmation', f'Эзэмшигчийн баталсан тайлан {stated}, хүснэгтэд {m(record["from"])}–{m(record["to"])} м', 'SOURCE_CONFLICT')

    confirmed = {(c['rig'], c['date'], c['shift']): c for c in (confirmations or {}).get('confirmed', [])}
    for rig in rigs:
        for slot in by_rig[rig]:
            if slot['records']:
                drilled = any(r['meters'] > 0 for r in slot['records'])
                unproven = [r for r in slot['records'] if evidence(r) in ('', 'sheet')]
                for r in unproven:
                    issue(slot, 'evidence', f'{r["hole"]}: эх тайлан Drive-д холбогдоогүй'
                          + (f' ({r["source"]})' if str(r.get('source', '')).strip() else ' (эх файлын нэр алга)'))
                if slot['status']:
                    pass
                elif unproven or any(r.get('dateCheck') for r in slot['records']):
                    slot['status'] = 'UNVERIFIED'
                else:
                    slot['status'] = 'VERIFIED_DRILLING' if drilled else 'VERIFIED_NON_DRILLING'
                if not drilled:
                    note = '; '.join(str(r.get('notes', '')).split(' | ')[0] for r in slot['records'] if r.get('notes'))
                    issue(slot, 'nonDrilling', '0 м өрөмдсөн тайлан' + (f': {note}' if note else ''))
                if len({r['hole'] for r in slot['records']}) > 1:
                    # The finished hole comes first, the hole collared at 0 m after it.
                    order = sorted(slot['records'], key=lambda r: r['from'] <= TOLERANCE)
                    issue(slot, 'transition', 'Ээлжийн дотор цооног солигдсон: ' + ' → '.join(r['hole'] for r in order))
                continue
            owner = confirmed.get((rig, slot['date'], slot['shift']))
            if slot['status']:
                if owner:
                    issue(slot, 'confirmation', f'Эзэмшигчийн баталгаа ({owner["reason"]}) гүний завсартай зөрчилдөж байна')
                continue
            if owner:
                slot['status'] = 'VERIFIED_NON_DRILLING'
                issue(slot, 'confirmation', f'{owner["reason"]} — {owner["evidence"]} ({owner["confirmedBy"]}, {owner["confirmedAt"]})')
                continue
            previous, following = rig_neighbours(rig, slot['t'])
            slot['holes'].update(r['hole'] for r in (previous, following) if r)
            slot['status'] = 'UNVERIFIED'
            if previous is None:
                issue(slot, 'noReport', f'{rig}-ийн анхны тайлангаас ({following["date"]} {following["shift"]}) өмнө — өрөм ажиллаж эхэлсэн эсэх баталгаагүй'
                      if following else f'{rig}-ийн тайлан алга')
                continue
            hole = collar.get(previous['hole'], {})
            deepest = max((r['to'] for r in records if r['hole'] == previous['hole']), default=previous['to'])
            finished = bool(hole.get('finish')) and previous['to'] >= deepest - TOLERANCE
            if not finished and (following is not None or slot['date'] < (through_day - timedelta(days=1)).isoformat()):
                slot['status'] = 'MISSING_REPORT'
                issue(slot, 'gap', f'{previous["hole"]} {m(previous["to"])} м-т дуусаагүй байхад тайлангүй ээлж')
            elif following is None:
                issue(slot, 'noReport', 'Сүүлийн тайлангаас хойш — тайлан хараахан ирээгүй байж болзошгүй')
            elif finished and following['hole'] != previous['hole']:
                issue(slot, 'noReport', f'{previous["hole"]} дууссан, {following["hole"]} эхлэхээс өмнө — нүүлт байж болзошгүй, тайлангаар баталгаажаагүй')
            else:
                issue(slot, 'noReport', 'Тайлан алга; гүн тасралтгүй тул өрөмдөөгүй байж болзошгүй — баталгаажаагүй')

    output, months = [], {}
    for slot in sorted(slots.values(), key=lambda s: (s['t'], s['rig'])):
        holes = sorted({r['hole'] for r in slot['records']}) or sorted(slot['holes'])
        row = {'rig': slot['rig'], 'date': slot['date'], 'shift': slot['shift'], 'status': slot['status'],
               'meters': round(sum(r['meters'] for r in slot['records']), 2) if slot['records'] else None,
               'records': [{'hole': r['hole'], 'from': r['from'], 'to': r['to'], 'meters': r['meters'],
                            'source': str(r.get('source', '')), 'evidence': evidence(r), 'sheet': r.get('sheet'),
                            'reports': [{'name': x.get('name', ''), 'url': x['url']} for x in r.get('reports', [])]}
                           for r in sorted(slot['records'], key=lambda r: r['from'])],
               'issues': slot['issues'], 'driveReports': slot.get('driveReports', []), 'inferred': slot.get('inferred', []),
               'folderUrl': daily_folder(data, holes[0]) if holes else ''}
        output.append(row)
        summary = months.setdefault(slot['date'][:7], {'month': slot['date'][:7], 'expected': 0,
                                                        'counts': {status: 0 for status in STATUSES},
                                                        'meters': {status: 0.0 for status in STATUSES}, 'missingMeters': 0.0,
                                                        'inferredMeters': 0.0, 'unallocated': []})
        summary['expected'] += 1
        summary['counts'][row['status']] += 1
        summary['meters'][row['status']] = round(summary['meters'][row['status']] + (row['meters'] or 0), 2)
        summary['inferredMeters'] = round(summary['inferredMeters'] + sum(i['meters'] for i in row['inferred'] if i['exact']), 2)
    for gap in gaps:
        if gap.get('inferred') and not gap['inferred']['exact']:
            # Known in total only: each month its shifts fall in lists it, with how many of them are its own.
            shares = {}
            for slot in gap['inferred']['slots']:
                shares[slot['date'][:7]] = shares.get(slot['date'][:7], 0) + 1
            for key, count in shares.items():
                if key in months:
                    months[key]['unallocated'].append({'rig': gap['rig'], 'hole': gap['hole'], 'from': gap['from'], 'to': gap['to'],
                                                       'meters': gap['inferred']['meters'], 'shifts': len(gap['inferred']['slots']), 'inMonth': count})
        month = (gap['slots'][0]['date'] if gap['slots'] else None)
        if month and month[:7] in months:
            months[month[:7]]['missingMeters'] = round(months[month[:7]]['missingMeters'] + gap['to'] - gap['from'], 2)
    return {'through': through, 'rigs': list(rigs), 'months': [months[k] for k in months_between(first_day, through_day) if k in months],
            'slots': output, 'foreman': [foreman_check(report, shifts, collar) for report in foreman]}


def load_foreman_reports(path=FOREMAN):
    """The drilling foreman's monthly metre reports (hole, dates, metres per rig), transcribed with their source cells."""
    if not Path(path).exists():
        return []
    reports = json.loads(Path(path).read_text(encoding='utf-8')).get('reports', [])
    for report in reports:
        if not re.fullmatch(r'\d{4}-\d{2}', report.get('month', '')) or not all(str(report.get(k, '')).strip() for k in ('title', 'from', 'file', 'received')):
            raise ValueError('A foreman report needs month, title, from, file and received')
        for row in report['rows']:
            if not isinstance(row.get('metres'), (int, float)) or row['metres'] < 0 or not str(row.get('raw', '')).strip():
                raise ValueError('A foreman report row needs its metres and the source cells it was read from')
            for key in ('start', 'finish'):
                if row.get(key):
                    Date.fromisoformat(row[key])
    return reports


def foreman_check(report, shifts, collar):
    """Each row of a foreman's monthly report against the shift reports and the collar register of that month."""
    month, order = report['month'], {'Өдөр': 0, 'Шөнө': 1}
    year, number = map(int, month.split('-'))
    last = (Date(year + number // 12, number % 12 + 1, 1) - timedelta(days=1)).isoformat()
    in_month = sorted((s for s in shifts if s['date'].startswith(month + '-')), key=lambda s: (s['date'], order[s['shift']], s['from']))
    rows = []
    for row in report['rows']:
        start, finish = row.get('start') or month + '-01', row.get('finish') or last
        window = [s for s in in_month if s['rig'] == row['rig'] and start <= s['date'] <= finish]
        hole, notes = row['hole'], []
        if not hole:
            # The row names no hole: take the one the rig collared (0 m) on the start date.
            opened = [s for s in window if s['date'] == start and s['from'] <= TOLERANCE]
            hole = opened[0]['hole'] if opened else ''
            notes.append(f'Цооногийн дугаар бичээгүй; {row["rig"]} {start}-нд {hole} цооногийг эхлүүлсэн' if hole else 'Цооногийн дугаар бичээгүй')
        rows.append({**row, 'hole': hole, 'holeText': row['hole'], 'start': start, 'finish': finish, 'window': window, 'notes': notes})
    listed = {(r['rig'], r['hole']) for r in rows}
    checks = []
    for row in rows:
        own = [s for s in in_month if s['rig'] == row['rig'] and s['hole'] == row['hole']]
        reported = round(sum(s['meters'] for s in own), 2)
        reached = max((s['to'] for s in own), default=None)
        depth = collar.get(row['hole'], {}).get('collarDepth')
        stated, notes = row['metres'], row['notes']
        # Holes of this rig in the row's dates that no row of the report names (inside the dates: the first
        # and last day are shared with the neighbouring rows).
        others = {}
        for s in row['window']:
            if (s['rig'], s['hole']) not in listed and (not own or row['start'] < s['date'] < row['finish']):
                others[s['hole']] = round(others.get(s['hole'], 0) + s['meters'], 2)
        if not own:
            status = 'differs'
            notes.append(f'{row["rig"]}-ийн энэ хугацааны тайланд {row["hole"] or "энэ цооног"} алга'
                         + ('; тайланд: ' + ', '.join(f'{h} {m(v)} м (collar {m(collar.get(h, {}).get("collarDepth") or 0)} м)' for h, v in others.items()) if others else ''))
        else:
            # The comparison is with the depth the shift reports reached; the foreman writes whole metres at times.
            gap = round(reached - stated, 2)
            status = 'agree' if abs(gap) <= TOLERANCE else 'rounded' if float(stated).is_integer() and 0 < gap < 1 else 'differs'
            if status == 'rounded':
                notes.append(f'Ахлах бүхэл метрээр бичсэн ({m(stated)} м); ээлжийн тайлангийн гүн {m(reached)} м')
            elif status == 'differs':
                cut = next((s for s in own if abs(s['to'] - stated) <= TOLERANCE), None)
                if cut and reached > stated:
                    notes.append(f'Ахлахын дүн {cut["date"]} {cut["shift"]}-ийн гүнээр ({m(stated)} м) тасарсан; ээлжийн тайлангаар {m(reached)} м хүрсэн')
                else:
                    notes.append(f'Ахлах {m(stated)} м, ээлжийн тайлангийн гүн {m(reached)} м ({m(abs(gap))} м зөрүү)')
            if depth is not None and abs(depth - stated) > TOLERANCE and collar.get(row['hole'], {}).get('finish', '9999') <= row['finish']:
                notes.append(f'Collar-ын эцсийн гүн {m(depth)} м')
            elif depth is not None and status == 'differs' and abs(depth - stated) <= TOLERANCE:
                notes.append(f'Ахлахын дүн collar-ын эцсийн гүнтэй ({m(depth)} м) таарч байна')
            if abs(reported - reached) > TOLERANCE:
                notes.append(f'Ээлжийн тайлангийн метрийн нийлбэр {m(reported)} м, гүн {m(reached)} м — '
                             + ('тайлангүй интервал бий' if reported < reached else 'давхардсан интервал бий'))
            if others:
                notes.append('Энэ хугацаанд ахлахын жагсаалтад үгүй цооногийн тайлан: ' + ', '.join(f'{h} {m(v)} м' for h, v in others.items()))
        checks.append({'rig': row['rig'], 'hole': row['hole'], 'holeText': row['holeText'], 'start': row['start'], 'finish': row['finish'],
                       'foreman': stated, 'reported': reported if own else None, 'reached': reached, 'collarDepth': depth,
                       'status': status, 'notes': notes, 'row': row['row'], 'raw': row['raw']})
    rigs = sorted({r['rig'] for r in report['rows']})
    return {'month': month, 'title': report['title'], 'from': report['from'], 'file': report['file'], 'received': report['received'],
            'rigs': [{'rig': rig, 'foreman': report.get('totals', {}).get(rig),
                      'reported': round(sum(s['meters'] for s in in_month if s['rig'] == rig), 2)} for rig in rigs],
            'rows': checks}
