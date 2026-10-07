#!/usr/bin/env python3
"""
Celebrity radar on top of TrendRadar RSS output (output/rss/YYYY-MM-DD.db).

  python tools/celeb_radar.py radar [--hours 48] [--top 5]
      Top stories per celebrity: headline, outlets, outlet count, first/last seen.

  python tools/celeb_radar.py check "Megan Fox MGK split" [--celeb "Megan Fox"]
      Pre-publication check: ГОРЯЧО / ОСТЫВАЕТ / МЕРТВО + reasons.

  python tools/celeb_radar.py feeds
      Per-feed status of the latest crawl (which sources work).

Stdlib only. Celebrities and their regexes are read from config/frequency_words.txt.
"""
from __future__ import annotations

import argparse
import glob
import os
import re
import sqlite3
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TZ = ZoneInfo("Asia/Bangkok")

# Tier 1 = allowed as slide source (pilot rule). Everything else = signal only.
TIER1 = {
    "people", "people.com", "variety", "the hollywood reporter", "hollywood reporter",
    "deadline", "reuters", "associated press", "ap news", "ap", "bbc", "bbc news",
    "bbc entertainment", "reuters (via gnews)", "ap (via gnews)",
}
SENSITIVE = re.compile(
    r"pregnan|baby bump|expecting|divorce|split|break ?up|separat|arrest|charged|"
    r"lawsuit|sued|court|police|rehab|hospital|cancer|diagnos|surgery|illness|health|"
    r"dies|died|death|overdose|gay|lesbian|bisexual|comes out|sexuality|cheat",
    re.I,
)
STOP = set(
    "a an the and or of to in on at for with from by as is are was were be been it its "
    "this that these those her his their she he they after before over new says said "
    "reveals shares just about into out up how why what who when where amid gets got "
    "has have had not no more than her's s vs via report reports".split()
)


# ───────────────────────── data loading ─────────────────────────

def load_celebs():
    path = os.path.join(ROOT, "config", "frequency_words.txt")
    celebs = []
    in_groups = False
    for raw in open(path, encoding="utf-8"):
        line = raw.strip()
        if line == "[WORD_GROUPS]":
            in_groups = True
            continue
        if not in_groups or not line or line.startswith("#"):
            continue
        m = re.match(r"^/(.+)/\s*(?:=>\s*(.+))?$", line)
        if m:
            celebs.append((m.group(2) or m.group(1), re.compile(m.group(1), re.I)))
        elif not line.startswith(("[", "+", "!", "@")):
            name = line.split("=>")[-1].strip()
            celebs.append((name, re.compile(re.escape(line.split("=>")[0].strip()), re.I)))
    return celebs


def parse_time(s):
    if not s:
        return None
    s = s.strip().replace("Z", "+00:00")
    for fmt in (None, "%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M"):
        try:
            dt = datetime.fromisoformat(s) if fmt is None else datetime.strptime(s, fmt)
            return dt if dt.tzinfo else dt.replace(tzinfo=TZ)
        except ValueError:
            continue
    return None


def split_outlet(title, feed_name):
    """Google News titles look like 'Headline - Outlet'. Others: outlet = feed name."""
    if feed_name.startswith(("GNews", "Tier1")) or "(via GNews)" in feed_name or feed_name == "People":
        if " - " in title:
            head, outlet = title.rsplit(" - ", 1)
            return head.strip(), outlet.strip()
    if feed_name.startswith("Reddit"):
        return title, feed_name
    return title, feed_name


def load_items(hours):
    now = datetime.now(TZ)
    since = now - timedelta(hours=hours)
    days = {(now - timedelta(days=d)).strftime("%Y-%m-%d") for d in range(hours // 24 + 2)}
    items, seen = [], set()
    for db in sorted(glob.glob(os.path.join(ROOT, "output", "rss", "*.db"))):
        if os.path.basename(db)[:-3] not in days:
            continue
        con = sqlite3.connect(db)
        names = dict(con.execute("SELECT id, name FROM rss_feeds"))
        for title, feed_id, url, pub, first, summary in con.execute(
            "SELECT title, feed_id, url, published_at, first_crawl_time, summary FROM rss_items"
        ):
            feed_name = names.get(feed_id, feed_id)
            ts = parse_time(pub)
            if ts is None:  # fall back to first crawl time (HH:MM of that day)
                ts = parse_time(f"{os.path.basename(db)[:-3]} {first}") if first and len(first) <= 5 else parse_time(first)
            if ts is None or ts < since:
                continue
            head, outlet = split_outlet(title, feed_name)
            key = (head.lower()[:90], outlet.lower())
            if key in seen:
                continue
            seen.add(key)
            items.append(dict(title=head, outlet=outlet, feed=feed_name, url=url, ts=ts,
                              summary=summary or ""))
        con.close()
    return items


# ───────────────────────── clustering ─────────────────────────

def tokens(text, drop):
    words = re.findall(r"[a-z0-9']+", text.lower())
    return {w.strip("'") for w in words if len(w) > 2 and w not in STOP and w not in drop}


def cluster(items, drop, thr=0.3):
    clusters = []
    for it in sorted(items, key=lambda x: x["ts"]):
        tk = tokens(it["title"], drop)
        best, best_sim = None, 0.0
        for c in clusters:
            inter = len(tk & c["tokens"])
            sim = inter / max(1, min(len(tk), len(c["tokens"])))
            if sim > best_sim:
                best, best_sim = c, sim
        if best and best_sim >= thr and len(tk & best["tokens"]) >= 2:
            best["items"].append(it)
            best["tokens"] |= tk
        else:
            clusters.append({"tokens": set(tk), "items": [it]})
    return clusters


def is_tier1(outlet):
    o = outlet.lower()
    return o in TIER1 or any(t in o for t in ("variety", "hollywood reporter", "deadline", "reuters", "associated press", "bbc", "people.com"))


def summarize(c):
    its = c["items"]
    outlets = sorted({i["outlet"] for i in its})
    t1 = sorted({i["outlet"] for i in its if is_tier1(i["outlet"])})
    lead = next((i for i in sorted(its, key=lambda x: x["ts"]) if is_tier1(i["outlet"])), None) or its[0]
    return dict(headline=lead["title"], url=lead["url"], outlets=outlets, n=len(outlets),
                tier1=t1, first=min(i["ts"] for i in its), last=max(i["ts"] for i in its),
                sensitive=bool(SENSITIVE.search(" ".join(i["title"] for i in its))))


def fmt(dt):
    return dt.astimezone(TZ).strftime("%d.%m %H:%M")


# ───────────────────────── commands ─────────────────────────

def cmd_radar(a):
    items = load_items(a.hours)
    print(f"# Celebrity radar — last {a.hours}h, {len(items)} items, now {fmt(datetime.now(TZ))} ICT\n")
    for name, rx in load_celebs():
        mine = [i for i in items if rx.search(i["title"])]
        if not mine:
            print(f"## {name}: нет упоминаний\n")
            continue
        drop = tokens(name, set()) | {w.lower() for w in name.split()}
        cs = sorted((summarize(c) for c in cluster(mine, drop)), key=lambda s: (-s["n"], -s["last"].timestamp()))
        print(f"## {name}: {len(mine)} публикаций, {len(cs)} тем")
        for s in cs[: a.top]:
            flags = (" ⚠️чувствит." if s["sensitive"] else "") + ("" if s["tier1"] else " ⛔нет tier-1")
            print(f"- [{s['n']} изд.] {s['headline']}{flags}")
            print(f"    {fmt(s['first'])} → {fmt(s['last'])} | tier-1: {', '.join(s['tier1']) or '—'}")
            print(f"    {', '.join(s['outlets'][:10])}{' …' if s['n'] > 10 else ''}")
        print()


def cmd_check(a):
    now = datetime.now(TZ)
    items = load_items(72)
    pool = items
    if a.celeb:
        rx = next((r for n, r in load_celebs() if n.lower() == a.celeb.lower()), re.compile(re.escape(a.celeb), re.I))
        pool = [i for i in items if rx.search(i["title"])]
    drop = tokens(a.celeb or "", set())
    q = tokens(a.topic, set()) - drop
    hits = []
    for i in pool:
        tk = tokens(i["title"] + " " + i["summary"][:300], set())
        if q and len(q & tk) / len(q) >= a.match:
            hits.append(i)

    def outlets(lo, hi):
        return {i["outlet"] for i in hits if now - timedelta(hours=hi) <= i["ts"] < now - timedelta(hours=lo)}

    h6, h24, h72 = outlets(0, 6), outlets(0, 24), outlets(0, 72)
    prev24 = outlets(24, 48)
    t1 = sorted({i["outlet"] for i in hits if is_tier1(i["outlet"])})
    last = max((i["ts"] for i in hits), default=None)
    age = (now - last).total_seconds() / 3600 if last else None
    new6 = h6 - outlets(6, 72)

    if not hits or age > 24 or len(h72) < 2:
        verdict = "МЕРТВО"
    elif len(h24) >= 3 and (new6 or age <= 6) and len(h24) >= len(prev24):
        verdict = "ГОРЯЧО"
    else:
        verdict = "ОСТЫВАЕТ"

    print(f"Тема: {a.topic}" + (f" | {a.celeb}" if a.celeb else ""))
    print(f"ВЕРДИКТ: {verdict}")
    print(f"- изданий: 6ч={len(h6)} (новых {len(new6)}), 24ч={len(h24)}, предыд.24ч={len(prev24)}, 72ч={len(h72)}")
    print(f"- последняя публикация: {fmt(last) + f' ({age:.1f}ч назад)' if last else '—'}")
    print(f"- tier-1: {', '.join(t1) if t1 else 'НЕТ → по правилу пилота публиковать нельзя'}")
    if SENSITIVE.search(a.topic + " " + " ".join(i["title"] for i in hits)):
        print("- ⚠️ чувствительная тема (здоровье/беременность/криминал/ориентация/развод): только с подтверждением tier-1 или заявлением самой звезды")
    for i in sorted(hits, key=lambda x: x["ts"], reverse=True)[:8]:
        print(f"    {fmt(i['ts'])} {i['outlet']}: {i['title']}")
    if verdict == "ОСТЫВАЕТ":
        print("Что делать: искать свежий угол из последних 6ч (новая деталь, реакция, заявление/пост самой звезды, связка с ближайшим событием). Нет нового угла → снять, взять тему из radar.")
    elif verdict == "МЕРТВО":
        print("Что делать: не публиковать. Взять тему из radar с ГОРЯЧО.")


def cmd_feeds(a):
    dbs = sorted(glob.glob(os.path.join(ROOT, "output", "rss", "*.db")))
    if not dbs:
        print("Нет данных в output/rss/")
        return
    con = sqlite3.connect(dbs[-1])
    rec = con.execute("SELECT id, crawl_time FROM rss_crawl_records ORDER BY id DESC LIMIT 1").fetchone()
    print(f"{os.path.basename(dbs[-1])} crawl {rec[1] if rec else '?'}")
    counts = dict(con.execute("SELECT feed_id, COUNT(*) FROM rss_items GROUP BY feed_id"))
    if rec:
        for fid, st, err in con.execute(
            "SELECT feed_id, status, error_message FROM rss_crawl_status WHERE crawl_record_id=? ORDER BY status, feed_id", (rec[0],)
        ):
            print(f"  {'OK ' if st == 'success' else 'ERR'} {fid:26} items_today={counts.get(fid, 0):4} {(err or '')[:90]}")


def main():
    p = argparse.ArgumentParser()
    sub = p.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("radar"); r.add_argument("--hours", type=int, default=48); r.add_argument("--top", type=int, default=5)
    c = sub.add_parser("check"); c.add_argument("topic"); c.add_argument("--celeb"); c.add_argument("--match", type=float, default=0.6)
    sub.add_parser("feeds")
    a = p.parse_args()
    {"radar": cmd_radar, "check": cmd_check, "feeds": cmd_feeds}[a.cmd](a)


if __name__ == "__main__":
    main()
