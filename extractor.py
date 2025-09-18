#!/usr/bin/env python3
import argparse, json, os, re, sys, hashlib
from datetime import datetime
from pathlib import Path

# Optional libs: pdfplumber, dateutil. OCR-Fallback (pytesseract) ist optional.
try:
    import pdfplumber
except Exception:
    pdfplumber = None

try:
    from dateutil import parser as dateparser
except Exception:
    dateparser = None

# ---------- Helpers ----------

def info(msg): print(f"[i] {msg}")
def warn(msg): print(f"[!] {msg}")
def err(msg):  print(f"[x] {msg}", file=sys.stderr)

# Grobe Normalisierung
def clean_text(s: str) -> str:
    if not s: return ""
    s = s.replace("\u0000", " ")
    s = re.sub(r"[ \t]+", " ", s)
    s = re.sub(r"\r", "", s)
    # Seitenköpfe/-füße häufig: „Drucksache …“, „- 1 -“
    s = re.sub(r"\n?- ?\d+ -\n?", "\n", s)
    s = re.sub(r"\n{3,}", "\n\n", s)
    return s.strip()

# PDF → Text
def pdf_to_text(pdf_path: str) -> str:
    text = ""
    if pdfplumber is not None:
        try:
            with pdfplumber.open(pdf_path) as pdf:
                pages = [p.extract_text() or "" for p in pdf.pages]
            text = "\n\n".join(pages)
        except Exception as e:
            warn(f"pdfplumber Fehler: {e}")
    if not text:
        # Fallback: pdftotext CLI (optional installiert)
        try:
            import subprocess, tempfile
            tmp = tempfile.NamedTemporaryFile(delete=False, suffix=".txt")
            tmp.close()
            subprocess.run(["pdftotext", "-layout", pdf_path, tmp.name], check=True)
            with open(tmp.name, "r", encoding="utf-8", errors="ignore") as f:
                text = f.read()
            os.unlink(tmp.name)
        except Exception as e:
            warn(f"pdftotext Fallback fehlgeschlagen: {e}")
    return clean_text(text or "")

# Datums-Normalisierung → ISO
def to_iso_date(s: str) -> str | None:
    s = (s or "").strip()
    if not s: return None
    # direkte Matches
    m = re.search(r"\b(20\d{2}|19\d{2})[-/.](\d{1,2})[-/.](\d{1,2})\b", s)
    if m:
        y, mo, d = int(m.group(1)), int(m.group(2)), int(m.group(3))
        try: return datetime(y, mo, d).date().isoformat()
        except: pass
    # deutsche Formate
    m = re.search(r"\b(\d{1,2})[.\-/](\d{1,2})[.\-/](\d{2,4})\b", s)
    if m:
        d, mo, y = int(m.group(1)), int(m.group(2)), int(m.group(3))
        if y < 100: y += 2000
        try: return datetime(y, mo, d).date().isoformat()
        except: pass
    # dateutil (falls verfügbar)
    if dateparser:
        try:
            return dateparser.parse(s, dayfirst=True).date().isoformat()
        except: pass
    return None

# Pflichtfeld-Validierung
def validate_v2(obj: dict) -> list[str]:
    required = ["tabelle","titel","datum","drucksache","inhalt","published","status","fraktion"]
    missing = [k for k in required if obj.get(k) in (None, "", [])]
    errs = []
    if missing: errs.append(f"Pflichtfelder fehlen: {', '.join(missing)}")
    if obj.get("tabelle") not in {"antraege","anfragen_klein","anfragen_gross","anfragen_muendlich"}:
        errs.append("tabelle muss eine der vier erlaubten sein.")
    try:
        datetime.fromisoformat(obj["datum"])
    except Exception:
        errs.append("datum muss ISO-8601 sein (YYYY-MM-DD).")
    if obj.get("inhalt") and len(obj["inhalt"]) < 200:
        warn("Hinweis: inhalt < 200 Zeichen – prüfe OCR/Parser.")
    return errs

def content_hash(titel: str, inhalt: str) -> str:
    raw = (titel or "").strip() + "\n\n" + (inhalt or "").strip()
    return "sha256:" + hashlib.sha256(raw.encode("utf-8")).hexdigest()

# Grobe Heuristiken
def guess_drucksache(text: str) -> str | None:
    # z.B. 0246/XXI, 1234/XX
    m = re.search(r"\b(\d{3,4}\s*/\s*[XVI]{2,4})\b", text, re.IGNORECASE)
    return m.group(1).replace(" ", "") if m else None

def guess_typ_und_tabelle(text: str) -> tuple[str|None, str|None]:
    t = text.lower()
    if "mündliche anfrage" in t or "muendliche anfrage" in t:
        return "anfrage_muendlich","anfragen_muendlich"
    if "große anfrage" in t or "grosse anfrage" in t:
        return "anfrage_gross","anfragen_gross"
    if "kleine anfrage" in t:
        return "anfrage_klein","anfragen_klein"
    if "antrag" in t:
        return "antrag","antraege"
    return None, None

def guess_title(text: str) -> str | None:
    # nimm erste sinnvolle Zeile > 8 Zeichen nach Kopfbereich
    lines = [l.strip() for l in text.splitlines() if l.strip()]
    # häufig stehen ganz oben formale Zeilen – überspringe die ersten paar
    for l in lines[:50]:
        if len(l) > 8 and not l.lower().startswith(("drucksache", "bezirksverordnetenversammlung", "bvv ", "begründung", "fragen:")):
            return l
    return None

def strip_content(text: str) -> str:
    # Entferne offensichtliche Kopf-/Fußzeilen nochmal weicher
    t = re.sub(r"(?i)drucksache.*", "", text)
    # schneide vor Signatur/Anlagen, aber lass „Begründung:“/„Fragen:“ drin
    t = re.split(r"(?i)\n\s*anlage[n]?:", t)[0]
    return clean_text(t)

# Interaktive Eingaben, falls unsicher/leer
def prompt_if_missing(current: str|None, label: str, default: str|None=None, required=True) -> str:
    cur = f" [{current}]" if current else (f" [{default}]" if default else "")
    while True:
        val = input(f"{label}{cur}: ").strip()
        if not val:
            val = current or default or ""
        if required and not val:
            print("  -> Pflichtfeld, bitte ausfüllen.")
            continue
        return val

# ---------- Hauptlogik ----------

def build_json_v2(pdf_path: str, args) -> dict:
    raw = pdf_to_text(pdf_path)
    if not raw:
        err("Konnte keinen Text aus PDF extrahieren. (OCR-Fallback wäre nächste Ausbaustufe.)")
        sys.exit(2)

    # heuristische Vorschläge
    ds = guess_drucksache(raw) or ""
    typ, tabelle_auto = guess_typ_und_tabelle(raw)
    titel_guess = guess_title(raw) or ""
    inhalt_full = strip_content(raw)

    # Datum: versuche Text, sonst Datei-MTime
    datum_guess = to_iso_date(raw) or datetime.fromtimestamp(Path(pdf_path).stat().st_mtime).date().isoformat()

    # Interaktive Ergänzung/Bestätigung
    tabelle = args.tabelle or tabelle_auto or prompt_if_missing(None, "Tabelle (antraege/anfragen_klein/anfragen_gross/anfragen_muendlich)", required=True)
    typ_val = args.typ or typ or ("antrag" if tabelle=="antraege" else
                                  "anfrage_klein" if tabelle=="anfragen_klein" else
                                  "anfrage_gross" if tabelle=="anfragen_gross" else
                                  "anfrage_muendlich")
    titel = args.titel or prompt_if_missing(titel_guess, "Titel", required=True)
    datum = args.datum or prompt_if_missing(datum_guess, "Datum (YYYY-MM-DD)", required=True)
    datum = to_iso_date(datum) or datum  # normalize
    drucksache = args.drucksache or prompt_if_missing(ds, "Drucksache (z.B. 0246/XXI)", required=True)
    fraktion = args.fraktion or prompt_if_missing(None, "Fraktion (z.B. AfD-Fraktion TS)", required=True)
    status = args.status or prompt_if_missing("eingereicht", "Status (eingereicht/überwiesen/abgelehnt/beantwortet)", default="eingereicht", required=True)
    published = True if args.published else (False if args.unpublished else True)
    thema = args.thema or ""
    kategorie = args.kategorie or ""
    pdf_url = args.pdf_url or ""

    # Inhalt kürzen? – Nein, wir nehmen den Volltext.
    inhalt = inhalt_full

    obj = {
        "tabelle": tabelle,
        "titel": titel,
        "datum": datum,
        "thema": thema,
        "drucksache": drucksache,
        "inhalt": inhalt,
        "published": published,
        "status": status,
        "fraktion": fraktion,
        "pdf_url": pdf_url,
        "kategorie": kategorie,
        "meta": {
            "seiten": inhalt.count("\f") + 1 if "\f" in inhalt else None,
            "parser": "bvv-extractor v2",
            "content_hash": content_hash(titel, inhalt)
        }
    }

    # Validierung
    errs = validate_v2(obj)
    if errs:
        for e in errs: err(e)
        sys.exit(3)

    return obj

def main():
    ap = argparse.ArgumentParser(description="PDF → BVV JSON v2 Extractor")
    ap.add_argument("pdf", help="Pfad zur PDF")
    ap.add_argument("--out-dir", default="out_json", help="Zielordner (default: out_json)")
    ap.add_argument("--tabelle", choices=["antraege","anfragen_klein","anfragen_gross","anfragen_muendlich"])
    ap.add_argument("--typ", choices=["antrag","anfrage_klein","anfrage_gross","anfrage_muendlich"])
    ap.add_argument("--titel")
    ap.add_argument("--datum")           # wird normalisiert
    ap.add_argument("--drucksache")
    ap.add_argument("--fraktion")
    ap.add_argument("--status")          # eingereicht/überwiesen/abgelehnt/beantwortet
    ap.add_argument("--thema")
    ap.add_argument("--kategorie")
    ap.add_argument("--pdf-url")
    ap.add_argument("--published", action="store_true")
    ap.add_argument("--unpublished", action="store_true")
    args = ap.parse_args()

    pdf_path = args.pdf
    if not os.path.isfile(pdf_path):
        err("PDF nicht gefunden."); sys.exit(1)

    obj = build_json_v2(pdf_path, args)

    out_dir = Path(args.out_dir); out_dir.mkdir(parents=True, exist_ok=True)
    # Dateiname aus Drucksache + Typ ableiten
    safe_ds = re.sub(r"[^\w\-./]+","-", obj["drucksache"])
    fname = f"{safe_ds}_{obj['tabelle'].rstrip('e')}.json" if safe_ds else f"doc_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
    out_path = out_dir / fname

    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False, indent=2)

    info(f"Gespeichert: {out_path}")

if __name__ == "__main__":
    main()
