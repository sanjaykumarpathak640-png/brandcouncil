"""Read text from TXT, DOCX and PDF uploads. Paragraphs are separated by a blank line so findings can be mapped to a paragraph number."""
import io, re, zipfile
import xml.etree.ElementTree as ET

MAX_BYTES = 4 * 1024 * 1024
MAX_CHARS = 30000
W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"


class DocError(Exception):
    """Message is safe to show to the user."""


def _docx(data):
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as z:
            xml = z.read("word/document.xml")
    except Exception:
        raise DocError("This does not look like a valid .docx file. Re-save it from Word and try again.")
    root = ET.fromstring(xml)
    paras = []
    for p in root.iter(W + "p"):
        t = "".join((n.text or "") if n.tag == W + "t" else ("\t" if n.tag == W + "tab" else "") for n in p.iter() if n.tag in (W + "t", W + "tab"))
        if t.strip(): paras.append(t.strip())
    return paras


def _pdf(data):
    try:
        from pypdf import PdfReader
        rd = PdfReader(io.BytesIO(data))
        if rd.is_encrypted:
            raise DocError("This PDF is password-protected. Remove the password and upload it again.")
        paras = []
        for page in rd.pages[:40]:
            txt = page.extract_text() or ""
            for block in re.split(r"\n\s*\n", txt):
                b = re.sub(r"\s*\n\s*", " ", block).strip()
                if b: paras.append(b)
    except DocError:
        raise
    except Exception:
        raise DocError("This PDF could not be read. It may be damaged.")
    if not paras:
        raise DocError("No readable text was found in this PDF (it may be a scanned image). Upload a text PDF, a .docx, or paste the text instead.")
    return paras


def _txt(data):
    for enc in ("utf-8-sig", "utf-16", "latin-1"):
        try:
            s = data.decode(enc); break
        except Exception:
            continue
    return [p.strip() for p in re.split(r"\n\s*\n", s.replace("\r\n", "\n")) if p.strip()]


def extract_text(filename, data):
    """Returns (text, kind, truncated)."""
    if not data: raise DocError("The file is empty.")
    if len(data) > MAX_BYTES: raise DocError("The file is larger than 4 MB.")
    name = (filename or "").lower()
    if name.endswith(".docx"): paras, kind = _docx(data), "docx"
    elif name.endswith(".pdf") or data[:5] == b"%PDF-": paras, kind = _pdf(data), "pdf"
    elif name.endswith((".txt", ".md", ".text")): paras, kind = _txt(data), "txt"
    elif name.endswith(".doc"): raise DocError("Old .doc files are not supported. Save as .docx, PDF or TXT.")
    else: raise DocError("Unsupported file type. Please upload a .docx, .pdf or .txt file.")
    text = "\n\n".join(paras).strip()
    if not text: raise DocError("No text was found in this file.")
    truncated = len(text) > MAX_CHARS
    if truncated:
        text = text[:MAX_CHARS]; text = text[:text.rfind("\n\n")] if "\n\n" in text else text
    return text, kind, truncated


def paragraph_of(text, pos):
    """1-based paragraph number containing character position pos."""
    return text.count("\n\n", 0, max(0, pos)) + 1
