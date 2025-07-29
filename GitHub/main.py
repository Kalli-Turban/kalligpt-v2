import os
import gradio as gr
from supabase import create_client
from dotenv import load_dotenv
from openai import OpenAI

load_dotenv()

SUPABASE_URL = os.environ["SUPABASE_URL"]
SUPABASE_KEY = os.environ["SUPABASE_SERVICE_ROLE"]
OPENAI_API_KEY = os.environ["OPENAI_API_KEY"]

supabase = create_client(SUPABASE_URL, SUPABASE_KEY)
openai_client = OpenAI(api_key=OPENAI_API_KEY)

def frage_kalli(prompt, debugmodus):
    try:
        response = openai_client.embeddings.create(
            input=prompt,
            model="text-embedding-3-small"
        )
        embedding = response.data[0].embedding

        response = supabase.rpc(
            "match_bvv_dokumente",
            {
                "query_embedding": embedding,
                "match_threshold": 0.4,
                "match_count": 3
            }
        ).execute()

        matches = response.data or []
        if not matches:
            return "😕 Leider keine passenden Inhalte gefunden."

        antwort = "\n\n".join([
            f"📌 **{m['titel']}** ({m['kategorie']}, {m['datum']})\n"
            + (f"🔹 Ähnlichkeit: {round(m['similarity'], 3)}\n" if debugmodus else "")
            + f"{m.get('inhalt', '').strip()}\n"
            + (f"[📎 PDF öffnen]({m['pdf_url']})" if m.get('pdf_url') else "")
            for m in matches
        ])

        return antwort

    except Exception as e:
        return f"💥 Fehler bei der Verarbeitung: {e}"

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

table_selector = {"selected": "antraege"}
cached_results = {"text": ""}

def fetch_data(offset=0, limit=3):
    table = table_selector["selected"]
    response = (
        supabase.table(table)
        .select("id, datum, titel, thema, drucksache")
        .order("datum", desc=True)
        .range(offset, offset + limit - 1)
        .execute()
    )
    data = response.data
    total_count = supabase.table(table).select("id", count="exact").execute().count

    new_text = "\n\n".join([
        f"📅 {entry['datum']} – {entry['thema']}\n📝 {entry['titel']}\n📎 Drucksache: {entry.get('drucksache', 'n/a')}"
        for entry in data
    ])

    cached_results["text"] += ("\n\n" if cached_results["text"] else "") + new_text
    next_offset = offset + limit
    more_to_load = next_offset < total_count

    import gr
    return cached_results["text"], next_offset, gr.update(visible=more_to_load)

def show_entries(table, offset=0):
    table_selector["selected"] = table
    cached_results["text"] = ""
    return fetch_data(offset)

def polit_viewer_ui():
    with gr.Blocks() as demo:
        gr.Markdown("## 📂 Politische Dokumente durchsuchen")
        with gr.Row():
            btn_antraege = gr.Button("🗂️ Anträge")
            btn_muendlich = gr.Button("💬 Mündliche Anfragen")
            btn_klein = gr.Button("📄 Kleine Anfragen")
            btn_gross = gr.Button("🧾 Große Anfragen")

        output = gr.Textbox(label="Ergebnisse", lines=20)
        offset_box = gr.Number(value=0, visible=False)
        more_button = gr.Button("🔁 Mehr anzeigen", visible=False)

        btn_antraege.click(fn=show_entries, inputs=[gr.Textbox(value="antraege", visible=False)], outputs=[output, offset_box, more_button])
        btn_muendlich.click(fn=show_entries, inputs=[gr.Textbox(value="anfragen_muendlich", visible=False)], outputs=[output, offset_box, more_button])
        btn_klein.click(fn=show_entries, inputs=[gr.Textbox(value="anfragen_klein", visible=False)], outputs=[output, offset_box, more_button])
        btn_gross.click(fn=show_entries, inputs=[gr.Textbox(value="anfragen_gross", visible=False)], outputs=[output, offset_box, more_button])

        more_button.click(fn=fetch_data, inputs=[offset_box], outputs=[output, offset_box, more_button])
    return demo

with gr.Blocks() as demo:
    with gr.Tabs():
        with gr.TabItem("Fragen"):
            gr.Interface(
                fn=frage_kalli,
                inputs=[
                    gr.Textbox(label="Was willst Du wissen?", placeholder="Stell mir eine Frage…"),
                    gr.Checkbox(label="Debugmodus aktivieren")
                ],
                outputs=gr.Markdown(label="Antwort von KalliGPT")
            ).render()

        with gr.TabItem("Diagnose"):
            gr.Interface(
                fn=diagnose_kalli,
                inputs=[],
                outputs=gr.Textbox(label="Systembericht")
            ).render()

        with gr.TabItem("Polit-Viewer"):
            polit_viewer_ui()

demo.launch(server_name="0.0.0.0", server_port=int(os.environ.get("PORT", 8080)))
