// Browser-side fallback of tools/celeb_radar.py (same rules), for when the
// GitHub Actions crawl is unavailable. Run on a news.google.com page after the
// fetch step has filled window.__gn (lines: "k\ttitle - Source\tSource\tISO").
// Produces window.__radar (compact, one line per story) and window.__rows (JSON).
(() => {
  const TZ_OFF = 7 * 3600e3; // Asia/Bangkok
  const celebs = {
    "gn-megan-fox": ["Megan Fox", /megan fox/i], "gn-taylor-swift": ["Taylor Swift", /taylor swift/i],
    "gn-selena-gomez": ["Selena Gomez", /selena gomez/i], "gn-zendaya": ["Zendaya", /\bzendaya\b/i],
    "gn-kim-kardashian": ["Kim Kardashian", /kim kardashian/i], "gn-kylie-jenner": ["Kylie Jenner", /kylie jenner/i],
    "gn-rihanna": ["Rihanna", /\brihanna\b/i], "gn-beyonce": ["Beyoncé", /beyonc[eé]/i],
    "gn-ariana-grande": ["Ariana Grande", /ariana grande/i], "gn-sabrina-carpenter": ["Sabrina Carpenter", /sabrina carpenter/i],
    "gn-margot-robbie": ["Margot Robbie", /margot robbie/i], "gn-jennifer-lopez": ["Jennifer Lopez", /jennifer lopez|\bj\.? ?lo\b/i],
    "gn-blake-lively": ["Blake Lively", /blake lively/i], "gn-hailey-bieber": ["Hailey Bieber", /hailey bieber/i],
    "gn-sydney-sweeney": ["Sydney Sweeney", /sydney sweeney/i], "gn-timothee-chalamet": ["Timothée Chalamet", /timoth[eé]e chalamet|chalamet/i],
    "gn-dua-lipa": ["Dua Lipa", /dua lipa/i],
  };
  const TIER1 = /variety|hollywood reporter|deadline|reuters|associated press|^ap news$|\bbbc\b|^people$|people\.com/i;
  const SENS = /pregnan|baby bump|expecting|divorc|split|break ?up|separat|arrest|charged|lawsuit|sued|court|trial|police|rehab|hospital|cancer|diagnos|surger|illness|health|erectile|\bed\b|dies|died|death|overdose|gay|lesbian|bisexual|comes out|sexuality|cheat|breast|boobs/i;
  const STOP = new Set("a an the and or of to in on at for with from by as is are was were be been it its this that these those her his their she he they after before over new says said reveals shares just about into out up how why what who when where amid gets got has have had not no more than vs via report reports latest news photos videos".split(" "));
  const tok = (s, drop) => new Set((s.toLowerCase().match(/[a-z0-9']+/g) || []).map(w => w.replace(/'/g, "")).filter(w => w.length > 2 && !STOP.has(w) && !drop.has(w)));
  const now = Date.now();
  const rows = []; let feed = null;
  for (const line of window.__gn.split("\n")) {
    if (line[0] === "#") { feed = line.slice(1).split(" ")[0]; continue; }
    const [k, t, s, p] = line.split("\t");
    const title = t.endsWith(" - " + s) ? t.slice(0, -(s.length + 3)) : t;
    rows.push({ feed, k: +k, title, src: s, ts: Date.parse(p + ":00Z") });
  }
  const fmt = ts => { const d = new Date(ts + TZ_OFF); return String(d.getUTCDate()).padStart(2, "0") + "." + String(d.getUTCMonth() + 1).padStart(2, "0") + " " + String(d.getUTCHours()).padStart(2, "0") + ":" + String(d.getUTCMinutes()).padStart(2, "0"); };
  const out = []; const res = [];
  for (const [fid, [name, rx]] of Object.entries(celebs)) {
    const drop = tok(name, new Set()); name.toLowerCase().split(" ").forEach(w => drop.add(w));
    const mine = rows.filter(r => r.feed === fid && rx.test(r.title)).sort((a, b) => a.ts - b.ts);
    const cl = [];
    for (const it of mine) {
      const tk = tok(it.title, drop); let best = null, bs = 0;
      for (const c of cl) { let inter = 0; tk.forEach(w => c.tk.has(w) && inter++); const sim = inter / Math.max(1, Math.min(tk.size, c.tk.size)); if (sim > bs && inter >= 2) { bs = sim; best = c; } }
      if (best && bs >= 0.3) { best.items.push(it); tk.forEach(w => best.tk.add(w)); } else cl.push({ tk: new Set(tk), items: [it] });
    }
    const sums = cl.map(c => {
      const outlets = [...new Set(c.items.map(i => i.src))];
      const t1 = outlets.filter(o => TIER1.test(o));
      const win = (lo, hi) => new Set(c.items.filter(i => now - i.ts >= lo * 3600e3 && now - i.ts < hi * 3600e3).map(i => i.src));
      const h6 = win(0, 6), h24 = win(0, 24), prev = win(24, 48), older = win(6, 72);
      const new6 = [...h6].filter(o => !older.has(o)).length;
      const last = Math.max(...c.items.map(i => i.ts)), first = Math.min(...c.items.map(i => i.ts));
      const age = (now - last) / 3600e3;
      let v = "МЕРТВО";
      if (!(age > 24 || outlets.length < 2)) v = (h24.size >= 3 && (new6 > 0 || age <= 6) && h24.size >= prev.size) ? "ГОРЯЧО" : "ОСТЫВАЕТ";
      const lead = c.items.find(i => TIER1.test(i.src)) || c.items[c.items.length - 1];
      return { celeb: name, headline: lead.title, lead_src: lead.src, feed: lead.feed, k: lead.k, n: outlets.length, outlets, tier1: t1, h6: h6.size, h24: h24.size, prev24: prev.size, first: fmt(first), last: fmt(last), age: +age.toFixed(1), verdict: v, sensitive: SENS.test(c.items.map(i => i.title).join(" ")) };
    }).sort((a, b) => b.n - a.n || a.age - b.age);
    out.push("## " + name + " | " + mine.length + " публ. | " + sums.length + " тем");
    sums.slice(0, 4).forEach(s => { res.push(s); out.push([s.verdict, s.n + "изд", "6ч" + s.h6 + "/24ч" + s.h24 + "/пр" + s.prev24, s.first + "→" + s.last, "t1:" + (s.tier1.join(",") || "-"), s.sensitive ? "SENS" : "", s.headline + " [" + s.lead_src + "]", s.outlets.slice(0, 6).join(",")].join("|")); });
  }
  window.__radar = out.join("\n"); window.__rows = res;
  return window.__radar.length;
})()
