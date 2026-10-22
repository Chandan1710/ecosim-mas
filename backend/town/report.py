"""
report.py — the two PDF reports for a town run.

  summary_pdf(run_id)  one to two pages: what the shock did to the town, the
                       key numbers, charts, key events, who was hit hardest
  agents_pdf(run_id)   one section per agent: who they are, how their money
                       moved, their major decisions in their own words, and
                       the pivotal points of their month

Both are built from the saved event log (town/analysis.py), so they can be
made for any finished run without calling an LLM. If the run's LLM-written
stories exist they are included, labelled as such.
"""

from __future__ import annotations

import datetime as _dt
import io
from typing import List, Optional

from reportlab.graphics.charts.legends import LineLegend
from reportlab.graphics.charts.lineplots import LinePlot
from reportlab.graphics.shapes import Drawing, Line, String
from reportlab.lib import colors
from reportlab.lib.enums import TA_LEFT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.platypus import (CondPageBreak, KeepTogether, PageBreak, Paragraph, SimpleDocTemplate, Spacer, Table,
                                TableStyle)
from xml.sax.saxutils import escape

from town.analysis import analyse, plain, rs
from town.runs import read_events, read_meta, read_stories

INK = colors.HexColor("#1A1A18")
MUTED = colors.HexColor("#6B6B68")
ACCENT = colors.HexColor("#2F6FED")
BORDER = colors.HexColor("#E5E5E0")
SURFACE = colors.HexColor("#F4F4F1")
DANGER = colors.HexColor("#B5483A")
AMBER = colors.HexColor("#A86B12")
OK = colors.HexColor("#4E8752")
STATUS_COLOR = {"In crisis": DANGER, "Under strain": AMBER, "Coping": OK}
SHOCK_LABELS = [("essential_cost", "Essential costs"), ("income", "Incomes"), ("credit_tightness", "Credit tightening"),
                ("demand", "Discretionary demand"), ("savings", "Saving mood")]

W, H = A4
MARGIN = 16 * mm
CONTENT_W = W - 2 * MARGIN

_base = dict(fontName="Helvetica", textColor=INK, leading=13, fontSize=9.5, alignment=TA_LEFT)
S = {
    "eyebrow": ParagraphStyle("eyebrow", **{**_base, "fontSize": 7.5, "textColor": MUTED, "leading": 10}),
    "title": ParagraphStyle("title", **{**_base, "fontName": "Helvetica-Bold", "fontSize": 19, "leading": 23}),
    "h2": ParagraphStyle("h2", **{**_base, "fontName": "Helvetica-Bold", "fontSize": 11, "leading": 14,
                                  "spaceBefore": 8, "spaceAfter": 4}),
    "h3": ParagraphStyle("h3", **{**_base, "fontName": "Helvetica-Bold", "fontSize": 9, "leading": 12,
                                  "spaceBefore": 6, "spaceAfter": 2, "textColor": MUTED}),
    "body": ParagraphStyle("body", **_base),
    "small": ParagraphStyle("small", **{**_base, "fontSize": 8, "leading": 10.5, "textColor": MUTED}),
    "cell": ParagraphStyle("cell", **{**_base, "fontSize": 8, "leading": 10.2}),
    "cellb": ParagraphStyle("cellb", **{**_base, "fontSize": 8, "leading": 10.2, "fontName": "Helvetica-Bold"}),
    "quote": ParagraphStyle("quote", **{**_base, "fontName": "Helvetica-Oblique", "fontSize": 8.6, "leading": 11.2}),
    "kpi_v": ParagraphStyle("kpi_v", **{**_base, "fontName": "Helvetica-Bold", "fontSize": 14, "leading": 17}),
    "kpi_k": ParagraphStyle("kpi_k", **{**_base, "fontSize": 7.5, "leading": 9.5, "textColor": MUTED}),
}


def P(text: str, style: str = "body") -> Paragraph:
    return Paragraph(text, S[style])


def E(text) -> str:
    return escape(plain(str(text)))


def pct(v: float) -> str:
    return f"{'+' if v > 0 else '-' if v < 0 else ''}{abs(v) * 100:.0f}%"


def _when(ts) -> str:
    try:
        return _dt.datetime.fromtimestamp(float(ts)).strftime("%d %b %Y, %H:%M")
    except (TypeError, ValueError):
        return ""


def _footer(title: str):
    def draw(canvas, doc):
        canvas.saveState()
        canvas.setFont("Helvetica", 7)
        canvas.setFillColor(MUTED)
        canvas.drawString(MARGIN, 9 * mm, f"EcoSim-MAS  ·  {title[:90]}")
        canvas.drawRightString(W - MARGIN, 9 * mm, f"Page {doc.page}")
        canvas.setStrokeColor(BORDER)
        canvas.line(MARGIN, 12 * mm, W - MARGIN, 12 * mm)
        canvas.restoreState()
    return draw


def _doc(buf, title):
    return SimpleDocTemplate(buf, pagesize=A4, leftMargin=MARGIN, rightMargin=MARGIN, topMargin=14 * mm,
                             bottomMargin=17 * mm, title=title, author="EcoSim-MAS")


def _table(rows, widths, header=True, zebra=False, extra=None):
    t = Table(rows, colWidths=widths, repeatRows=1 if header else 0)
    style = [("VALIGN", (0, 0), (-1, -1), "TOP"), ("LEFTPADDING", (0, 0), (-1, -1), 4),
             ("RIGHTPADDING", (0, 0), (-1, -1), 4), ("TOPPADDING", (0, 0), (-1, -1), 3),
             ("BOTTOMPADDING", (0, 0), (-1, -1), 3), ("LINEBELOW", (0, 0), (-1, -1), 0.4, BORDER)]
    if header:
        style += [("LINEBELOW", (0, 0), (-1, 0), 0.8, INK)]
    if zebra:
        for i in range(1 if header else 0, len(rows), 2):
            style.append(("BACKGROUND", (0, i), (-1, i), SURFACE))
    t.setStyle(TableStyle(style + (extra or [])))
    return t


def _chart(series, width, height, title, y_from_zero=True, y_fmt="{:.0f}", x_labels: Optional[List[int]] = None):
    """Flat line chart. series = [(name, color, [values...])], x = day number."""
    d = Drawing(width, height)
    d.add(String(0, height - 10, title, fontName="Helvetica-Bold", fontSize=8.5, fillColor=INK))
    lp = LinePlot()
    lp.x, lp.y = 28, 30
    lp.width, lp.height = width - 38, height - (74 if len(series) > 3 else 64)
    days = x_labels or list(range(1, max(len(s[2]) for s in series) + 1))
    lp.data = [[(days[i], v) for i, v in enumerate(vals)] for _, _, vals in series]
    for i, (_, col, _) in enumerate(series):
        lp.lines[i].strokeColor = col
        lp.lines[i].strokeWidth = 1.6
    allv = [v for _, _, vals in series for v in vals] or [0]
    lo = 0 if y_from_zero else min(allv)
    hi = max(allv)
    if hi - lo < 1e-9:
        hi = lo + 1
    pad = (hi - lo) * 0.12
    lp.yValueAxis.valueMin = lo if y_from_zero else lo - pad
    lp.yValueAxis.valueMax = hi + pad
    lp.yValueAxis.labelTextFormat = lambda v: y_fmt.format(v)
    lp.xValueAxis.valueMin, lp.xValueAxis.valueMax = days[0], max(days[-1], days[0] + 1)
    step = max(1, len(days) // 8)
    lp.xValueAxis.valueSteps = days[::step]
    for ax in (lp.xValueAxis, lp.yValueAxis):
        ax.labels.fontName = "Helvetica"
        ax.labels.fontSize = 6.5
        ax.labels.fillColor = MUTED
        ax.strokeColor = BORDER
    lp.yValueAxis.visibleGrid = True
    lp.yValueAxis.gridStrokeColor = BORDER
    lp.yValueAxis.gridStrokeWidth = 0.4
    lp.yValueAxis.maximumTicks = 5
    d.add(lp)
    d.add(String(lp.x + lp.width / 2, 14, "day", fontName="Helvetica", fontSize=6.5, fillColor=MUTED,
                 textAnchor="middle"))
    lg = LineLegend()
    lg.x, lg.y = 0, height - 20
    lg.alignment = "right"
    lg.fontName, lg.fontSize = "Helvetica", 7
    if len(series) > 3:          # two rows so long names never run into the next chart
        lg.columnMaximum = 2
        lg.deltax = (width - 10) / 2
        lg.deltay = 10
    else:
        lg.columnMaximum = 1
        lg.deltax = max(48, (width - 10) / max(1, len(series)))
    lg.dx, lg.dy = 10, 2
    lg.colorNamePairs = [(c, n) for n, c, _ in series]
    d.add(lg)
    return d


def _spark(values, width=140, height=40, color=INK):
    d = Drawing(width, height)
    d.add(String(0, height - 8, "cash, day by day", fontName="Helvetica", fontSize=6.5, fillColor=MUTED))
    if len(values) < 2:
        return d
    lo, hi = min(values), max(values)
    span = (hi - lo) or 1
    top = height - 12
    pts = [(2 + i * (width - 4) / (len(values) - 1), 3 + (v - lo) / span * (top - 4)) for i, v in enumerate(values)]
    for (x1, y1), (x2, y2) in zip(pts, pts[1:]):
        d.add(Line(x1, y1, x2, y2, strokeColor=color, strokeWidth=1.4))
    return d


def _rule():
    t = Table([[""]], colWidths=[CONTENT_W], rowHeights=[1])
    t.setStyle(TableStyle([("LINEABOVE", (0, 0), (-1, 0), 0.8, INK)]))
    return t


def _kpi_row(items):
    cells = [[P(E(v), "kpi_v") for _, v in items], [P(E(k), "kpi_k") for k, _ in items]]
    w = CONTENT_W / len(items)
    t = Table(cells, colWidths=[w] * len(items))
    t.setStyle(TableStyle([("LEFTPADDING", (0, 0), (-1, -1), 6), ("RIGHTPADDING", (0, 0), (-1, -1), 4),
                           ("TOPPADDING", (0, 0), (-1, 0), 7), ("BOTTOMPADDING", (0, 1), (-1, 1), 7),
                           ("TOPPADDING", (0, 1), (-1, 1), 0), ("BOX", (0, 0), (-1, -1), 0.5, BORDER),
                           ("LINEAFTER", (0, 0), (-2, -1), 0.5, BORDER), ("VALIGN", (0, 0), (-1, -1), "TOP")]))
    return t


def _shock_line(shock: dict) -> str:
    parts = [f"{label} {pct(shock[k])}" for k, label in SHOCK_LABELS if abs(shock.get(k, 0) or 0) >= 0.005]
    return "  ·  ".join(parts) if parts else "No shock (baseline)"


def _header(r, kind):
    when = _when(r.get("created_at"))
    pace = ("shock from day {o}, full strength by day {f}".format(o=r["onset_day"], f=r["full_day"])
            if any(abs(v or 0) >= 0.005 for v in (r.get("shock") or {}).values()) else "no shock")
    meta = f"{len(r['agents'])} agents  ·  {r['days_run']} of {r['days_planned']} days  ·  {pace}"
    if r.get("seed") is not None:
        meta += f"  ·  population seed {r['seed']}"
    return [P(f"ECOSIM-MAS  ·  {kind.upper()}  ·  RUN {E(r['run_id'])}" + (f"  ·  {E(when)}" if when else ""), "eyebrow"),
            Spacer(1, 3), P(E(r["title"] or "Town simulation"), "title"), Spacer(1, 2),
            P(E(meta), "small"), P(E(_shock_line(r.get("shock") or {})), "small"), Spacer(1, 8)]


def _fallback_town_story(r) -> str:
    k = r["kpis"]
    c = r["status_counts"]
    bits = [f"Over {r['days_run']} days, prices for groceries reached {k['grocery_index_end']:.2f}x and fuel "
            f"{k['fuel_index_end']:.2f}x their normal level."]
    bits.append(f"The typical (median) person's cash went from {rs(k['median_money_start'])} to {rs(k['median_money_end'])}, "
                f"and {k['cash_fell']} of {len(r['agents'])} people ended with noticeably less cash than on day 1.")
    if k["moneylender_end"] > k["moneylender_start"]:
        bits.append(f"Moneylender borrowing rose from {k['moneylender_start']} to {k['moneylender_end']} people.")
    if k["defaulted_end"]:
        bits.append(f"{k['defaulted_end']} defaulted on a loan.")
    if k["unemployed_end"]:
        bits.append(f"{k['unemployed_end']} were left without work.")
    bits.append(f"By the end, {c.get('In crisis', 0)} were in crisis, {c.get('Under strain', 0)} under strain "
                f"and {c.get('Coping', 0)} coping.")
    return " ".join(bits)


# ── summary ──────────────────────────────────────────────────────────────────
def summary_pdf(run_id: str) -> bytes:
    meta = read_meta(run_id) or {}
    r = analyse(read_events(run_id), meta)
    stories = read_stories(run_id)
    k = r["kpis"]
    buf = io.BytesIO()
    doc = _doc(buf, f"{r['title']} — summary")
    f: list = _header(r, "Simulation summary")

    c = r["status_counts"]
    med0, med1 = k["median_money_start"], k["median_money_end"]
    f.append(_kpi_row([
        ("Median cash per person, day 1 to end", f"{pct((med1 - med0) / med0) if med0 else '0%'}"),
        ("People under strain or in crisis", f"{c.get('Under strain', 0) + c.get('In crisis', 0)} of {len(r['agents'])}"),
        ("Borrowing from the moneylender", f"{k['moneylender_start']} -> {k['moneylender_end']}"),
        ("Loan defaults / without work", f"{k['defaulted_end']} / {k['unemployed_end']}"),
        ("Groceries / petrol vs normal", f"x{k['grocery_index_end']:.2f} / x{k['fuel_index_end']:.2f}"),
    ]))
    f.append(Spacer(1, 10))

    town = stories.get("town") or {}
    f.append(P("What happened", "h2"))
    f.append(P(E(town.get("summary") or _fallback_town_story(r))))
    if town.get("lessons"):
        f.append(Spacer(1, 4))
        f.append(P("Findings", "h3"))
        for s in town["lessons"]:
            f.append(P("-&nbsp;&nbsp;" + E(s)))
    if town.get("summary"):
        f.append(P("Written by the LLM from this run's event log; the numbers above are computed directly from the log.",
                   "small"))
    f.append(Spacer(1, 8))

    days = [d["day"] for d in r["days"]]
    if len(days) >= 2:
        t = [d["town"] for d in r["days"]]
        left = _chart([("Low on food", AMBER, [x.get("low_food", 0) for x in t]),
                       ("Moneylender", DANGER, [x.get("moneylender_borrowers", 0) for x in t]),
                       ("Defaulted", INK, [x.get("defaulted", 0) for x in t]),
                       ("Without work", MUTED, [x.get("unemployed", 0) for x in t])],
                      CONTENT_W / 2 - 4, 170, "People affected, by day", x_labels=days)
        right = _chart([("Groceries", OK, [d["prices"].get("groceries", 1) for d in r["days"]]),
                        ("Fuel", ACCENT, [d["prices"].get("fuel", 1) for d in r["days"]]),
                        ("Eating out", AMBER, [d["prices"].get("eating_out", 1) for d in r["days"]])],
                       CONTENT_W / 2 - 4, 170, "Prices (1.00 = normal)", y_from_zero=False, y_fmt="{:.2f}", x_labels=days)
        ct = Table([[left, right]], colWidths=[CONTENT_W / 2, CONTENT_W / 2])
        ct.setStyle(TableStyle([("LEFTPADDING", (0, 0), (-1, -1), 0), ("RIGHTPADDING", (0, 0), (-1, -1), 0)]))
        f.append(ct)

    f.append(CondPageBreak(60 * mm))
    f.append(P("Who was hit hardest", "h2"))
    ag_stories = stories.get("agents") or {}
    rows = [[P("Person", "cellb"), P("Outcome", "cellb"), P("Cash day 1 -> end", "cellb"), P("Turning point", "cellb")]]
    hardest = [a for a in r["agents"] if a["status"] != "Coping"][:6] or r["agents"][:3]
    for a in hardest:
        tp = (ag_stories.get(a["id"]) or {}).get("turning_point") or (
            f"Day {a['pivots'][-1]['day']}: {a['pivots'][-1]['text']}" if a["pivots"] else "")
        rows.append([P(f"<b>{E(a['name'])}</b><br/>{E(a['job'])}", "cell"),
                     P(f"<font color='{STATUS_COLOR[a['status']].hexval()}'>{a['status']}</font>", "cell"),
                     P(f"{rs(a['start']['money'])} -> {rs(a['end']['money'])}", "cell"), P(E(tp), "cell")])
    f.append(_table(rows, [42 * mm, 22 * mm, 34 * mm, CONTENT_W - 98 * mm], zebra=False))

    coping = [a for a in r["agents"] if a["status"] == "Coping"]
    if coping:
        best = sorted(coping, key=lambda a: -(a["end"]["money"] - a["start"]["money"]) / max(1, a["start"]["money"]))[:3]
        f.append(Spacer(1, 6))
        f.append(P("Coped best: " + "; ".join(f"{E(a['name'])} ({E(a['job'])})" for a in best), "small"))

    if r["key_events"]:
        f.append(CondPageBreak(40 * mm))
        f.append(P("Key events", "h2"))
        rows = [[P("Day", "cellb"), P("Event", "cellb")]] + [[P(str(x["day"]), "cell"), P(E(x["text"]), "cell")]
                                                             for x in r["key_events"][:14]]
        f.append(_table(rows, [14 * mm, CONTENT_W - 14 * mm]))

    f.append(CondPageBreak(30 * mm))
    f.append(P("How this was simulated", "h2"))
    modes = r["decision_modes"]
    llm_n, routine, fb = modes.get("llm", 0), modes.get("routine", 0), modes.get("fallback", 0) + modes.get("mock", 0)
    f.append(P(E(
        f"Each of the {len(r['agents'])} people is a generative agent: every morning that something has changed, an LLM "
        f"reads their situation, memories and conclusions and writes their plan and reasoning; the town's economy "
        f"(prices, wages, bank rules, bills) is fixed code that enforces the consequences. In this run: {llm_n} plans "
        f"were written by the LLM, {routine} were routine days (nothing new, so yesterday's plan was kept), "
        f"and {fb} used the rule-based fallback. Agents held {r['conversations']} conversations and formed "
        f"{r['reflections']} reflections. Models: {r['providers'] or r['brain']}. Memory: {r['memory']}."), "small"))
    doc.build(f, onFirstPage=_footer(r["title"]), onLaterPages=_footer(r["title"]))
    return buf.getvalue()


# ── per-agent ────────────────────────────────────────────────────────────────
def agents_pdf(run_id: str) -> bytes:
    meta = read_meta(run_id) or {}
    r = analyse(read_events(run_id), meta)
    stories = (read_stories(run_id).get("agents") or {})
    buf = io.BytesIO()
    doc = _doc(buf, f"{r['title']} — agents")
    f: list = _header(r, "Agent report")

    f.append(P("All agents", "h2"))
    rows = [[P(h, "cellb") for h in ("Person", "Outcome", "Cash day 1 -> end", "Debt", "Credit score", "LLM plans")]]
    for a in r["agents"]:
        rows.append([P(f"<b>{E(a['name'])}</b>, {a['age']}<br/>{E(a['job'])}", "cell"),
                     P(f"<font color='{STATUS_COLOR[a['status']].hexval()}'>{a['status']}</font>", "cell"),
                     P(f"{rs(a['start']['money'])} -> {rs(a['end']['money'])}", "cell"),
                     P(f"{rs(a['start']['debt'])} -> {rs(a['end']['debt'])}", "cell"),
                     P(f"{a['start']['credit_score']} -> {a['end']['credit_score']}", "cell"),
                     P(str(a["llm_decisions"]), "cell")])
    f.append(_table(rows, [52 * mm, 22 * mm, 36 * mm, 36 * mm, 20 * mm, CONTENT_W - 166 * mm], zebra=True))
    f.append(Spacer(1, 4))
    f.append(P("Outcome: <b>In crisis</b> = defaulted, lost their job or went 2+ days without food; <b>Under strain</b> = "
               "borrowed from the moneylender, ran up shop credit, skipped a bill, went a day without food or lost over "
               "40% of their cash; otherwise <b>Coping</b>. Cash on day 1 is after the 1st's salaries and pensions arrive.",
               "small"))

    for i, a in enumerate(r["agents"]):
        if i == 0:
            f.append(PageBreak())
        else:
            f.append(CondPageBreak(95 * mm))      # start a new page unless there is plenty of room
            f.append(Spacer(1, 6))
            f.append(_rule())
            f.append(Spacer(1, 8))
        f += _agent_section(a, r, stories.get(a["id"]))
    doc.build(f, onFirstPage=_footer(r["title"]), onLaterPages=_footer(r["title"]))
    return buf.getvalue()


def _agent_section(a: dict, r: dict, story: Optional[dict]) -> list:
    col = STATUS_COLOR[a["status"]]
    out = [P(f"{E(a['name'])} <font size='9' color='{col.hexval()}'>&nbsp;&nbsp;{a['status'].upper()}</font>", "title")]
    hh = "lives alone" if a["household"] == 1 else f"household of {a['household']}"
    if a.get("children"):
        hh += f", {a['children']} school-going child{'ren' if a['children'] > 1 else ''}"
    extra = f"  ·  sends money home to {a['migrant_from']}" if a.get("migrant_from") else ""
    out.append(P(E(f"{a['age']}, {a['job']}  ·  {hh}{extra}"), "small"))
    out.append(P(E("Goals: " + "; ".join(a["goals"])), "small"))
    out.append(Spacer(1, 6))

    e, s = a["end"], a["start"]
    nums = [[P("<b>Cash</b>", "cell"), P(f"{rs(s['money'])} -> <b>{rs(e['money'])}</b>", "cell"),
             P("<b>Debt</b>", "cell"), P(f"{rs(s['debt'])} -> <b>{rs(e['debt'])}</b>", "cell"),
             _spark(a["money_series"], width=CONTENT_W - 132 * mm, color=col)],
            [P("<b>Credit score</b>", "cell"), P(f"{s['credit_score']} -> <b>{e['credit_score']}</b>", "cell"),
             P("<b>Earned</b>", "cell"), P(rs(e.get("earned", 0)), "cell"), ""]]
    flags = []
    if True:
        if e.get("khata_due"):
            flags.append(f"owes the kirana {rs(e['khata_due'])}")
        if e.get("days_hungry"):
            flags.append(f"{e['days_hungry']} day(s) without food")
        if e.get("defaulted"):
            flags.append("in default")
        if a["pivots"] and any(x["text"].startswith("Lost their job") for x in a["pivots"]):
            flags.append("lost their job")
    if flags:
        nums.append([P("<b>At the end</b>", "cell"), P(E(", ".join(flags)), "cell"), "", "", ""])
    t = Table(nums, colWidths=[22 * mm, 42 * mm, 16 * mm, 46 * mm, CONTENT_W - 126 * mm])
    t.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "MIDDLE"), ("LEFTPADDING", (0, 0), (-1, -1), 3),
                           ("BOX", (0, 0), (-1, -1), 0.5, BORDER), ("SPAN", (4, 0), (4, 1)),
                           ("TOPPADDING", (0, 0), (-1, -1), 3), ("BOTTOMPADDING", (0, 0), (-1, -1), 3)]))
    out.append(t)

    if story and story.get("story"):
        out.append(P("Their month", "h3"))
        out.append(P(E(story["story"])))
        if story.get("turning_point"):
            out.append(P("<b>Turning point:</b> " + E(story["turning_point"])))
        out.append(P("Written by the LLM from the facts below.", "small"))

    if a["major_decisions"]:
        out.append(P("Major decisions, in their own words", "h3"))
        rows = []
        for d in a["major_decisions"][:9]:
            plan = d.get("plan") or {}
            route = " -> ".join(f"{(plan.get(ph) or {}).get('place', '?')}:{(plan.get(ph) or {}).get('do', '')}"
                                for ph in ("morning", "afternoon", "evening"))
            why = ", ".join(d["why"])
            body = f"<i>\"{E(d['thought'])}\"</i>"
            if d["money_moves"]:
                moves = "; ".join(d["money_moves"])
                body += "<br/><b>" + E(moves[:1].upper() + moves[1:]) + "</b>"
            body += f"<br/><font color='{MUTED.hexval()}'>{E(route)}</font>"
            rows.append([P(f"<b>Day {d['day']}</b><br/><font color='{MUTED.hexval()}'>{E(why)}</font>", "cell"),
                         P(body, "cell")])
        out.append(_table(rows, [28 * mm, CONTENT_W - 28 * mm], header=False))

    out.append(P("Pivotal points", "h3"))
    if a["pivots"]:
        rows = [[P(f"Day {x['day']}" + (f"-{x['last_day']}" if x["times"] > 1 and x["last_day"] != x["day"] else ""), "cell"),
                 P(E(x["text"]) + (f" <font color='{MUTED.hexval()}'>(x{x['times']})</font>" if x["times"] > 1 else ""),
                   "cell")] for x in a["pivots"][:12]]
        out.append(_table(rows, [22 * mm, CONTENT_W - 22 * mm], header=False))
    else:
        out.append(P("Nothing went seriously wrong this month.", "small"))

    talks = [t for t in a["talks"] if t["learned"]][:3]
    if talks:
        out.append(P("Conversations that mattered", "h3"))
        rows = [[P(f"Day {t['day']}<br/><font color='{MUTED.hexval()}'>with {E(t['with'])}</font>", "cell"),
                 P(E(t["learned"]), "cell")] for t in talks]
        out.append(_table(rows, [28 * mm, CONTENT_W - 28 * mm], header=False))

    if a["reflections"]:
        out.append(P("Conclusions they reached", "h3"))
        for x in a["reflections"]:
            out.append(P(f"<b>Day {x['day']}:</b> " + " ".join(f"\"{E(s)}\"" for s in x["insights"]), "quote"))
    return out
