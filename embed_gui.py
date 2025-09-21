#!/usr/bin/env python3
import gradio as gr
from pathlib import Path
import json, sys, subprocess, re, unicodedata, datetime

EMBEDDER_DEFAULT = str((Path(__file__).parent / "embed_from_json_v2.py").resolve())
ALLOWED_TABLES = ["antraege","anfragen_klein","anfragen_gross","anfragen_muendlich"]
STATI = ["eingereicht","beantwortet","abgelehnt","in Bearbeitung","zurückgezogen","überwiesen","sonstiges"]

# --- helpers ------------------------------------------------------------
def clean_text(s: str) -> str:
    if not s: return ""
    s = unicodedata.normalize("NFKC", s)
    s = s.replace("\r\n","\n").replace("\r","\n")
    s = s.replace("\u00A0"," ").replace("\u202F"," ")
    s = s.replace("„","\"").replace("“","\"").replace("‚","'").replace("’","'")
    s = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f]", " ", s)
    s = re.sub(r"[ \t]+", " ", s)
    s = re.sub(r"\n{3,}", "\n\n", s)
    return s.strip()

def validate_flat(doc: dict) -> list[str]:
    errs = []
    req = ["tabelle","titel","datum","drucksache","inhalt","status","fraktion"]
    miss = [k for k in req if not (doc.get(k) or "").strip()]
    if miss: errs.append("Pflichtfelder fehlen: " + ", ".join(miss))
    if doc.get("tabelle") not in ALLOWED_TABLES:
        errs.append("tabelle ungültig")
    try:
        datetime.date.fromisoformat(doc.get("datum",""))
    except Exception:
        errs.append("datum muss YYYY-MM-DD sein")
    if len(doc.get("inhalt","")) < 200:
        errs.append("inhalt zu kurz (<200 Zeichen)")
    return errs

def save_json(doc: dict, outdir: str) -> str:
    outdir_p = Path(outdir).expanduser().resolve()
    outdir_p.mkdir(parents=True, exist_ok=True)
    name = (doc.get("drucksache") or "unbenannt").replace("/","-").replace("\\","-") + ".json"
    fp = outdir_p / name
    fp.write_text(json.dumps(doc, ensure_ascii=False, indent=2), encoding="utf-8")
    return str(fp)

def run_embedder(embedder_path: str, json_path: str, dry_run: bool) -> str:
    p = Path(embedder_path) if embedder_path else Path(EMBEDDER_DEFAULT)
    cmd = [sys.executable, str(p), json_path]
    if dry_run:
        cmd.append("--dry-run")
    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    out, _ = proc.communicate()
    return out

# --- Tab 1: JSON importieren -------------------------------------------
def import_preview(file_obj):
    if not file_obj:
        return "", "Bitte JSON-Datei auswählen."
    try:
        raw = file_obj.read().decode("utf-8-sig")
        data = json.loads(raw)
    except Exception as e:
        return "", f"❌ JSON-Fehler: {e}"

    doc = data.get("vorgang", data)  # flach oder verschachtelt
    # nur Mini-Check, echte Validierung macht dein Embedder
    md = (
        f"**Tabelle:** {doc.get('tabelle')}\n\n"
        f"**Titel:** {doc.get('titel')}\n\n"
        f"**Datum / Drucksache:** {doc.get('datum')} · {doc.get('drucksache')}\n\n"
        f"**Status / Fraktion:** {doc.get('status')} · {doc.get('fraktion')}\n\n"
        f"**Inhalt (Ausschnitt):**\n\n{(doc.get('inhalt') or '')[:600]}{'…' if len(doc.get('inhalt') or '')>600 else ''}"
    )
    tmp = Path.cwd() / "_tmp_embed"; tmp.mkdir(exist_ok=True)
    out = tmp / ((doc.get("drucksache") or "unbenannt").replace("/","-") + ".json")
    out.write_text(json.dumps(doc, ensure_ascii=False, indent=2), encoding="utf-8")  # unverändert; Embedder cleaned
    return str(out), f"✅ JSON geladen & gesichert: {out}\n\n{md}"

def import_embed(cleaned_path: str, embedder_path: str, dry_run: bool):
    if not cleaned_path:
        return "Bitte zuerst Vorschau ausführen."
    if not Path(cleaned_path).exists():
        return "Temp-JSON nicht gefunden – bitte Vorschau erneut ausführen."
    try:
        log = run_embedder(embedder_path, cleaned_path, dry_run)
        return f"🧠 Embedder-Log:\n{log}"
    except Exception as e:
        return f"❌ Embedder-Fehler: {e}"

# --- Tab 2: Manuell erfassen -------------------------------------------
def manual_clean(inhalt):
    c = clean_text(inhalt or "")
    msg = "Bereinigt." if c != (inhalt or "") else "Text war bereits sauber."
    return c, msg

def manual_save(tabelle,titel,datum,drucksache,fraktion,status,thema,kategorie,pdf_url,inhalt,outdir):
    doc = {
        "tabelle": tabelle,
        "titel": (titel or "").strip(),
        "datum": (datum or "").strip(),
        "thema": (thema or "").strip() or None,
        "drucksache": (drucksache or "").strip(),
        "inhalt": clean_text(inhalt or ""),
        "published": True,
        "status": (status or "").strip(),
        "fraktion": (fraktion or "").strip(),
        "pdf_url": (pdf_url or "").strip(),
        "kategorie": (kategorie or "").strip() or None,
    }
    errs = validate_flat(doc)
    if errs:
        return "", "❌ " + "\n❌ ".join(errs)
    path = save_json(doc, outdir or ".")
    return path, f"💾 JSON gespeichert: {path}"

def manual_save_embed(tabelle,titel,datum,drucksache,fraktion,status,thema,kategorie,pdf_url,inhalt,outdir,embedder_path,dry_run):
    p, msg = manual_save(tabelle,titel,datum,drucksache,fraktion,status,thema,kategorie,pdf_url,inhalt,outdir)
    if not p:
        return "", msg
    log = run_embedder(embedder_path, p, dry_run)
    return p, f"{msg}\n\n🧠 Embedder-Log:\n{log}"

# --- UI -----------------------------------------------------------------
with gr.Blocks(title="BVV · JSON importieren oder manuell erfassen") as app:
    gr.Markdown("## 🧱 BVV • JSON importieren **oder** manuell erfassen\nSchlank & sicher: JSON prüfen/bauen → an **embed_from_json_v2.py** übergeben (optional **Dry-Run**).")

    with gr.Tabs():
        with gr.TabItem("📂 JSON importieren"):
            f = gr.File(file_types=[".json"], label="JSON-Datei wählen")
            embedder1 = gr.Textbox(label="Pfad zu embed_from_json_v2.py", value=EMBEDDER_DEFAULT)
            dry1 = gr.Checkbox(label="Dry-Run (nur testen)", value=False)
            btn_prev = gr.Button("🔎 Vorschau sichern")
            btn_run  = gr.Button("🤖 Jetzt embedden", variant="primary")
            cleaned1 = gr.Textbox(label="Temp-JSON", interactive=False)
            log1 = gr.Markdown()

            btn_prev.click(import_preview, inputs=[f], outputs=[cleaned1, log1])
            btn_run.click(import_embed, inputs=[cleaned1, embedder1, dry1], outputs=[log1])

        with gr.TabItem("✍️ Manuell erfassen"):
            tabelle = gr.Dropdown(ALLOWED_TABLES, label="Tabelle", value="anfragen_gross")
            status  = gr.Dropdown(STATI, label="Status", value="eingereicht")
            with gr.Row():
                titel = gr.Textbox(label="Titel", placeholder="z. B. PV-Anlagen auf Liegenschaften")
                datum = gr.Textbox(label="Datum (YYYY-MM-DD)")
                drs   = gr.Textbox(label="Drucksache", placeholder="1733/XXI")
            with gr.Row():
                frak  = gr.Textbox(label="Fraktion", placeholder="AfD-Fraktion Tempelhof-Schöneberg")
                thema = gr.Textbox(label="Thema (optional)")
                kat   = gr.Textbox(label="Kategorie (optional)")
            pdf    = gr.Textbox(label="PDF URL (optional)")
            inhalt = gr.Textbox(label="Inhalt (Volltext, paste)", lines=14)

            with gr.Row():
                btn_clean = gr.Button("🧹 Text bereinigen")
                clean_info = gr.Markdown()

            outdir = gr.Textbox(label="Ausgabe-Ordner", value=str(Path.cwd()))
            embedder2 = gr.Textbox(label="Pfad zu embed_from_json_v2.py", value=EMBEDDER_DEFAULT)
            dry2 = gr.Checkbox(label="Dry-Run (nur testen)", value=False)

            with gr.Row():
                btn_save = gr.Button("💾 Nur JSON speichern")
                btn_save_embed = gr.Button("💾 Speichern + 🤖 embedden", variant="primary")

            saved = gr.Textbox(label="Gespeichert unter", interactive=False)
            log2  = gr.Textbox(label="Log / Hinweise", lines=10)

            btn_clean.click(manual_clean, inputs=[inhalt], outputs=[inhalt, clean_info])
            btn_save.click(manual_save, inputs=[tabelle,titel,datum,drs,frak,status,thema,kat,pdf,inhalt,outdir],
                           outputs=[saved, log2])
            btn_save_embed.click(manual_save_embed,
                                 inputs=[tabelle,titel,datum,drs,frak,status,thema,kat,pdf,inhalt,outdir,embedder2,dry2],
                                 outputs=[saved, log2])

if __name__ == "__main__":
    app.launch()
