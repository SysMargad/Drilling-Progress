"""Post drilling progress for newly synced shifts to a Google Chat space.

The card starts from the hole numbers, then shows daily totals against the
dashboard norm, hole progress and rig performance. Financial figures are left
out on purpose. GOOGLE_CHAT_WEBHOOK_URL holds the space's incoming webhook URL.
"""
from __future__ import annotations

import argparse
import html
import json
import os
import re
import sys
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent
DASHBOARD_URL = "https://sysmargad.github.io/Drilling-Progress/"
SITE = "Нэргүй Өндөр"
RIGS = ("C-1800", "CSD-1300")
SHIFT_ORDER = {"Өдөр": 0, "Шөнө": 1}
SHIFT_TARGET, DAY_TARGET = 30, 60  # metres per rig, as on the dashboard chart
MUTED, GOOD, LOW = "#9aa0a6", "#34a853", "#ea4335"


def load_json(path):
    return json.loads(Path(path).read_text(encoding="utf-8-sig"))


def fmt(value, digits=1):
    """Dashboard number format: thousands separators, trailing zeros dropped."""
    if value is None:
        return "—"
    text = f"{value:,.{digits}f}"
    return text.rstrip("0").rstrip(".") if digits else text


def shift_key(row):
    return row["rig"], row["date"], row["shift"], row["hole"]


def shift_order(row):
    return row["date"], SHIFT_ORDER.get(row["shift"], 2), row["rig"]


def new_shifts(previous, current):
    seen = {shift_key(row) for row in previous.get("shifts", [])}
    return [row for row in current["shifts"] if shift_key(row) not in seen]


def area_of(hole):
    area = (hole.get("targetArea") or "").lower()
    if area == "дорнын төмөр" or (not area and hole["id"].startswith("DTDH")):
        return "Дорнын Төмөр"
    if area == "замт хөндий" or (not area and hole["id"].startswith("ZHDH")):
        return "Замт Хөндий"
    return hole.get("targetArea") or "—"


def status(hole, shifts):
    if hole.get("finish"):
        return "Дууссан"
    return "Өрөмдөж байна" if any(row["hole"] == hole["id"] for row in shifts) else "Төлөвлөсөн"


def depth(hole_id, shifts):
    return max((row["to"] for row in shifts if row["hole"] == hole_id), default=None)


def label(text):
    return f'<font color="{MUTED}">{text}</font>'


def coloured(text, good):
    return f'<font color="{GOOD if good else LOW}"><b>{text}</b></font>'


def rate(meters, hours):
    return f"{fmt(meters / hours, 2)} м/ц" if hours else "—"


def utilisation(rows):
    hours = sum(row["hours"] for row in rows)
    return f"{fmt(sum(row['dt'] for row in rows) / hours * 100)}%" if hours else "—"


def hole_section(hole, rows, shifts):
    rigs = " / ".join(dict.fromkeys(row["rig"] for row in rows))
    reached, plan = depth(hole["id"], shifts), hole.get("plan")
    progress = f" ({fmt(reached / plan * 100, 0)}%)" if reached is not None and plan else ""
    lines = [f"<b>{html.escape(hole['id'])}</b> · {html.escape(area_of(hole))} · {rigs}",
             f"{label('Төлөв')} : <b>{status(hole, shifts)}</b>",
             f"{label('Гүн')} : <b>{fmt(reached)} / {fmt(plan)} м</b>{progress}"]
    for row in rows:
        reports = " · ".join(f'<a href="{html.escape(report["url"])}">тайлан</a>'
                             for report in row.get("reports") or [])
        details = [f"DT {fmt(row['dt'])} ц", *([f"ST {fmt(row['st'])} ц"] if row.get("st") is not None else []),
                   f"ROP {rate(row['meters'], row['dt'])}", html.escape(row.get("driller") or ""), reports]
        lines.append(f"{label(row['date'][5:] + ' ' + row['shift'])} : {fmt(row['from'])} – {fmt(row['to'])} м · "
                     f"{coloured(fmt(row['meters']) + ' м', row['meters'] >= SHIFT_TARGET)}")
        lines.append(label(" · ".join(part for part in details if part)))
    if len(rows) > 1:
        lines.append(f"{label('Нийт')} : <b>{fmt(sum(row['meters'] for row in rows))} м</b>")
    if hole.get("finish"):
        core = [f"Collar {fmt(hole.get('collarDepth'))} м",
                *([f"керн гарц {fmt(hole['recovery'])}%"] if hole.get("recovery") is not None else []),
                *([f"{fmt(hole['boxes'], 0)} хайрцаг"] if hole.get("boxes") is not None else [])]
        lines.append(f"{label('Дууссан ' + hole['finish'])} : {' · '.join(core)}")
    return {"widgets": [{"textParagraph": {"text": "<br>".join(lines)}}]}


def daily_section(dates, shifts):
    lines = ["<b>ӨДРИЙН ГҮЙЦЭТГЭЛ</b>"]
    for day in dates:
        lines.append(f"<b>{day}</b> {label(f'· норм {DAY_TARGET} м / өрөм')}")
        for rig in RIGS:
            rows = [row for row in shifts if row["date"] == day and row["rig"] == rig]
            if not rows:
                lines.append(f"{rig} : {label('мэдээ ороогүй')}")
                continue
            meters = sum(row["meters"] for row in rows)
            missing = [name for name in SHIFT_ORDER if not any(row["shift"] == name for row in rows)]
            total = (f"<b>{fmt(meters)} м</b> {label('· ' + ', '.join(missing) + ' мэдээ ороогүй')}" if missing
                     else coloured(f"{fmt(meters)} м", meters >= DAY_TARGET))
            lines.append(f"{rig} : {total}")
    return {"widgets": [{"textParagraph": {"text": "<br>".join(lines)}}]}


def progress_section(data):
    shifts, holes = data["shifts"], data["collar"]
    def having(state):
        return [hole for hole in holes if status(hole, shifts) == state]
    lines = ["<b>ЦООНОГИЙН АХИЦ</b>"]
    for hole in sorted(having("Өрөмдөж байна"), key=lambda hole: (hole.get("start") or "", hole["id"])):
        reached, plan = depth(hole["id"], shifts), hole.get("plan")
        percent = f" · <b>{fmt(reached / plan * 100, 0)}%</b>" if reached is not None and plan else ""
        lines.append(f"<b>{html.escape(hole['id'])}</b> · Өрөмдөж байна · {fmt(reached)} / {fmt(plan)} м{percent}")
    for hole in sorted(having("Төлөвлөсөн"), key=lambda hole: hole["id"]):
        plan = f" · {fmt(hole['plan'])} м" if hole.get("plan") else ""
        lines.append(f"<b>{html.escape(hole['id'])}</b> · {label('Төлөвлөсөн')}{plan}")
    for hole in sorted(having("Дууссан"), key=lambda hole: (hole["finish"], hole["id"]), reverse=True):
        final = hole.get("collarDepth") if hole.get("collarDepth") is not None else depth(hole["id"], shifts)
        lines.append(f"<b>{html.escape(hole['id'])}</b> · {label('Дууссан ' + hole['finish'][5:])} · {fmt(final)} м")
    return {"widgets": [{"textParagraph": {"text": "<br>".join(lines)}}]}


def performance_section(data):
    shifts, holes = data["shifts"], data["collar"]
    meters, dt = sum(row["meters"] for row in shifts), sum(row["dt"] for row in shifts)
    states = [status(hole, shifts) for hole in holes]
    counts = f"· дууссан {states.count('Дууссан')} · өрөмдөж буй {states.count('Өрөмдөж байна')}"
    lines = [f"<b>ӨРМИЙН ГҮЙЦЭТГЭЛ</b> {label('· ' + html.escape(data.get('period', '')))}",
             f"{label('Өрөмдсөн')} : <b>{fmt(meters)} м</b>",
             f"{label('Цооног')} : <b>{len(holes)} ш</b> {label(counts)}",
             f"{label('Ашиглалт')} : <b>{utilisation(shifts)}</b>",
             f"{label('Дундаж хурд · ROP')} : <b>{rate(meters, dt)}</b>"]
    for rig in RIGS:
        rows = [row for row in shifts if row["rig"] == rig]
        rig_meters = sum(row["meters"] for row in rows)
        details = [f"{len(rows)} ээлж", f"ROP {rate(rig_meters, sum(row['dt'] for row in rows))}",
                   f"ашиглалт {utilisation(rows)}"]
        known_st = [row["st"] for row in rows if row.get("st") is not None]
        if known_st:  # Same "≥" convention as the dashboard when some ST hours are blank.
            details.append(f"ST {'≥ ' if len(known_st) < len(rows) else ''}{fmt(sum(known_st))} ц")
        lines.append(f"{rig} : <b>{fmt(rig_meters)} м</b> {label('· ' + ' · '.join(details))}")
    return {"widgets": [{"textParagraph": {"text": "<br>".join(lines)}}]}


def build_message(data, rows):
    shifts, rows = data["shifts"], sorted(rows, key=shift_order)
    collar = {hole["id"]: hole for hole in data["collar"]}
    by_hole = {}
    for row in rows:
        by_hole.setdefault(row["hole"], []).append(row)
    dates = sorted({row["date"] for row in rows})
    period = dates[0] if len(dates) == 1 else f"{dates[0]} – {dates[-1]}"
    sections = [hole_section(collar.get(hole_id, {"id": hole_id}), hole_rows, shifts)
                for hole_id, hole_rows in sorted(by_hole.items(), key=lambda item: (
                    RIGS.index(item[1][-1]["rig"]) if item[1][-1]["rig"] in RIGS else len(RIGS), item[0]))]
    sections += [daily_section(dates, shifts), progress_section(data), performance_section(data),
                 {"widgets": [{"buttonList": {"buttons": [
                     {"text": "Хяналтын самбар нээх", "onClick": {"openLink": {"url": DASHBOARD_URL}}}]}}]}]
    return {"cardsV2": [{"cardId": "drilling-progress", "card": {
        "header": {"title": "Өрөмдлөгийн явц", "subtitle": f"{SITE} · {period} · {len(rows)} шинэ ээлж"},
        "sections": sections}}]}


def post(url, message):
    if not url.startswith("https://chat.googleapis.com/"):
        raise ValueError("GOOGLE_CHAT_WEBHOOK_URL must be a Google Chat incoming webhook URL")
    request = urllib.request.Request(url, data=json.dumps(message, ensure_ascii=False).encode("utf-8"),
                                     headers={"Content-Type": "application/json; charset=UTF-8"})
    with urllib.request.urlopen(request, timeout=30) as response:
        response.read()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data", type=Path, default=ROOT / "dist" / "data.json")
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--previous", type=Path, help="data.json before the sync; posts only shifts added since")
    source.add_argument("--date", help="Post every shift recorded on this date (YYYY-MM-DD)")
    parser.add_argument("--dry-run", action="store_true", help="Print the message instead of posting it")
    args = parser.parse_args()
    if args.date and not re.fullmatch(r"\d{4}-\d{2}-\d{2}", args.date):
        parser.error("--date must be YYYY-MM-DD")
    data = load_json(args.data)
    rows = (new_shifts(load_json(args.previous), data) if args.previous
            else [row for row in data["shifts"] if row["date"] == args.date])
    if not rows:
        print("No shifts to report; nothing posted.")
        return
    message = build_message(data, rows)
    if args.dry_run:
        sys.stdout.reconfigure(encoding="utf-8")
        print(json.dumps(message, ensure_ascii=False, indent=2))
        return
    url = os.environ.get("GOOGLE_CHAT_WEBHOOK_URL", "").strip()
    if not url:
        parser.error("Set GOOGLE_CHAT_WEBHOOK_URL to the space's incoming webhook URL")
    post(url, message)
    print(f"Posted {len(rows)} shifts to Google Chat.")


if __name__ == "__main__":
    main()
