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
TZ = timezone(timedelta(hours=8))
NS = {"s": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}
SCOPE = "https://www.googleapis.com/auth/drive.readonly"
RIGS = {"C-1800", "CSD-1300"}
FINANCE_FOLDER_ID = "1j8QjgqCHBh50pJwl68hBpTCvTu1tUYgj"
FINANCE_SHEET_MIME = "application/vnd.google-apps.spreadsheet"
XLSX_MIME = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
FOLDER_MIME = "application/vnd.google-apps.folder"
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
        result = []
        for name in sorted(z.namelist()):
            if not re.fullmatch(r"xl/worksheets/sheet\d+\.xml", name):
                continue
            rows = []
            for row in ET.fromstring(z.read(name)).findall("s:sheetData/s:row", NS):
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
            result.append((name, rows))
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
    n = float(text.replace(",", ""))
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
    h = str(value).strip().upper().replace("-", "")
    return h if re.fullmatch(r"(?:DTDH|ZHDH)\d{4,}", h) else None


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
        output.append({"id": h, "site": "Нэргүй Өндөр",
                       "targetArea": "Дорнын Төмөр" if h.startswith("DT") else "Замт Хөндий",
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
                       "boxes": number(get(lambda x: "core boxes" in x))})
    return output


def parse_shifts(rows):
    output = []
    headers = None
    for row in rows:
        names = [norm(v) for v in row]
        if "dt" in names and any("source" in h for h in names) and any("hole id" in h for h in names):
            headers = names
            continue
        if not headers:
            continue
        def get(match):
            i = next((i for i, h in enumerate(headers) if match(h)), -1)
            return row[i] if 0 <= i < len(row) else ""
        rig = get(lambda x: x == "rig" or x.endswith(" rig")).strip()
        h = hole_id(get(lambda x: "hole id" in x))
        if rig not in RIGS or not h:
            continue
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
                "hours": number(get(lambda x: x.endswith("total"))),
                "notes": get(lambda x: "work notes" in x)}
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
        output.append(item)
    return output


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
        for rig in sorted(RIGS):
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
                keys = [(date_key, rig, shift) for rig in sorted(RIGS)
                        for shift in ('Өдөр', 'Шөнө')]
            base = position['monthlySalary'] / month_days
            incentive = position['incentiveDailyRate'] or 0.0
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
        with urllib.request.urlopen(req, timeout=90) as response:
            content = response.read(25_000_001)
            if len(content) > 25_000_000:
                raise ValueError("Drive file exceeds 25 MB download limit")
            return content

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


def attach_reports(rows, reports):
    index = {}
    for report in reports:
        key = (report["hole"], report["rig"], report["date"], report["shift"])
        group = index.setdefault(key, [])
        if not any(old["url"] == report["url"] for old in group):
            group.append(report)
    for row in rows:
        row["reports"] = index.get((row["hole"], row["rig"], row["date"], row["shift"]), [])


def drive_sources(folder, credentials_path):
    drive = Drive(credentials_path)
    pending, seen, records, folders, reports = [(folder, None, None, False)], set(), [], {}, []
    while pending:
        fid, hole, rig, daily = pending.pop()
        if fid in seen:
            continue
        seen.add(fid)
        children = drive.files(fid)
        if hole and hole not in folders and not daily and not rig:
            folders[hole] = {"url": f"https://drive.google.com/drive/folders/{fid}",
                             "folders": [{"name": f["name"], "url": f"https://drive.google.com/drive/folders/{f['id']}"}
                                         for f in children if f["mimeType"] == "application/vnd.google-apps.folder"]}
        for f in children:
            if f["mimeType"] == "application/vnd.google-apps.folder":
                if re.search(r"duplicat|archive|to_delete", f["name"], re.I):
                    continue
                pending.append((f["id"], hole_id(f["name"]) or hole,
                                f["name"] if f["name"] in RIGS else rig,
                                daily or f["name"].startswith("02.")))
            elif "collar" in f["name"].lower() or "shift report" in f["name"].lower():
                if f["mimeType"] in {"application/vnd.google-apps.spreadsheet",
                                     "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"}:
                    records.append({"name": f["name"], "url": f.get("webViewLink", ""),
                                    "modified": f.get("modifiedTime", ""),
                                    "content": drive.download(f), "suffix": ".xlsx"})
            elif daily:
                report = report_metadata(f, hole, rig, f"https://drive.google.com/drive/folders/{fid}")
                if report:
                    reports.append(report)
    return sorted(records, key=lambda x: x["modified"], reverse=True), folders, reports


def drive_finance_aggregates(credentials_path, shifts):
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

    salary_sheets = attendance_sheets = None
    for file in sorted(files.values(), key=lambda item: item.get("modifiedTime", ""), reverse=True):
        try:
            content = drive.download(file)
        except urllib.error.HTTPError as error:
            if error.code == 404:
                continue
            raise FinanceSourceError("workbook in shared finance folder", error.code) from error
        sheets = workbook_rows(content, ".xlsx")
        if salary_sheets is None and _finance_has_headers(
                sheets, ("албан тушаал", "ажилтны тоо", "нэрлэсэн цалин")):
            _salary_table(sheets)
            salary_sheets = sheets
        if attendance_sheets is None and _finance_has_headers(
                sheets, ("нэр", "албан тушаал"), exact=True):
            _attendance_layout(sheets)
            attendance_sheets = sheets
        if salary_sheets is not None and attendance_sheets is not None:
            break
    if salary_sheets is None:
        raise FinanceSourceError("salary workbook in shared finance folder", 404)
    if attendance_sheets is None:
        raise FinanceSourceError("attendance sheet in shared finance folder", 404)
    return finance_aggregates(
        salary_sheets,
        attendance_sheets,
        shifts,
    )


def assemble(records, seed, folders=None, report_index=None, finance=None):
    collar, shifts, warnings, provenance = {}, {}, [], []
    collar_url, shift_url = seed.get("collarUrl", ""), seed.get("shiftUrl", "")
    for source in records:
        c, s = [], []
        for _, rows in workbook_rows(source["content"], source["suffix"]):
            c.extend(parse_collar(rows))
            s.extend(parse_shifts(rows))
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
            if key in shifts and shifts[key] != item:
                warnings.append(f"Shift conflict: {' / '.join(key)}; newer file retained")
            shifts.setdefault(key, item)
    if not collar or not shifts:
        raise ValueError("No recognized collar and shift records; previous dashboard data preserved")
    unknown = {s["hole"] for s in shifts.values()} - set(collar)
    if unknown:
        raise ValueError("Shift holes missing from collar: " + ", ".join(sorted(unknown)))
    if report_index is None:
        report_index = [report for row in seed.get("shifts", []) for report in row.get("reports", [])]
    attach_reports(list(shifts.values()), report_index)
    for item in shifts.values():
        missing = [key.upper() for key in ("st", "rt") if item[key] is None]
        if missing:
            warnings.append(f"Unreported time codes: {item['hole']} / {item['date']} / {item['shift']} / {', '.join(missing)}; preserved as null")
    now = datetime.now(TZ)
    dates = sorted(s["date"] for s in shifts.values())
    data = {"schemaVersion": 1, "asOf": now.date().isoformat(), "updatedAt": now.isoformat(timespec="seconds"),
            "period": dates[0] + " – " + dates[-1], "collarUrl": collar_url, "shiftUrl": shift_url,
            "driveUrl": seed["driveUrl"], "collar": list(collar.values()),
            "shifts": sorted(shifts.values(), key=lambda x: (x["date"], x["rig"], x["shift"])),
            "folderMap": folders if folders is not None else seed.get("folderMap", {}),
            "syncWarnings": sorted(set(warnings)), "sources": provenance}
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
                    records, folders, report_index = drive_sources(args.folder_id, args.credentials)
                    data = assemble(records, seed, folders, report_index, seed.get("finance"))
                    try:
                        data["finance"] = drive_finance_aggregates(args.credentials, data["shifts"])
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
                changed = signature(seed) != signature(data)
                if not changed:
                    data = seed  # Stable metadata prevents empty periodic commits.
                else:
                    atomic_json(args.output, data)
                LOG.info("Prepared %d holes, %d shifts, %.2f m; %d source conflicts",
                         len(data["collar"]), len(data["shifts"]),
                         sum(s["meters"] for s in data["shifts"]), len(data["syncWarnings"]))
                event.update({"status": "updated" if changed else "unchanged",
                              "completedAt": datetime.now(TZ).isoformat(timespec="seconds"),
                              "files": len(records), "holes": len(data["collar"]),
                              "shifts": len(data["shifts"]),
                              "meters": round(sum(s["meters"] for s in data["shifts"]), 3),
                              "note": "; ".join(note for note in (
                                  f"{len(data['syncWarnings'])} source conflicts" if data["syncWarnings"] else "",
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
