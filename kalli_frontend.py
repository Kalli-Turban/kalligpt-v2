import os
import gradio as gr
from supabase import create_client
from dotenv import load_dotenv
from openai import OpenAI

# 🌱 Umgebungsvariablen laden
load_dotenv()

SUPABASE_URL = os.environ["SUPABASE_URL"]
SUPABASE_KEY = os.environ["SUPABASE_SERVICE_ROLE"]
OPENAI_API_KEY = os.environ["OPENAI_API_KEY"]

# 🔌 Clients initialisieren
supabase = create_client(SUPABASE_URL, SUPABASE_KEY)
openai_client = OpenAI(api_key=OPENAI_API_KEY)

# 🔍 Semantische Abfrage an match_bvv_dokumente
def frage_kalli(prompt):
    print(f"\n🟡 Neue Anfrage: {prompt}")

    try:
        # 🧠 Embedding erzeugen (neue Syntax!)
        response = openai_client.embeddings.create(
            input=prompt,
            model="text-embedding-3-small"
        )
        embedding = response.data[0].embedding
        print(f"🔹 Embedding erzeugt. Länge: {len(embedding)}")

        # 📡 RPC ausführen
        response = supabase.rpc(
            "match_bvv_dokumente",
            {
                "query_embedding": embedding,
                "match_threshold": 0.4,
                "match_count": 3
            }
        ).execute()

        matches = response.data or []
        print(f"🟢 Treffer: {len(matches)}")

        if not matches:
            return "😕 Leider keine passenden Inhalte gefunden."

        # ✍️ Ausgabe formatieren
        antwort = "\n\n".join([
            f"📌 **{m['titel']}** ({m['kategorie']}, {m['datum']})\n{m.get('inhalt', '').strip()}"
            for m in matches
        ])
        return antwort

    except Exception as e:
        print(f"🔴 Fehler bei Anfrage: {e}")
        return f"💥 Fehler bei der Verarbeitung: {e}"

# 🎛️ Gradio UI starten
iface = gr.Interface(
    fn=frage_kalli,
    inputs=gr.Textbox(label="Was willst Du wissen?", placeholder="Stell mir eine Frage…"),
    outputs=gr.Markdown(label="Antwort von KalliGPT"),
    title="KalliGPT 🧠",
    description="Frage Kalli nach BVV-Anträgen und Anfragen – direkt aus der Datenbank!"
)

iface.launch()
