#!/usr/bin/env python3
import os, sys, json, glob, hashlib
from pathlib import Path
from typing import List, Dict
from uuid import uuid4
from supabase import create_client, Client
from openai import OpenAI
from dotenv import load_dotenv
#python .\embed_from_json_v2.py .\1479-XXI.json


# 🌱 .env laden
env_path = Path(__file__).parent / ".env"
load_dotenv(dotenv_path=env_path)

# Erwartete Variablen
REQUIRED_VARS = ["SUPABASE_URL", "SUPABASE_SERVICE_ROLE", "OPENAI_API_KEY"]
missing = [var for var in REQUIRED_VARS if not os.getenv(var)]
if missing:
    raise RuntimeError(f"❌ Fehlende Variablen: {', '.join(missing)} → bitte .env prüfen!")

SUPABASE_URL = os.environ["SUPABASE_URL"]
SUPABASE_KEY = os.environ["SUPABASE_SERVICE_ROLE"]
OPENAI_API_KEY = os.environ["OPENAI_API_KEY"]

# Clients
sb: Client = create_client(SUPABASE_URL, SUPABASE_KEY)
oc = OpenAI(api_key=OPENAI_API_KEY)

# 🔧 Embedding-Parameter
EMB_MODEL  = "text-embedding-3-small"    # 1536 dims
BATCH_SIZE = 64
SLEEP_429  = 2.0

# Erlaubte Quelltabellen
ALLOWED_TABLES = {"antraege", "anfragen_klein", "anfragen_gross", "anfragen_muendlich"}


# --- Helfer ---
def embed_text(text: str) -> List[float]:
    """Embedding für Text erzeugen (OpenAI)."""
    resp = oc.embeddings.create(input=text, model=EMB_MODEL)
    return resp.data[0].embedding


def collect_json_inputs(path_like: str):
    """
    Nimmt einen Pfad entgegen und liefert eine Liste von JSON-Dateien zurück.
    - Einzelne Datei → Liste mit genau dieser Datei
    - Ordner → alle *.json drin
    - Glob-Pattern (*.json) → alle Treffer
    """
    p = Path(path_like)
    if p.is_file():
        return [str(p)]
    if p.is_dir():
        return sorted(glob.glob(str(p / "*.json")))
    return sorted(glob.glob(path_like))  # z. B. "*.json"

def _clean_text(s: str) -> str:     # entfernt Kontrollcharakter wie nl
    if not s:
        return ""
    import re
    s = s.replace("\r\n", "\n").replace("\r", "\n")
    # alle Steuerzeichen außer \n und \t entfernen
    s = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f]", " ", s)
    # Doppelleerzeichen weg
    s = re.sub(r"[ \t]+", " ", s)
    # mehr als 2 Zeilenumbrüche -> auf 2 reduzieren
    s = re.sub(r"\n{3,}", "\n\n", s)
    return s.strip()

def pre_sanitize_json(raw: str) -> str:
    """Macht JSON mit multiline-Strings/Steuerzeichen parsebar:
       - Ersetzt LF innerhalb Strings durch '\\n'
       - Entfernt CR
       - Killt Control-Chars <0x20 (außer \t) innerhalb Strings
       - NBSP -> Space
    """
    raw = raw.replace("\u00A0", " ")  # NBSP -> Space
    out = []
    in_str = False
    esc = False
    for ch in raw:
        if esc:
            out.append(ch)
            esc = False
            continue
        if ch == '\\':
            out.append(ch)
            esc = True
            continue
        if ch == '"':
            out.append(ch)
            in_str = not in_str
            continue
        # nur innerhalb von Strings bereinigen
        if in_str:
            o = ord(ch)
            if ch == '\r':
                # drop CR
                continue
            if ch == '\n':
                out.append('\\n')
                continue
            if o < 0x20 and ch != '\t':
                out.append(' ')
                continue
        out.append(ch)
    return ''.join(out)




def run(json_dir: str, dry_run: bool = False):
    """
    Hauptlogik: Einlesen von JSON-Dateien, Embeddings erzeugen, optional Upsert nach Supabase.
    """
    files = collect_json_inputs(json_dir)

    if not files:
        print(f"[i] Keine JSONs gefunden unter: {json_dir}")
        return

    print(f"[i] Scanne {len(files)} Datei(en) unter: {json_dir}")
    for p in files:
        print(f"    - {Path(p).name}")

    new_cnt, skip_cnt = 0, 0
    for fn in files:
        try:
            #with open(fn, "r", encoding="utf-8-sig") as f:
            #    data = json.load(f)
            with open(fn, "r", encoding="utf-8-sig") as f:
                raw_text = f.read()
            sanitized = pre_sanitize_json(raw_text)
            data = json.loads(sanitized)

        except Exception as e:
            print(f"[!] {fn}: JSON-Fehler → {e}")
            skip_cnt += 1
            continue

        # Sowohl flache JSONs (v2) als auch verschachtelte (meta/vorgang) akzeptieren
        meta = data.get("meta", {})
        vorgang = data.get("vorgang", data)

        # Pflichtfelder prüfen
        if not vorgang.get("titel") or not vorgang.get("inhalt"):
            print(f"[!] {Path(fn).name}: fehlende Pflichtfelder → übersprungen")
            skip_cnt += 1
            continue

        # Inhalt säubern
        orig_len = len(vorgang["inhalt"])
        vorgang["inhalt"] = _clean_text(vorgang["inhalt"])
        if len(vorgang["inhalt"]) != orig_len:
            print(f"[~] {Path(fn).name}: Inhalt bereinigt ({orig_len} → {len(vorgang['inhalt'])} Zeichen)")

        # Hash bilden
        content_hash = hashlib.sha256(
            (vorgang.get("titel", "") + vorgang.get("inhalt", "")).encode("utf-8")
        ).hexdigest()

        # Embedding erzeugen
        try:
            emb_input = f"Titel: {vorgang['titel']}\n\n{vorgang['inhalt']}"
            emb = embed_text(emb_input)
        except Exception as e:
            print(f"[!] {Path(fn).name}: Fehler beim Embedding → {e}")
            skip_cnt += 1
            continue

        if dry_run:
            print(f"[dry] {Path(fn).name}: ok → Tabelle={meta.get('tabelle') or data.get('tabelle')}; hash={content_hash[:8]}...")
            continue

        # >>> AB HIER NEU: in der Schleife bleiben! <<<
        table = (meta.get("tabelle") or data.get("tabelle") or vorgang.get("tabelle"))
        if table not in ALLOWED_TABLES:
            print(f"[!] {Path(fn).name}: ungültige Tabelle '{table}' → skip")
            skip_cnt += 1
            continue

        # vorhandene ID über drucksache suchen
        doc_id = vorgang.get("id")
        if not doc_id and vorgang.get("drucksache"):
            exist = sb.table(table).select("id").eq("drucksache", vorgang["drucksache"]).limit(1).execute().data or []
            if exist:
                doc_id = exist[0]["id"]

        # wenn immer noch keine ID -> neu generieren
        if not doc_id:
            doc_id = str(uuid4())

        # Upsert in Supabase (Quelltabelle)
        try:
            sb.table(table).upsert({
                "id": doc_id,
                "titel":      vorgang["titel"],
                "inhalt":     vorgang["inhalt"],
                "datum":      vorgang.get("datum"),
                "kategorie":  vorgang.get("kategorie"),
                "thema":      vorgang.get("thema"),
                "pdf_url":    vorgang.get("pdf_url"),
                "drucksache": vorgang.get("drucksache"),
                "fraktion":   vorgang.get("fraktion"),
                "einreicher": vorgang.get("einreicher"),
                "status":     vorgang.get("status"),
                "published":  bool(vorgang.get("published", False)),
                "embedding":  emb,  # nur wenn du die Spalte in der Quelltabelle halten willst
            }, on_conflict="id").execute()

            # Spiegel in vorgang_embeddings (für Semantik)
            sb.table("vorgang_embeddings").upsert({
                "id": doc_id,
                "embedding": emb
            }, on_conflict="id").execute()

            print(f"[✓] {Path(fn).name}: upsert → {table} & vorgang_embeddings (id={doc_id[:8]}…)")
            new_cnt += 1

        except Exception as e:
            print(f"[!] {Path(fn).name}: Fehler beim Upsert → {e}")
            skip_cnt += 1
            continue


    print(f"[i] Done. Neu/aktualisiert: {new_cnt}, übersprungen: {skip_cnt}")


# --- Main ---
if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python embed_from_json_v2.py <json_file_or_dir> [--dry-run]")
        sys.exit(1)

    path = sys.argv[1]
    dry = "--dry-run" in sys.argv
    run(path, dry_run=dry)
