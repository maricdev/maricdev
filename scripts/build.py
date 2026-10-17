"""Builds the profile README images (light and dark) from the maric.dev design tokens.

Every image is a self-contained SVG: the fonts are subset to the glyphs it uses and embedded as
WOFF2, the portrait is embedded as JPEG, so GitHub renders them exactly with no external requests.
Motion is CSS and SMIL inside the SVG; prefers-reduced-motion shows the final state at once.

Run: python3 scripts/build.py   (needs fonttools and brotli)
"""

from __future__ import annotations

import base64
import io
import re
from dataclasses import dataclass
from html import escape
from pathlib import Path

from fontTools import subset
from fontTools.ttLib import TTFont

ROOT = Path(__file__).resolve().parent.parent
FONTS = ROOT / "source" / "fonts"
OUT = ROOT / "assets"

W = 1280
PAD = 64
RADIUS = 28

# Tokens from maric-dev/src/app/globals.css (sage paper / green-black, one ochre signal).
THEMES = {
    "light": {
        "paper": "#e4e8dd",
        "paper2": "#d7ddcf",
        "ink": "#102322",
        "ink2": "#384a47",
        "ink3": "#475550",
        "line": "rgb(16 35 34 / 0.14)",
        "lineStrong": "rgb(16 35 34 / 0.28)",
        "pineSoft": "#cddcd9",
        "signal": "#b07c22",
        "signalInk": "#744e0e",
        "signalSoft": "rgb(176 124 34 / 0.14)",
        "ok": "#276749",
        "button": "#102322",
        "buttonInk": "#e4e8dd",
    },
    "dark": {
        "paper": "#0b1514",
        "paper2": "#111e1d",
        "ink": "#ede7da",
        "ink2": "#bcc5bf",
        "ink3": "#939f9a",
        "line": "rgb(237 231 218 / 0.12)",
        "lineStrong": "rgb(237 231 218 / 0.26)",
        "pineSoft": "#1c3331",
        "signal": "#dca84a",
        "signalInk": "#e6bd6e",
        "signalSoft": "rgb(220 168 74 / 0.14)",
        "ok": "#6fcf97",
        "button": "#ede7da",
        "buttonInk": "#0b1514",
    },
}


@dataclass(frozen=True)
class Face:
    family: str
    file: str
    style: str = "normal"
    weight: int = 400


SERIF = Face("Instrument Serif", "InstrumentSerif-Regular.ttf")
SERIF_ITALIC = Face("Instrument Serif", "InstrumentSerif-Italic.ttf", style="italic")
SANS = Face("Hanken Grotesk", "HankenGrotesk-Regular.ttf")
SANS_SEMI = Face("Hanken Grotesk", "HankenGrotesk-SemiBold.ttf", weight=600)
MONO = Face("JetBrains Mono", "JetBrainsMono-Regular.ttf")

_fonts: dict[str, TTFont] = {}


def font(face: Face) -> TTFont:
    if face.file not in _fonts:
        _fonts[face.file] = TTFont(FONTS / face.file)
    return _fonts[face.file]


def frosted_crop(path: Path, frame: tuple[float, float], box: tuple[float, float, float, float]) -> str:
    """The part of the photo behind `box` (frame coordinates, photo drawn with "slice"), blurred, as JPEG base64."""
    from PIL import Image, ImageFilter

    image = Image.open(path).convert("RGB")
    scale = max(frame[0] / image.width, frame[1] / image.height)
    dx = (frame[0] - image.width * scale) / 2
    dy = (frame[1] - image.height * scale) / 2
    x, y, w, h = box
    blurred = image.filter(ImageFilter.GaussianBlur(28))
    crop = blurred.crop(
        (round((x - dx) / scale), round((y - dy) / scale), round((x + w - dx) / scale), round((y + h - dy) / scale))
    )
    buffer = io.BytesIO()
    crop.resize((round(w * 2), round(h * 2))).save(buffer, "JPEG", quality=80)
    return base64.b64encode(buffer.getvalue()).decode()


def measure(text: str, face: Face, size: float, tracking: float = 0) -> float:
    """Advance width in px (no kerning; close enough for layout and wrapping)."""
    tt = font(face)
    cmap = tt.getBestCmap()
    hmtx = tt["hmtx"]
    upem = tt["head"].unitsPerEm
    units = sum(hmtx[cmap.get(ord(ch), ".notdef")][0] for ch in text)
    return units / upem * size + tracking * size * len(text)


def wrap(text: str, face: Face, size: float, width: float) -> list[str]:
    lines: list[str] = []
    current = ""
    for word in text.split():
        candidate = f"{current} {word}".strip()
        if current and measure(candidate, face, size) > width:
            lines.append(current)
            current = word
        else:
            current = candidate
    if current:
        lines.append(current)
    return lines


def wrap_list(text: str, face: Face, size: float, width: float) -> list[str]:
    """Wraps a "a · b · c" list between items, so a separator never ends a line."""
    if " · " not in text:
        return wrap(text, face, size, width)
    lines: list[str] = []
    for item in text.split(" · "):
        candidate = f"{lines[-1]} · {item}" if lines else item
        if lines and measure(candidate, face, size) <= width:
            lines[-1] = candidate
        else:
            lines.append(item)
    return lines


class Svg:
    """Collects the markup and the text used per font, then embeds subset fonts."""

    def __init__(self, height: int, theme: str, title: str, width: int = W):
        self.w = width
        self.h = height
        self.t = THEMES[theme]
        self.theme = theme
        self.title = title
        self.defs: list[str] = []
        self.body: list[str] = []
        self.used: dict[Face, set[str]] = {}

    def text(self, x, y, content, face: Face, size, fill, *, tracking=0.0, anchor="start", cls="", style="",
             spans: list[tuple[str, Face, str]] | None = None):
        """One line of text; `spans` appends inline runs (text, face, fill) after `content`."""
        self.used.setdefault(face, set()).update(content)
        inner = escape(content)
        for run, run_face, run_fill in spans or []:
            self.used.setdefault(run_face, set()).update(run)
            inner += (
                f'<tspan font-style="{run_face.style}" font-weight="{run_face.weight}" fill="{run_fill}">'
                f"{escape(run)}</tspan>"
            )
        attrs = [
            f'x="{x:.1f}"', f'y="{y:.1f}"', f'font-family="{face.family}"', f'font-size="{size}"',
            f'font-style="{face.style}"', f'font-weight="{face.weight}"', f'fill="{fill}"',
        ]
        if tracking:
            attrs.append(f'letter-spacing="{tracking * size:.2f}"')
        if anchor != "start":
            attrs.append(f'text-anchor="{anchor}"')
        if cls:
            attrs.append(f'class="{cls}"')
        if style:
            attrs.append(f'style="{style}"')
        return f"<text {' '.join(attrs)}>{inner}</text>"

    def add(self, *parts: str):
        self.body.extend(parts)

    def card(self, glow: tuple[float, float, float] | None = None):
        t = self.t
        self.defs.append(
            f'<clipPath id="card"><rect width="{W}" height="{self.h}" rx="{RADIUS}"/></clipPath>'
        )
        parts = [f'<rect width="{W}" height="{self.h}" rx="{RADIUS}" fill="{t["paper"]}"/>']
        if glow:
            gx, gy, gr = glow
            self.defs.append(
                f'<radialGradient id="glow" cx="{gx}" cy="{gy}" r="{gr}" gradientUnits="userSpaceOnUse">'
                f'<stop offset="0" stop-color="{t["pineSoft"]}" stop-opacity="0.9"/>'
                f'<stop offset="1" stop-color="{t["pineSoft"]}" stop-opacity="0"/></radialGradient>'
            )
            parts.append(f'<rect width="{W}" height="{self.h}" fill="url(#glow)" clip-path="url(#card)"/>')
        self.body[:0] = parts

    def eyebrow(self, x, y, label, delay=0.0):
        t = self.t
        return (
            f'<g class="fade" style="animation-delay:{delay}s">'
            f'<line x1="{x}" y1="{y - 6}" x2="{x + 32}" y2="{y - 6}" stroke="{t["ink3"]}" stroke-width="1.25"/>'
            + self.text(x + 48, y, label.upper(), MONO, 17, t["ink3"], tracking=0.14)
            + "</g>"
        )

    def chip(self, x, y, label, *, accent=False, size=15, anchor="start"):
        """A mono pill; (x, y) is its left (or right, with anchor="end") edge and vertical centre."""
        t = self.t
        width = measure(label, MONO, size) + 28
        left = x - width if anchor == "end" else x
        stroke = t["signal"] if accent else t["lineStrong"]
        fill = t["signalSoft"] if accent else "none"
        colour = t["signalInk"] if accent else t["ink2"]
        return (
            f'<rect x="{left:.1f}" y="{y - 15}" width="{width:.1f}" height="30" rx="15" fill="{fill}" stroke="{stroke}"/>'
            + self.text(left + width / 2, y + size * 0.34, label, MONO, size, colour, anchor="middle")
        ), width

    def font_faces(self) -> str:
        rules = []
        for face, chars in self.used.items():
            options = subset.Options()
            options.flavor = "woff2"
            options.layout_features = ["kern", "liga", "calt"]
            options.name_IDs = []
            options.notdef_outline = True
            subsetter = subset.Subsetter(options)
            tt = TTFont(FONTS / face.file)
            subsetter.populate(text="".join(sorted(chars | {" "})))
            subsetter.subset(tt)
            buffer = io.BytesIO()
            tt.flavor = "woff2"
            tt.recalcTimestamp = False  # same bytes on every build, so unchanged cards stay out of the diff
            tt.save(buffer)
            data = base64.b64encode(buffer.getvalue()).decode()
            rules.append(
                f"@font-face{{font-family:'{face.family}';font-style:{face.style};font-weight:{face.weight};"
                f"src:url(data:font/woff2;base64,{data}) format('woff2')}}"
            )
        return "".join(rules)

    def render(self) -> str:
        css = (
            self.font_faces()
            + "text{font-kerning:normal;text-rendering:geometricPrecision}"
            ".rise{transform-box:fill-box;animation:rise 1.2s cubic-bezier(.16,1,.3,1) both}"
            ".fade{animation:fade 0.64s cubic-bezier(.16,1,.3,1) both}"
            ".draw{animation:draw 1.4s cubic-bezier(.65,0,.35,1) both}"
            ".photo{transform-box:fill-box;transform-origin:center;animation:photo 1.4s cubic-bezier(.16,1,.3,1) both}"
            # An SVG image repaints whole on every frame, so the live dot pulses a few times after the
            # intro instead of forever (an endless pulse over the portrait stalled the intro).
            ".ring{transform-box:fill-box;transform-origin:center;opacity:0;"
            "animation:ring 2.4s cubic-bezier(.16,1,.3,1) 2s 4 both}"
            "@keyframes rise{from{transform:translateY(110%)}to{transform:none}}"
            "@keyframes fade{from{opacity:0;transform:translateY(12px)}to{opacity:1;transform:none}}"
            "@keyframes draw{from{stroke-dashoffset:var(--len)}to{stroke-dashoffset:0}}"
            "@keyframes photo{from{opacity:0;transform:scale(1.05)}to{opacity:1;transform:none}}"
            "@keyframes ring{0%{transform:scale(.6);opacity:.6}100%{transform:scale(2.4);opacity:0}}"
            "@media (prefers-reduced-motion:reduce){*{animation:none!important}.traveler{display:none}}"
        )
        return (
            f'<svg xmlns="http://www.w3.org/2000/svg" xmlns:xlink="http://www.w3.org/1999/xlink" '
            f'viewBox="0 0 {self.w} {self.h}" width="{self.w}" height="{self.h}" role="img" aria-label="{escape(self.title)}">'
            f"<title>{escape(self.title)}</title><style>{css}</style><defs>{''.join(self.defs)}</defs>"
            f"{''.join(self.body)}</svg>\n"
        )


# ---------------------------------------------------------------------------------------------
# Hero: the maric.dev hero, headline left, portrait right with the availability pill.
# ---------------------------------------------------------------------------------------------
def hero(theme: str) -> Svg:
    h = 720
    s = Svg(h, theme, "Ivan Marić, technology consultant. I help define and build digital products.")
    t = s.t
    s.card(glow=(260, 240, 620))

    # Wordmark: "maric" in the serif italic, an ochre dot, "dev" in mono, as in the site header.
    mark_size = 38
    maric_w = measure("maric", SERIF_ITALIC, mark_size)
    s.add(
        '<g class="fade" style="animation-delay:.05s">',
        s.text(PAD, 96, "maric", SERIF_ITALIC, mark_size, t["ink"]),
        f'<circle cx="{PAD + maric_w + 6:.1f}" cy="90" r="4.5" fill="{t["signal"]}"/>',
        s.text(PAD + maric_w + 16, 96, "dev", MONO, 21, t["ink2"]),
        "</g>",
    )
    s.add(s.eyebrow(PAD, 178, "Ivan Marić · Technology consultant", delay=0.15))

    size = 112
    baselines = [300, 408, 516]
    lines = [("I help define", None), ("and build", None), ("digital ", "products.")]
    for index, ((lead, accent), base) in enumerate(zip(lines, baselines)):
        s.defs.append(
            f'<clipPath id="line{index}"><rect x="{PAD - 20}" y="{base - size}" width="680" height="{size * 1.32}"/></clipPath>'
        )
        spans = [(accent, SERIF_ITALIC, t["signalInk"])] if accent else None
        s.add(
            f'<g clip-path="url(#line{index})">',
            s.text(PAD - 4, base, lead, SERIF, size, t["ink"], tracking=-0.03, cls="rise",
                   style=f"animation-delay:{0.25 + index * 0.08:.2f}s", spans=spans),
            "</g>",
        )

    intro = "Digital products, process automation and AI adoption, backed by Java, Spring Boot and business systems."
    for index, line in enumerate(wrap(intro, SANS, 23, 600)):
        s.add(s.text(PAD, 596 + index * 34, line, SANS, 23, t["ink2"], cls="fade",
                     style=f"animation-delay:{0.7 + index * 0.06:.2f}s"))

    # Portrait in a double frame, as on the site.
    portrait = ROOT / "source" / "images" / "portrait.jpg"
    photo = base64.b64encode(portrait.read_bytes()).decode()
    fx, fy, fw, fh = 772, 52, 456, 616
    ix, iy, iw, ih = fx + 12, fy + 12, fw - 24, fh - 24
    pill_label = "Project-based consulting"
    pill_w = measure(pill_label, SANS, 17) + 58
    px, py, ph = ix + 18, iy + ih - 18 - 40, 40
    frost = frosted_crop(portrait, (iw, ih), (px - ix, py - iy, pill_w, ph))
    s.defs.append(
        f'<clipPath id="photo"><rect x="{ix}" y="{iy}" width="{iw}" height="{ih}" rx="22"/></clipPath>'
        f'<clipPath id="pill"><rect x="{px}" y="{py}" width="{pill_w:.1f}" height="{ph}" rx="20"/></clipPath>'
    )
    s.add(
        f'<rect x="{fx}" y="{fy}" width="{fw}" height="{fh}" rx="32" fill="{t["paper2"]}" stroke="{t["line"]}"/>',
        '<g class="photo" style="animation-delay:.3s">',
        f'<image x="{ix}" y="{iy}" width="{iw}" height="{ih}" preserveAspectRatio="xMidYMid slice" '
        f'clip-path="url(#photo)" href="data:image/jpeg;base64,{photo}"/>',
        # Liquid-glass pill: the photo behind it pre-frosted (a live blur filter repaints every frame
        # of the pulsing dot and stalls the animation), a dark tint and a lit rim.
        f'<g clip-path="url(#pill)"><image x="{px}" y="{py}" width="{pill_w:.1f}" height="{ph}" '
        f'preserveAspectRatio="none" href="data:image/jpeg;base64,{frost}"/>'
        f'<rect x="{px}" y="{py}" width="{pill_w:.1f}" height="{ph}" fill="rgb(11 21 20 / 0.5)"/></g>',
        f'<rect x="{px + 0.5}" y="{py + 0.5}" width="{pill_w - 1:.1f}" height="{ph - 1}" rx="19.5" fill="none" '
        f'stroke="rgb(255 255 255 / 0.22)"/>',
        "</g>",
        # The live dot sits outside the animated photo group so its pulse repaints only itself.
        f'<g class="fade" style="animation-delay:1.2s">'
        f'<circle class="ring" cx="{px + 22}" cy="{py + ph / 2}" r="4.5" fill="#6fcf97"/>'
        f'<circle cx="{px + 22}" cy="{py + ph / 2}" r="4.5" fill="#6fcf97"/>'
        + s.text(px + 38, py + ph / 2 + 6, pill_label, SANS, 17, "#ede7da")
        + "</g>",
    )
    return s


# ---------------------------------------------------------------------------------------------
# How a project moves: the site's signal line, then the four facts.
# ---------------------------------------------------------------------------------------------
STRANDS = [
    "M20 52 C 70 18, 92 150, 132 92 C 160 52, 186 104, 220 110",
    "M20 96 C 58 142, 102 38, 142 122 C 168 150, 190 114, 220 110",
    "M20 142 C 62 92, 92 182, 152 100 C 176 70, 194 106, 220 110",
    "M20 176 C 82 160, 82 58, 152 142 C 180 160, 196 116, 220 110",
    "M20 72 C 52 112, 110 172, 162 80 C 182 50, 198 102, 220 110",
]
BRANCHES = ["UX", "Processes", "Data", "APIs", "Integrations", "Automation", "AI"]
PULSE_ORDER = [3, 1, 5, 0, 4, 6, 2]
FLOW_TOP = 46
FLOW_K = (W - 2 * PAD) / 600


def fx_(x: float) -> float:
    return PAD + (x - 20) * FLOW_K


def fy_(y: float) -> float:
    return FLOW_TOP + y


def map_path(d: str) -> str:
    """Maps an absolute M/C/L/H path from the site's 660x220 drawing into this card."""
    out, command, index = [], "", 0
    for token in re.findall(r"[A-Za-z]|-?\d*\.?\d+", d):
        if token.isalpha():
            command, index = token, 0
            out.append(token)
            continue
        value = float(token)
        is_x = command == "H" or index % 2 == 0
        index += 1
        out.append(f"{fx_(value) if is_x else fy_(value):.1f}")
    return " ".join(out)


def branch_tail(y: float) -> str:
    return f"C 256 110, 262 {y}, 300 {y} H 420 C 458 {y}, 464 110, 500 110 L 620 110"


def flow(theme: str) -> Svg:
    h = 436
    s = Svg(h, theme, "How a project moves: business need, scope, solution design across UX, processes, data, "
                      "APIs, integrations, automation and AI, then a working product.")
    t = s.t
    s.card()
    gap = 27
    branch_ys = [110 + (i - 3) * gap for i in range(len(BRANCHES))]
    strand_len, branch_len = 900, 1300
    label = dict(face=MONO, size=17, fill=t["ink2"], tracking=0.02)

    def lbl(x, y, text, anchor="start", delay=0.0):
        return s.text(x, y, text, label["face"], label["size"], label["fill"], tracking=label["tracking"],
                      anchor=anchor, cls="fade", style=f"animation-delay:{delay:.2f}s")

    for index, d in enumerate(STRANDS):
        s.add(
            f'<path class="draw" style="--len:{strand_len};animation-delay:{0.3 + index * 0.06:.2f}s" '
            f'd="{map_path(d)}" fill="none" stroke="{t["lineStrong"]}" stroke-width="1.4" stroke-linecap="round" '
            f'stroke-dasharray="{strand_len}"/>'
        )
    s.add(lbl(fx_(20), fy_(8), "Business need", delay=0.3))
    for index, y in enumerate(branch_ys):
        middle = index == 3
        s.add(
            f'<path class="draw" style="--len:{branch_len};animation-delay:{1.2 + abs(index - 3) * 0.02:.2f}s" '
            f'd="{map_path(f"M220 110 {branch_tail(y)}")}" fill="none" stroke="{t["signal"]}" '
            f'stroke-opacity="{1 if middle else 0.6}" stroke-width="{2 if middle else 1.4}" stroke-linecap="round" '
            f'stroke-dasharray="{branch_len}"/>'
        )
    s.add(lbl(fx_(360), fy_(-6), "Solution design", anchor="middle", delay=1.3))
    chip_w, chip_h = 164, 23
    for index, (y, name) in enumerate(zip(branch_ys, BRANCHES)):
        cx = fx_(360)
        s.add(
            f'<g class="fade" style="animation-delay:{1.4 + index * 0.05:.2f}s">',
            f'<rect x="{cx - chip_w / 2:.1f}" y="{fy_(y) - chip_h / 2:.1f}" width="{chip_w}" height="{chip_h}" '
            f'rx="{chip_h / 2}" fill="{t["paper"]}" stroke="{t["lineStrong"]}"/>',
            s.text(cx, fy_(y) + 5.2, name, MONO, 14.5, t["ink2"], anchor="middle"),
            "</g>",
        )
    for x, last, delay in ((220, False, 1.1), (620, True, 2.2)):
        s.add(
            f'<g class="fade" style="animation-delay:{delay}s">',
            f'<circle cx="{fx_(x):.1f}" cy="{fy_(110)}" r="{10 if last else 7}" fill="{t["paper"]}" '
            f'stroke="{t["ink"]}" stroke-width="1.6"/>',
            f'<circle cx="{fx_(x):.1f}" cy="{fy_(110)}" r="4" fill="{t["signal"]}"/>' if last else "",
            s.text(fx_(x), fy_(156 if not last else 150), "Working product" if last else "Scope", MONO, 17,
                   t["ink2"], anchor="end" if last else "middle"),
            "</g>",
        )
    for run, branch in enumerate(PULSE_ORDER):
        rid, prev = f"p{run}", f"p{(run - 1) % len(PULSE_ORDER)}"
        begin = f"2.6s; {prev}.end+0.5s" if run == 0 else f"{prev}.end+0.5s"
        path = map_path(f"{STRANDS[run % len(STRANDS)]} {branch_tail(branch_ys[branch])}")
        s.add(
            f'<g class="traveler" opacity="0"><set attributeName="opacity" to="1" begin="{rid}.begin" end="{rid}.end"/>'
            f'<circle r="10" fill="{t["signalSoft"]}"/><circle r="4.5" fill="{t["signal"]}"/>'
            f'<animateMotion id="{rid}" dur="5.2s" begin="{begin}" path="{path}" keyPoints="0;1" keyTimes="0;1" '
            f'calcMode="spline" keySplines="0.65 0 0.35 1"/></g>'
        )

    # Facts row between hairlines, as under the site's hero.
    top = 296
    s.add(f'<line x1="{PAD}" y1="{top}" x2="{W - PAD}" y2="{top}" stroke="{t["line"]}"/>')
    facts = [
        ("How I help", "Discovery · Design · Development"),
        ("Technical background", "Java · Spring Boot · PostgreSQL"),
        ("Business systems", "Documents, workflows, integrations"),
        ("Based in", "Belgrade, Serbia"),
    ]
    column = (W - 2 * PAD) / 4
    for index, (key, value) in enumerate(facts):
        x = PAD + index * column
        s.add(
            f'<g class="fade" style="animation-delay:{2.3 + index * 0.06:.2f}s">',
            s.text(x, top + 50, key.upper(), MONO, 14, t["ink3"], tracking=0.12),
            *[s.text(x, top + 86 + i * 28, part, SANS, 20, t["ink"])
              for i, part in enumerate(wrap_list(value, SANS, 20, column - 24))],
            "</g>",
        )
    return s


# ---------------------------------------------------------------------------------------------
# Selected work: a heading card, then one ruled card per project (each links to its page).
# ---------------------------------------------------------------------------------------------
def work_head(theme: str) -> Svg:
    h = 390
    s = Svg(h, theme, "Selected work: products and systems I've worked on.")
    t = s.t
    s.card(glow=(1100, 40, 520))
    s.add(s.eyebrow(PAD, 98, "Selected work"))
    for index, line in enumerate(["Products and systems", "I've worked on."]):
        s.add(s.text(PAD - 3, 184 + index * 80, line, SERIF, 84, t["ink"], tracking=-0.025, cls="fade",
                     style=f"animation-delay:{0.1 + index * 0.08:.2f}s"))
    intro = "Document management at Comtrade, a travel product in development, and a volunteer platform shaped with therapists."
    for index, line in enumerate(wrap(intro, SANS, 21, 760)):
        s.add(s.text(PAD, 322 + index * 30, line, SANS, 21, t["ink2"]))
    label = "All work"
    width = measure(label, SANS_SEMI, 19) + 76
    x, y = W - PAD - width, 298
    s.add(
        f'<rect x="{x:.1f}" y="{y}" width="{width:.1f}" height="48" rx="24" fill="none" stroke="{t["lineStrong"]}"/>',
        s.text(x + 26, y + 31, label, SANS_SEMI, 19, t["ink"]),
        arrow(x + width - 36, y + 24, t["ink"]),
    )
    return s


def arrow(cx: float, cy: float, colour: str, size: float = 9) -> str:
    return (
        f'<path d="M{cx - size:.1f} {cy} H{cx + size:.1f} M{cx + size * 0.35:.1f} {cy - size * 0.6:.1f} '
        f'L{cx + size:.1f} {cy} L{cx + size * 0.35:.1f} {cy + size * 0.6:.1f}" fill="none" stroke="{colour}" '
        f'stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"/>'
    )


PROJECTS = [
    {
        "slug": "document-management-system",
        "number": "01",
        "kind": "Enterprise backend · Comtrade",
        "name": "Document Management System",
        "summary": "Document workflows, approvals and audit trails for sensitive public-sector documentation, built on Alfresco.",
        "stack": ["Java", "Spring Boot", "Alfresco", "PostgreSQL"],
    },
    {
        "slug": "tripollon",
        "number": "02",
        "kind": "Travel product · independent project",
        "status": "Early stage",
        "name": "Tripollon",
        "summary": "A B2B/B2C travel platform in development for agencies and travellers, with shared itineraries.",
        "stack": ["Java", "Spring Boot", "PostgreSQL", "TypeScript"],
    },
    {
        "slug": "feelsafehub",
        "number": "03",
        "kind": "Non-profit · volunteer",
        "name": "Safe Space · Feel Safe Hub",
        "summary": "Structure, identity and website for a non-profit platform connecting people with free online psychotherapy.",
        "stack": ["PHP", "MySQL", "JavaScript"],
    },
]


def work_row(theme: str, project: dict) -> Svg:
    h = 270
    s = Svg(h, theme, f"{project['name']}: {project['summary']}")
    t = s.t
    s.card()
    s.add(s.text(PAD, 84, project["number"], MONO, 17, t["signalInk"], tracking=0.06))
    kind_x = PAD + 64
    s.add(s.text(kind_x, 84, project["kind"].upper(), MONO, 15, t["ink3"], tracking=0.12))
    if project.get("status"):
        chip, _ = s.chip(kind_x + measure(project["kind"].upper(), MONO, 15, 0.12) + 16, 79, project["status"],
                         accent=True, size=13)
        s.add(chip)
    s.add(s.text(kind_x - 3, 150, project["name"], SERIF, 56, t["ink"], tracking=-0.02))
    for index, line in enumerate(wrap(project["summary"], SANS, 21, 820)):
        s.add(s.text(kind_x, 196 + index * 30, line, SANS, 21, t["ink2"]))
    # Stack chips top right, the "open" arrow bottom right.
    right = W - PAD
    for name in reversed(project["stack"]):
        chip, width = s.chip(right, 79, name, size=13, anchor="end")
        s.add(chip)
        right -= width + 8
    cx, cy = W - PAD - 28, h - 64
    s.add(
        f'<circle cx="{cx}" cy="{cy}" r="28" fill="none" stroke="{t["lineStrong"]}"/>',
        arrow(cx, cy, t["ink"]),
    )
    return s


# ---------------------------------------------------------------------------------------------
# Next step: the closing call to action.
# ---------------------------------------------------------------------------------------------
def cta(theme: str) -> Svg:
    h = 420
    s = Svg(h, theme, "Let's talk about your product. Book a 30-minute intro call.")
    t = s.t
    s.card(glow=(240, 420, 640))
    s.add(s.eyebrow(PAD, 98, "Next step"))
    s.add(s.text(PAD - 3, 196, "Let's talk about your ", SERIF, 92, t["ink"], tracking=-0.03, cls="fade",
                 style="animation-delay:.1s", spans=[("product.", SERIF_ITALIC, t["signalInk"])]))
    body = "Tell me what you're trying to build or improve. We can start with a message or a 30-minute call."
    for index, line in enumerate(wrap(body, SANS, 22, 700)):
        s.add(s.text(PAD, 254 + index * 32, line, SANS, 22, t["ink2"]))
    label = "Book an intro call"
    width = measure(label, SANS_SEMI, 20) + 94
    x, y = PAD, 316
    s.add(
        f'<rect x="{x}" y="{y}" width="{width:.1f}" height="56" rx="28" fill="{t["button"]}"/>',
        calendar(x + 34, y + 28, t["buttonInk"]),
        s.text(x + 56, y + 35, label, SANS_SEMI, 20, t["buttonInk"]),
    )
    s.add(s.text(W - PAD, y + 35, "maric.dev", MONO, 17, t["ink3"], anchor="end", tracking=0.04))
    return s


def calendar(cx: float, cy: float, colour: str) -> str:
    return (
        f'<g fill="none" stroke="{colour}" stroke-width="1.6" stroke-linecap="round">'
        f'<rect x="{cx - 9}" y="{cy - 8}" width="18" height="17" rx="3"/>'
        f'<path d="M{cx - 9} {cy - 2} H{cx + 9} M{cx - 4} {cy - 11} V{cy - 5} M{cx + 4} {cy - 11} V{cy - 5}"/></g>'
    )


# ---------------------------------------------------------------------------------------------
# Links: three tiles in one row under the cards. Each tile is its own image (and link); the row
# is cut into thirds of the card width with the gaps inside the images, so the tiles line up with
# the cards' edges when the README shows them at 33.333% with no whitespace between them.
# Booking is not here: the CTA card above is that link.
LINKS = [
    {"key": "site", "eyebrow": "Website", "label": "maric.dev", "icon": "globe"},
    {"key": "linkedin", "eyebrow": "LinkedIn", "label": "in/maric-dev", "icon": "linkedin"},
    {"key": "instagram", "eyebrow": "Instagram", "label": "@maric.dev", "icon": "instagram"},
]
TILE_GAP = 16


def icon(name: str, cx: float, cy: float, colour: str) -> str:
    stroke = f'fill="none" stroke="{colour}" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round"'
    if name == "calendar":
        return calendar(cx, cy, colour)
    if name == "globe":
        return (
            f'<g {stroke}><circle cx="{cx}" cy="{cy}" r="9.5"/><ellipse cx="{cx}" cy="{cy}" rx="4" ry="9.5"/>'
            f'<path d="M{cx - 9.5} {cy} H{cx + 9.5}"/></g>'
        )
    if name == "linkedin":
        return (
            f'<g {stroke}><rect x="{cx - 10}" y="{cy - 10}" width="20" height="20" rx="4.5"/>'
            f'<path d="M{cx - 4.5} {cy - 1} V{cy + 5} M{cx - 0.5} {cy + 5} V{cy - 1} M{cx - 0.5} {cy + 1.8} '
            f'Q{cx - 0.5} {cy - 1.4} {cx + 2.4} {cy - 1.4} Q{cx + 5} {cy - 1.4} {cx + 5} {cy + 1.6} V{cy + 5}"/></g>'
            f'<circle cx="{cx - 4.5}" cy="{cy - 4.6}" r="1.3" fill="{colour}"/>'
        )
    if name == "instagram":
        return (
            f'<g {stroke}><rect x="{cx - 10}" y="{cy - 10}" width="20" height="20" rx="6"/>'
            f'<circle cx="{cx}" cy="{cy}" r="4.6"/></g>'
            f'<circle cx="{cx + 5.2}" cy="{cy - 5.2}" r="1.2" fill="{colour}"/>'
        )
    raise ValueError(name)


def link_tile(theme: str, link: dict, index: int) -> Svg:
    h = 200
    segment = W / len(LINKS)
    tile = (W - TILE_GAP * (len(LINKS) - 1)) / len(LINKS)
    x0 = index * (tile + TILE_GAP) - index * segment
    s = Svg(h, theme, f"{link['eyebrow']}: {link['label']}", width=round(segment, 2))
    t = s.t
    pad = 36
    cx, cy = x0 + tile - pad - 24, pad + 24
    s.add(
        f'<rect x="{x0:.2f}" y="0" width="{tile:.2f}" height="{h}" rx="{RADIUS}" fill="{t["paper"]}"/>',
        icon(link["icon"], x0 + pad + 11, cy, t["signalInk"]),
        s.text(x0 + pad + 36, cy + 5.5, link["eyebrow"].upper(), MONO, 15, t["ink3"], tracking=0.12),
        f'<circle cx="{cx:.2f}" cy="{cy}" r="24" fill="none" stroke="{t["lineStrong"]}"/>',
        arrow_out(cx, cy, t["ink"]),
        s.text(x0 + pad - 2, h - pad - 4, link["label"], SERIF, 50, t["ink"], tracking=-0.02),
    )
    return s


def arrow_out(cx: float, cy: float, colour: str, size: float = 7) -> str:
    """A ↗ arrow: the link leaves GitHub."""
    return (
        f'<path d="M{cx - size:.1f} {cy + size:.1f} L{cx + size:.1f} {cy - size:.1f} M{cx - size * 0.3:.1f} '
        f'{cy - size:.1f} H{cx + size:.1f} V{cy + size * 0.3:.1f}" fill="none" stroke="{colour}" stroke-width="1.8" '
        f'stroke-linecap="round" stroke-linejoin="round"/>'
    )

def main():
    OUT.mkdir(exist_ok=True)
    builders = {"hero": hero, "flow": flow, "work": work_head, "cta": cta}
    for theme in THEMES:
        for name, build in builders.items():
            (OUT / f"{name}-{theme}.svg").write_text(build(theme).render())
        for project in PROJECTS:
            (OUT / f"work-{project['number']}-{theme}.svg").write_text(work_row(theme, project).render())
        for index, link in enumerate(LINKS):
            (OUT / f"link-{link['key']}-{theme}.svg").write_text(link_tile(theme, link, index).render())
    for path in sorted(OUT.glob("*.svg")):
        print(f"{path.name:28} {path.stat().st_size / 1024:7.1f} KB")


if __name__ == "__main__":
    main()
