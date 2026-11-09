"""Post the two rigs' latest drilling to a Google Chat space.

The evening card shows each rig's latest reported date (both its shifts), whether or not the date is new, so
the space always sees where each rig stands; a report filed late for an earlier date shows only in the totals
(owner 2026-11-09). The card starts from the hole numbers, then shows daily totals against the
dashboard norm, hole progress and rig performance. Financial figures are left
out on purpose. GOOGLE_CHAT_WEBHOOK_URL holds the space's incoming webhook URL.
chat-posted.json records the shifts already reported, so the card can say how
many of the shifts are new, whether they arrived through the Drive sync or a local data commit.
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
LEDGER = ROOT / "chat-posted.json"
DASHBOARD_URL = "https://sysmargad.github.io/Drilling-Progress/"
SITE = "Нэргүй Өндөр"
RIGS = ("C-1800", "CSD-1300")
SHIFT_ORDER = {"Өдөр": 0, "Шөнө": 1}
SHIFT_TARGET, DAY_TARGET = 30, 60  # metres per rig, as on the dashboard chart
MUTED, GOOD, LOW = "#9aa0a6", "#34a853", "#ea4335"
DASHBOARD_BUTTON = {"widgets": [{"buttonList": {"buttons": [
    {"text": "Хяналтын самбар нээх", "onClick": {"openLink": {"url": DASHBOARD_URL}}}]}}]}


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


def shift_keys(row):
    """The shift's key and, for a shift whose hole number the owner corrected, its key under the old hole,
    so the correction does not post the shift a second time."""
    keys = {shift_key(row)}
    if row.get("correction"):
        keys.add((row["rig"], row["date"], row["shift"], row["correction"]["hole"]))
    if row.get("rigCorrection"):
        # Likewise a corrected rig: the shift may have been posted under the rig its sheet gave.
        from drilling_sync import canonical_rig
        old = canonical_rig(row["rigCorrection"]["rig"])
        keys.update({(old, row["date"], row["shift"], hole) for hole in
                     {row["hole"], *([row["correction"]["hole"]] if row.get("correction") else [])}})
    return keys


def load_ledger(path):
    return {tuple(key) for key in load_json(path)["posted"]} if Path(path).exists() else None


def save_ledger(path, posted, data):
    # Keys of shifts later removed from the data are dropped, keeping the file bounded.
    current = set().union(*(shift_keys(row) for row in data["shifts"]))
    keys = sorted((key for key in posted if key in current),
                  key=lambda key: (key[1], SHIFT_ORDER.get(key[2], 2), key[0], key[3]))
    lines = ",\n".join("  " + json.dumps(list(key), ensure_ascii=False) for key in keys)
    Path(path).write_text('{"posted": [\n' + lines + "\n]}\n", encoding="utf-8")


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
        # A rig is reported from its first shift on, so a new rig is not "missing" before it arrived.
        for rig in (rig for rig in RIGS if any(row["rig"] == rig and row["date"] <= day for row in shifts)):
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
        if not rows:
            continue
        rig_meters = sum(row["meters"] for row in rows)
        details = [f"{len(rows)} ээлж", f"ROP {rate(rig_meters, sum(row['dt'] for row in rows))}",
                   f"ашиглалт {utilisation(rows)}"]
        known_st = [row["st"] for row in rows if row.get("st") is not None]
        if known_st:  # Same "≥" convention as the dashboard when some ST hours are blank.
            details.append(f"ST {'≥ ' if len(known_st) < len(rows) else ''}{fmt(sum(known_st))} ц")
        lines.append(f"{rig} : <b>{fmt(rig_meters)} м</b> {label('· ' + ' · '.join(details))}")
    return {"widgets": [{"textParagraph": {"text": "<br>".join(lines)}}]}


def latest_rows(data):
    """Each rig's shifts on its latest reported date."""
    latest = {}
    for row in data["shifts"]:
        if row["rig"] in RIGS:
            latest[row["rig"]] = max(latest.get(row["rig"], ""), row["date"])
    return [row for row in data["shifts"] if latest.get(row["rig"]) == row["date"]]


def latest_label(rows):
    dates = {rig: max(row["date"] for row in rows if row["rig"] == rig) for rig in RIGS if any(r["rig"] == rig for r in rows)}
    return " · ".join(f"{rig} {date[5:]}" for rig, date in dates.items())


def build_message(data, rows, new=None, period=None):
    """new: how many of the rows are not yet posted (all of them when not given); period: the subtitle's dates."""
    shifts, rows = data["shifts"], sorted(rows, key=shift_order)
    collar = {hole["id"]: hole for hole in data["collar"]}
    by_hole = {}
    for row in rows:
        by_hole.setdefault(row["hole"], []).append(row)
    dates = sorted({row["date"] for row in rows})
    period = period or (dates[0] if len(dates) == 1 else f"{dates[0]} – {dates[-1]}")
    new = len(rows) if new is None else new
    news = f"{new} шинэ ээлж" if new else "шинэ ээлж ороогүй"
    sections = [hole_section(collar.get(hole_id, {"id": hole_id}), hole_rows, shifts)
                for hole_id, hole_rows in sorted(by_hole.items(), key=lambda item: (
                    RIGS.index(item[1][-1]["rig"]) if item[1][-1]["rig"] in RIGS else len(RIGS), item[0]))]
    sections += [daily_section(dates, shifts), progress_section(data), performance_section(data), DASHBOARD_BUTTON]
    return {"cardsV2": [{"cardId": "drilling-progress", "card": {
        "header": {"title": "Өрөмдлөгийн явц", "subtitle": f"{SITE} · {period} · {news}"},
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
    parser.add_argument("--ledger", type=Path, default=LEDGER, help="Shifts already posted")
    parser.add_argument("--date", help="Post every shift recorded on this date again (YYYY-MM-DD)")
    parser.add_argument("--dry-run", action="store_true", help="Print the message; post and record nothing")
    args = parser.parse_args()
    if args.date and not re.fullmatch(r"\d{4}-\d{2}-\d{2}", args.date):
        parser.error("--date must be YYYY-MM-DD")
    data, posted = load_json(args.data), load_ledger(args.ledger)
    if posted is None and not args.date:
        # Without a record, posting the whole history would flood the space.
        if not args.dry_run:
            save_ledger(args.ledger, {shift_key(row) for row in data["shifts"]}, data)
        print(f"No {args.ledger.name}; recorded {len(data['shifts'])} existing shifts without posting.")
        return
    if args.date:
        rows = [row for row in data["shifts"] if row["date"] == args.date]
        if not rows:
            print(f"No shifts recorded on {args.date}; nothing posted.")
            return
        message = build_message(data, rows)
    else:
        rows = latest_rows(data)
        if not rows:
            print("No shifts of the two rigs; nothing posted.")
            return
        # The evening post goes out every day with the rigs' latest dates, so a quiet day is not mistaken for a
        # broken bot, and a late report for an earlier date does not take over the card.
        fresh = [row for row in rows if not shift_keys(row) & posted]
        message = build_message(data, rows, new=len(fresh), period=latest_label(rows))
    if args.dry_run:
        sys.stdout.reconfigure(encoding="utf-8")
        print(json.dumps(message, ensure_ascii=False, indent=2))
        return
    url = os.environ.get("GOOGLE_CHAT_WEBHOOK_URL", "").strip()
    if not url:
        parser.error("Set GOOGLE_CHAT_WEBHOOK_URL to the space's incoming webhook URL")
    post(url, message)
    # Every shift now in the data counts as reported: the totals in the card include the late ones.
    save_ledger(args.ledger, (posted or set()) | (set() if args.date else {shift_key(row) for row in data["shifts"]})
                | {shift_key(row) for row in rows}, data)
    print(f"Posted {len(rows)} shifts of the rigs' latest dates to Google Chat.")


if __name__ == "__main__":
    main()
