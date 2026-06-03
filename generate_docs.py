"""Generate PDF documentation for the Market Risk & Pricing Engine."""

from reportlab.lib.pagesizes import A4
from reportlab.lib import colors
from reportlab.lib.units import mm, cm
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.enums import TA_LEFT, TA_CENTER, TA_JUSTIFY
from reportlab.platypus import (
    SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle,
    PageBreak, HRFlowable, KeepTogether
)
from reportlab.platypus.tableofcontents import TableOfContents
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
import datetime

# ─────────────────────────────────────────────────────────
# Page layout
# ─────────────────────────────────────────────────────────

W, H = A4
LEFT = RIGHT = 22*mm
TOP  = 22*mm
BOT  = 22*mm

# ─────────────────────────────────────────────────────────
# Colour palette
# ─────────────────────────────────────────────────────────

DARK_BLUE   = colors.HexColor("#0D2137")
MID_BLUE    = colors.HexColor("#1A4A7A")
ACCENT      = colors.HexColor("#2E7BCF")
LIGHT_BLUE  = colors.HexColor("#EBF4FF")
LIGHT_GREY  = colors.HexColor("#F4F6F9")
BORDER_GREY = colors.HexColor("#C8D6E5")
TEXT        = colors.HexColor("#1A1A2E")
MUTED       = colors.HexColor("#5A6A7E")
WHITE       = colors.white
GREEN       = colors.HexColor("#1B7A3E")
ORANGE      = colors.HexColor("#C25B00")
RED         = colors.HexColor("#A01020")

# ─────────────────────────────────────────────────────────
# Styles
# ─────────────────────────────────────────────────────────

base = getSampleStyleSheet()

def S(name, **kw):
    return ParagraphStyle(name, **kw)

# Typography scale
styles = dict(
    cover_title = S("CoverTitle",
        fontName="Helvetica-Bold", fontSize=32, leading=40,
        textColor=WHITE, alignment=TA_CENTER, spaceAfter=8),
    cover_sub   = S("CoverSub",
        fontName="Helvetica", fontSize=14, leading=20,
        textColor=colors.HexColor("#A8C8F0"), alignment=TA_CENTER, spaceAfter=4),
    cover_meta  = S("CoverMeta",
        fontName="Helvetica", fontSize=10, leading=14,
        textColor=colors.HexColor("#7AAFD4"), alignment=TA_CENTER),

    h1  = S("H1",
        fontName="Helvetica-Bold", fontSize=18, leading=24,
        textColor=DARK_BLUE, spaceBefore=18, spaceAfter=8,
        borderPadding=(0,0,4,0)),
    h2  = S("H2",
        fontName="Helvetica-Bold", fontSize=13, leading=18,
        textColor=MID_BLUE, spaceBefore=14, spaceAfter=6),
    h3  = S("H3",
        fontName="Helvetica-Bold", fontSize=11, leading=16,
        textColor=ACCENT, spaceBefore=10, spaceAfter=4),

    body = S("Body",
        fontName="Helvetica", fontSize=10, leading=15,
        textColor=TEXT, alignment=TA_JUSTIFY, spaceAfter=6),
    body_small = S("BodySmall",
        fontName="Helvetica", fontSize=9, leading=13,
        textColor=TEXT, alignment=TA_JUSTIFY, spaceAfter=4),

    formula = S("Formula",
        fontName="Courier-Bold", fontSize=10, leading=15,
        textColor=MID_BLUE, leftIndent=14, spaceAfter=4,
        borderPadding=6, backColor=LIGHT_BLUE),
    formula_sm = S("FormulaSm",
        fontName="Courier", fontSize=9, leading=13,
        textColor=DARK_BLUE, leftIndent=14, spaceAfter=2),
    code = S("Code",
        fontName="Courier", fontSize=8.5, leading=13,
        textColor=colors.HexColor("#2B2B2B"), leftIndent=8,
        backColor=LIGHT_GREY, spaceAfter=4, borderPadding=5),

    caption = S("Caption",
        fontName="Helvetica-Oblique", fontSize=8.5, leading=12,
        textColor=MUTED, alignment=TA_CENTER, spaceAfter=6),
    bullet  = S("Bullet",
        fontName="Helvetica", fontSize=10, leading=15,
        textColor=TEXT, leftIndent=16, spaceAfter=3,
        bulletIndent=6),
    note    = S("Note",
        fontName="Helvetica-Oblique", fontSize=9, leading=13,
        textColor=MUTED, leftIndent=10, spaceAfter=4),
    toc_h1  = S("TOCH1",
        fontName="Helvetica-Bold", fontSize=11, leading=15,
        textColor=MID_BLUE, spaceAfter=2),
    toc_h2  = S("TOCH2",
        fontName="Helvetica", fontSize=10, leading=14,
        textColor=TEXT, leftIndent=16, spaceAfter=1),
)


def H1(text): return Paragraph(text, styles["h1"])
def H2(text): return Paragraph(text, styles["h2"])
def H3(text): return Paragraph(text, styles["h3"])
def P(text):  return Paragraph(text, styles["body"])
def Ps(text): return Paragraph(text, styles["body_small"])
def F(text):  return Paragraph(text, styles["formula"])
def Fs(text): return Paragraph(text, styles["formula_sm"])
def C(text):  return Paragraph(text, styles["code"])
def N(text):  return Paragraph(text, styles["note"])
def B(text):  return Paragraph(f"&#x2022; &nbsp; {text}", styles["bullet"])
def SP(n=6):  return Spacer(1, n)
def HR():     return HRFlowable(width="100%", thickness=0.5, color=BORDER_GREY, spaceAfter=6)


# ─────────────────────────────────────────────────────────
# Header / Footer
# ─────────────────────────────────────────────────────────

def on_page(canvas, doc):
    canvas.saveState()
    pn = doc.page
    # header bar
    canvas.setFillColor(DARK_BLUE)
    canvas.rect(LEFT, H - TOP + 4*mm, W - LEFT - RIGHT, 6*mm, fill=1, stroke=0)
    canvas.setFillColor(WHITE)
    canvas.setFont("Helvetica-Bold", 8)
    canvas.drawString(LEFT + 3*mm, H - TOP + 6*mm, "Market Risk & Pricing Engine")
    canvas.setFont("Helvetica", 8)
    canvas.drawRightString(W - RIGHT - 3*mm, H - TOP + 6*mm, "Technical Documentation v1.0")
    # footer
    canvas.setFillColor(LIGHT_GREY)
    canvas.rect(LEFT, BOT - 10*mm, W - LEFT - RIGHT, 6*mm, fill=1, stroke=0)
    canvas.setFillColor(MUTED)
    canvas.setFont("Helvetica", 7.5)
    canvas.drawString(LEFT + 3*mm, BOT - 7*mm, f"© {datetime.date.today().year}  |  Confidential")
    canvas.drawRightString(W - RIGHT - 3*mm, BOT - 7*mm, f"Page {pn}")
    canvas.restoreState()


def on_cover(canvas, doc):
    # solid dark cover background
    canvas.setFillColor(DARK_BLUE)
    canvas.rect(0, 0, W, H, fill=1, stroke=0)
    # accent stripe
    canvas.setFillColor(ACCENT)
    canvas.rect(0, H*0.42, W, 3*mm, fill=1, stroke=0)
    canvas.setFillColor(MID_BLUE)
    canvas.rect(0, H*0.42 - 1*mm, W, 1*mm, fill=1, stroke=0)


# ─────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────

def info_table(rows, col_w=None):
    col_w = col_w or [70*mm, W - LEFT - RIGHT - 70*mm]
    t = Table(rows, colWidths=col_w)
    t.setStyle(TableStyle([
        ("BACKGROUND", (0,0), (0,-1), LIGHT_BLUE),
        ("BACKGROUND", (1,0), (1,-1), WHITE),
        ("FONTNAME",   (0,0), (0,-1), "Helvetica-Bold"),
        ("FONTNAME",   (1,0), (1,-1), "Helvetica"),
        ("FONTSIZE",   (0,0), (-1,-1), 9),
        ("LEADING",    (0,0), (-1,-1), 13),
        ("TEXTCOLOR",  (0,0), (0,-1), MID_BLUE),
        ("TEXTCOLOR",  (1,0), (1,-1), TEXT),
        ("VALIGN",     (0,0), (-1,-1), "MIDDLE"),
        ("TOPPADDING", (0,0), (-1,-1), 5),
        ("BOTTOMPADDING",(0,0),(-1,-1), 5),
        ("LEFTPADDING",(0,0), (-1,-1), 8),
        ("GRID",       (0,0), (-1,-1), 0.4, BORDER_GREY),
    ]))
    return t


def formula_box(lines, title=None):
    elems = []
    if title:
        elems.append(Paragraph(title, styles["h3"]))
    for l in lines:
        elems.append(Paragraph(l, styles["formula"]))
    return elems


def two_col(left_items, right_items):
    data = [[left_items, right_items]]
    t = Table(data, colWidths=[(W-LEFT-RIGHT-6*mm)/2]*2)
    t.setStyle(TableStyle([
        ("VALIGN", (0,0), (-1,-1), "TOP"),
        ("LEFTPADDING",  (0,0), (-1,-1), 0),
        ("RIGHTPADDING", (0,0), (-1,-1), 6),
    ]))
    return t


def section_badge(text, color=ACCENT):
    data = [[Paragraph(f"<font color='white'><b>{text}</b></font>",
                        ParagraphStyle("badge", fontName="Helvetica-Bold",
                                       fontSize=9, textColor=WHITE, alignment=TA_CENTER))]]
    t = Table(data, colWidths=[W - LEFT - RIGHT])
    t.setStyle(TableStyle([
        ("BACKGROUND", (0,0), (-1,-1), color),
        ("TOPPADDING",    (0,0), (-1,-1), 5),
        ("BOTTOMPADDING", (0,0), (-1,-1), 5),
        ("LEFTPADDING",   (0,0), (-1,-1), 10),
    ]))
    return t


# ─────────────────────────────────────────────────────────
# Content builders
# ─────────────────────────────────────────────────────────

def build_cover():
    return [
        Spacer(1, 60*mm),
        Paragraph("Market Risk &amp; Pricing Engine", styles["cover_title"]),
        SP(4),
        Paragraph("Technical Documentation &amp; Methodology Reference", styles["cover_sub"]),
        SP(8),
        Paragraph("Version 1.0  ·  Python Implementation", styles["cover_meta"]),
        SP(2),
        Paragraph(f"Compiled {datetime.date.today().strftime('%B %d, %Y')}", styles["cover_meta"]),
        Spacer(1, 20*mm),
    ]


def build_toc_page():
    story = [H1("Table of Contents"), SP(4), HR()]
    toc_items = [
        ("1.", "Overview & Architecture",              ""),
        ("2.", "Mathematical Models",                   ""),
        ("  2.1", "Black-Scholes-Merton (BSM)",         ""),
        ("  2.2", "Black-76 (Futures & Forwards)",      ""),
        ("  2.3", "Garman-Kohlhagen (FX Options)",      ""),
        ("  2.4", "Bachelier (Normal Model)",            ""),
        ("  2.5", "Binomial Trees (CRR, LR, Trinomial)",""),
        ("  2.6", "Monte Carlo Engine",                  ""),
        ("  2.7", "Heston Stochastic Volatility",       ""),
        ("  2.8", "SABR Model",                          ""),
        ("  2.9", "Implied Volatility Solvers",          ""),
        ("3.", "Vanilla Options",                        ""),
        ("4.", "Barrier Options",                        ""),
        ("5.", "Asian Options",                          ""),
        ("6.", "Digital Options",                        ""),
        ("7.", "Lookback Options",                       ""),
        ("8.", "Exotic Options",                         ""),
        ("  8.1", "Chooser & Compound Options",          ""),
        ("  8.2", "Forward-Start, Shout, Power Options", ""),
        ("  8.3", "Cliquet / Ratchet Options",           ""),
        ("  8.4", "Reset, Range Accrual",                ""),
        ("9.", "Multi-Asset Options",                    ""),
        ("  9.1", "Exchange Option (Margrabe)",          ""),
        ("  9.2", "Spread Options (Kirk / MC)",          ""),
        ("  9.3", "Basket Options",                      ""),
        ("  9.4", "Rainbow Options",                     ""),
        ("  9.5", "Quanto Options",                      ""),
        ("  9.6", "Mountain Range (Himalaya, Altiplano)",""),
        ("10.", "Variance & Volatility Products",        ""),
        ("11.", "Fixed Income Instruments",              ""),
        ("  11.1", "Bonds: Price, Duration, Convexity",  ""),
        ("  11.2", "Interest Rate Swaps",                ""),
        ("  11.3", "Cap / Floor / Swaption",             ""),
        ("12.", "Credit Instruments",                    ""),
        ("  12.1", "Credit Default Swap (CDS)",          ""),
        ("  12.2", "CDO Tranche Pricing",                ""),
        ("  12.3", "CVA / DVA",                          ""),
        ("13.", "FX Instruments",                        ""),
        ("14.", "Market Risk Metrics",                   ""),
        ("  14.1", "Value at Risk (VaR)",                ""),
        ("  14.2", "Stress Testing",                     ""),
        ("  14.3", "P&L Attribution",                    ""),
        ("15.", "CLI Usage Guide",                       ""),
    ]
    rows = []
    for num, title, _ in toc_items:
        is_main = not num.strip().startswith("  ")
        fn = "Helvetica-Bold" if is_main else "Helvetica"
        indent = 0 if is_main else 12
        style = ParagraphStyle("toc", fontName=fn, fontSize=10,
                                textColor=MID_BLUE if is_main else TEXT,
                                leftIndent=indent, leading=15)
        rows.append([Paragraph(num, style),
                     Paragraph(title, style),
                     Paragraph("·" * 30, ParagraphStyle("dots", fontName="Helvetica",
                                                          fontSize=9, textColor=BORDER_GREY))])
    t = Table(rows, colWidths=[14*mm, W-LEFT-RIGHT-38*mm, 24*mm])
    t.setStyle(TableStyle([
        ("VALIGN",  (0,0), (-1,-1), "MIDDLE"),
        ("TOPPADDING",    (0,0), (-1,-1), 2),
        ("BOTTOMPADDING", (0,0), (-1,-1), 2),
        ("LEFTPADDING",   (0,0), (-1,-1), 0),
    ]))
    story.append(t)
    return story


def build_overview():
    story = [H1("1. Overview & Architecture"), HR()]
    story += [P(
        "The <b>Market Risk &amp; Pricing Engine</b> is a Python library designed to replicate "
        "the core analytical capabilities of professional quantitative finance platforms such as "
        "Numerix, Murex, and Bloomberg MARS. It provides a unified framework for pricing and "
        "risk-managing a wide range of financial instruments — from vanilla equity options to "
        "exotic path-dependent derivatives and credit products."
    ), SP(4)]

    story.append(H2("Key Capabilities"))
    caps = [
        ("Pricing Models", "BSM, Black-76, Garman-Kohlhagen, Bachelier, Heston, SABR, Binomial CRR/LR, Trinomial, Monte Carlo, LSM"),
        ("Vanilla Options", "European, American, Bermudan — 7 model choices per instrument"),
        ("Barrier Options", "Single knock-in/out, double barrier, partial/window barrier"),
        ("Path-Dependent", "Asian (arithmetic & geometric), Lookback (fixed & floating), Cliquet, Shout"),
        ("Digital Options", "Cash/asset-or-nothing, One-touch, No-touch, Double no-touch, Supershare"),
        ("Exotic Options",  "Chooser, Compound, Forward-start, Power, Reset, Range Accrual"),
        ("Multi-Asset",     "Exchange (Margrabe), Spread, Basket, Rainbow, Quanto, Himalaya, Altiplano"),
        ("Variance Prods.", "Variance swap, Vol swap, Gamma swap, Corridor/Conditional var swap"),
        ("Fixed Income",    "Bonds, FRN, IRS, OIS, Basis swap, Cap/Floor/Collar, Swaption, CMS"),
        ("Credit",          "CDS, Binary CDS, CDO tranche (LHP/Gaussian copula), CVA/DVA"),
        ("FX Instruments",  "FX Forward, FX Option, FX Barrier, Risk reversal, Strangle, Straddle"),
        ("Greeks",          "Full set: Delta, Gamma, Vega, Theta, Rho, Vanna, Volga, Charm, Speed, Color, Zomma, Ultima"),
        ("Risk Metrics",    "Historical / Parametric / MC / EVT VaR, CVaR, Component VaR, Kupiec & Christoffersen tests"),
        ("Stress Testing",  "14 historical scenarios, reverse stress, PnL attribution, Greeks ladder"),
    ]
    story.append(info_table([[k, v] for k, v in caps]))
    story.append(SP(10))

    story.append(H2("Module Architecture"))
    arch = [
        ["Module", "File", "Contents"],
        ["models/", "black_scholes.py", "BSM · Black-76 · GK · Bachelier · full Greeks"],
        ["",        "trees.py",         "CRR · Leisen-Reimer · Trinomial trees"],
        ["",        "monte_carlo.py",   "GBM paths · Heston paths · MC pricer · LSM"],
        ["",        "heston.py",        "Heston semi-analytical · SABR · calibration"],
        ["",        "implied_vol.py",   "IV solvers · SVI · volatility surface"],
        ["instruments/", "vanilla.py",       "European · American · Bermudan"],
        ["",             "barrier.py",       "Single/double barrier · MC barrier"],
        ["",             "asian.py",         "Geometric exact · Arithmetic MC+CV"],
        ["",             "digital.py",       "Cash/asset-or-nothing · Touch options"],
        ["",             "lookback.py",      "Fixed/floating lookback · MC"],
        ["",             "exotic.py",        "Chooser · Compound · Cliquet · Shout · etc."],
        ["",             "multi_asset.py",   "Margrabe · Kirk · Basket · Rainbow · Quanto"],
        ["",             "variance_swaps.py","Var swap · Vol swap · Corridor var"],
        ["",             "fixed_income.py",  "Bonds · IRS · Cap/Floor · Swaption"],
        ["",             "credit.py",        "CDS · CDO-LHP · CVA/DVA"],
        ["",             "fx.py",            "FX Forward · GK Option · Barrier · RR/STR"],
        ["risk/",   "var.py",           "VaR · CVaR · EVT · Portfolio VaR · Backtesting"],
        ["",        "stress.py",        "Stress scenarios · Greeks ladder · PnL explain"],
    ]
    t = Table(arch, colWidths=[28*mm, 44*mm, W-LEFT-RIGHT-76*mm])
    t.setStyle(TableStyle([
        ("BACKGROUND",    (0,0), (-1,0),  DARK_BLUE),
        ("TEXTCOLOR",     (0,0), (-1,0),  WHITE),
        ("FONTNAME",      (0,0), (-1,0),  "Helvetica-Bold"),
        ("FONTSIZE",      (0,0), (-1,-1), 8.5),
        ("LEADING",       (0,0), (-1,-1), 12),
        ("BACKGROUND",    (0,1), (-1,-1), WHITE),
        ("ROWBACKGROUNDS",(0,1), (-1,-1), [WHITE, LIGHT_GREY]),
        ("FONTNAME",      (0,1), (0,-1),  "Helvetica-Bold"),
        ("TEXTCOLOR",     (0,1), (0,-1),  ACCENT),
        ("FONTNAME",      (1,1), (-1,-1), "Courier"),
        ("TEXTCOLOR",     (1,1), (1,-1),  MID_BLUE),
        ("GRID",          (0,0), (-1,-1), 0.3, BORDER_GREY),
        ("VALIGN",        (0,0), (-1,-1), "MIDDLE"),
        ("TOPPADDING",    (0,0), (-1,-1), 4),
        ("BOTTOMPADDING", (0,0), (-1,-1), 4),
        ("LEFTPADDING",   (0,0), (-1,-1), 6),
    ]))
    story.append(t)
    return story


def build_models():
    story = [PageBreak(), H1("2. Mathematical Models"), HR()]

    # ── 2.1 BSM ──────────────────────────────────────────
    story += [H2("2.1 Black-Scholes-Merton (BSM)"), SP(2)]
    story.append(P(
        "The Black-Scholes-Merton model is the foundational closed-form solution for pricing "
        "European options on a stock paying a continuous dividend yield <i>q</i>. "
        "It assumes log-normal price dynamics with constant volatility."
    ))
    story.append(H3("Dynamics"))
    story.append(F("dS = (r - q) S dt  +  sigma S dW"))
    story.append(H3("Option Price"))
    story.append(F("C = S e^(-qT) N(d1) - K e^(-rT) N(d2)"))
    story.append(F("P = K e^(-rT) N(-d2) - S e^(-qT) N(-d1)"))
    story.append(F("d1 = [ln(S/K) + (r - q + sigma^2/2) T] / (sigma sqrt(T))"))
    story.append(F("d2 = d1 - sigma sqrt(T)"))
    story.append(H3("Greeks (First Order)"))
    greeks_data = [
        ["Greek", "Call", "Put"],
        ["Delta  (dP/dS)",    "e^(-qT) N(d1)",              "e^(-qT) [N(d1) - 1]"],
        ["Gamma  (d²P/dS²)",  "e^(-qT) n(d1) / (S sigma sqrt(T))", "Same as Call"],
        ["Vega   (dP/dsigma)","S e^(-qT) n(d1) sqrt(T) / 100",     "Same as Call"],
        ["Theta  (dP/dt) /day","-(S e^(-qT) n(d1) sigma)/(2sqrt(T)) - rK e^(-rT) N(d2) + qS e^(-qT) N(d1)  /365",
                               "+(qS e^(-qT) N(-d1) - rK e^(-rT) N(-d2)) term /365"],
        ["Rho    (dP/dr) /1%", "K T e^(-rT) N(d2) / 100",          "-K T e^(-rT) N(-d2) / 100"],
    ]
    t = Table(greeks_data, colWidths=[36*mm, (W-LEFT-RIGHT-40*mm)/2]*2)
    t.setStyle(TableStyle([
        ("BACKGROUND",    (0,0), (-1,0),  MID_BLUE),
        ("TEXTCOLOR",     (0,0), (-1,0),  WHITE),
        ("FONTNAME",      (0,0), (-1,0),  "Helvetica-Bold"),
        ("FONTNAME",      (0,1), (0,-1),  "Helvetica-Bold"),
        ("FONTNAME",      (1,1), (-1,-1), "Courier"),
        ("FONTSIZE",      (0,0), (-1,-1), 8),
        ("LEADING",       (0,0), (-1,-1), 11),
        ("ROWBACKGROUNDS",(0,1), (-1,-1), [WHITE, LIGHT_GREY]),
        ("GRID",          (0,0), (-1,-1), 0.3, BORDER_GREY),
        ("VALIGN",        (0,0), (-1,-1), "MIDDLE"),
        ("TOPPADDING",    (0,0), (-1,-1), 4),
        ("BOTTOMPADDING", (0,0), (-1,-1), 4),
        ("LEFTPADDING",   (0,0), (-1,-1), 5),
    ]))
    story += [t, SP(6)]

    story.append(H3("Higher-Order Greeks"))
    ho_data = [
        ["Greek",   "Formula",                                          "Interpretation"],
        ["Vanna",   "-e^(-qT) n(d1) d2 / sigma",                       "dDelta/dVol — vol-spot sensitivity"],
        ["Volga",   "S e^(-qT) n(d1) sqrt(T) d1 d2 / sigma / 100",    "d²Price/dVol² (Vomma) — vol convexity"],
        ["Charm",   "-e^(-qT) [n(d1)(2(r-q)T - d2 sigma sqrt(T)) / (2T sigma sqrt(T)) + q N(+/-d1)] /365",
                                                                         "dDelta/dt — delta bleed"],
        ["Speed",   "-Gamma / S * (d1/(sigma sqrt(T)) + 1)",           "dGamma/dS — gamma of gamma"],
        ["Color",   "-e^(-qT) n(d1) / (2S T sigma sqrt(T)) * (1 + d1 d2) /365",
                                                                         "dGamma/dt — gamma decay"],
        ["Zomma",   "Gamma * (d1 d2 - 1) / sigma",                     "dGamma/dVol"],
        ["Ultima",  "-Vega/sigma * (d1 d2 (1-d1 d2) + d1² + d2²)",    "d³Price/dVol³"],
    ]
    t2 = Table(ho_data, colWidths=[18*mm, 70*mm, W-LEFT-RIGHT-92*mm])
    t2.setStyle(TableStyle([
        ("BACKGROUND",    (0,0), (-1,0), DARK_BLUE),
        ("TEXTCOLOR",     (0,0), (-1,0), WHITE),
        ("FONTNAME",      (0,0), (-1,0), "Helvetica-Bold"),
        ("FONTNAME",      (0,1), (0,-1), "Helvetica-Bold"),
        ("TEXTCOLOR",     (0,1), (0,-1), ACCENT),
        ("FONTNAME",      (1,1), (1,-1), "Courier"),
        ("FONTSIZE",      (0,0), (-1,-1), 8),
        ("LEADING",       (0,0), (-1,-1), 11),
        ("ROWBACKGROUNDS",(0,1), (-1,-1), [WHITE, LIGHT_GREY]),
        ("GRID",          (0,0), (-1,-1), 0.3, BORDER_GREY),
        ("VALIGN",        (0,0), (-1,-1), "MIDDLE"),
        ("TOPPADDING",    (0,0), (-1,-1), 3),
        ("BOTTOMPADDING", (0,0), (-1,-1), 3),
        ("LEFTPADDING",   (0,0), (-1,-1), 5),
    ]))
    story += [t2, SP(8)]

    # ── 2.2 Black-76 ─────────────────────────────────────
    story += [H2("2.2 Black-76 (Futures & Forwards)"), SP(2)]
    story.append(P(
        "Black-76 extends BSM to options on futures/forwards. It is the market standard for "
        "pricing interest rate caps, floors, and European swaptions. The forward price <i>F</i> "
        "replaces the spot, eliminating the dividend yield."
    ))
    story.append(F("C = e^(-rT) [F N(d1) - K N(d2)]"))
    story.append(F("d1 = [ln(F/K) + sigma^2 T/2] / (sigma sqrt(T));   d2 = d1 - sigma sqrt(T)"))
    story.append(F("Delta = e^(-rT) N(d1)     [for call on futures]"))
    story.append(N("Note: For caps/floors, each caplet uses the forward LIBOR rate as F, discounted by the zero-coupon price."))
    story += [SP(6)]

    # ── 2.3 GK ───────────────────────────────────────────
    story += [H2("2.3 Garman-Kohlhagen (FX Options)"), SP(2)]
    story.append(P(
        "The Garman-Kohlhagen (1983) model adapts BSM to currency options. "
        "The foreign interest rate <i>r_f</i> plays the role of the dividend yield. "
        "Premium can be quoted in four conventions: domestic pips, % of domestic notional, "
        "% of foreign notional, or premium-adjusted delta."
    ))
    story.append(F("C = S e^(-r_f T) N(d1) - K e^(-r_d T) N(d2)"))
    story.append(F("d1 = [ln(S/K) + (r_d - r_f + sigma^2/2) T] / (sigma sqrt(T))"))
    story.append(H3("Delta Conventions"))
    dc = [
        ["Convention",          "Formula"],
        ["Spot delta",          "phi * e^(-r_f T) * N(phi * d1)"],
        ["Forward delta",       "phi * N(phi * d1)"],
        ["Premium-adj. delta",  "Delta_spot - Premium / S"],
    ]
    t3 = Table(dc, colWidths=[50*mm, W-LEFT-RIGHT-54*mm])
    t3.setStyle(TableStyle([
        ("BACKGROUND", (0,0), (-1,0), MID_BLUE), ("TEXTCOLOR",(0,0),(-1,0),WHITE),
        ("FONTNAME",(0,0),(-1,0),"Helvetica-Bold"), ("FONTNAME",(1,1),(-1,-1),"Courier"),
        ("FONTSIZE",(0,0),(-1,-1),9), ("GRID",(0,0),(-1,-1),0.3,BORDER_GREY),
        ("ROWBACKGROUNDS",(0,1),(-1,-1),[WHITE,LIGHT_GREY]),
        ("TOPPADDING",(0,0),(-1,-1),4), ("BOTTOMPADDING",(0,0),(-1,-1),4),
        ("LEFTPADDING",(0,0),(-1,-1),6),
    ]))
    story += [t3, SP(6)]

    # ── 2.4 Bachelier ────────────────────────────────────
    story += [H2("2.4 Bachelier (Normal Model)"), SP(2)]
    story.append(P(
        "The Bachelier (normal) model assumes arithmetic Brownian motion rather than geometric. "
        "This makes it suitable for near-zero or negative rates (e.g., EUR rates in 2016-2022), "
        "and for pricing options on spreads."
    ))
    story.append(F("dF = sigma_n dW     (absolute, not relative volatility)"))
    story.append(F("C = e^(-rT) [(F-K) N(d) + sigma_n sqrt(T) n(d)]"))
    story.append(F("d = (F - K) / (sigma_n sqrt(T))"))
    story += [SP(6)]

    # ── 2.5 Binomial ─────────────────────────────────────
    story += [H2("2.5 Binomial Trees"), SP(2)]
    story.append(P(
        "Lattice methods discretise the price process into up/down moves and price "
        "derivatives by backward induction. They naturally handle early exercise (American) "
        "and discrete barriers."
    ))
    story.append(H3("Cox-Ross-Rubinstein (CRR)"))
    story.append(F("u = e^(sigma sqrt(dt));   d = 1/u;   p = (e^((r-q)dt) - d) / (u - d)"))
    story.append(H3("Leisen-Reimer (LR)"))
    story.append(P(
        "LR improves convergence by applying the Peizer-Pratt inversion to match "
        "the risk-neutral probabilities to the normal CDF. For a given N, accuracy "
        "is O(1/N²) vs O(1/N) for CRR."
    ))
    story.append(F("p = h(d2, N);   u = e^((r-q)dt) * h(d1,N) / h(d2,N)"))
    story.append(H3("Trinomial Tree"))
    story.append(P(
        "The trinomial tree has three branches per node (up, middle, down) and offers "
        "better convergence for barrier options where the barrier falls between nodes."
    ))
    story.append(F("dx = sigma sqrt(3 dt);   pu, pm, pd = quadratic functions of (r,q,sigma,dt)"))
    story += [SP(6)]

    # ── 2.6 Monte Carlo ──────────────────────────────────
    story += [H2("2.6 Monte Carlo Engine"), SP(2)]
    story.append(P(
        "Monte Carlo simulation generates thousands of price paths to estimate expected "
        "discounted payoffs. The implementation includes variance reduction techniques "
        "for efficiency."
    ))
    story.append(H3("GBM Path Generation"))
    story.append(F("S(t+dt) = S(t) exp[(r - q - sigma^2/2) dt  +  sigma sqrt(dt) Z]"))
    story.append(F("Z ~ N(0,1),  antithetic variates: Z and -Z paired"))
    story.append(H3("Variance Reduction Methods"))
    vr = [
        ["Method",              "Description",                                                     "Typical Speedup"],
        ["Antithetic Variates", "Use Z and -Z pairs — halves sampling variance",                  "~35-50%"],
        ["Moment Matching",     "Rescale Z so that sample mean=0, variance=1 exactly",            "~20-30%"],
        ["Control Variate",     "Use geometric average (known analytically) as control for Asian","~60-80%"],
        ["Quasi-MC (Sobol)",    "Use low-discrepancy sequences instead of pseudo-random",         "~70-90%"],
    ]
    t4 = Table(vr, colWidths=[38*mm, 90*mm, 30*mm])
    t4.setStyle(TableStyle([
        ("BACKGROUND",(0,0),(-1,0),DARK_BLUE), ("TEXTCOLOR",(0,0),(-1,0),WHITE),
        ("FONTNAME",(0,0),(-1,0),"Helvetica-Bold"), ("FONTNAME",(0,1),(0,-1),"Helvetica-Bold"),
        ("TEXTCOLOR",(0,1),(0,-1),ACCENT),
        ("FONTSIZE",(0,0),(-1,-1),8.5), ("LEADING",(0,0),(-1,-1),12),
        ("ROWBACKGROUNDS",(0,1),(-1,-1),[WHITE,LIGHT_GREY]),
        ("GRID",(0,0),(-1,-1),0.3,BORDER_GREY),
        ("TOPPADDING",(0,0),(-1,-1),4), ("BOTTOMPADDING",(0,0),(-1,-1),4),
        ("LEFTPADDING",(0,0),(-1,-1),5),
    ]))
    story += [t4, SP(6)]

    story.append(H3("Longstaff-Schwartz LSM (American / Bermudan)"))
    story.append(P(
        "LSM (2001) estimates the continuation value at each exercise date by regressing "
        "discounted future payoffs on basis functions of the current stock price, "
        "allowing optimal early exercise decisions."
    ))
    story.append(F("V(S_i, t) = E[disc * V(S_{i+1}, t+dt) | S_i]  ~  beta_0 + beta_1 S + beta_2 S^2 + ..."))
    story.append(P(
        "At each step moving backwards, the holder exercises if the intrinsic value exceeds "
        "the estimated continuation value. Basis functions are Laguerre polynomials "
        "or simple monomials (degree 3 by default)."
    ))
    story += [SP(6)]

    # ── 2.7 Heston ───────────────────────────────────────
    story += [H2("2.7 Heston Stochastic Volatility Model"), SP(2)]
    story.append(P(
        "Heston (1993) is the industry-standard stochastic volatility model. It captures "
        "the volatility smile by allowing variance to follow a mean-reverting CIR process "
        "correlated with the spot."
    ))
    story.append(F("dS = (r-q) S dt + sqrt(v) S dW_S"))
    story.append(F("dv = kappa (theta - v) dt + xi sqrt(v) dW_v"))
    story.append(F("dW_S dW_v = rho dt"))
    story.append(H3("Parameters"))
    hp = [
        ["Parameter", "Symbol", "Meaning"],
        ["Initial variance",       "v0",    "Starting level of instantaneous variance"],
        ["Mean-reversion speed",   "kappa", "Rate at which v reverts to theta"],
        ["Long-run variance",      "theta", "Equilibrium level of variance (theta = sigma_LR^2)"],
        ["Vol of vol",             "xi",    "Volatility of the variance process"],
        ["Correlation",            "rho",   "Spot-vol correlation (typically negative: -0.3 to -0.8)"],
        ["Feller condition",       "",      "2*kappa*theta > xi^2  (ensures v > 0)"],
    ]
    t5 = Table(hp, colWidths=[50*mm, 22*mm, W-LEFT-RIGHT-76*mm])
    t5.setStyle(TableStyle([
        ("BACKGROUND",(0,0),(-1,0),MID_BLUE),("TEXTCOLOR",(0,0),(-1,0),WHITE),
        ("FONTNAME",(0,0),(-1,0),"Helvetica-Bold"),("FONTNAME",(0,1),(0,-1),"Helvetica-Bold"),
        ("FONTNAME",(1,1),(1,-1),"Courier"),("TEXTCOLOR",(1,1),(1,-1),ACCENT),
        ("FONTSIZE",(0,0),(-1,-1),9),("LEADING",(0,0),(-1,-1),13),
        ("ROWBACKGROUNDS",(0,1),(-1,-1),[WHITE,LIGHT_GREY]),
        ("GRID",(0,0),(-1,-1),0.3,BORDER_GREY),
        ("TOPPADDING",(0,0),(-1,-1),4),("BOTTOMPADDING",(0,0),(-1,-1),4),
        ("LEFTPADDING",(0,0),(-1,-1),6),
    ]))
    story += [t5, SP(4)]
    story.append(H3("Semi-Analytical Pricing (Gil-Pelaez)"))
    story.append(F("C = S e^(-qT) P1 - K e^(-rT) P2"))
    story.append(F("P_j = 1/2 + (1/pi) int_0^inf Re[e^(-i phi ln K) phi_j(phi) / (i phi)] dphi"))
    story.append(F("phi(u) = exp[i u (ln S + (r-q)T) + (kappa theta / xi^2)(D-alpha)T - (v0/xi^2)G]"))
    story.append(N("Numerically integrated via scipy.integrate.quad with 500 integration points."))
    story += [SP(6)]

    # ── 2.8 SABR ─────────────────────────────────────────
    story += [H2("2.8 SABR Model"), SP(2)]
    story.append(P(
        "SABR (Hagan et al. 2002) is the market-standard model for interest rate volatility "
        "surfaces. It provides a closed-form approximation for implied volatility as a function "
        "of strike, making calibration highly efficient."
    ))
    story.append(F("dF = alpha F^beta dW_F"))
    story.append(F("dalpha = nu alpha dW_alpha,   dW_F dW_alpha = rho dt"))
    story.append(H3("Implied Volatility Approximation (ATM)"))
    story.append(F("sigma_ATM ~ alpha / F^(1-beta) * [1 + ((1-beta)^2/24 * alpha^2/F^(2-2beta) + rho*beta*nu*alpha/(4 F^(1-beta)) + (2-3rho^2) nu^2/24) T]"))
    story.append(N("For away-from-the-money strikes, the full formula includes a z/chi(z) correction term."))
    sp = [
        ["Parameter","Role"],
        ["alpha", "Initial vol level (ATM vol proxy when beta=1)"],
        ["beta",  "CEV exponent: 0=Normal, 0.5=CIR-like, 1=Log-normal"],
        ["rho",   "Correlation — controls skew (negative = put skew)"],
        ["nu",    "Vol of vol — controls smile curvature"],
    ]
    ts = Table(sp, colWidths=[20*mm, W-LEFT-RIGHT-24*mm])
    ts.setStyle(TableStyle([
        ("BACKGROUND",(0,0),(-1,0),MID_BLUE),("TEXTCOLOR",(0,0),(-1,0),WHITE),
        ("FONTNAME",(0,0),(-1,0),"Helvetica-Bold"),("FONTNAME",(0,1),(0,-1),"Courier"),
        ("TEXTCOLOR",(0,1),(0,-1),ACCENT),
        ("FONTSIZE",(0,0),(-1,-1),9),("GRID",(0,0),(-1,-1),0.3,BORDER_GREY),
        ("ROWBACKGROUNDS",(0,1),(-1,-1),[WHITE,LIGHT_GREY]),
        ("TOPPADDING",(0,0),(-1,-1),4),("BOTTOMPADDING",(0,0),(-1,-1),4),
        ("LEFTPADDING",(0,0),(-1,-1),6),
    ]))
    story += [ts, SP(6)]

    story += [H2("2.9 Implied Volatility Solvers"), SP(2)]
    story.append(P(
        "Implied volatility is extracted from market prices by inverting the pricing formula. "
        "The engine uses Newton-Raphson with a Vega-based update step, falling back to Brent's "
        "method if convergence fails."
    ))
    story.append(F("sigma_{n+1} = sigma_n - (C(sigma_n) - C_market) / Vega(sigma_n)"))
    story.append(F("Fallback: Brent bisection on [sigma_lo, sigma_hi] with tol=1e-8"))
    story.append(N("Initial guess uses the Brenner-Subrahmanyam approximation: sigma ~ sqrt(2 |ln(S/K) + 2rT| / T)."))
    story.append(P("The <b>SVI (Stochastic Volatility Inspired)</b> parameterisation fits the full vol smile slice:"))
    story.append(F("w(k) = a + b [rho (k-m) + sqrt((k-m)^2 + sigma^2)],   k = ln(K/F),  w = sigma_imp^2 T"))

    return story


def build_instruments():
    story = [PageBreak(), H1("3–9. Instrument Pricing"), HR()]

    # ── Vanilla ──────────────────────────────────────────
    story += [H2("3. Vanilla Options"), SP(2)]
    story.append(P("All vanilla options support 7 model backends:"))
    vm = [
        ["Model key", "Method",         "Notes"],
        ["bsm",       "Black-Scholes",  "Exact, with dividends (default)"],
        ["black76",   "Black-76",       "Spot treated as forward F"],
        ["gk",        "Garman-Kohlhagen","FX: q = r_f"],
        ["bachelier",  "Normal model",  "For near-zero rates"],
        ["binomial",  "CRR tree N=500", "Handles American & Bermudan"],
        ["binomial_lr","LR tree N=501", "Higher accuracy than CRR"],
        ["trinomial", "Trinomial N=300","Better convergence for barriers"],
        ["mc",        "Monte Carlo",    "With antithetic + moment matching"],
        ["lsm",       "LSM 50k paths",  "American/Bermudan only"],
    ]
    t = Table(vm, colWidths=[26*mm, 38*mm, W-LEFT-RIGHT-68*mm])
    t.setStyle(TableStyle([
        ("BACKGROUND",(0,0),(-1,0),MID_BLUE),("TEXTCOLOR",(0,0),(-1,0),WHITE),
        ("FONTNAME",(0,0),(-1,0),"Helvetica-Bold"),("FONTNAME",(0,1),(0,-1),"Courier"),
        ("TEXTCOLOR",(0,1),(0,-1),ACCENT),
        ("FONTSIZE",(0,0),(-1,-1),9),("LEADING",(0,0),(-1,-1),13),
        ("ROWBACKGROUNDS",(0,1),(-1,-1),[WHITE,LIGHT_GREY]),
        ("GRID",(0,0),(-1,-1),0.3,BORDER_GREY),
        ("TOPPADDING",(0,0),(-1,-1),4),("BOTTOMPADDING",(0,0),(-1,-1),4),
        ("LEFTPADDING",(0,0),(-1,-1),6),
    ]))
    story += [t, SP(8)]

    # ── Barrier ──────────────────────────────────────────
    story += [H2("4. Barrier Options"), SP(2)]
    story.append(P(
        "Barrier options are path-dependent: they are activated (knock-in) or deactivated "
        "(knock-out) when the underlying reaches a barrier level H."
    ))
    story.append(H3("Reiner-Rubinstein Closed Form"))
    story.append(F("Price = A - B + C - D + F  (exact combination depends on K vs H and in/out type)"))
    story.append(F("mu = (b - sigma^2/2) / sigma^2;   lambda = sqrt(mu^2 + 2r/sigma^2)"))
    story.append(F("x1 = ln(S/K)/(sigma sqrt(T)) + (1+mu) sigma sqrt(T)"))
    story.append(F("y1 = ln(H^2/(SK))/(sigma sqrt(T)) + (1+mu) sigma sqrt(T)"))
    story.append(H3("Barrier Types"))
    bt = [
        ["Type",       "Trigger",         "Effect"],
        ["Down-and-Out","S falls to H",   "Option dies, pays rebate"],
        ["Down-and-In", "S falls to H",   "Option activates"],
        ["Up-and-Out",  "S rises to H",   "Option dies, pays rebate"],
        ["Up-and-In",   "S rises to H",   "Option activates"],
        ["Double KO",   "S < L or S > U", "Option dies (Ikeda-Kunitomo series)"],
        ["Partial",     "Subperiod only", "Barrier active only during [t1, t2]"],
        ["Window",      "t_start to t_end","Time-windowed monitoring (MC)"],
    ]
    tb = Table(bt, colWidths=[28*mm, 34*mm, W-LEFT-RIGHT-66*mm])
    tb.setStyle(TableStyle([
        ("BACKGROUND",(0,0),(-1,0),DARK_BLUE),("TEXTCOLOR",(0,0),(-1,0),WHITE),
        ("FONTNAME",(0,0),(-1,0),"Helvetica-Bold"),("FONTNAME",(0,1),(0,-1),"Helvetica-Bold"),
        ("TEXTCOLOR",(0,1),(0,-1),ACCENT),
        ("FONTSIZE",(0,0),(-1,-1),9),("LEADING",(0,0),(-1,-1),13),
        ("ROWBACKGROUNDS",(0,1),(-1,-1),[WHITE,LIGHT_GREY]),
        ("GRID",(0,0),(-1,-1),0.3,BORDER_GREY),
        ("TOPPADDING",(0,0),(-1,-1),4),("BOTTOMPADDING",(0,0),(-1,-1),4),
        ("LEFTPADDING",(0,0),(-1,-1),6),
    ]))
    story += [tb, SP(2)]
    story.append(N("Knock-in + Knock-out = Vanilla (put-call parity for barriers)"))
    story += [SP(8)]

    # ── Asian ────────────────────────────────────────────
    story += [H2("5. Asian Options"), SP(2)]
    story.append(P(
        "Asian options pay based on an average of the underlying price over the life of "
        "the option, reducing volatility exposure and manipulation risk at expiry."
    ))
    story.append(H3("Geometric Average — Closed Form (Kemna-Vorst)"))
    story.append(P("The geometric average is log-normally distributed, enabling exact pricing via adjusted BSM:"))
    story.append(F("sigma_G = sigma / sqrt(3)  (continuous),  sigma_G = sigma sqrt((n+1)(2n+1)/(6n^2))  (discrete)"))
    story.append(F("b_G = (r-q-sigma^2/2)(n+1)/(2n) + sigma_G^2/2"))
    story.append(H3("Arithmetic Average — Monte Carlo with Control Variate"))
    story.append(F("Arith. payoff = max(A_arith - K, 0);   control = geom avg (known analytically)"))
    story.append(F("PV_corrected = PV_arith - beta * (PV_geom_sim - PV_geom_CF)"))
    story.append(F("beta = Cov(PV_arith, PV_geom) / Var(PV_geom)"))
    story.append(N("Averaging: Fixed strike (vs K) or Floating strike (vs S_T). Both supported."))
    story += [SP(8)]

    # ── Digital ──────────────────────────────────────────
    story += [H2("6. Digital Options"), SP(2)]
    dt_data = [
        ["Instrument",          "Payoff",                          "Method"],
        ["Cash-or-Nothing",     "cash * 1{S_T > K}",              "e^(-rT) N(d2) * cash"],
        ["Asset-or-Nothing",    "S_T * 1{S_T > K}",               "S e^(-qT) N(d1)"],
        ["Gap Option",          "(S_T - K2) * 1{S_T > K1}",       "BSM-style with two strikes"],
        ["One-Touch",           "cash if H ever touched",          "Reiner-Rubinstein rebate formula"],
        ["No-Touch",            "cash if H never touched",         "Bond - One-touch"],
        ["Double No-Touch",     "cash if L < S < U always",        "Monte Carlo simulation"],
        ["Supershare",          "S_T/K_lo * 1{K_lo < S_T < K_hi}","Difference of asset-or-nothings"],
    ]
    t = Table(dt_data, colWidths=[36*mm, 54*mm, W-LEFT-RIGHT-94*mm])
    t.setStyle(TableStyle([
        ("BACKGROUND",(0,0),(-1,0),MID_BLUE),("TEXTCOLOR",(0,0),(-1,0),WHITE),
        ("FONTNAME",(0,0),(-1,0),"Helvetica-Bold"),("FONTNAME",(1,1),(-1,-1),"Courier"),
        ("FONTSIZE",(0,0),(-1,-1),8.5),("LEADING",(0,0),(-1,-1),12),
        ("ROWBACKGROUNDS",(0,1),(-1,-1),[WHITE,LIGHT_GREY]),
        ("GRID",(0,0),(-1,-1),0.3,BORDER_GREY),
        ("TOPPADDING",(0,0),(-1,-1),4),("BOTTOMPADDING",(0,0),(-1,-1),4),
        ("LEFTPADDING",(0,0),(-1,-1),5),
    ]))
    story += [t, SP(8)]

    # ── Lookback ─────────────────────────────────────────
    story += [H2("7. Lookback Options (Goldman-Sosin-Gatto)"), SP(2)]
    story.append(P(
        "Lookback options pay based on the extremum of the underlying price over the option's life. "
        "They have no exercise risk — the holder always gets the best possible outcome. "
        "Exact closed-form exists for European-style."
    ))
    story.append(F("Floating Call: max(S_T - S_min, 0)  [pays S_T minus running minimum]"))
    story.append(F("Floating Put:  max(S_max - S_T, 0)  [pays running maximum minus S_T]"))
    story.append(F("Fixed Call:    max(S_max - K, 0)    [call on maximum]"))
    story.append(F("Fixed Put:     max(K - S_min, 0)    [put on minimum]"))
    story.append(H3("Floating Lookback Call (Continuous Monitoring)"))
    story.append(F("Price = S e^(-qT) N(a1) - M e^(-rT) N(a2) + S e^(-rT) (sigma^2/2b) * [(S/M)^(-2b/sigma^2) N(-a3) - e^(bT) N(-a1)]"))
    story.append(F("a1 = [ln(S/M) + (b + sigma^2/2) T] / (sigma sqrt(T));   M = min(S_t) observed so far"))
    story += [SP(8)]

    # ── Exotic ───────────────────────────────────────────
    story += [H2("8. Exotic Single-Asset Options"), SP(2)]

    ex_data = [
        ["Option",           "Reference",       "Key Formula / Method"],
        ["Simple Chooser",   "Rubinstein 1991", "C(S,K,T) + P(S, K*e^(-(r-q)(T-Tc)), Tc)"],
        ["Complex Chooser",  "Rubinstein 1991", "Bivariate normal, critical S* solves C(S*)=P(S*)"],
        ["Compound",         "Geske 1979",      "Bivariate normal on critical S*; option on option"],
        ["Forward-Start",    "—",               "At T_start, K := alpha * S(T_start); adjusted BSM"],
        ["Shout",            "—",               "LSM: shout when intrinsic > continuation value"],
        ["Power (symmetric)","—",               "BSM with S^n, adjusted drift and vol"],
        ["Power (asymmetric)","—",              "MC: payoff = S_T^n * max(S_T - K, 0)"],
        ["Cliquet/Ratchet",  "—",               "MC: sum of period returns R_i, capped and floored"],
        ["Reset",            "—",               "MC: K resets at T_reset if OTM"],
        ["Range Accrual",    "—",               "MC: coupon * fraction of days in [L, U]"],
    ]
    t = Table(ex_data, colWidths=[36*mm, 30*mm, W-LEFT-RIGHT-70*mm])
    t.setStyle(TableStyle([
        ("BACKGROUND",(0,0),(-1,0),DARK_BLUE),("TEXTCOLOR",(0,0),(-1,0),WHITE),
        ("FONTNAME",(0,0),(-1,0),"Helvetica-Bold"),("FONTNAME",(0,1),(0,-1),"Helvetica-Bold"),
        ("TEXTCOLOR",(0,1),(0,-1),ACCENT),
        ("FONTSIZE",(0,0),(-1,-1),8.5),("LEADING",(0,0),(-1,-1),12),
        ("ROWBACKGROUNDS",(0,1),(-1,-1),[WHITE,LIGHT_GREY]),
        ("GRID",(0,0),(-1,-1),0.3,BORDER_GREY),
        ("TOPPADDING",(0,0),(-1,-1),4),("BOTTOMPADDING",(0,0),(-1,-1),4),
        ("LEFTPADDING",(0,0),(-1,-1),5),
    ]))
    story += [t, SP(8)]

    # ── Multi-asset ──────────────────────────────────────
    story += [H2("9. Multi-Asset Options"), SP(2)]
    ma_data = [
        ["Option",           "Payoff / Method"],
        ["Exchange (Margrabe)","max(S1_T - S2_T, 0) — Margrabe (1978) bivariate BSM"],
        ["Spread (Kirk)",    "max(S1 - S2 - K, 0) — Kirk (1995) approximation"],
        ["Basket (MC)",      "max(sum(w_i S_i) - K, 0) — correlated GBM Monte Carlo"],
        ["Basket (moments)", "Levy (1992) moment-matched log-normal approximation"],
        ["Best-of (n=2)",    "max(S1, S2, K) — Stulz (1982) exact formula"],
        ["Best-of (n>2)",    "max(S1,...,Sn, cash) — Monte Carlo"],
        ["Worst-of",         "min(S1,...,Sn) — Monte Carlo"],
        ["Rainbow call",     "max(S_best - K, 0) — MC on best performer"],
        ["Quanto",           "Domestic payoff on foreign asset; GK with drift adj rho*sigma_S*sigma_FX"],
        ["Himalaya",         "Sum of best performers per period (removed each period) — MC"],
        ["Altiplano",        "Full coupon if all assets above barrier, else basket return — MC"],
    ]
    t = Table(ma_data, colWidths=[44*mm, W-LEFT-RIGHT-48*mm])
    t.setStyle(TableStyle([
        ("BACKGROUND",(0,0),(-1,0),MID_BLUE),("TEXTCOLOR",(0,0),(-1,0),WHITE),
        ("FONTNAME",(0,0),(-1,0),"Helvetica-Bold"),("FONTNAME",(0,1),(0,-1),"Helvetica-Bold"),
        ("TEXTCOLOR",(0,1),(0,-1),ACCENT),
        ("FONTSIZE",(0,0),(-1,-1),9),("LEADING",(0,0),(-1,-1),13),
        ("ROWBACKGROUNDS",(0,1),(-1,-1),[WHITE,LIGHT_GREY]),
        ("GRID",(0,0),(-1,-1),0.3,BORDER_GREY),
        ("TOPPADDING",(0,0),(-1,-1),4),("BOTTOMPADDING",(0,0),(-1,-1),4),
        ("LEFTPADDING",(0,0),(-1,-1),6),
    ]))
    story.append(t)
    story.append(H3("Correlated Multi-Asset GBM"))
    story.append(F("paths = Cholesky(Corr) @ Z,  Z ~ N(0, I_{n x steps})"))
    story.append(F("S_i(t+dt) = S_i(t) exp[(r - q_i - sigma_i^2/2) dt + sigma_i sqrt(dt) * paths_i]"))
    return story


def build_fixed_income():
    story = [PageBreak(), H1("10–12. Fixed Income & Credit"), HR()]

    story += [H2("10. Variance & Volatility Products"), SP(2)]
    story.append(P("Variance products allow direct trading of realised volatility, independent of direction."))
    vp_data = [
        ["Product",          "Payoff",                                "Fair Strike"],
        ["Variance Swap",    "N * (RV^2 - K_var)",                   "Model-free via log-contract replication"],
        ["Vol Swap",         "N * (RV - K_vol)",                     "Brockhaus-Long approx or MC"],
        ["Gamma Swap",       "N * integral (S_t/S_0) dV_t",          "= sigma^2 under GBM"],
        ["Corridor Var",     "N * sum_in_{[L,U]} r_i^2 * ann.",      "MC simulation"],
        ["Conditional Var",  "E[RV | in corridor]",                  "MC: corridor var / fraction time in"],
    ]
    t = Table(vp_data, colWidths=[36*mm, 60*mm, W-LEFT-RIGHT-100*mm])
    t.setStyle(TableStyle([
        ("BACKGROUND",(0,0),(-1,0),MID_BLUE),("TEXTCOLOR",(0,0),(-1,0),WHITE),
        ("FONTNAME",(0,0),(-1,0),"Helvetica-Bold"),("FONTNAME",(0,1),(0,-1),"Helvetica"),
        ("FONTSIZE",(0,0),(-1,-1),8.5),("LEADING",(0,0),(-1,-1),12),
        ("ROWBACKGROUNDS",(0,1),(-1,-1),[WHITE,LIGHT_GREY]),
        ("GRID",(0,0),(-1,-1),0.3,BORDER_GREY),
        ("TOPPADDING",(0,0),(-1,-1),4),("BOTTOMPADDING",(0,0),(-1,-1),4),
        ("LEFTPADDING",(0,0),(-1,-1),5),
    ]))
    story += [t, SP(4)]
    story.append(H3("Model-Free Variance Strike (Demeterfi et al. 1999)"))
    story.append(F("K_var = (2/T) [ln(F/S_0) - (F/S_0 - 1)] + (2/T) int_0^F (P(K)/K^2 * (1-ln(K/F))) dK"))
    story.append(F("                                            + (2/T) int_F^inf (C(K)/K^2 * (1-ln(K/F))) dK"))
    story += [SP(8)]

    story += [H2("11. Fixed Income Instruments"), SP(2)]
    story.append(H3("Bond Pricing"))
    story.append(F("P = sum_{i=1}^{n} CF_i * D(t_i),   D(t) = e^(-r(t) * t)  [continuous]"))
    story.append(H3("Risk Metrics"))
    fi_data = [
        ["Metric",           "Formula"],
        ["Macaulay Duration","D_mac = sum t_i * PV(CF_i) / P"],
        ["Modified Duration","D_mod = D_mac / (1 + y/freq)  [periodic compounding]"],
        ["Convexity",        "C = sum t_i^2 * PV(CF_i) / P"],
        ["DV01",             "DV01 = P * D_mod / 10000  (price change per 1bp)"],
        ["YTM",              "Flat yield y: P = sum CF_i e^(-y t_i)  (solved via Brent)"],
        ["Z-spread",         "Spread z added to curve: P = sum CF_i D(t_i) e^(-z t_i)"],
        ["Delta Price",      "dP/P ~ -D_mod * dy + 0.5 * C * (dy)^2  [Taylor expansion]"],
    ]
    tf = Table(fi_data, colWidths=[42*mm, W-LEFT-RIGHT-46*mm])
    tf.setStyle(TableStyle([
        ("BACKGROUND",(0,0),(-1,0),DARK_BLUE),("TEXTCOLOR",(0,0),(-1,0),WHITE),
        ("FONTNAME",(0,0),(-1,0),"Helvetica-Bold"),("FONTNAME",(0,1),(0,-1),"Helvetica-Bold"),
        ("TEXTCOLOR",(0,1),(0,-1),ACCENT),("FONTNAME",(1,1),(-1,-1),"Courier"),
        ("FONTSIZE",(0,0),(-1,-1),9),("LEADING",(0,0),(-1,-1),13),
        ("ROWBACKGROUNDS",(0,1),(-1,-1),[WHITE,LIGHT_GREY]),
        ("GRID",(0,0),(-1,-1),0.3,BORDER_GREY),
        ("TOPPADDING",(0,0),(-1,-1),4),("BOTTOMPADDING",(0,0),(-1,-1),4),
        ("LEFTPADDING",(0,0),(-1,-1),6),
    ]))
    story += [tf, SP(6)]

    story.append(H3("Interest Rate Swap (IRS)"))
    story.append(F("NPV = N * [PV_float - PV_fixed]"))
    story.append(F("PV_fixed = K * sum dt_i * D(T_i)  =  K * Annuity"))
    story.append(F("PV_float = D(T_0) - D(T_n)  [par FRN approximation]"))
    story.append(F("Fair rate K* = (D(T_0) - D(T_n)) / Annuity"))
    story.append(F("DV01 = N * Annuity / 10000"))
    story += [SP(4)]

    story.append(H3("Cap / Floor Pricing (Black-76 Caplets)"))
    story.append(F("Caplet_i = N * tau_i * D(T_i) * Black76(F_i, K, T_{i-1}, r, sigma)"))
    story.append(F("Cap = sum_{i=1}^{n} Caplet_i;   Floor = sum_{i=1}^{n} Floorlet_i"))
    story.append(F("Collar = Cap - Floor  (costless when strike of cap and floor chosen appropriately)"))
    story += [SP(4)]

    story.append(H3("European Swaption (Black-76)"))
    story.append(F("Swaption = N * Annuity * Black76(S_0, K, T_opt, r, sigma, call/put)"))
    story.append(F("Annuity = sum_{i=1}^{m} dt_i * D(T_opt + i/freq)"))
    story.append(F("S_0 = (D(T_opt) - D(T_opt + T_swap)) / Annuity   [forward swap rate]"))
    story += [SP(8)]

    story += [H2("12. Credit Instruments"), SP(2)]
    story.append(H3("CDS Pricing (Constant Hazard Rate)"))
    story.append(F("Survival probability: Q(tau > T) = e^(-lambda * T)"))
    story.append(F("Hazard rate approx:   lambda ~ spread / (1 - R)"))
    story.append(F("Premium leg PV  = N * spread * sum dt_i * D(T_i) * Q(T_i)   [risky annuity]"))
    story.append(F("Protection leg  = N * (1-R) * lambda * integral e^(-(r+lambda)t) dt"))
    story.append(F("Fair spread     = Protection_PV / (N * Risky_Annuity)"))
    story.append(F("Risky DV01      = N * Risky_Annuity / 10000"))
    story += [SP(4)]

    story.append(H3("CDO Tranche (Large Homogeneous Pool / Gaussian Copula)"))
    story.append(F("Cond. default prob: p(x) = N[(N^-1(p) - sqrt(rho) x) / sqrt(1-rho)]"))
    story.append(F("E[Tranche loss | x] = E[max(L-K1,0)] - E[max(L-K2,0)] via normal approx"))
    story.append(F("E[Tranche loss] = integral p(x) phi(x) dx  (Gauss-Hermite quadrature)"))
    story += [SP(4)]

    story.append(H3("CVA / DVA"))
    story.append(F("CVA = (1-R_cpty) * integral_0^T EPE(t) * lambda_cpty * e^(-(r+lambda)t) dt"))
    story.append(F("DVA = (1-R_own)  * integral_0^T ENE(t) * lambda_own  * e^(-(r+lambda)t) dt"))
    story.append(N("EPE = Expected Positive Exposure. DVA is the bilateral counterpart to CVA."))
    return story


def build_risk():
    story = [PageBreak(), H1("13–15. FX, Risk Metrics & CLI"), HR()]

    story += [H2("13. FX Instruments"), SP(2)]
    story.append(H3("FX Forward"))
    story.append(F("F = S * e^((r_d - r_f) * T)"))
    story.append(F("Swap points = F - S  (quoted in pips = 4th decimal place for major pairs)"))
    story += [SP(4)]
    story.append(H3("FX Option — Garman-Kohlhagen (q = r_f)"))
    story.append(P("Four premium conventions are computed simultaneously:"))
    fx_dc = [
        ["Convention",              "Formula"],
        ["Domestic pips",           "GK price (per 1 unit of foreign)"],
        ["Premium %domestic",       "GK price / S"],
        ["Premium %foreign",        "GK price / (K e^(-r_d T))"],
        ["Spot delta",              "phi * e^(-r_f T) * N(phi d1)"],
        ["Forward delta",           "phi * N(phi d1)"],
        ["Premium-adjusted delta",  "Delta_spot - Premium / S"],
    ]
    tf = Table(fx_dc, colWidths=[50*mm, W-LEFT-RIGHT-54*mm])
    tf.setStyle(TableStyle([
        ("BACKGROUND",(0,0),(-1,0),MID_BLUE),("TEXTCOLOR",(0,0),(-1,0),WHITE),
        ("FONTNAME",(0,0),(-1,0),"Helvetica-Bold"),("FONTNAME",(1,1),(-1,-1),"Courier"),
        ("FONTSIZE",(0,0),(-1,-1),9),("LEADING",(0,0),(-1,-1),13),
        ("ROWBACKGROUNDS",(0,1),(-1,-1),[WHITE,LIGHT_GREY]),
        ("GRID",(0,0),(-1,-1),0.3,BORDER_GREY),
        ("TOPPADDING",(0,0),(-1,-1),4),("BOTTOMPADDING",(0,0),(-1,-1),4),
        ("LEFTPADDING",(0,0),(-1,-1),6),
    ]))
    story += [tf, SP(4)]
    story.append(H3("Vol Surface Conventions"))
    story.append(F("sigma_call(25D) = ATM + Strangle + RR/2"))
    story.append(F("sigma_put(25D)  = ATM + Strangle - RR/2"))
    story.append(N("RR = Risk Reversal = sigma_call - sigma_put. Strangle = 0.5*(sigma_call+sigma_put) - ATM."))
    story += [SP(8)]

    story += [H2("14. Market Risk Metrics"), SP(2)]
    story.append(H3("14.1 Value at Risk (VaR)"))
    var_data = [
        ["Method",           "Formula",                                        "When to Use"],
        ["Historical",       "Percentile of sorted historical P&L distribution","Captures fat tails; no model assumption"],
        ["Parametric Normal","VaR = -(mu T + z_a sigma sqrt(T))",              "Fast; assumes normality"],
        ["Parametric t-dist","VaR using Student-t quantile with fitted df",    "Better fat-tail capture"],
        ["Monte Carlo",      "Simulate P&L; percentile of simulated dist.",    "For non-linear portfolios"],
        ["EVT / POT",        "Fit GPD to tail exceedances; extrapolate",       "For high-confidence (99%+) VaR"],
    ]
    tv = Table(var_data, colWidths=[34*mm, 70*mm, W-LEFT-RIGHT-108*mm])
    tv.setStyle(TableStyle([
        ("BACKGROUND",(0,0),(-1,0),DARK_BLUE),("TEXTCOLOR",(0,0),(-1,0),WHITE),
        ("FONTNAME",(0,0),(-1,0),"Helvetica-Bold"),("FONTNAME",(0,1),(0,-1),"Helvetica-Bold"),
        ("TEXTCOLOR",(0,1),(0,-1),ACCENT),
        ("FONTSIZE",(0,0),(-1,-1),8.5),("LEADING",(0,0),(-1,-1),12),
        ("ROWBACKGROUNDS",(0,1),(-1,-1),[WHITE,LIGHT_GREY]),
        ("GRID",(0,0),(-1,-1),0.3,BORDER_GREY),
        ("TOPPADDING",(0,0),(-1,-1),4),("BOTTOMPADDING",(0,0),(-1,-1),4),
        ("LEFTPADDING",(0,0),(-1,-1),5),
    ]))
    story += [tv, SP(4)]

    story.append(F("CVaR (ES) = E[Loss | Loss > VaR]  =  - mu*T + sigma*sqrt(T) * n(z_a)/(1-alpha)"))
    story.append(F("Component VaR_i = w_i * (Cov_i . port_vol) * z_a * N  [sum = total VaR]"))
    story.append(F("Horizon scaling: VaR(h days) = VaR(1 day) * sqrt(h)  [square-root-of-time rule]"))
    story += [SP(4)]

    story.append(H3("EVT — Peaks Over Threshold (GPD)"))
    story.append(F("Threshold u = percentile(losses, (1-p_thr) * 100)"))
    story.append(F("Fit Generalised Pareto: F(y) = 1 - (1 + xi y / beta)^(-1/xi)  to exceedances y = L - u"))
    story.append(F("VaR = u + beta/xi * ((alpha * N / N_u)^(-xi) - 1)"))
    story.append(F("CVaR = (VaR + beta - xi * u) / (1 - xi)  [requires xi < 1]"))
    story += [SP(4)]

    story.append(H3("Backtesting"))
    bt_data = [
        ["Test",              "H0",                          "Statistic"],
        ["Kupiec POF",        "Exception rate = 1 - alpha",  "LR = -2 ln[L_const / L_hat] ~ chi2(1)"],
        ["Christoffersen",    "Exceptions are independent",  "LR_ind ~ chi2(1) based on pi01, pi11"],
        ["Basel Traffic Light","Model acceptance",           "Green: exc < expected; Red: >3*expected"],
    ]
    tb = Table(bt_data, colWidths=[40*mm, 60*mm, W-LEFT-RIGHT-104*mm])
    tb.setStyle(TableStyle([
        ("BACKGROUND",(0,0),(-1,0),MID_BLUE),("TEXTCOLOR",(0,0),(-1,0),WHITE),
        ("FONTNAME",(0,0),(-1,0),"Helvetica-Bold"),("FONTNAME",(0,1),(0,-1),"Helvetica-Bold"),
        ("TEXTCOLOR",(0,1),(0,-1),ACCENT),
        ("FONTSIZE",(0,0),(-1,-1),9),("LEADING",(0,0),(-1,-1),13),
        ("ROWBACKGROUNDS",(0,1),(-1,-1),[WHITE,LIGHT_GREY]),
        ("GRID",(0,0),(-1,-1),0.3,BORDER_GREY),
        ("TOPPADDING",(0,0),(-1,-1),4),("BOTTOMPADDING",(0,0),(-1,-1),4),
        ("LEFTPADDING",(0,0),(-1,-1),5),
    ]))
    story += [tb, SP(8)]

    story += [H2("14.2 Stress Testing"), SP(2)]
    story.append(P("14 calibrated historical scenarios with spot, volatility, and rate shocks:"))
    sc_data = [
        ["Scenario",                    "Spot Shock", "Vol Shock", "Rate Shock"],
        ["Black Monday (1987)",         "-22.5%",     "+60%",      "+0.2%"],
        ["Gulf War (1990)",             "-15.0%",     "+30%",      "-0.3%"],
        ["LTCM / Russia (1998)",        "-20.0%",     "+50%",      "-1.0%"],
        ["Dot-com bust (2000-2002)",    "-49.0%",     "+35%",      "-2.5%"],
        ["9/11 (2001)",                 "-7.0%",      "+30%",      "-0.5%"],
        ["Lehman collapse (2008)",      "-35.0%",     "+80%",      "-2.0%"],
        ["EUR Sovereign (2010-12)",     "-22.0%",     "+40%",      "+3.0%"],
        ["Taper Tantrum (2013)",        "-6.0%",      "+25%",      "+1.0%"],
        ["China Devaluation (2015)",    "-11.0%",     "+35%",      "-0.5%"],
        ["COVID crash (2020-03)",       "-35.0%",     "+80%",      "-1.5%"],
        ["Meme squeeze (2021-01)",      "+50.0%",     "+60%",      "0%"],
        ["Rate hike shock (2022)",      "-18.0%",     "+30%",      "+4.0%"],
        ["Bull run (generic)",          "+30.0%",     "-25%",      "+0.5%"],
        ["Flash crash (generic)",       "-10.0%",     "+70%",      "0%"],
    ]
    ts = Table(sc_data, colWidths=[64*mm, 26*mm, 24*mm, 28*mm])
    ts.setStyle(TableStyle([
        ("BACKGROUND",(0,0),(-1,0),DARK_BLUE),("TEXTCOLOR",(0,0),(-1,0),WHITE),
        ("FONTNAME",(0,0),(-1,0),"Helvetica-Bold"),("FONTNAME",(0,1),(0,-1),"Helvetica"),
        ("FONTSIZE",(0,0),(-1,-1),8.5),("LEADING",(0,0),(-1,-1),12),
        ("ROWBACKGROUNDS",(0,1),(-1,-1),[WHITE,LIGHT_GREY]),
        ("GRID",(0,0),(-1,-1),0.3,BORDER_GREY),
        ("ALIGN",(1,0),(-1,-1),"CENTER"),
        ("TOPPADDING",(0,0),(-1,-1),3),("BOTTOMPADDING",(0,0),(-1,-1),3),
        ("LEFTPADDING",(0,0),(-1,-1),5),
    ]))
    story += [ts, SP(8)]

    story += [H2("14.3 P&L Attribution"), SP(2)]
    story.append(P("Decomposes realised P&L into contributions from each risk factor:"))
    story.append(F("PnL = Delta * dS  +  0.5 * Gamma * dS^2  +  Vega * dSigma * 100"))
    story.append(F("    + Theta * dt  +  Rho * dr * 100  +  Vanna * dS * dSigma  +  0.5 * Volga * dSigma^2"))
    story.append(N("Unexplained residual = actual P&L minus sum of above terms (higher-order cross effects)."))
    story += [SP(8)]

    # ── CLI ──────────────────────────────────────────────
    story += [H2("15. CLI Usage Guide"), SP(2), HR()]
    story.append(P("All functionality is accessible from the command line via <b>main.py</b>:"))
    story.append(C("python3 main.py <command> [--param value ...]"))
    story += [SP(6)]

    cmds = [
        ("Vanilla Options",),
        ("option", "--spot 100 --strike 105 --expiry 0.5 --vol 0.25 --type call --model bsm"),
        ("option", "--spot 100 --strike 100 --expiry 1.0 --vol 0.20 --exercise american --model lsm"),
        ("option", "--spot 100 --strike 100 --expiry 0.5 --vol 0.20 --exercise bermudan --model binomial"),
        ("Barrier Options",),
        ("barrier","--spot 100 --strike 100 --barrier 85 --expiry 0.5 --barrier_type down-out"),
        ("barrier","--spot 100 --strike 100 --barrier 90 --expiry 0.5 --barrier_type down-in --mc"),
        ("barrier","--spot 100 --strike 100 --lower 80 --upper 120 --expiry 1.0 --double"),
        ("Asian Options",),
        ("asian",  "--spot 100 --strike 100 --expiry 0.5 --vol 0.20 --fixings 12"),
        ("asian",  "--spot 100 --strike 100 --expiry 0.5 --geometric --continuous"),
        ("asian",  "--averaging floating --expiry 0.5 --vol 0.25"),
        ("Digital Options",),
        ("digital","--digital_type cash_or_nothing --strike 100 --cash 1.0"),
        ("digital","--digital_type one_touch --barrier 110 --direction up --payment expiry"),
        ("digital","--digital_type double_no_touch --lower 90 --upper 110"),
        ("Lookback Options",),
        ("lookback","--lb_style floating --type call"),
        ("lookback","--lb_style fixed --strike 100"),
        ("lookback","--lb_style floating --mc"),
        ("Variance Swaps",),
        ("variance_swap","--spot 100 --vol 0.20 --expiry 1.0 --notional 1000000"),
        ("variance_swap","--spot 100 --vol 0.20 --expiry 1.0 --lower 90 --upper 110"),
        ("Fixed Income",),
        ("bond",   "--face 100 --coupon 0.05 --expiry 10 --rate 0.04 --freq 2"),
        ("irs",    "--notional 10000000 --fixed_rate 0.04 --expiry 5 --rate 0.035"),
        ("cap_floor","--notional 10000000 --strike 0.05 --expiry 5 --vol 0.20"),
        ("swaption","--notional 10000000 --strike 0.04 --t_option 1.0 --t_swap 5.0 --vol 0.20"),
        ("cds",    "--notional 10000000 --spread 0.01 --expiry 5 --recovery 0.40"),
        ("FX Instruments",),
        ("fx_forward","--spot 1.08 --r_d 0.04 --r_f 0.02 --expiry 0.25"),
        ("fx_option", "--spot 1.08 --strike 1.09 --r_d 0.04 --r_f 0.02 --vol 0.08"),
        ("fx_barrier","--spot 1.08 --strike 1.09 --barrier 1.05 --barrier_type down-out"),
        ("Risk Metrics",),
        ("var",    "--value 5000000 --confidence 0.99 --horizon 10"),
        ("var",    "--value 1000000 --confidence 0.95 --returns returns.csv"),
        ("stress", "--spot 100 --strike 100 --expiry 0.5 --vol 0.20"),
        ("greeks_ladder","--spot 100 --strike 100 --expiry 0.5 --vol 0.20"),
        ("pnl_explain","--spot 100 --strike 100 --expiry 0.5 --ds 3.0 --dvol 0.02 --dt 1"),
        ("Stochastic Models",),
        ("implied_vol","--market_price 5.0 --spot 100 --strike 100 --expiry 0.5"),
        ("heston", "--spot 100 --strike 100 --expiry 0.5 --v0 0.04 --kappa 2.0 --xi 0.3 --rho_heston -0.7"),
        ("sabr",   "--spot 100 --strike 105 --expiry 0.5 --alpha 0.15 --beta 0.5 --nu 0.4 --rho_sabr -0.3"),
    ]

    for item in cmds:
        if len(item) == 1:
            story += [SP(4), Paragraph(item[0], styles["h3"])]
        else:
            cmd, params = item
            story.append(Paragraph(
                f'<font name="Courier" color="#1A4A7A" size="8">python3 main.py {cmd}</font>'
                f'<font name="Courier" color="#2B5C8A" size="8"> {params}</font>',
                ParagraphStyle("cli", fontName="Courier", fontSize=8, leading=12,
                                backColor=LIGHT_GREY, leftIndent=6, spaceAfter=2,
                                borderPadding=4)
            ))

    story += [SP(8), HR(), SP(6)]
    story.append(H2("Dependencies"))
    deps = [
        ["Package", "Version", "Usage"],
        ["numpy",   ">=1.24",  "Array operations, random number generation"],
        ["scipy",   ">=1.11",  "Optimization, integration, statistics, distributions"],
        ["reportlab",">=4.0",  "PDF document generation (documentation only)"],
    ]
    td = Table(deps, colWidths=[30*mm, 22*mm, W-LEFT-RIGHT-56*mm])
    td.setStyle(TableStyle([
        ("BACKGROUND",(0,0),(-1,0),MID_BLUE),("TEXTCOLOR",(0,0),(-1,0),WHITE),
        ("FONTNAME",(0,0),(-1,0),"Helvetica-Bold"),("FONTNAME",(1,1),(-1,-1),"Courier"),
        ("FONTSIZE",(0,0),(-1,-1),9),("LEADING",(0,0),(-1,-1),13),
        ("ROWBACKGROUNDS",(0,1),(-1,-1),[WHITE,LIGHT_GREY]),
        ("GRID",(0,0),(-1,-1),0.3,BORDER_GREY),
        ("TOPPADDING",(0,0),(-1,-1),4),("BOTTOMPADDING",(0,0),(-1,-1),4),
        ("LEFTPADDING",(0,0),(-1,-1),6),
    ]))
    story.append(td)
    story += [SP(4)]
    story.append(C("pip3 install numpy scipy"))
    story += [SP(6)]
    story.append(H2("References"))
    refs = [
        "Black, F. &amp; Scholes, M. (1973). The Pricing of Options and Corporate Liabilities. <i>Journal of Political Economy</i>, 81(3), 637-654.",
        "Black, F. (1976). The Pricing of Commodity Contracts. <i>Journal of Financial Economics</i>, 3, 167-179.",
        "Garman, M.B. &amp; Kohlhagen, S.W. (1983). Foreign Currency Option Values. <i>Journal of International Money and Finance</i>, 2, 231-237.",
        "Heston, S. (1993). A Closed-Form Solution for Options with Stochastic Volatility. <i>Review of Financial Studies</i>, 6(2), 327-343.",
        "Hagan, P. et al. (2002). Managing Smile Risk. <i>Wilmott Magazine</i>, 84-108. [SABR model]",
        "Cox, J., Ross, S. &amp; Rubinstein, M. (1979). Option Pricing: A Simplified Approach. <i>Journal of Financial Economics</i>, 7, 229-263. [CRR]",
        "Longstaff, F. &amp; Schwartz, E. (2001). Valuing American Options by Simulation. <i>Review of Financial Studies</i>, 14(1), 113-147. [LSM]",
        "Margrabe, W. (1978). The Value of an Option to Exchange One Asset for Another. <i>Journal of Finance</i>, 33(1), 177-186.",
        "Reiner, E. &amp; Rubinstein, M. (1991). Breaking Down the Barriers. <i>Risk Magazine</i>, 4(8), 28-35.",
        "Kemna, A.G.Z. &amp; Vorst, A.C.F. (1990). A Pricing Method for Options Based on Average Asset Values. <i>Journal of Banking and Finance</i>, 14, 113-129. [Asian]",
        "Demeterfi, K. et al. (1999). A Guide to Volatility and Variance Swaps. <i>Journal of Derivatives</i>, 6(3), 9-32.",
        "Goldman, B., Sosin, H. &amp; Gatto, M. (1979). Path Dependent Options: Buy at the Low, Sell at the High. <i>Journal of Finance</i>, 34, 1111-1127. [Lookback]",
        "Kirk, E. (1995). Correlation in the Energy Markets. In V. Kaminski (Ed.), <i>Managing Energy Price Risk</i>. Risk Publications.",
        "Geske, R. (1979). The Valuation of Compound Options. <i>Journal of Financial Economics</i>, 7(1), 63-81.",
        "Kupiec, P. (1995). Techniques for Verifying the Accuracy of Risk Measurement Models. <i>Journal of Derivatives</i>, 3(2), 73-84.",
        "Christoffersen, P. (1998). Evaluating Interval Forecasts. <i>International Economic Review</i>, 39(4), 841-862.",
        "Stulz, R. (1982). Options on the Minimum or Maximum of Two Risky Assets. <i>Journal of Financial Economics</i>, 10, 161-185.",
    ]
    for r in refs:
        story.append(Paragraph(f"&#x2022; &nbsp; {r}", ParagraphStyle("ref",
            fontName="Helvetica", fontSize=8.5, leading=13, leftIndent=12,
            spaceAfter=3, textColor=TEXT, alignment=TA_JUSTIFY)))
    return story


# ─────────────────────────────────────────────────────────
# Build PDF
# ─────────────────────────────────────────────────────────

def main():
    out = "/Users/dmitriykiselev/Library/Mobile Documents/com~apple~CloudDocs/Python/RiskCalc/RiskEngine_Documentation.pdf"

    doc = SimpleDocTemplate(
        out, pagesize=A4,
        leftMargin=LEFT, rightMargin=RIGHT,
        topMargin=TOP + 4*mm, bottomMargin=BOT + 2*mm,
        title="Market Risk & Pricing Engine — Documentation",
        author="RiskCalc",
        subject="Quantitative Finance Documentation",
    )

    story = []

    # Cover (no header/footer)
    story += build_cover()
    story.append(PageBreak())

    # TOC
    story += build_toc_page()
    story.append(PageBreak())

    # Content sections
    story += build_overview()
    story += build_models()
    story += build_instruments()
    story += build_fixed_income()
    story += build_risk()

    def on_first(canvas, doc):
        on_cover(canvas, doc)

    def on_later(canvas, doc):
        on_page(canvas, doc)

    doc.build(
        story,
        onFirstPage=on_first,
        onLaterPages=on_later,
    )
    print(f"PDF saved: {out}")


if __name__ == "__main__":
    main()
