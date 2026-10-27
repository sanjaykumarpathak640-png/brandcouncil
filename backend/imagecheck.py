"""Deterministic image checks: brand palette, overall contrast, alt-text presence (no AI needed)."""
import io
from PIL import Image


def _rgb(h): h = h.lstrip("#"); return tuple(int(h[i:i + 2], 16) for i in (0, 2, 4))
def _dist(a, b): return sum((x - y) ** 2 for x, y in zip(a, b)) ** 0.5
def _lum(c):
    def ch(v):
        v /= 255; return v / 12.92 if v <= 0.03928 else ((v + 0.055) / 1.055) ** 2.4
    r, g, b = (ch(x) for x in c); return 0.2126 * r + 0.7152 * g + 0.0722 * b
def contrast(a, b):
    la, lb = sorted((_lum(a), _lum(b)), reverse=True); return (la + 0.05) / (lb + 0.05)


def dominant_colors(data, n=6):
    img = Image.open(io.BytesIO(data)).convert("RGB"); img.thumbnail((140, 140))
    q = img.quantize(colors=n, method=Image.Quantize.MEDIANCUT); pal = q.getpalette()
    total = img.size[0] * img.size[1]
    cols = [(cnt / total, tuple(pal[i * 3:i * 3 + 3])) for cnt, i in q.getcolors()]
    return sorted(cols, reverse=True), img.size


def analyze_image(data, alt_text, G):
    """Returns list of dicts with keys: g (guideline), reason, suggestion, severity, text, confidence."""
    out = []
    cols, size = dominant_colors(data)
    g = G.get("access.alt")
    if g and not (alt_text or "").strip():
        out.append({"g": g, "severity": "high", "text": "image alt-text", "confidence": 1.0,
                    "reason": "This image has no alt-text, so screen-reader users cannot understand it.",
                    "suggestion": "Add a short description, e.g. 'Cup of latte on a wooden table'."})
    g = G.get("visual.palette")
    if g:
        pal = [_rgb(c) for c in g["data"].get("palette", [])]
        tol, share = g["data"].get("tolerance", 80), g["data"].get("min_share", 0.12)
        for frac, col in cols:
            if frac >= share and pal and min(_dist(col, p) for p in pal) > tol:
                hexc = "#%02X%02X%02X" % col
                out.append({"g": g, "severity": "medium", "text": f"colour {hexc} ({frac:.0%} of the image)", "confidence": 0.8,
                            "reason": f"Colour {hexc} covers {frac:.0%} of the image and is far from every brand palette colour.",
                            "suggestion": "Recolour that area using espresso brown, cream or caramel."})
    g = G.get("access.contrast")
    big = [c for f, c in cols if f >= 0.08]
    if g and len(big) >= 2:
        best = max(contrast(a, b) for a in big for b in big)
        need = g["data"].get("min_ratio", 3.0)
        if best < need:
            out.append({"g": g, "severity": "medium", "text": f"overall contrast {best:.1f}:1", "confidence": 0.7,
                        "reason": f"The strongest contrast between the main colours is {best:.1f}:1, below the required {need}:1, so text on this image may be hard to read.",
                        "suggestion": "Use a darker background or lighter text so text reaches at least 3:1 (heuristic check, not OCR)."})
    return out, {"width": size[0], "height": size[1],
                 "palette": ["#%02X%02X%02X" % c for f, c in cols[:5]]}
