# ============================================================
#  BVV-Frontend
# 
#   - v1.1 (2025-09-04) [KI+Kalli]:
#       • Code refaktorisiert in Blöcke
#       • Deployment/Local-Test Switch (demo.launch)
#
#  Autoren: KI + Kalli
# ============================================================

# =============================
# BLOCK 1 — Header & Setup
# =============================

# ----- Imports & Setup -----

import os
import gradio as gr
from supabase import create_client
from dotenv import load_dotenv
from openai import OpenAI

# ----- App Version -----
__APP_VERSION__ = "Frontend BVV v1.1 (Rebuild)"


# 🌱 Umgebungsvariablen laden
load_dotenv()

SUPABASE_URL = os.environ["SUPABASE_URL"]
SUPABASE_KEY = os.environ["SUPABASE_SERVICE_ROLE"]
OPENAI_API_KEY = os.environ["OPENAI_API_KEY"]

#Konstanten
APP_TITLE = "Ein Service von Karl-Heinz -Kalli- Turban • BVV-Fraktion TeS"
LOGO_PATH = "assets/logo_160_80.png"




# 🔌 Clients initialisieren
supabase = create_client(SUPABASE_URL, SUPABASE_KEY)
openai_client = OpenAI(api_key=OPENAI_API_KEY)

# ----- CSS -----
CUSTOM_CSS = """
#footer, footer { display:none !important; }
button[aria-label="Herunterladen"], button[aria-label="Vollbild"],
button[title="Herunterladen"], button[title="Vollbild"],
button[aria-label="Fullscreen"], button[title="Fullscreen"] { display:none !important; }
.kalli-header { display:flex; align-items:center; gap:12px; padding:10px 12px;
  border-radius:12px; background:#87CEEB; overflow-x:visible; white-space:normal; }
.kalli-header::-webkit-scrollbar { display:none; }
.kalli-header { scrollbar-width:none; }
.kalli-title { font-weight:700; font-size:1.05rem; color:#000; }
.kalli-subtitle { font-weight:500; font-size:0.9rem; opacity:0.8; }
.kalli-actions { gap:12px; flex-wrap:wrap; }
.kalli-actions .gr-button { flex: 1 1 200px; }
.logo img { width:160px; height:80px; border-radius:10%; object-fit:cover; }
.kalli-event-level { font-weight: bold; color: #555; margin-bottom: 6px; }

@media print {
  body * { visibility: hidden !important; }
  #kalli-events, #kalli-events * { visibility: visible !important; }
  #kalli-events { position: absolute !important; left: 0; top: 0; width: 100%;
    padding: 0 !important; background: #fff !important; }

  /* Filterleiste, Header, Aktionen komplett aus dem Layout entfernen */
  .kalli-header, .kalli-actions, #filterbar { display: none !important; }
  .kalli-header *, .kalli-actions *, #filterbar * { display: none !important; }

  /* Sicherheitsnetz gegen Tooltips/Popover/Portals */
  [role="tooltip"], [data-testid="tooltip"], .tooltip, .popover { display: none !important; }
  #btn-clear { display: none !important; }
}
"""


# 🧠 Semantische Anfrage

def frage_kalli(prompt, debugmodus):
    try:
        response = openai_client.embeddings.create(
            input=prompt,
            model="text-embedding-3-small"
        )
        embedding = response.data[0].embedding

        # Erst: alle Treffer für Zähler abrufen (match_count hochsetzen)
        all_matches_response = supabase.rpc(
            "match_bvv_dokumente",
            {
                "query_embedding": embedding,
                "match_threshold": 0.4,
                "match_count": 999
            }
        ).execute()

        all_matches = all_matches_response.data or []
        total_matches = len(all_matches)

        if not all_matches:
            return "😕 Leider keine passenden Inhalte gefunden."

        # Dann: nur die Top-N ausgeben
        matches = all_matches[:5]

        header = f"**{len(matches)} von {total_matches} Treffern angezeigt:**\n\n"

        antwort = "\n\n".join([
            f"📌 **{m.get('titel', 'Unbekannter Titel')}** ({m.get('kategorie', 'ohne Kategorie')}, {m.get('datum', 'kein Datum')})\n"
            + (f"🔹 Ähnlichkeit: {round(m.get('similarity', 0), 3)}\n" if debugmodus else "")
            + f"{(m.get('inhalt') or '').strip()}\n"
            + (f"[📎 PDF öffnen]({m.get('pdf_url')})" if (m.get('pdf_url') or "").startswith('http') else "🔗 Kein PDF-Link vorhanden")
            for m in matches
        ])

        return header + antwort

    except Exception as e:
        return f"💥 Fehler bei der Verarbeitung: {e}"



# 🧪 Diagnosefunktion
def diagnose_kalli():
    report = []
    try:
        supabase.table("antraege").select("id").limit(1).execute()
        report.append("✅ Supabase-Verbindung OK")
    except Exception as e:
        report.append(f"❌ Supabase-Verbindung fehlgeschlagen: {e}")

    try:
        view = supabase.table("match_bvv_dokumente").select("*").limit(1).execute()
        keys = list(view.data[0].keys()) if view.data else []
        if "pdf_url" in keys:
            report.append("✅ View `match_bvv_dokumente` liefert `pdf_url`")
        else:
            report.append("⚠️ View OK, aber `pdf_url` fehlt")
    except Exception as e:
        report.append(f"❌ Fehler beim Lesen der View: {e}")

    try:
        embedding = openai_client.embeddings.create(
            input="Testfrage zur Verkehrssicherheit",
            model="text-embedding-3-small"
        ).data[0].embedding

        result = supabase.rpc(
            "match_bvv_dokumente",
            {
                "query_embedding": embedding,
                "match_threshold": 0.2,
                "match_count": 1
            }
        ).execute()

        if not result.data:
            report.append("⚠️ RPC erfolgreich, aber keine Ergebnisse geliefert")
        elif "pdf_url" in result.data[0]:
            report.append("✅ RPC liefert `pdf_url` mit")
        else:
            report.append("⚠️ RPC liefert Ergebnis, aber kein `pdf_url`")
    except Exception as e:
        report.append(f"❌ Fehler bei RPC-Test: {e}")

    return "\n".join(report)

# 🔧 Lazy Loader Logik
table_selector = {"selected": "antraege"}
cached_results = {"text": ""}


def fetch_data(offset=0, limit=3):
    table = table_selector["selected"]

    # Einträge laden
    response = (
        supabase.table(table)
        .select("id, datum, titel, thema, drucksache")
        .order("datum", desc=True)
        .range(offset, offset + limit - 1)
        .execute()
    )
    data = response.data

    # Gesamtzahl bestimmen
    total_count = supabase.table(table).select("id", count="exact").execute().count

    # Text anhängen
    cached_results["text"] += ("\n\n" if cached_results["text"] else "") + "\n\n".join([
        f"📅 {entry['datum']} – {entry['thema']}\n📝 {entry['titel']}\n📎 Drucksache: {entry.get('drucksache', 'n/a')}"
        for entry in data
    ])

    next_offset = offset + limit
    more_to_load = next_offset < total_count

    # Header-Zeile
    header = f"**{min(next_offset, total_count)} von {total_count} Einträgen angezeigt:**\n\n---\n"

    # Sichtbarkeit des Buttons dynamisch
    show_button = gr.update(visible=more_to_load)

    return header + cached_results["text"], next_offset, show_button



def show_entries(table, offset=0):
    table_selector["selected"] = table
    cached_results["text"] = ""
    offset_box = 0
    return fetch_data(offset=0)


# =============================
# BLOCK 4 — UI & Handlers
# =============================

CUSTOM_CSS += """
.kalli-disclaimer {
  display:flex; align-items:center; gap:14px;
  background:#ffebcc; color:#333;
  padding:10px 14px; border:1px solid #e6c07b; border-radius:8px;
}
@media (max-width:700px){
  .kalli-disclaimer { flex-direction:column; align-items:stretch; }
}
"""

# 📦 Gradio App


with gr.Blocks(css=CUSTOM_CSS, title=f"{APP_TITLE} · {__APP_VERSION__}") as demo:
#with gr.Blocks() as demo:

    # Disclaimer-Row
    with gr.Row(visible=True, elem_classes="kalli-disclaimer") as disclaimer_box:
        gr.HTML(
            "⚠️ Hinweis: Diese Anwendung lädt Schriften von externen Anbietern "
            "(z. B. Google Fonts). Wenn du das nicht möchtest, nutze die App bitte nicht weiter."
        )
        understood = gr.Checkbox(label="Verstanden (nicht mehr anzeigen)", value=False)

    def _toggle_disclaimer(checked: bool):
        return gr.update(visible=not checked)

    understood.change(_toggle_disclaimer, inputs=understood, outputs=disclaimer_box)

    with gr.Tabs():
        with gr.TabItem("Fragen"):
            with gr.Row():
                frage_input = gr.Textbox(label="Was willst Du wissen?", placeholder="Stell mir eine Frage…")
                debug_checkbox = gr.Checkbox(label="Debugmodus aktivieren")
            antwort_output = gr.Markdown()
            frage_button = gr.Button("Absenden")
            frage_button.click(fn=frage_kalli, inputs=[frage_input, debug_checkbox], outputs=antwort_output)

        #with gr.TabItem("Diagnose"):
        #    diagnose_output = gr.Textbox(label="Systembericht")
        #    diagnose_button = gr.Button("Diagnose starten")
        #    diagnose_button.click(fn=diagnose_kalli, outputs=diagnose_output)

        with gr.TabItem("Polit-Viewer"):
            gr.Markdown("## 📂 Politische Dokumente durchsuchen")

            with gr.Row():
                btn_antraege = gr.Button("🗂️ Anträge")
                btn_muendlich = gr.Button("💬 Mündliche Anfragen")
                btn_klein = gr.Button("📄 Kleine Anfragen")
                btn_gross = gr.Button("🧾 Große Anfragen")

            output = gr.Textbox(label="Ergebnisse", lines=20)
            offset_box = gr.Number(value=0, visible=False)
            more_button = gr.Button("🔁 Mehr anzeigen", visible=False)

            btn_antraege.click(fn=show_entries, inputs=[gr.Textbox(value="antraege", visible=False)],
                               outputs=[output, offset_box, more_button])
            btn_muendlich.click(fn=show_entries, inputs=[gr.Textbox(value="anfragen_muendlich", visible=False)],
                                outputs=[output, offset_box, more_button])
            btn_klein.click(fn=show_entries, inputs=[gr.Textbox(value="anfragen_klein", visible=False)],
                            outputs=[output, offset_box, more_button])
            btn_gross.click(fn=show_entries, inputs=[gr.Textbox(value="anfragen_gross", visible=False)],
                            outputs=[output, offset_box, more_button])

            more_button.click(fn=fetch_data, inputs=[offset_box],
                              outputs=[output, offset_box, more_button])


# Für Deployment auf Render oder Server
demo.queue().launch(server_name="0.0.0.0", server_port=int(os.environ.get("PORT", 7860)))

# Für lokale Ausführung (z. B. auf dem eigenen PC)
#demo.launch()
