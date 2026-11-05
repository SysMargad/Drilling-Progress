"""Google Drive/local workbooks -> validated dashboard JSON -> GitHub Pages.

Local CSV/XLSX processing uses Python's standard library. Google Drive access
uses google-auth with read-only OAuth credentials, ADC, or a service account.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
import logging
import math
import os
import re
import subprocess
import tempfile
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import zipfile
import uuid
from datetime import datetime, timedelta, timezone
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from xml.etree import ElementTree as ET

ROOT = Path(__file__).resolve().parent
# Asia/Ulaanbaatar: UTC+8 all year (no daylight saving since 2017). Fixed so Windows needs no tz database.
TZ = timezone(timedelta(hours=8), "Asia/Ulaanbaatar")
NS = {"s": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}
REL = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
SCOPE = "https://www.googleapis.com/auth/drive.readonly"
RIGS = {"C-1800", "CSD-1300"}
# Attendance codes, fuel and mud ledgers cover the two contracted rigs only.
FINANCE_RIGS = {"C-1800", "CSD-1300"}
FINANCE_FOLDER_ID = "1j8QjgqCHBh50pJwl68hBpTCvTu1tUYgj"
DIAMOND_SHEET_ID = "1BOrreNEAqlVQm6_D4OXc9wmXQUfMKk_Xmxp_cJ8tfe8"
SALARY_SOURCE_ID = "1pIjJeUEM86RkUy4TIvgboWBlq8-scGIy"
FINANCE_SHEET_MIME = "application/vnd.google-apps.spreadsheet"
XLSX_MIME = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
FOLDER_MIME = "application/vnd.google-apps.folder"
# Areas by hole id prefix. Holes of a new prefix take the name of their Drive area folder
# (01. Field Data Acquisition / 2026 / <n. area> / <hole>), Mongolian where it is known.
AREAS = {"DTDH": "Дорнын Төмөр", "ZHDH": "Замт Хөндий", "UGDH": "Уртын гол", "STDH": "Сант", "KHDH": "Харгант"}
AREA_FOLDERS = {"dorniin tumur": "Дорнын Төмөр", "zamt hundii": "Замт Хөндий", "urtiin gol": "Уртын гол", "sant": "Сант", "kh": "Харгант", "khargant": "Харгант"}
UNKNOWN_AREA = "Тодорхойгүй"
# Hole sub-folders listed on the Drilling Data page (folder number -> data kind), as used by the
# NGM geological log system: box photos, geological / geotechnical workbooks, pXRF, downhole surveys.
INVENTORY_SECTIONS = {"03": "surveys", "04": "geological", "05": "photos", "07": "geotechnical", "10": "pxrf"}
PHOTO_FORMATS = {"CR2", "JPG", "PNG", "TIF", "TIFF", "HEIC"}
INVENTORY_FILE_LIMIT = 60
FOOD_COST_PER_FIELD_DAY = 35000.0
SALARY_PRORATION_DAYS = 31
LOG = logging.getLogger("drilling")


class FinanceSourceError(RuntimeError):
    def __init__(self, source, status):
        self.source = source
        self.status = status
        super().__init__(f"{source} returned HTTP {status}")


def load_json(path):
    return json.loads(Path(path).read_text(encoding="utf-8-sig"))


def atomic_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = None
    try:
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=path.parent,
                                         prefix=".drilling-", suffix=".tmp", delete=False) as f:
            temp = Path(f.name)
            json.dump(value, f, ensure_ascii=False, allow_nan=False, indent=2)
            f.write("\n")
            f.flush()
            os.fsync(f.fileno())
        os.replace(temp, path)
    finally:
        if temp and temp.exists():
            temp.unlink()


def workbook_rows(content, suffix):
    if suffix.lower() == ".csv":
        text = content.decode("utf-8-sig")
        return [(str(i + 1), list(csv.reader(io.StringIO(section))))
                for i, section in enumerate(text.split("\f"))]
    if suffix.lower() != ".xlsx":
        return []
    with zipfile.ZipFile(io.BytesIO(content)) as z:
        if sum(i.file_size for i in z.infolist()) > 80_000_000:
            raise ValueError("Workbook exceeds 80 MB uncompressed limit")
        shared = []
        if "xl/sharedStrings.xml" in z.namelist():
            root = ET.fromstring(z.read("xl/sharedStrings.xml"))
            shared = ["".join(t.text or "" for t in si.iter(f"{{{NS['s']}}}t"))
                      for si in root]
        # Tab titles, so an audit can cite "2_Ээлжийн_бүртгэл" rather than the archive member name.
        titles = {}
        if {"xl/workbook.xml", "xl/_rels/workbook.xml.rels"} <= set(z.namelist()):
            targets = {r.get("Id"): r.get("Target", "") for r in ET.fromstring(z.read("xl/_rels/workbook.xml.rels"))}
            for sheet in ET.fromstring(z.read("xl/workbook.xml")).iter(f"{{{NS['s']}}}sheet"):
                target = targets.get(sheet.get(f"{{{REL}}}id"), "").lstrip("/")
                titles[target if target.startswith("xl/") else "xl/" + target] = sheet.get("name")
        result = []
        for name in sorted(z.namelist()):
            if not re.fullmatch(r"xl/worksheets/sheet\d+\.xml", name):
                continue
            rows = []
            for row in ET.fromstring(z.read(name)).findall("s:sheetData/s:row", NS):
                # Empty rows are left out of the file; pad them so a row's index + 1 is its sheet row number.
                number = int(row.get("r") or len(rows) + 1)
                rows.extend([] for _ in range(number - 1 - len(rows)))
                cells = {}
                for c in row.findall("s:c", NS):
                    letters = re.match(r"[A-Z]+", c.get("r", "A1"))[0]
                    index = 0
                    for letter in letters:
                        index = index * 26 + ord(letter) - 64
                    raw = c.find("s:v", NS)
                    value = raw.text if raw is not None else ""
                    if c.get("t") == "s" and value:
                        value = shared[int(value)]
                    elif c.get("t") == "inlineStr":
                        value = "".join(t.text or "" for t in c.findall("s:is//s:t", NS))
                    cells[index - 1] = value or ""
                rows.append([cells.get(i, "") for i in range(max(cells, default=-1) + 1)])
            result.append((titles.get(name, name), rows))
        return result


def norm(value):
    return re.sub(r"\s+", " ", str(value).strip().lower())


ATTENDANCE_ROLE_ALIASES = {
    norm("Туслах тогооч"): norm("Тогоочийн туслах"),
    norm("Угаагч"): norm("Туслах угаагч"),
    norm("ХАБЭА мэргэжилтэн"): norm("ХАБ, Кемп менежер"),
    norm("Аж ахуйн ажилтан"): norm("Кемп бой"),
    norm("Жолооч"): norm("Усны жолооч"),
}


def number(value):
    text = str(value).strip()
    if not text or text.startswith("#") or text in {"—", "-"}:
        return None
    # Thousands may be grouped with commas or spaces ("671 289.0" in the collar sheet).
    n = float(re.sub(r"[\s,]", "", text))
    if not math.isfinite(n):
        raise ValueError("Non-finite numeric value")
    return n


def date(value):
    text = str(value).strip()
    if not text:
        return ""
    if re.fullmatch(r"\d{4}-\d{2}-\d{2}.*", text):
        datetime.strptime(text[:10], "%Y-%m-%d")
        return text[:10]
    if re.fullmatch(r"\d+(\.\d+)?", text):
        return (datetime(1899, 12, 30) + timedelta(days=float(text))).strftime("%Y-%m-%d")
    for form in ("%Y/%m/%d", "%d/%m/%Y", "%Y.%m.%d"):
        try:
            return datetime.strptime(text, form).strftime("%Y-%m-%d")
        except ValueError:
            pass
    raise ValueError(f"Unrecognized date: {text}")


def hole_id(value):
    # Any area's drill holes: DTDH, ZHDH, UGDH, STDH, KHDH, ...
    h = str(value).strip().upper().replace("-", "")
    return h if re.fullmatch(r"[A-Z]{2}DH\d{4,}", h) else None


def area_of(hole, folder_area=""):
    """Area of a hole: by its id prefix, else from its Drive area folder ("4. Sant")."""
    return AREAS.get(hole[:4]) or folder_area or UNKNOWN_AREA


def folder_area(name):
    plain = re.sub(r"^\s*\d+\s*\.\s*", "", name).strip()
    return AREA_FOLDERS.get(plain.lower(), plain)


def parse_collar(rows):
    output = []
    headers = None
    for row in rows:
        names = [norm(v) for v in row]
        if "hole id" in names and any("plan depth" in v for v in names):
            headers = names
            continue
        if not headers:
            continue
        def get(match):
            i = next((i for i, h in enumerate(headers) if match(h)), -1)
            return row[i] if 0 <= i < len(row) else ""
        h = hole_id(get(lambda x: x == "hole id"))
        if not h:
            continue
        output.append({"id": h, "site": "Нэргүй Өндөр", "targetArea": AREAS.get(h[:4], ""),
                       "e": number(get(lambda x: x == "e")),
                       "n": number(get(lambda x: x == "n")),
                       "z": number(get(lambda x: x == "z")),
                       "az": number(get(lambda x: x.startswith("azimuth"))),
                       "dip": number(get(lambda x: x.startswith("dip"))),
                       "plan": number(get(lambda x: "plan depth" in x)),
                       "collarDepth": number(get(lambda x: "drilled depth" in x)),
                       "start": date(get(lambda x: "started date" in x)),
                       "finish": date(get(lambda x: "finished date" in x)),
                       "recovery": number(get(lambda x: x == "core recovery")),
                       "boxes": number(get(lambda x: "core boxes" in x)),
                       # The team's log register ("Completed", "in progress", blank = not done).
                       "geologyLog": str(get(lambda x: x == "geology log")).strip(),
                       "geotechLog": str(get(lambda x: x == "geotechnical log")).strip(),
                       "pxrfLog": str(get(lambda x: x == "xrf combined log")).strip(),
                       "corePhoto": str(get(lambda x: x == "core photo")).strip(),
                       "sampling": str(get(lambda x: x == "sampling")).strip()})
    return output


def canonical_rig(value):
    # Owner correction 2026-11-05: C-1600 was a transcription error, not a third rig.
    value = value.strip()
    return "C-1800" if value == "C-1600" else value


def parse_shifts(rows, unassigned=None, rejected=None):
    """Shift records of a sheet. Rows whose rig is not C-1800/CSD-1300 go to `unassigned`; with a
    `rejected` list an invalid row is reported there (with its reason) instead of failing the sheet."""
    output = []
    headers = None
    for row_number, row in enumerate(rows, start=1):
        try:
            item = _parse_shift_row(row, headers, unassigned, row_number)
        except ValueError as error:
            if rejected is None:
                raise
            rejected.append({**_row_identity(row, headers), "row": row_number, "reason": str(error)})
            continue
        if item == "header":
            headers = [norm(v) for v in row]
        elif item:
            output.append(item)
    return output


def _row_identity(row, headers):
    """Rig, date, shift and hole of a rejected row, as far as they can be read."""
    identity = {"rig": "", "date": "", "shift": "", "hole": ""}
    if not headers:
        return identity
    def get(match):
        i = next((i for i, h in enumerate(headers) if match(h)), -1)
        return str(row[i]).strip() if 0 <= i < len(row) else ""
    identity["rig"] = canonical_rig(get(lambda x: x == "rig" or x.endswith(" rig")))
    identity["shift"] = get(lambda x: x == "shift" or x.endswith(" shift"))
    identity["hole"] = hole_id(get(lambda x: "hole id" in x)) or ""
    try:
        identity["date"] = date(get(lambda x: x == "date" or x.endswith(" date")))
    except ValueError:
        pass
    return identity


def _parse_shift_row(row, headers, unassigned, row_number):
    """"header" for the header row, None for rows that are not a shift, else the shift record."""
    names = [norm(v) for v in row]
    if "dt" in names and any("source" in h for h in names) and any("hole id" in h for h in names):
        return "header"
    if not headers:
        return None
    def get(match):
        i = next((i for i, h in enumerate(headers) if match(h)), -1)
        return row[i] if 0 <= i < len(row) else ""
    rig = canonical_rig(get(lambda x: x == "rig" or x.endswith(" rig")))
    h = hole_id(get(lambda x: "hole id" in x))
    if h and rig not in RIGS and unassigned is not None and any(str(v).strip() for v in row):
        # A row whose rig is blank or "Баталгаажаагүй" is kept aside for the audit, never guessed.
        try:
            day = date(get(lambda x: x == "date" or x.endswith(" date")))
        except ValueError:
            day = ""
        shift = get(lambda x: x == "shift" or x.endswith(" shift")).strip()
        if day and shift in {"Өдөр", "Шөнө"}:
            unassigned.append({"rigText": str(get(lambda x: x == "rig" or x.endswith(" rig"))).strip(), "date": day,
                               "shift": shift, "hole": h, "from": number(get(lambda x: x.endswith("from"))),
                               "to": number(get(lambda x: x.endswith("to"))),
                               "meters": number(get(lambda x: x.endswith("drilled"))),
                               "source": str(get(lambda x: "source" in x)).strip(), "row": row_number})
    if rig not in RIGS or not h:
        return None
    shift = get(lambda x: x == "shift" or x.endswith(" shift")).strip()
    item = {"rig": rig, "source": get(lambda x: "source" in x),
            "date": date(get(lambda x: x == "date" or x.endswith(" date"))),
            "shift": shift, "driller": get(lambda x: x == "driller" or x.endswith(" driller")),
            "hole": h, "from": number(get(lambda x: x.endswith("from"))),
            "to": number(get(lambda x: x.endswith("to"))),
            "meters": number(get(lambda x: x.endswith("drilled"))),
            "st": number(get(lambda x: x == "st")),
            "rt": number(get(lambda x: x == "rt")),
            "dt": number(get(lambda x: x == "dt")),
            "hours": number(get(lambda x: x == "shift hours (source)")),
            "notes": get(lambda x: "work notes" in x), "sheetRow": row_number}
    # The source shift duration is distinct from the subtotal of filled codes.
    # Partially coded shifts may have a 6 h code subtotal but a 12 h duration.
    if item['hours'] is None:
        item['hours'] = number(get(lambda x: x.endswith('total') or x == 'total code hrs'))
    # Owner correction (2026-10-22): this uncoded shift has DT=0;
    # its source work notes explicitly report a 12-hour shift.
    if (h == 'ZHDH2602' and rig == 'C-1800'
            and item['date'] == '2026-10-19' and shift == 'Шөнө'
            and item['from'] == 287 and item['to'] == 326):
        if item['dt'] is None:
            item['dt'] = 0.0
            item['notes'] += ' | Owner correction 2026-10-22: DT=0.'
        if item['hours'] is None and '12ц' in item['notes']:
            item['hours'] = 12.0
    # This zero-metre incident shift is fully accounted for by PT and OT.
    if (h == 'DTDH2602' and rig == 'C-1800'
            and item['date'] == '2026-10-18' and shift == 'Шөнө'
            and item['from'] == 266 and item['to'] == 266
            and item['meters'] == 0 and item['dt'] is None
            and item['hours'] == 12
            and number(get(lambda x: x == 'pt')) == 0.5
            and number(get(lambda x: x == 'ot')) == 11.5):
        item['dt'] = 0.0
        item['notes'] += ' | DT=0: PT 0.5 + OT 11.5 accounts for all 12 hours.'
    # Owner policy 2026-10-27: genuinely blank DT/total hours use 12 h.
    # Keep explicit zero, malformed values and previously verified corrections.
    assumed = []
    for key, match in (('dt', lambda x: x == 'dt'),
                       ('hours', lambda x: x == 'shift hours (source)' or x.endswith('total') or x == 'total code hrs')):
        if item[key] is None and not str(get(match)).strip():
            item[key] = 12.0
            assumed.append('DT' if key == 'dt' else 'TOTAL')
    if assumed:
        item['notes'] += ' | User default 2026-10-27: ' + ', '.join(assumed) + '=12 h (source blank; estimated).'
    water_header = next((h for h in headers if 'water consumption' in h or 'усны хэрэглээ' in h), '')
    water = number(get(lambda h: h == water_header)) if water_header else None
    if water is not None and water < 0:
        raise ValueError('Invalid water consumption')
    # Publish volume in m3 only when source units are explicit.
    if water is not None and any(unit in water_header for unit in ('литр', 'liter', '(l)', '(л)')):
        water /= 1000
    elif water is not None and not any(unit in water_header for unit in ('м³', 'м3', 'm³', 'm3')):
        water = None
    item['waterUsageM3'] = water
    if not item["date"] or shift not in {"Өдөр", "Шөнө"}:
        raise ValueError(f"Missing/invalid date or shift for {h}")
    for key in ("from", "to", "meters", "st", "rt", "dt", "hours"):
        # A blank optional time code is unknown, not zero. Keep it null.
        if key in {"st", "rt"} and item[key] is None and str(get(lambda x: x == key)).strip() in {"", "-", "—"}:
            continue
        if item[key] is None or item[key] < 0:
            raise ValueError(f"Missing/invalid {key} for {h} on {item['date']}")
    if abs(item["to"] - item["from"] - item["meters"]) > 0.05:
        raise ValueError(f"Depth/meters mismatch for {h} on {item['date']}")
    if item["dt"] + (item["st"] or 0) + (item["rt"] or 0) > item["hours"] + 0.01:
        raise ValueError(f"Work hours mismatch for {h} on {item['date']}")
    return item


def _finance_number(value):
    text = str(value).replace("₮", "").replace(",", "").replace("\u00a0", "").strip()
    return number(text)


def _finance_cell(row, index):
    return str(row[index]).strip() if 0 <= index < len(row) else ""


def _calendar_day_cell(row, index):
    value = _finance_cell(row, index)
    if not re.fullmatch(r"\d+(?:\.0+)?", value):
        return None
    return int(float(value))


def _find_finance_table(sheets, required_headers):
    for name, rows in sheets:
        for index, row in enumerate(rows):
            headers = [norm(value) for value in row]
            if all(any(required in header for header in headers) for required in required_headers):
                return name, rows, index, headers
    raise ValueError("Finance workbook is missing a required header row")


def _finance_has_headers(sheets, required_headers, exact=False):
    return any(
        all(
            required in [norm(value) for value in row]
            if exact else any(required in norm(value) for value in row)
            for required in required_headers
        )
        for _, rows in sheets
        for row in rows
    )


def _salary_table(sheets):
    # The revised file supplies take-home monthly rates in its role summary.
    # Read that summary once; employee/contract tabs must never be combined.
    if _finance_has_headers(sheets, ('албан тушаалын нэрс', 'гарт авах цалин')):
        _, rows, header_index, headers = _find_finance_table(sheets, ('албан тушаалын нэрс', 'гарт авах цалин'))
        title_col = next(i for i,h in enumerate(headers) if h == 'албан тушаалын нэрс')
        monthly_col = next(i for i,h in enumerate(headers) if h == 'гарт авах цалин')
        count_col = next(i for i,h in enumerate(headers) if h in {'албан тушаалын тоо', 'тоо'})
        extra_col = next((i for i,h in enumerate(headers) if h == 'нэмэгдэл цалингийн мэдээлэл'), -1)
        aliases = {
            'өрөмдлөгийн ахлах ажилтан': 'супервайзер',
            'өрөмдлөгийн өдрийн ээлжийн мастер': 'өрмийн мастер',
            'өрөмдлөгийн шөнийн ээлжийн мастер': 'өрмийн мастер',
            'өрөмдлөгийн ээлжийн мастер': 'өрмийн мастер',
            'өрөмдлөгийн өдрийн ээлжийн туслах': 'өрмийн туслах',
            'өрөмдлөгийн шөнийн ээлжийн туслах': 'өрмийн туслах',
            'өрөмдлөгийн ээлжийн туслах': 'өрмийн туслах',
            'өрөмдлөгийн өдрийн ээлжийн жолооч': 'усны жолооч',
            'өрөмдлөгийн шөнийн ээлжийн жолооч': 'усны жолооч',
            'өрөмдлөгийн усны ээлжийн жолооч': 'усны жолооч',
            'түлшний нярав, механикч, жолооч': 'механик, түлшний жолооч',
            'экскаватор, үйлчилгээний жолооч': 'унагалдай оператор, үйлчилгээний жолооч',
            'өрмийн дээж зүсэгч': 'дээж зүсэгч',
            'хабэаа, кэмп менежер': 'хаб, кемп менежер',
            'туслах тогооч': 'тогоочийн туслах',
            'угаагч, үйлчилгээний ажилтан': 'туслах угаагч',
            'кэмпийн ажилтан, галч': 'кемп бой',
            'сэлбэг, хангамж бэлтгэх нярав': 'нярав',
        }
        result = {}
        for row in rows[header_index + 1:]:
            title = norm(_finance_cell(row,title_col))
            count = _finance_number(_finance_cell(row,count_col))
            if not title or title.startswith('нийт') or count is None:
                continue
            key = aliases.get(title,title)
            note = _finance_cell(row,extra_col)
            bonus = re.search(r'1\s*метр\s*тутамд\s*([\d, ]+)\s*төгрөг',note,re.I)
            position = {'headcount':count,'monthlySalary':_finance_number(_finance_cell(row,monthly_col)),
                        'incentiveDailyRate':None,'bonusPerMeter':_finance_number(bonus[1]) if bonus else None}
            alone = re.search(r'30\s*хоногт\s*([\d, ]+)\s*төгрөг',note,re.I) if 'ганцаараа' in note else None
            if alone and key == 'өрмийн туслах':
                position['singleAssistantDailyExtra'] = _finance_number(alone[1]) / 30
            if key in result:
                old = result[key]
                if any(old[k] != position[k] for k in ('monthlySalary','bonusPerMeter')):
                    raise ValueError('Conflicting day/night compensation rates')
                old['headcount'] += count
                if 'singleAssistantDailyExtra' in position:
                    old['singleAssistantDailyExtra'] = position['singleAssistantDailyExtra']
            else:
                result[key] = position
        if not result:
            raise ValueError('Revised compensation summary has no rates')
        return result
    _, rows, header_index, headers = _find_finance_table(
        sheets, ("албан тушаал", "ажилтны тоо", "нэрлэсэн цалин"))
    title_col = next(i for i, value in enumerate(headers) if "албан тушаал" in value)
    count_col = next(i for i, value in enumerate(headers) if "ажилтны тоо" in value)
    monthly_col = next(i for i, value in enumerate(headers) if "нэрлэсэн цалин" in value)
    bonus_col = next((i for i, value in enumerate(headers) if "бонус" in value), -1)
    daily_col = next((i for i, value in enumerate(headers) if "урамшуулал" in value), -1)
    if daily_col < 0:
        daily_col = next((i for i, value in enumerate(headers) if value.startswith("өдрийн")), -1)
    payroll = {}
    for row in rows[header_index + 1:]:
        title = _finance_cell(row, title_col)
        count = _finance_number(_finance_cell(row, count_col))
        if not title or count is None or norm(title).startswith("нийт"):
            continue
        key = norm(title)
        if key in payroll:
            raise ValueError("Salary workbook contains a duplicate job title")
        payroll[key] = {
            "headcount": count,
            "monthlySalary": _finance_number(_finance_cell(row, monthly_col)),
            "incentiveDailyRate": _finance_number(_finance_cell(row, daily_col)),
            "bonusPerMeter": _finance_number(_finance_cell(row, bonus_col)),
        }
    if not payroll:
        raise ValueError("Salary workbook contains no payroll positions")
    return payroll


def _attendance_layout(sheets):
    _, rows, header_index, headers = _find_finance_table(sheets, ("нэр", "албан тушаал"))
    name_col = next(i for i, value in enumerate(headers) if value == "нэр")
    role_col = next(i for i, value in enumerate(headers) if value == "албан тушаал")
    day_header_index, day_columns = None, None
    for index, row in enumerate(rows):
        for start in range(len(row)):
            if _calendar_day_cell(row, start) != 1:
                continue
            columns = []
            for day in range(1, 32):
                if _calendar_day_cell(row, start + day - 1) != day:
                    break
                columns.append(start + day - 1)
            if len(columns) >= 28:
                day_header_index, day_columns = index, columns
                break
        if day_columns:
            break
    if day_columns is None:
        raise ValueError("Attendance workbook has no sequential calendar-day header")
    all_text = "\n".join(str(cell) for row in rows for cell in row)
    month_match = re.search(r"(?<!\d)(\d{1,2})\s*[-–]?\s*р\s*сар", all_text, re.I)
    year_match = re.search(r"\b(20\d{2})\b", all_text)
    if not month_match or not year_match:
        raise ValueError("Attendance workbook is missing its reporting month or year")
    year, month = int(year_match[1]), int(month_match[1])
    if month < 1 or month > 12:
        raise ValueError("Attendance workbook contains an invalid reporting month")
    month_days = (datetime(year + (month == 12), month % 12 + 1, 1) -
                  timedelta(days=1)).day
    if len(day_columns) > month_days:
        raise ValueError("Attendance calendar contains days outside the reporting month")
    return rows, header_index, day_header_index, day_columns, name_col, role_col, year, month


def finance_aggregates(salary_sheets, attendance_sheets, shifts):
    """Aggregate attendance-based pay, production bonus and daily field incentives."""
    payroll = _salary_table(salary_sheets)
    rows, _, day_header_index, day_columns, name_col, role_col, year, month = _attendance_layout(attendance_sheets)
    period = f"{year:04d}-{month:02d}"
    month_days = (datetime(year + (month == 12), month % 12 + 1, 1) - timedelta(days=1)).day
    period_shifts = [row for row in shifts if row['date'].startswith(period + '-')]
    if not period_shifts:
        raise ValueError("No drilling records match the finance reporting month")
    last_day = max(int(row['date'][-2:]) for row in period_shifts)
    # The source's daily amount is an additional field incentive, not base pay.
    food_daily = FOOD_COST_PER_FIELD_DAY * 21
    amounts = ('laborCost', 'foodCost', 'bonusCost', 'incentiveCost')
    rig_shifts = {}
    for day in range(1, last_day + 1):
        for rig in sorted(FINANCE_RIGS):
            for shift in ('Өдөр', 'Шөнө'):
                date_key = f"{period}-{day:02d}"
                rig_shifts[(date_key, rig, shift)] = {
                    'date': date_key, 'rig': rig, 'shift': shift,
                    'laborCost': 0.0, 'foodCost': round(food_daily / 4, 2),
                    'bonusCost': 0.0, 'incentiveCost': 0.0,
                }
    meters = {}
    for row in period_shifts:
        key = (row['date'], row['rig'], row['shift'])
        meters[key] = meters.get(key, 0.0) + row['meters']
    # Only explicitly assigned assistant attendance can prove one-person staffing.
    assistant_counts = {}
    role = ''
    for row in rows[day_header_index + 1:]:
        if not _finance_cell(row, name_col):
            continue
        role = _finance_cell(row, role_col) or role
        if ATTENDANCE_ROLE_ALIASES.get(norm(role),norm(role)) != 'өрмийн туслах':
            continue
        for column, day in zip(day_columns[:last_day], range(1,last_day+1)):
            code = _finance_cell(row,column).upper()
            if re.fullmatch(r'C(13|18)(D|N)',code):
                assistant_counts[(day,code)] = assistant_counts.get((day,code),0) + 1
    role = ''
    for row in rows[day_header_index + 1:]:
        if not _finance_cell(row, name_col):
            continue
        role = _finance_cell(row, role_col) or role
        position_key = ATTENDANCE_ROLE_ALIASES.get(norm(role), norm(role))
        for column, day in zip(day_columns[:last_day], range(1, last_day + 1)):
            code = _finance_cell(row, column).upper()
            match = re.fullmatch(r'C(13|18)(D|N)', code)
            # P is factory attendance, outside the drilling field cost centre.
            if not match and code not in {'A', 'W', 'D'}:
                continue
            position = payroll.get(position_key)
            if position is None or position['monthlySalary'] is None:
                raise ValueError('Field attendance has no matching base pay rate')
            date_key = f"{period}-{day:02d}"
            if match:
                keys = [(date_key, 'CSD-1300' if match[1] == '13' else 'C-1800',
                         'Өдөр' if match[2] == 'D' else 'Шөнө')]
            else:
                # Shared field staff are distributed evenly across two rigs/two shifts.
                keys = [(date_key, rig, shift) for rig in sorted(FINANCE_RIGS)
                        for shift in ('Өдөр', 'Шөнө')]
            base = position['monthlySalary'] / month_days
            incentive = position['incentiveDailyRate'] or 0.0
            if match and assistant_counts.get((day,code)) == 1 and position_key == 'өрмийн туслах':
                incentive += position.get('singleAssistantDailyExtra',0.0)
            for key in keys:
                bonus = (position['bonusPerMeter'] or 0.0) * meters.get(key, 0.0) if match else 0.0
                # Apply the user's 13% loading to each person's components once.
                entry = rig_shifts[key]
                entry['laborCost'] += base * 1.13 / len(keys)
                entry['bonusCost'] += bonus * 1.13
                entry['incentiveCost'] += incentive * 1.13 / len(keys)
    daily = {}
    for entry in rig_shifts.values():
        day = daily.setdefault(entry['date'], {'date': entry['date'], **dict.fromkeys(amounts, 0.0)})
        for key in amounts:
            entry[key] = round(entry[key], 2)
            day[key] = round(day[key] + entry[key], 2)
    return {'period': period, 'daily': [daily[key] for key in sorted(daily)],
            'rigShifts': [entry for _, entry in sorted(rig_shifts.items())]}



class Drive:
    def __init__(self, credentials_path=None):
        try:
            import google.auth
            from google.auth.transport.requests import Request
        except ImportError as e:
            raise RuntimeError("Drive access needs: python -m pip install -r requirements.txt") from e
        if credentials_path:
            self.credentials, _ = google.auth.load_credentials_from_file(str(credentials_path), scopes=[SCOPE])
        elif os.getenv("GOOGLE_DRIVE_SERVICE_ACCOUNT_JSON"):
            from google.oauth2 import service_account
            self.credentials = service_account.Credentials.from_service_account_info(
                json.loads(os.environ["GOOGLE_DRIVE_SERVICE_ACCOUNT_JSON"]), scopes=[SCOPE])
        else:
            self.credentials, _ = google.auth.default(scopes=[SCOPE])
        self.refresh_request = Request()

    def request(self, url):
        if not self.credentials.valid:
            self.credentials.refresh(self.refresh_request)
        req = urllib.request.Request(url, headers={"Authorization": "Bearer " + self.credentials.token})
        for attempt in range(3):
            try:
                with urllib.request.urlopen(req, timeout=90) as response:
                    content = response.read(25_000_001)
                    if len(content) > 25_000_000:
                        raise ValueError("Drive file exceeds 25 MB download limit")
                    return content
            except urllib.error.HTTPError as error:
                if error.code not in {429, 500, 502, 503, 504} or attempt == 2:
                    raise
                LOG.warning("Temporary Drive read error HTTP %s; retrying", error.code)
                time.sleep(2 ** attempt)

    def files(self, folder):
        token = None
        result = []
        while True:
            params = {"q": f"'{folder}' in parents and trashed = false", "pageSize": "1000",
                      "fields": "nextPageToken,files(id,name,mimeType,modifiedTime,webViewLink)",
                      "supportsAllDrives": "true", "includeItemsFromAllDrives": "true"}
            if token:
                params["pageToken"] = token
            data = json.loads(self.request("https://www.googleapis.com/drive/v3/files?" + urllib.parse.urlencode(params)))
            result.extend(data.get("files", []))
            token = data.get("nextPageToken")
            if not token:
                return result

    def download(self, f):
        base = "https://www.googleapis.com/drive/v3/files/" + urllib.parse.quote(f["id"], safe="")
        if f["mimeType"] == "application/vnd.google-apps.spreadsheet":
            url = base + "/export?" + urllib.parse.urlencode({"mimeType": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"})
        else:
            url = base + "?alt=media&supportsAllDrives=true"
        return self.request(url)


def local_sources(directory):
    records = []
    for p in Path(directory).rglob("*"):
        if p.suffix.lower() not in {".csv", ".xlsx"} or p.name.startswith("~$"):
            continue
        if p.stat().st_size > 25_000_000:
            raise ValueError(f"Source exceeds 25 MB: {p.name}")
        records.append({"name": p.name, "url": "", "modified": p.stat().st_mtime,
                        "content": p.read_bytes(), "suffix": p.suffix})
    # Workbooks supersede seeded CSV exports when both are present.
    return sorted(records, key=lambda x: (x["suffix"] == ".xlsx", x["modified"]), reverse=True)


def report_metadata(file, hole, rig, folder_url):
    rig = canonical_rig(rig or "")
    name = file.get("name", "")
    match = re.search(r"(20\d{2})(\d{2})(\d{2})[_\s-]([dn])(?:[.\s_-]|$)", name, re.I)
    if not hole or rig not in RIGS or not match or not file.get("mimeType", "").startswith("image/"):
        return None
    report_date = f"{match[1]}-{match[2]}-{match[3]}"
    try:
        datetime.strptime(report_date, "%Y-%m-%d")
    except ValueError:
        return None
    return {"hole": hole, "rig": rig, "date": report_date,
            "shift": "Өдөр" if match[4].lower() == "d" else "Шөнө", "name": name,
            "url": file.get("webViewLink") or f"https://drive.google.com/file/d/{file['id']}/view",
            "fileId": file["id"], "folderUrl": folder_url}


def daily_file(file, hole, rig, folder_url):
    """Any photo or PDF in a hole's 02 folder; date and shift are read from its name when they are there."""
    name = file.get("name", "")
    if not hole or not (file.get("mimeType", "").startswith("image/") or file.get("mimeType") == "application/pdf"):
        return None
    report_date = shift = ""
    match = re.search(r"(20\d{2})-?(\d{2})-?(\d{2})", name)
    if match:
        try:
            report_date = datetime(int(match[1]), int(match[2]), int(match[3])).strftime("%Y-%m-%d")
        except ValueError:
            report_date = ""
    token = re.search(r"(?:^|[_\s-])([dn])(?:[._\s-]|$)", name[match.end():] if match else name, re.I)
    if token:
        shift = "Өдөр" if token[1].lower() == "d" else "Шөнө"
    rig = canonical_rig(rig or "")
    return {"hole": hole, "rig": rig if rig in RIGS else "", "date": report_date, "shift": shift, "name": name,
            "url": file.get("webViewLink") or f"https://drive.google.com/file/d/{file['id']}/view",
            "fileId": file["id"], "folderUrl": folder_url}


def report_stem(name):
    """File name without image/PDF extensions ("x.JPG.jpg" -> "x"), lower case, for matching a sheet's Source."""
    stem = str(name).strip().lower()
    while re.search(r"\.(jpe?g|png|heic|pdf)$", stem):
        stem = re.sub(r"\.(jpe?g|png|heic|pdf)$", "", stem)
    return stem


def attach_reports(rows, reports):
    """Link each shift to its raw Drive report: by hole, rig, date and shift, else by the file its Source cites."""
    index, names = {}, {}
    for report in reports:
        key = (report["hole"], report["rig"], report["date"], report["shift"])
        group = index.setdefault(key, [])
        if not any(old["url"] == report["url"] for old in group):
            group.append(report)
        names.setdefault(report_stem(report["name"]), []).append(report)
    linked = set()
    for row in rows:
        row["reports"] = index.get((row["hole"], row["rig"], row["date"], row["shift"]), [])
        if not row["reports"] and str(row.get("source", "")).strip():
            candidates = names.get(report_stem(row["source"]), [])
            # The same file name in two hole folders: the shift's own hole folder holds its report.
            candidates = [r for r in candidates if r["hole"] == row["hole"]] or candidates[:1]
            row["reports"] = [{**r, "hole": row["hole"], "rig": row["rig"], "date": row["date"],
                               "shift": row["shift"], "match": "source"} for r in candidates[:1]]
        linked.update(r["url"] for r in row["reports"])
    return [r for r in reports if r["url"] not in linked]


def inventory_section(name):
    """Logging data kind of a hole sub-folder ("05. Core & RC Photography" -> photos; "10.pXRF" -> pxrf)."""
    match = re.match(r"\s*(\d{2})\s*\.", name)
    return INVENTORY_SECTIONS.get(match[1], "") if match else ""


def add_inventory_file(inventory, hole, section, f):
    entry = inventory.setdefault(hole, {}).setdefault(section, {"url": "", "files": []})
    entry["files"].append({"name": f["name"], "modified": f.get("modifiedTime", ""),
                           "url": f.get("webViewLink") or f"https://drive.google.com/file/d/{f['id']}/view"})


def summarize_inventory(inventory):
    """Photo folders become counts (box photos are numerous); document folders keep their file list.

    A photo is counted once per name stem: a box's CR2 and its JPEG export, or a resized copy in a
    sub-folder, are one photo. Files renamed "delete..." (rejected repeat shots) are not counted."""
    result = {}
    for hole, sections in sorted(inventory.items()):
        result[hole] = {}
        for section, entry in sorted(sections.items()):
            files = sorted(entry["files"], key=lambda f: (f["name"].lower(), f["url"]))
            latest = max((f["modified"] for f in files), default="")
            if section != "photos":
                result[hole][section] = {"url": entry["url"], "count": len(files), "latest": latest,
                                         "files": files[:INVENTORY_FILE_LIMIT]}
                continue
            stems, formats = set(), {}
            for f in files:
                stem, dot, suffix = f["name"].rpartition(".")
                suffix = suffix.upper().replace("JPEG", "JPG")
                if not dot or suffix not in PHOTO_FORMATS or stem.strip().lower().startswith("delete"):
                    continue
                stems.add(stem.strip().lower())
                formats[suffix] = formats.get(suffix, 0) + 1
            result[hole][section] = {"url": entry["url"], "count": len(stems), "latest": latest,
                                     "formats": dict(sorted(formats.items()))}
    return result


def drive_sources(folder, credentials_path):
    drive = Drive(credentials_path)
    pending, seen, records, folders, reports, inventory = [(folder, None, None, False, None, ())], set(), [], {}, [], {}
    while pending:
        # section: None above and at the hole folder; inside it, the data kind of its sub-folder ("" = not tracked).
        # path: folder names from the root down to this folder.
        fid, hole, rig, daily, section, path = pending.pop()
        if fid in seen:
            continue
        seen.add(fid)
        children = drive.files(fid)
        if hole and hole not in folders and not daily and not rig:
            folders[hole] = {"url": f"https://drive.google.com/drive/folders/{fid}",
                             "area": folder_area(path[-2]) if len(path) > 1 else "",
                             "folders": [{"name": f["name"], "url": f"https://drive.google.com/drive/folders/{f['id']}"}
                                         for f in children if f["mimeType"] == "application/vnd.google-apps.folder"]}
        for f in children:
            if f["mimeType"] == "application/vnd.google-apps.folder":
                if re.search(r"duplicat|archive|to_delete", f["name"], re.I):
                    continue
                child_section = section
                if hole and section is None:
                    child_section = inventory_section(f["name"])
                    if child_section:
                        entry = inventory.setdefault(hole, {}).setdefault(child_section, {"url": "", "files": []})
                        entry["url"] = entry["url"] or f"https://drive.google.com/drive/folders/{f['id']}"
                pending.append((f["id"], hole_id(f["name"]) or hole,
                                canonical_rig(f["name"]) if canonical_rig(f["name"]) in RIGS else rig,
                                daily or f["name"].startswith("02."), child_section, path + (f["name"],)))
            elif "collar" in f["name"].lower() or "shift report" in f["name"].lower():
                if f["mimeType"] in {"application/vnd.google-apps.spreadsheet",
                                     "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"}:
                    records.append({"name": f["name"], "url": f.get("webViewLink", ""),
                                    "modified": f.get("modifiedTime", ""),
                                    "content": drive.download(f), "suffix": ".xlsx"})
            elif daily:
                folder_url = f"https://drive.google.com/drive/folders/{fid}"
                report = report_metadata(f, hole, rig, folder_url) or daily_file(f, hole, rig, folder_url)
                if report:
                    reports.append(report)
            elif hole and section:
                add_inventory_file(inventory, hole, section, f)
    return (sorted(records, key=lambda x: x["modified"], reverse=True), folders, reports,
            summarize_inventory(inventory))


def mud_aggregates(sheets):
    """Use the confirmed stock total and source shift allocation, never metres as a norm."""
    bag_kg = price = total = None
    allocations = []
    for _, rows in sheets:
        for row in rows:
            if row and norm(row[0]) == 'mud':
                bag_kg, price = _finance_number(_finance_cell(row, 1)), _finance_number(_finance_cell(row, 3))
            for index, cell in enumerate(row):
                if norm(cell) == 'нийт тооцооны шуудай':
                    total = _finance_number(_finance_cell(row, index + 1))
        header = None
        for row in rows:
            names = [norm(c) for c in row]
            if 'mud тооцоо (шуудай)' in names and 'огноо' in names:
                header = names
                continue
            if header is None:
                continue
            def get(label):
                return _finance_cell(row, header.index(label))
            if get('өрөм') not in FINANCE_RIGS or get('ээлж') not in {'Өдөр', 'Шөнө'}:
                continue
            bags = _finance_number(get('mud тооцоо (шуудай)'))
            if bags is None or bags < 0:
                raise ValueError('Missing or invalid source mud allocation')
            allocations.append({'date': date(get('огноо')), 'rig': get('өрөм'),
                                'shift': get('ээлж'), 'hole': hole_id(get('цооног')), 'bags': bags})
    if any(value is None or value <= 0 for value in (total, bag_kg, price)) or not allocations:
        raise ValueError('Missing mud total, unit price or shift allocations')
    allocated = sum(row['bags'] for row in allocations)
    if not math.isclose(allocated, total, abs_tol=0.001):
        raise ValueError('Source mud allocation does not balance to confirmed total')
    # Exported formula decimals can have tiny rounding differences.
    for row in allocations:
        row['bags'] = round(row['bags'] * total / allocated, 8)
    allocations[-1]['bags'] = round(total - sum(row['bags'] for row in allocations[:-1]), 8)
    return {'totalBags': total, 'bagKg': bag_kg, 'pricePerBag': price, 'allocations': allocations}


def fuel_aggregates(sheets, shifts, period):
    """Read drilling issues and source cost; allocate daily issues by reported hours."""
    daily, allocations = [], []
    for _, rows in sheets:
        header = None
        for row in rows:
            names = [norm(c) for c in row]
            if 'зарлага (өрөм) (л)' in names and 'огноо' in names:
                header = names
                if 'өрөмийн зардал (төгрөг)' not in header:
                    raise ValueError('Fuel ledger has no drilling cost column')
                continue
            if header is None or not _finance_cell(row, header.index('огноо')):
                continue
            raw_date = _finance_cell(row, header.index('огноо'))
            if not re.match(r'^(?:20\d{2}[-./]|\d+(?:\.\d+)?$)', raw_date):
                continue
            day = date(raw_date)
            if not day.startswith(period + '-'):
                continue
            litres = _finance_number(_finance_cell(row, header.index('зарлага (өрөм) (л)')))
            cost = _finance_number(_finance_cell(row, header.index('өрөмийн зардал (төгрөг)')))
            if litres is None:
                if cost not in (None, 0):
                    raise ValueError('Fuel ledger cost has no issue volume')
                daily.append({'date': day, 'litres': None, 'cost': None})
                continue
            if litres < 0 or cost is None or cost < 0:
                raise ValueError('Fuel ledger has invalid quantity or cost')
            daily.append({'date': day, 'litres': litres, 'cost': cost})
            weights = {}
            for entry in shifts:
                if entry['date'] == day:
                    key = (entry['rig'], entry['shift'], entry['hole'])
                    weights[key] = weights.get(key, 0.0) + entry.get('hours', 0)
            if not weights or sum(weights.values()) <= 0:
                weights = {(rig, shift, ''): 1 for rig in sorted(FINANCE_RIGS) for shift in ('Өдөр','Шөнө')}
            total_weight = sum(weights.values())
            items = []
            for (rig, shift, hole), weight in weights.items():
                items.append({'date': day, 'rig': rig, 'shift': shift, 'hole': hole,
                              'litres': round(litres * weight / total_weight, 8),
                              'cost': round(cost * weight / total_weight, 2)})
            items[-1]['litres'] = round(litres - sum(r['litres'] for r in items[:-1]), 8)
            items[-1]['cost'] = round(cost - sum(r['cost'] for r in items[:-1]), 2)
            allocations.extend(items)
    if not daily:
        raise ValueError('No fuel ledger dates match the reporting month')
    return {'daily': sorted(daily, key=lambda row: row['date']), 'allocations': allocations}


def apply_uploaded_fuel(finance, shifts, upload_path=None):
    """Retain explicitly supplied ledger issues across scheduled Drive refreshes."""
    upload_path = Path(upload_path) if upload_path is not None else ROOT / 'input' / 'fuel-supplement.json'
    if finance is None or not upload_path.exists():
        return finance
    supplement = load_json(upload_path)
    if supplement['period'] != finance['period']:
        return finance
    from validate_data import validate_fuel
    daily = {row['date']: dict(row) for row in finance['fuel']['daily']}
    uploaded = supplement['daily']
    if len({row['date'] for row in uploaded}) != len(uploaded):
        raise ValueError('Duplicate uploaded fuel date')
    daily.update({row['date']: dict(row) for row in uploaded})
    rows = [['Огноо', 'Зарлага (өрөм) (л)', 'Өрөмийн Зардал (Төгрөг)']]
    rows.extend([row['date'], '' if row['litres'] is None else str(row['litres']),
                 '' if row['cost'] is None else str(row['cost'])]
                for row in sorted(daily.values(), key=lambda row: row['date']))
    fuel = fuel_aggregates([('merged ledger', rows)], shifts, finance['period'])
    validate_fuel(fuel, finance['period'])
    return {**finance, 'fuel': fuel}


def diamond_budget(sheets):
    """Only drill bits and reaming shells; never reusable tools or spare parts."""
    planned = None
    for _, rows in sheets:
        for row in rows:
            if row and norm(row[0]) == norm('Төлөвлөсөн метр'):
                planned = _finance_number(_finance_cell(row, 1))
    if planned is None or planned <= 0:
        raise ValueError('Diamond budget has no positive planned metres')
    _, rows, index, headers = _find_finance_table(sheets, ('нэршил', 'тоо хэмжээ', 'нэгж үнэ төг'))
    total, count = 0.0, 0
    for row in rows[index + 1:]:
        name = _finance_cell(row, headers.index('нэршил'))
        if not re.search(r'\b(?:drill bit|reaming shell)\b', name, re.I):
            continue
        quantity = _finance_number(_finance_cell(row, headers.index('тоо хэмжээ')))
        price = _finance_number(_finance_cell(row, headers.index('нэгж үнэ төг')))
        if quantity is None or price is None or quantity < 0 or price < 0:
            raise ValueError('Invalid diamond budget item')
        total += quantity * price
        count += 1
    if not count or total <= 0:
        raise ValueError('Diamond budget has no eligible items')
    return {'plannedMeters': planned, 'totalBudget': total, 'ratePerMeter': total / planned,
            'sourceUrl': f'https://docs.google.com/spreadsheets/d/{DIAMOND_SHEET_ID}/edit#gid=672180000'}


def apply_diamond_budget(finance):
    if finance is not None and 'diamond' not in finance:
        path = ROOT / 'input' / 'diamond-budget.json'
        if path.exists():
            return {**finance, 'diamond': load_json(path)}
    return finance


def drive_finance_aggregates(credentials_path, shifts, salary_source_id=SALARY_SOURCE_ID):
    drive = Drive(credentials_path)
    pending, seen, files = [FINANCE_FOLDER_ID], set(), {}
    while pending:
        folder = pending.pop()
        if folder in seen:
            continue
        seen.add(folder)
        try:
            children = drive.files(folder)
        except urllib.error.HTTPError as error:
            raise FinanceSourceError("shared finance folder", error.code) from error
        if folder == FINANCE_FOLDER_ID and not children:
            # Drive can return an empty list instead of 403 for a folder whose
            # contents are not shared with the service account.
            raise FinanceSourceError("finance folder contents not visible to sync account", 403)
        for file in children:
            if file["mimeType"] == FOLDER_MIME:
                pending.append(file["id"])
            elif file["mimeType"] in {FINANCE_SHEET_MIME, XLSX_MIME}:
                files[file["id"]] = file

    salary_sheets = attendance_sheets = products_sheets = fuel_sheets = diamond_sheets = None
    if salary_source_id:
        try:
            salary_sheets = workbook_rows(drive.download({'id':salary_source_id,'mimeType':XLSX_MIME}),'.xlsx')
            _salary_table(salary_sheets)
        except urllib.error.HTTPError as error:
            raise FinanceSourceError('selected compensation workbook',error.code) from error
    for file in sorted(files.values(), key=lambda item: item.get("modifiedTime", ""), reverse=True):
        try:
            content = drive.download(file)
        except urllib.error.HTTPError as error:
            if error.code == 404:
                continue
            raise FinanceSourceError("workbook in shared finance folder", error.code) from error
        sheets = workbook_rows(content, ".xlsx")
        if file['id'] == DIAMOND_SHEET_ID:
            diamond_sheets = sheets
        if salary_sheets is None and _finance_has_headers(
                sheets, ("албан тушаал", "ажилтны тоо", "нэрлэсэн цалин")):
            _salary_table(sheets)
            salary_sheets = sheets
        if attendance_sheets is None and _finance_has_headers(
                sheets, ("нэр", "албан тушаал"), exact=True):
            _attendance_layout(sheets)
            attendance_sheets = sheets
        if products_sheets is None and _finance_has_headers(sheets, ('бүтээгдэхүүн', 'тоо хэмжээ', 'нэгж', 'үнэ')):
            products_sheets = sheets
        if fuel_sheets is None and _finance_has_headers(sheets, ('зарлага (өрөм) (л)', 'өрөмийн зардал (төгрөг)')):
            fuel_sheets = sheets
        if salary_sheets is not None and attendance_sheets is not None and products_sheets is not None and fuel_sheets is not None and diamond_sheets is not None:
            break
    if salary_sheets is None:
        raise FinanceSourceError("salary workbook in shared finance folder", 404)
    if attendance_sheets is None:
        raise FinanceSourceError("attendance sheet in shared finance folder", 404)
    if products_sheets is None:
        raise FinanceSourceError("mud workbook in shared finance folder", 404)
    result = finance_aggregates(salary_sheets, attendance_sheets, shifts)
    result['mud'] = mud_aggregates(products_sheets)
    if fuel_sheets is None:
        raise FinanceSourceError('drilling fuel ledger with cost', 404)
    result['fuel'] = fuel_aggregates(fuel_sheets, shifts, result['period'])
    if diamond_sheets is not None:
        result['diamond'] = diamond_budget(diamond_sheets)
    return result



# A shift's measured values; two sources that differ only in notes or file names do not conflict.
SHIFT_VALUES = ("from", "to", "meters", "st", "rt", "dt", "hours")


def assemble(records, seed, folders=None, report_index=None, finance=None, inventory=None):
    collar, shifts, warnings, provenance = {}, {}, [], []
    conflicts, unassigned, rejected = {}, {}, {}
    collar_url, shift_url = seed.get("collarUrl", ""), seed.get("shiftUrl", "")
    for source in records:
        c, s = [], []
        for tab, rows in workbook_rows(source["content"], source["suffix"]):
            c.extend(parse_collar(rows))
            aside, invalid = [], []
            for item in parse_shifts(rows, aside, invalid):
                # The structured record keeps the sheet row it came from; its raw report is linked below.
                item["sheet"] = {"name": source["name"], "tab": tab, "row": item.pop("sheetRow"), "url": source["url"]}
                s.append(item)
            for row in aside:
                key = (row["date"], row["shift"], row["hole"], row["from"], row["to"], row["source"])
                unassigned.setdefault(key, {**row, "sheet": source["name"], "tab": tab, "url": source["url"]})
            for row in invalid:
                rejected.setdefault((row["reason"], row["date"], row["hole"]),
                                    {**row, "sheet": source["name"], "tab": tab, "url": source["url"]})
        if not c and not s:
            continue
        provenance.append({"name": source["name"], "url": source["url"], "collarRows": len(c), "shiftRows": len(s)})
        if c and not collar and source["url"]:
            collar_url = source["url"]
        if s and not shifts and source["url"]:
            shift_url = source["url"]
        for h in c:
            # Repeated sheet rows can add populated fields without losing values.
            old = collar.setdefault(h["id"], h.copy())
            for k, value in h.items():
                if old.get(k) in (None, "") and value not in (None, ""):
                    old[k] = value
                elif value not in (None, "") and old.get(k) != value:
                    warnings.append(f"Collar conflict: {h['id']} / {k}; newer file/first row retained")
        for item in s:
            key = (item["rig"], item["date"], item["shift"], item["hole"])
            kept = shifts.get(key)
            differing = {k: [kept[k], item[k]] for k in SHIFT_VALUES if kept and kept[k] != item[k]}
            if differing:
                warnings.append(f"Shift conflict: {' / '.join(key)}; newer file retained")
                conflict = conflicts.setdefault(key, {"rig": key[0], "date": key[1], "shift": key[2], "hole": key[3],
                                                      "kept": f"{kept['sheet']['name']} / {kept['sheet']['tab']} мөр {kept['sheet']['row']}",
                                                      "fields": {}, "others": []})
                for k, values in differing.items():
                    conflict["fields"].setdefault(k, [values[0]])
                    if values[1] not in conflict["fields"][k]:
                        conflict["fields"][k].append(values[1])
                conflict["others"].append(f"{item['sheet']['name']} / {item['sheet']['tab']} мөр {item['sheet']['row']}")
            shifts.setdefault(key, item)
    if not collar or not shifts:
        raise ValueError("No recognized collar and shift records; previous dashboard data preserved")
    folder_map = folders if folders is not None else seed.get("folderMap", {})
    # A hole folder found on Drive registers its hole before the collar sheet has a row for it;
    # the collar row takes its place once added. Local runs keep the collar of their sources.
    for h in sorted(set(folders or {}) - set(collar)):
        collar[h] = {"id": h, "site": "Нэргүй Өндөр", "targetArea": "", "e": None, "n": None, "z": None,
                     "az": None, "dip": None, "plan": None, "collarDepth": None, "start": "", "finish": "",
                     "recovery": None, "boxes": None, "registered": "drive"}
        warnings.append(f"Collar missing: {h}; registered from its Drive folder")
    for h in collar.values():
        h["targetArea"] = h["targetArea"] or area_of(h["id"], folder_map.get(h["id"], {}).get("area", ""))
    unknown = {s["hole"] for s in shifts.values()} - set(collar)
    if unknown:
        from photo_import import PATH
        if PATH.exists():
            for h in load_json(PATH)['collar']:
                if h['id'] in unknown:
                    collar[h['id']] = h
        unknown -= set(collar)
    if unknown:
        raise ValueError("Shift holes missing from collar: " + ", ".join(sorted(unknown)))
    if report_index is None:
        report_index = [report for row in seed.get("shifts", []) for report in row.get("reports", [])]
        unlinked = seed.get("unlinkedReports", [])
        attach_reports(list(shifts.values()), report_index)
    else:
        unlinked = attach_reports(list(shifts.values()), report_index)
    for item in shifts.values():
        if 'User default 2026-10-27:' in item.get('notes', ''):
            warnings.append(f"Estimated time: {item['hole']} / {item['date']} / {item['shift']}; blank DT/total uses owner-approved 12 h")
        missing = [key.upper() for key in ("st", "rt") if item[key] is None]
        if missing:
            warnings.append(f"Unreported time codes: {item['hole']} / {item['date']} / {item['shift']} / {', '.join(missing)}; preserved as null")
    now = datetime.now(TZ)
    dates = sorted(s["date"] for s in shifts.values())
    data = {"schemaVersion": 1, "asOf": now.date().isoformat(), "updatedAt": now.isoformat(timespec="seconds"),
            "period": dates[0] + " – " + dates[-1], "collarUrl": collar_url, "shiftUrl": shift_url,
            "driveUrl": seed["driveUrl"], "collar": list(collar.values()),
            "shifts": sorted(shifts.values(), key=lambda x: (x["date"], x["rig"], x["shift"])),
            "folderMap": folder_map,
            "dataInventory": inventory if inventory is not None else seed.get("dataInventory", {}),
            "syncWarnings": sorted(set(warnings)), "sources": provenance,
            # Audit evidence: numeric disagreements between sheets, rows with no known rig, rows that
            # failed validation (the rest of the sheet still loads) and Drive reports no shift cites.
            "sourceConflicts": list(conflicts.values()),
            "unassignedShifts": sorted(unassigned.values(), key=lambda r: (r["date"], r["shift"], r["hole"])),
            "rejectedShifts": sorted(rejected.values(), key=lambda r: (r["date"], r["hole"], r["reason"])),
            "unlinkedReports": sorted(({k: r[k] for k in ("hole", "rig", "date", "shift", "name", "url", "folderUrl")}
                                       for r in unlinked), key=lambda r: (r["hole"], r["date"], r["name"]))}
    if finance is not None:
        data["finance"] = finance
    elif seed.get("finance") is not None:
        data["finance"] = seed["finance"]
    return data


def signature(data):
    data = {k: v for k, v in data.items() if k not in {"updatedAt", "asOf"}}
    def canonical(value):
        if isinstance(value, dict):
            return {k: canonical(v) for k, v in value.items()}
        if isinstance(value, list):
            return [canonical(v) for v in value]
        # JavaScript serializes 305.0 as 305; both represent the same data.
        if isinstance(value, float) and value.is_integer():
            return int(value)
        return value
    return hashlib.sha256(json.dumps(canonical(data), sort_keys=True, ensure_ascii=False, allow_nan=False).encode()).hexdigest()


def append_data_log(path, event):
    """Keep actual collection attempts, including failures, across sync runs."""
    history = load_json(path) if Path(path).exists() else {"schemaVersion": 1, "entries": []}
    history["entries"] = (history.get("entries", []) + [event])[-500:]
    atomic_json(path, history)


def publish(data, repository):
    """Commit only validated data and its collection history; Pages deploys main."""
    repository = Path(repository).resolve()
    def git(*args, allow=(0,)):
        result = subprocess.run(["git", "-C", str(repository), *args],
                                capture_output=True, text=True, encoding="utf-8", errors="replace")
        if result.returncode not in allow:
            raise RuntimeError("Git operation failed: " + " ".join(args[:2]) +
                               ". Local data and commits are preserved; check GitHub authentication or remote changes.")
        return result
    if git("rev-parse", "--show-toplevel").stdout.strip().replace("\\", "/").lower() != str(repository).replace("\\", "/").lower():
        raise RuntimeError("Run the updater from the Drilling-Progress Git checkout")
    if git("branch", "--show-current").stdout.strip() != "main":
        raise RuntimeError("Automatic data publishing requires the main branch")
    remote = git("remote", "get-url", "origin").stdout.strip()
    if remote not in {"https://github.com/SysMargad/Drilling-Progress.git", "git@github.com:SysMargad/Drilling-Progress.git"}:
        raise RuntimeError("origin must be SysMargad/Drilling-Progress")
    staged = git("diff", "--cached", "--name-only").stdout.splitlines()
    paths = ["dist/data.json", "dist/data-log.json"]
    if any(path not in paths for path in staged):
        raise RuntimeError("Other staged files exist; automatic data commit aborted")
    changed = git("diff", "--quiet", "HEAD", "--", *paths, allow=(0, 1)).returncode == 1
    changed = changed or bool(git("ls-files", "--others", "--exclude-standard", "--", *paths).stdout.strip())
    if changed:
        git("add", "--", *paths)
        git("commit", "-m", "Update drilling data and collection log", "--", *paths)
    # Retry an earlier unpushed data commit even when the current data is unchanged.
    git("push", "origin", "HEAD:main")
    LOG.info("GitHub data push completed; GitHub Pages deploys the validated commit")


def shift_changes(before, after):
    """Shift records added, removed or changed between two datasets, for the collection log."""
    def index(data):
        return {(s["rig"], s["date"], s["shift"], s["hole"]): {k: s.get(k) for k in SHIFT_VALUES} for s in data.get("shifts", [])}
    old, new = index(before), index(after)
    label = lambda key: " / ".join(key)
    result = {"added": sorted(label(k) for k in new.keys() - old.keys()),
              "removed": sorted(label(k) for k in old.keys() - new.keys()),
              "changed": sorted(label(k) for k in new.keys() & old.keys() if new[k] != old[k])}
    return {k: v[:40] for k, v in result.items() if v}


def ulaanbaatar_date(moment=None):
    """Calendar date in Ulaanbaatar; GitHub runners run in UTC, eight hours behind the site."""
    moment = moment or datetime.now(TZ)
    return moment.astimezone(TZ).date().isoformat()


def finance_shifts(data):
    return [row for row in data["shifts"] if row["rig"] in FINANCE_RIGS]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", choices=["local", "drive"], default="local")
    parser.add_argument("--input", type=Path, default=ROOT / "input")
    parser.add_argument("--output", type=Path, default=ROOT / "dist" / "data.json")
    parser.add_argument("--credentials", type=Path, help="Google credential file outside source directory")
    parser.add_argument("--folder-id", default="1b3n84juCY9UbrCMz7D6aITuV3lhgbvVI")
    parser.add_argument("--publish", action="store_true", help="Commit data.json and push to GitHub Pages repository")
    parser.add_argument("--watch", type=int, metavar="SECONDS", help="Repeat until Ctrl+C; minimum 60 seconds")
    parser.add_argument("--serve", action="store_true", help="Serve the local dashboard on 127.0.0.1:4318")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    if args.watch is not None and args.watch < 60:
        parser.error("--watch must be at least 60 seconds")
    if not re.fullmatch(r"[A-Za-z0-9_-]+", args.folder_id):
        parser.error("Invalid Drive folder ID")
    server = None
    if args.serve:
        class Handler(SimpleHTTPRequestHandler):
            def __init__(self, *a, **kw):
                super().__init__(*a, directory=str(ROOT / "dist"), **kw)
            def end_headers(self):
                self.send_header("Cache-Control", "no-store")
                super().end_headers()
        server = ThreadingHTTPServer(("127.0.0.1", 4318), Handler)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        LOG.info("Local dashboard: http://127.0.0.1:4318")
    try:
        while True:
            event = {"id": str(uuid.uuid4()), "source": args.source,
                     "startedAt": datetime.now(TZ).isoformat(timespec="seconds")}
            recorded = False
            log_path = args.output.parent / "data-log.json"
            try:
                seed = load_json(args.output if args.output.exists() else ROOT / "dist" / "data.json")
                finance = seed.get("finance")
                finance_note = ""
                if args.source == "drive":
                    records, folders, report_index, inventory = drive_sources(args.folder_id, args.credentials)
                    data = assemble(records, seed, folders, report_index, seed.get("finance"), inventory)
                    from photo_import import apply_photos
                    data = apply_photos(data)
                    try:
                        data["finance"] = drive_finance_aggregates(args.credentials, finance_shifts(data))
                    except Exception as finance_error:
                        finance_note = f"Finance refresh failed ({type(finance_error).__name__})"
                        if isinstance(finance_error, FinanceSourceError):
                            finance_note = (f"Finance refresh failed ({finance_error.source} "
                                            f"HTTP {finance_error.status})")
                        elif isinstance(finance_error, urllib.error.HTTPError):
                            finance_note = f"Finance refresh failed (HTTP {finance_error.code})"
                        LOG.warning("%s; previous aggregate retained", finance_note)
                else:
                    records, folders = local_sources(args.input), None
                    report_file = args.input / "report-index.json"
                    report_index = load_json(report_file) if report_file.exists() else None
                    data = assemble(records, seed, folders, report_index, seed.get("finance"))
                from photo_import import apply_photos, apply_daily_water
                data = apply_photos(data)
                if data.get('finance') is not None:
                    data['finance'] = apply_uploaded_fuel(data['finance'], finance_shifts(data))
                    data['finance'] = apply_diamond_budget(data['finance'])
                    from consumption_model import load_corrections, apply_corrections
                    correction_config = load_corrections()
                    if args.source == 'drive':
                        try:
                            correction_config = load_corrections(Drive(args.credentials), workbook_rows)
                        except Exception as correction_error:
                            finance_note = '; '.join(filter(None, (finance_note,
                                'Consumption Sheet refresh failed; verified snapshot used (' + type(correction_error).__name__ + ')')))
                    data = apply_corrections(data, correction_config)
                    data = apply_daily_water(data)
                from shift_audit import build_audit, load_confirmations, load_foreman_reports
                data["shiftAudit"] = build_audit(data, sorted(RIGS), ulaanbaatar_date(), load_confirmations(), load_foreman_reports())
                trail = shift_changes(seed, data)
                changed = signature(seed) != signature(data)
                if not changed:
                    data = seed  # Stable metadata prevents empty periodic commits.
                else:
                    atomic_json(args.output, data)
                LOG.info("Prepared %d holes, %d shifts, %.2f m; %d source conflicts",
                         len(data["collar"]), len(data["shifts"]),
                         sum(s["meters"] for s in data["shifts"]), len(data["syncWarnings"]))
                month = data["shiftAudit"]["months"][-1]
                event.update({"status": "updated" if changed else "unchanged",
                              "completedAt": datetime.now(TZ).isoformat(timespec="seconds"),
                              "files": len(records), "holes": len(data["collar"]),
                              "shifts": len(data["shifts"]),
                              "meters": round(sum(s["meters"] for s in data["shifts"]), 3),
                              # Audit trail: which shift records this run added, removed or changed.
                              "changes": trail,
                              "audit": {"month": month["month"], "expected": month["expected"], **month["counts"]},
                              "note": "; ".join(note for note in (
                                  f"{len(data['sourceConflicts'])} numeric source conflicts" if data.get("sourceConflicts") else "",
                                  f"{len(data['rejectedShifts'])} rows rejected by validation" if data.get("rejectedShifts") else "",
                                  finance_note) if note)})
                append_data_log(log_path, event)
                recorded = True
                if args.publish:
                    if args.output.resolve() != (ROOT / "dist" / "data.json").resolve():
                        raise ValueError("--publish requires the default dist/data.json output")
                    publish(data, ROOT)
            except Exception as e:
                if not recorded:
                    event.update({"status": "failed", "completedAt": datetime.now(TZ).isoformat(timespec="seconds"),
                                  "error": f"HTTP {e.code}" if isinstance(e, urllib.error.HTTPError) else type(e).__name__})
                    # Validation messages name the sheet value at fault (hole, date, field); other
                    # errors may carry request details, so only their type is logged.
                    if isinstance(e, ValueError):
                        event["validation"] = str(e)[:300]
                    append_data_log(log_path, event)
                # Credentials and request URLs are intentionally excluded from logs.
                LOG.error("Update failed (%s): %s", type(e).__name__,
                          str(e) if not isinstance(e, urllib.error.HTTPError) else f"HTTP {e.code}")
                if not args.watch:
                    return 1
            if not args.watch:
                if server:
                    LOG.info("Press Ctrl+C to stop")
                    while True:
                        time.sleep(1)
                return 0
            time.sleep(args.watch)
    except KeyboardInterrupt:
        LOG.info("Stopped")
        return 0
    finally:
        if server:
            server.shutdown()
            server.server_close()


if __name__ == "__main__":
    raise SystemExit(main())
