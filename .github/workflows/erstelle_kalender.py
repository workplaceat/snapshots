#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Erstellt eine statische Wochenübersicht (Mo–Fr) als HTML aus einer ICS-Quelle.

- Zielauflösung: 1920×1080 (Full-HD TV)
- Reines HTML + CSS, kein JavaScript
- Performance: ein eingebetteter CSS-Block, Systemschriften
- Aktueller Tag: dezente grüne Umrandung
- Fußzeile: steht immer am Seitenende (Sticky-Footer)
- Branding: Kopfzeilen-Grün fest im Code (#527A42)

Voraussetzung: Environment-Variable ICS_URL mit der öffentlich erreichbaren ICS-Datei.
Ausgabe: public/calendar/index.html
"""

from __future__ import annotations

import os
import sys
import html
import requests
from icalendar import Calendar
from zoneinfo import ZoneInfo
from dateutil.rrule import rrulestr
from datetime import datetime, date, time, timedelta
from typing import Any, Dict, List

OUTPUT_HTML_FILE = "public/calendar/index.html"


# ----------------------------- Hilfsfunktionen (Zeit) -----------------------------

def to_local(dt_raw: date | datetime, tz_local: ZoneInfo) -> datetime:
    """
    Normalisiert ICS-Zeitwerte nach lokaler Zeit.
    - DATE (Ganztag): 00:00 lokale Zeit
    - DATETIME mit/ohne tzinfo: in lokale Zeit umrechnen (naiv = lokal)
    """
    if isinstance(dt_raw, date) and not isinstance(dt_raw, datetime):
        return datetime.combine(dt_raw, time.min, tzinfo=tz_local)
    if isinstance(dt_raw, datetime):
        if dt_raw.tzinfo is None:
            return dt_raw.replace(tzinfo=tz_local).astimezone(tz_local)
        return dt_raw.astimezone(tz_local)
    # Fallback (sollte nicht passieren)
    return datetime.now(tz_local)


def is_all_day_component(component) -> bool:
    """Erkennt All-Day-Events am dtstart-Typ."""
    dtstart = component.get("dtstart")
    if not dtstart:
        return False
    v = dtstart.dt
    return isinstance(v, date) and not isinstance(v, datetime)


# -------------------------- Termin in Wochenstruktur schreiben --------------------------

def add_event_local(
    week_events: Dict[date, List[Dict[str, Any]]],
    component,
    start_local: datetime,
    end_local: datetime,
    summary: str,
    location: str,
    week_days_local: set[date],
    event_uid: str | None,
) -> None:
    """Fügt ein (ggf. mehrtägiges) Ereignis allen betroffenen lokalen Tagen hinzu."""
    all_day = is_all_day_component(component)

    # DTEND ist exklusiv: wenn 00:00 und Dauer > 0, gilt der Vortag als letzter voller Tag
    loop_end_date = end_local.date()
    if (all_day or end_local.time() == time.min) and end_local > start_local:
        loop_end_date -= timedelta(days=1)

    same_day = (start_local.date() == end_local.date())
    ends_midnight_next = (
        end_local.time() == time.min and end_local.date() > start_local.date()
    )

    current = start_local.date()
    while current <= loop_end_date:
        if current in week_days_local:
            if all_day:
                time_str = "Ganztägig"
                is_all = True
            else:
                if same_day:
                    time_str = f"{start_local:%H:%M} – {end_local:%H:%M}"
                elif ends_midnight_next and current == start_local.date():
                    # 24h-Block: 00:00 – 00:00 → Ganztägig
                    time_str = "Ganztägig" if start_local.time() == time.min else f"{start_local:%H:%M} – 00:00"
                elif current == start_local.date():
                    time_str = f"Start: {start_local:%H:%M}"
                elif current == loop_end_date and end_local.time() > time.min:
                    time_str = f"Ende: {end_local:%H:%M}"
                else:
                    time_str = "Ganztägig"
                is_all = (time_str == "Ganztägig")

            event_data = {
                "summary": summary,
                "location": location,
                "time": time_str,
                "is_all_day": is_all,
                "start_time": start_local,  # für Sortierung
            }
            if event_uid:
                event_data["uid"] = event_uid
            week_events[current].append(event_data)
        current += timedelta(days=1)


# ------------------------------------ HTML rendern -------------------------------------

def render_html(
    week_events: Dict[date, List[Dict[str, Any]]],
    monday_local: date,
    friday_local: date,
    now_local_dt: datetime,
) -> str:
    calendar_week = now_local_dt.isocalendar()[1]
    tz_local = now_local_dt.tzinfo  # type: ignore
    timestamp_local = datetime.now(tz_local).strftime("%d.%m.%Y um %H:%M:%S Uhr")

    def fmt_short(d: date) -> str:
        return d.strftime("%d.%m.")

    date_range_str = f"{fmt_short(monday_local)}–{fmt_short(friday_local)}"
    today_local_date = now_local_dt.date()

    days = ["Montag", "Dienstag", "Mittwoch", "Donnerstag", "Freitag"]

    parts: List[str] = []
    parts.append(f"""<!DOCTYPE html>
<html lang="de">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=1920, initial-scale=1">
<title>Öffentlicher Wochenplan</title>
<style>
:root {{
  --bg: #f5f6f8;
  --card: #ffffff;
  --text: #1f2937;
  --muted: #6b7280;
  --border: #e5e7eb;
  --radius: 12px;

  --brand: #527A42;      /* Kopfzeilen-Grün (R82 G122 B66 / #527A42) */
  --brand2: #527A42;
  --accent: #4f9f5a;     /* Badges/Hervorhebung */
  --accent-soft: #eaf6ee;
}}

* {{ box-sizing: border-box; }}
html, body {{ height: 100%; }}
body {{
  margin: 0;
  background: var(--bg);
  color: var(--text);
  font: 21px/1.42 -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "Helvetica Neue", Arial;
  display: flex;
  flex-direction: column;
  min-height: 100vh;
}}

header.topbar {{
  background: linear-gradient(135deg, var(--brand), var(--brand2));
  color: #fff;
  padding: 48px 32px 56px;
}}
.topbar-inner {{
  display: flex;
  align-items: center;
  gap: 72px;
  margin-left: 0;
  margin-right: auto;
  flex-wrap: wrap;
  row-gap: 36px;
}}
.logo {{
  background: rgba(255, 255, 255, .9);
  border-radius: 999px;
  padding: 26px;
  min-width: 132px;
  min-height: 132px;
  display: flex; align-items: center; justify-content: center;
  box-shadow: 0 20px 44px rgba(0,0,0,.18);
}}
.logo img {{ width: 74px; height: 74px; display: block; }}
.headline {{
  display: flex;
  flex-direction: column;
  gap: 18px;
  min-width: min(560px, 100%);
  padding-left: 8px;
}}
.headline-text {{
  display: flex;
  flex-direction: column;
  gap: 12px;
}}
.title-meta {{
  font-size: 30px;
  font-weight: 600;
  letter-spacing: .24px;
  line-height: 1.14;
  opacity: .94;
}}
.title {{
  font-weight: 700;
  font-size: 48px;
  line-height: 1.08;
  letter-spacing: .3px;
}}
.sub {{
  font-size: 24px;
  font-weight: 500;
  letter-spacing: .18px;
  opacity: .92;
}}

main.container {{ padding: 16px 20px 8px; flex: 1; }}

.grid {{
  display: grid;
  grid-template-columns: repeat(5, 1fr);
  gap: 24px;
  align-items: stretch;
}}

.day {{
  background: var(--card);
  border: 1px solid var(--border);
  border-radius: var(--radius);
  box-shadow: 0 6px 18px rgba(0,0,0,.06);
  min-height: 380px;
  display: flex; flex-direction: column;
}}
.day-header {{
  padding: 22px 24px;
  border-bottom: 1px solid var(--border);
  display: flex; align-items: baseline; justify-content: space-between;
  background: linear-gradient(180deg, rgba(0,0,0,.02), transparent);
}}
.day-name {{ font-weight: 700; font-size: 24px; }}
.day-date {{ color: var(--muted); font-size: 18px; }}

.day.today {{
  border-color: rgba(79,159,90,.55);
  box-shadow: 0 0 0 3px rgba(79,159,90,.14), 0 6px 18px rgba(0,0,0,.06);
}}
.day.today .day-header {{
  background: linear-gradient(180deg, var(--accent-soft), transparent);
  border-bottom-color: rgba(79,159,90,.35);
}}

.events {{
  padding: 22px 24px 26px;
  display: flex;
  flex-direction: column;
  gap: 18px;
}}
.event {{
  background: linear-gradient(180deg, rgba(79,159,90,.08), rgba(79,159,90,.02));
  border: 1px solid rgba(79,159,90,.28);
  border-radius: var(--radius);
  padding: 20px 22px 22px;
  box-shadow: 0 10px 24px rgba(0,0,0,.06);
  display: flex;
  flex-direction: column;
  gap: 12px;
}}
.event-time {{
  margin: 0;
  font-size: 24px;
  font-weight: 700;
  letter-spacing: .2px;
  color: var(--brand);
}}
.event-body {{
  font-size: 18px;
  line-height: 1.55;
  color: var(--text);
}}
.summary {{
  margin: 0;
  font-weight: 600;
}}
.event-body .meta {{ font-size: 16px; color: var(--muted); margin-top: 6px; }}

.no-events {{
  color: var(--muted);
  text-align: center;
  padding: 28px 16px 32px;
  font-style: italic;
}}

footer.foot {{
  color: #6b7280; font-size: 13px; text-align: center; padding: 6px 0 12px;
  margin-top: auto;
}}
</style>
</head>
<body>
<header class="topbar" role="banner">
  <div class="topbar-inner">
    <div class="logo" aria-hidden="true">
      <img src="https://cdn.riverty.design/logo/riverty-logomark-green.svg" alt="Riverty Logo">
    </div>
    <div class="headline">
      <div class="headline-text">
        <div class="title">Öffentlicher Wochenplan</div>
        <div class="title-meta">Kalenderwoche {calendar_week}</div>
      </div>
      <div class="sub">{date_range_str}</div>
    </div>
  </div>
</header>

<main class="container" role="main">
  <section class="grid" aria-label="Wochentage">""")

    for i, day_name in enumerate(days):
        current_date = monday_local + timedelta(days=i)
        events = week_events.get(current_date, [])
        # Ganztägig zuerst, dann Startzeit, dann Titel
        events.sort(key=lambda x: (not x["is_all_day"], x["start_time"], x["summary"].lower()))
        is_today_cls = " today" if current_date == today_local_date else ""

        parts.append(
            "".join(
                [
                    f'<article class="day{is_today_cls}" aria-labelledby="d{i}-label">',
                    f'<div class="day-header"><div id="d{i}-label" class="day-name">{day_name}</div>',
                    f'<div class="day-date">{current_date.strftime("%d.%m.")}</div></div>',
                    '<div class="events">',
                ]
            )
        )

        if not events:
            parts.append('<div class="no-events">–</div>')
        else:
            for ev in events:
                loc_html = ""
                if ev.get("location"):
                    loc_html = f'<div class="meta">{html.escape(ev["location"])}</div>'
                body_html = f'<div class="summary">{ev["summary"]}</div>{loc_html}'
                parts.append(
                    "".join(
                        [
                            f'<article class="event"><h3 class="event-time">{ev["time"]}</h3>',
                            f'<div class="event-body">{body_html}</div></article>',
                        ]
                    )
                )

        parts.append("</div></article>")

    parts.append(
        f'</section></main><footer class="foot" role="contentinfo">Kalender zuletzt aktualisiert am {timestamp_local}</footer></body></html>'
    )
    return "".join(parts)


# ------------------------------------ Hauptlogik -------------------------------------

def erstelle_kalender_html() -> None:
    ics_url = os.getenv("ICS_URL")
    if not ics_url:
        print("Fehler: Die Environment-Variable 'ICS_URL' ist nicht gesetzt!", file=sys.stderr)
        sys.exit(1)

    print("Lade Kalender von der bereitgestellten URL...")

    try:
        # WICHTIG: Bytes, nicht .text
        response = requests.get(ics_url, timeout=30)
        response.raise_for_status()
        cal = Calendar.from_ical(response.content)
    except Exception as e:
        print(f"Fehler beim Herunterladen/Parsen der ICS-Datei: {e}", file=sys.stderr)
        sys.exit(2)

    tz_vienna = ZoneInfo("Europe/Vienna")
    now_local = datetime.now(tz_vienna)

    # Woche in lokaler Zeit (Mo 00:00 – Fr 23:59:59)
    start_of_week_local_dt = now_local.replace(hour=0, minute=0, second=0, microsecond=0) - timedelta(days=now_local.weekday())
    end_of_week_local_dt = start_of_week_local_dt + timedelta(days=4, hours=23, minutes=59, seconds=59)

    monday_local = start_of_week_local_dt.date()
    friday_local = (start_of_week_local_dt + timedelta(days=4)).date()

    # Zielstruktur (lokale Kalendertage)
    week_days_local = {monday_local + timedelta(days=i) for i in range(5)}
    week_events: Dict[date, List[Dict[str, Any]]] = {d: [] for d in week_days_local}

    # De-Duping über (UID oder summary|location, Startzeit lokal)
    dedup_keys: set[tuple[str, str]] = set()
    cancelled_occurrences: set[tuple[str, str]] = set()

    # Overrides (RECURRENCE-ID) vorab sammeln
    vevents = list(cal.walk("VEVENT"))
    overrides: Dict[tuple[str, datetime], Any] = {}
    for component in vevents:
        rec_id_prop = component.get("recurrence-id")
        if not rec_id_prop:
            continue
        uid = str(component.get("uid") or "").strip()
        rec_local = to_local(rec_id_prop.dt, tz_vienna)
        overrides[(uid, rec_local)] = component

    def add_occurrence(component, occ_start_local: datetime, occ_end_local: datetime, summary_str: str) -> None:
        uid = str(component.get("uid") or "").strip()
        location_str = str(component.get("location") or "").strip()
        dedup_id = uid or f"{summary_str}|{location_str}"
        dedup_key = (dedup_id, occ_start_local.isoformat())
        if dedup_key in cancelled_occurrences:
            return
        if dedup_key in dedup_keys:
            return
        dedup_keys.add(dedup_key)
        add_event_local(
            week_events,
            component,
            occ_start_local,
            occ_end_local,
            summary_str,
            location_str,
            week_days_local,
            uid if uid else None,
        )
        cancelled_occurrences.discard(dedup_key)

    for component in vevents:
        summary_str = ""
        try:
            # Titel + Ort
            raw_summary = str(component.get("summary") or "Ohne Titel")
            summary_str = html.escape(raw_summary)
            location_str = str(component.get("location") or "").strip()
            uid = str(component.get("uid") or "").strip()
            status = str(component.get("status") or "").strip().upper()
            rec_id_prop = component.get("recurrence-id")
            dtstart_prop = component.get("dtstart")

            if status == "CANCELLED":
                if rec_id_prop:
                    cancel_start_local = to_local(rec_id_prop.dt, tz_vienna)
                elif dtstart_prop:
                    cancel_start_local = to_local(dtstart_prop.dt, tz_vienna)
                else:
                    continue

                cancel_key = (
                    uid if uid else f"{summary_str}|{location_str}",
                    cancel_start_local.isoformat(),
                )
                cancelled_occurrences.add(cancel_key)
                dedup_keys.discard(cancel_key)

                for events in week_events.values():
                    if uid:
                        events[:] = [
                            ev
                            for ev in events
                            if not (
                                ev.get("start_time") == cancel_start_local
                                and ev.get("uid") == uid
                            )
                        ]
                    else:
                        events[:] = [
                            ev
                            for ev in events
                            if not (
                                ev.get("start_time") == cancel_start_local
                                and ev.get("summary") == summary_str
                                and ev.get("location") == location_str
                            )
                        ]
                continue

            if rec_id_prop:
                continue
            if not dtstart_prop:
                continue

            # Start/Ende (lokal)
            dtstart_raw = dtstart_prop.dt
            start_local = to_local(dtstart_raw, tz_vienna)

            dtend_prop = component.get("dtend")
            duration_prop = component.get("duration")

            if not dtend_prop and duration_prop:
                end_local = start_local + duration_prop.dt
            else:
                dtend_raw = dtend_prop.dt if dtend_prop else dtstart_raw
                end_local = to_local(dtend_raw, tz_vienna)

            # Dauer (für Suchfenster-Puffer)
            duration = end_local - start_local
            pad = duration if duration > timedelta(0) else timedelta(0)

            # Wiederholungen (RRULE)
            rrule_prop = component.get("rrule")
            if rrule_prop:
                # EXDATE sammeln
                exdates_local: set[datetime] = set()
                ex_prop = component.get("exdate")
                ex_list = ex_prop if isinstance(ex_prop, list) else ([ex_prop] if ex_prop else [])
                for ex in ex_list:
                    for d in ex.dts:
                        exdates_local.add(to_local(d.dt, tz_vienna))

                rule = rrulestr(rrule_prop.to_ical().decode(), dtstart=start_local)
                # leicht nach vorne ziehen, damit Events, die am Sonntag 24h laufen, montags erscheinen
                search_start = start_of_week_local_dt - pad
                search_end = end_of_week_local_dt

                for occ_start_local in rule.between(search_start, search_end, inc=True):
                    occ_start_local = to_local(occ_start_local, tz_vienna)
                    if occ_start_local in exdates_local:
                        continue
                    if (uid, occ_start_local) in overrides:
                        continue
                    add_occurrence(component, occ_start_local, occ_start_local + duration, summary_str)
            else:
                # Einzeltermin
                add_occurrence(component, start_local, end_local, summary_str)

            # Zusätzliche Einzeltermine (RDATE)
            rdate_prop = component.get("rdate")
            rdate_list = rdate_prop if isinstance(rdate_prop, list) else ([rdate_prop] if rdate_prop else [])
            for r in rdate_list:
                for d in r.dts:
                    r_local = to_local(d.dt, tz_vienna)
                    if (uid, r_local) in overrides:
                        continue
                    add_occurrence(component, r_local, r_local + duration, summary_str)

        except Exception as e:
            print(f"Fehler beim Verarbeiten eines Termins ('{summary_str}'): {e}", file=sys.stderr)

    for override_component in overrides.values():
        summary_str = ""
        try:
            status = str(override_component.get("status") or "").strip().upper()
            if status == "CANCELLED":
                continue

            raw_summary = str(override_component.get("summary") or "Ohne Titel")
            summary_str = html.escape(raw_summary)

            dtstart_prop = override_component.get("dtstart")
            if not dtstart_prop:
                continue

            occ_start_local = to_local(dtstart_prop.dt, tz_vienna)

            dtend_prop = override_component.get("dtend")
            duration_prop = override_component.get("duration")

            if not dtend_prop and duration_prop:
                occ_end_local = occ_start_local + duration_prop.dt
            else:
                dtend_raw = dtend_prop.dt if dtend_prop else dtstart_prop.dt
                occ_end_local = to_local(dtend_raw, tz_vienna)

            add_occurrence(override_component, occ_start_local, occ_end_local, summary_str)
        except Exception as e:
            print(
                f"Fehler beim Verarbeiten eines Override-Termins ('{summary_str}'): {e}",
                file=sys.stderr,
            )

    # HTML erzeugen & schreiben
    html_str = render_html(week_events, monday_local, friday_local, now_local)
    os.makedirs(os.path.dirname(OUTPUT_HTML_FILE), exist_ok=True)
    with open(OUTPUT_HTML_FILE, "w", encoding="utf-8") as f:
        f.write(html_str)

    print(f"Fertig! Wochenkalender wurde erfolgreich in '{OUTPUT_HTML_FILE}' erstellt.")


if __name__ == "__main__":
    erstelle_kalender_html()
