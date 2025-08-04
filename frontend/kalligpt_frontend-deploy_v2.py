import os
import gradio as gr
from supabase import create_client
from dotenv import load_dotenv
from openai import OpenAI
# nur lokales Test Frontend!

# 🌱 Umgebungsvariablen laden
load_dotenv()

SUPABASE_URL = os.environ["SUPABASE_URL"]
SUPABASE_KEY = os.environ["SUPABASE_SERVICE_ROLE"]
OPENAI_API_KEY = os.environ["OPENAI_API_KEY"]

# 🔌 Clients initialisieren
supabase = create_client(SUPABASE_URL, SUPABASE_KEY)
openai_client = OpenAI(api_key=OPENAI_API_KEY)

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
            return "🚫 Leider keine passenden Inhalte gefunden."

        # Dann: nur die Top-N ausgeben
        matches = all_matches[:5]

        header = f"**{len(matches)} von {total_matches} Treffern angezeigt:**\n\n"

        antwort = "\n\n".join([
            f"📌 **{m.get('titel', 'Unbekannter Titel')}** ({m.get('kategorie', 'ohne Kategorie')}, {m.get('datum', 'kein Datum')})\n"
            + (f"🔹 Ähnlichkeit: {round(m.get('similarity', 0), 3)}\n" if debugmodus else "")
            + f"{(m.get('inhalt') or '').strip()}\n"
            + (f"[📌 PDF öffnen]({m.get('pdf_url')})" if (m.get('pdf_url') or "").startswith('http') else "🔗 Kein PDF-Link vorhanden")
            for m in matches
        ])

        return header + antwort

    except Exception as e:
        return f"💥 Fehler bei der Verarbeitung: {e}"


# 🔧 Lazy Loader Logik
table_selector = {"selected": "antraege"}
cached_results = {"text": ""}

def fetch_data(offset=0, limit=3):
    table = table_selector["selected"]

    # Einträge laden
    response = (
        supabase.table(table)
        .select("id, datum, titel, thema, drucksache, pdf_url")
        .order("datum", desc=True)
        .range(offset, offset + limit - 1)
        .execute()
    )
    data = response.data

    # Gesamtzahl bestimmen
    total_count = supabase.table(table).select("id", count="exact").execute().count

    # Text anhängen
    
    cached_results["text"] = "\n\n".join([
        f"🗕️ {entry['datum']} – {entry['thema']}\n"
        f"📝 {entry['titel']}\n"
        f"📌 Drucksache: {entry.get('drucksache', 'n/a')}\n"
        + (
            f"[📎 PDF öffnen]({entry['pdf_url']})"
            if (entry.get('pdf_url') or "").startswith("http")
            else "🚫  Kein PDF-Link vorhanden"
        )
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

def reset_output():
    cached_results["text"] = ""
    return gr.update(value=""), gr.update(value=0)


# 📦 Gradio App
with gr.Blocks() as demo:
    with gr.Tabs():
        with gr.TabItem("Fragen"):
            with gr.Row():
                frage_input = gr.Textbox(label="Was willst Du wissen?", placeholder="Stell mir eine Frage…")
                debug_checkbox = gr.Checkbox(label="Debugmodus aktivieren")
            antwort_output = gr.Markdown()
            frage_button = gr.Button("Absenden")
            frage_button.click(fn=frage_kalli, inputs=[frage_input, debug_checkbox], outputs=antwort_output)

        with gr.TabItem("Diagnose"):
            gr.Markdown("🚩 Diagnosefunktion aktuell deaktiviert.")
            # diagnose_output = gr.Textbox(label="Systembericht")
            # diagnose_button = gr.Button("Diagnose starten")
            # diagnose_button.click(fn=diagnose_kalli, outputs=diagnose_output)

        with gr.TabItem("Listen-Viewer"):
            gr.Markdown("## 📂 Anträge, Anfragen durchsuchen")

            with gr.Row():
                btn_antraege = gr.Button("📂 Anträge")
                btn_muendlich = gr.Button("💬 Mündliche Anfragen")
                btn_klein = gr.Button("📄 Kleine Anfragen")
                btn_gross = gr.Button("🗏️ Große Anfragen")

            output = gr.Markdown(label="Ergebnisse")
            reset_button = gr.Button("♻️ Zurücksetzen")
            reset_button.click(fn=lambda: gr.update(value=""), outputs=output)

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
# demo.launch()
