import os
import sys
import json
from dotenv import load_dotenv
from uuid import uuid4
from datetime import datetime
from openai import OpenAI
from supabase import create_client

# 🌱 .env laden
load_dotenv()

SUPABASE_URL = os.environ["SUPABASE_URL"]
SUPABASE_KEY = os.environ["SUPABASE_SERVICE_ROLE"]
OPENAI_API_KEY = os.environ["OPENAI_API_KEY"]
client = OpenAI(api_key=OPENAI_API_KEY)
supabase = create_client(SUPABASE_URL, SUPABASE_KEY)

# 🔁 Hilfsfunktion zum Loggen
def log(message):
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    with open("./log/embedding_log.txt", "a", encoding="utf-8") as logfile:
        logfile.write(f"[{timestamp}] {message}\n")

# 🔧 Hauptfunktion
def embed_and_insert(json_path):
    try:
        with open(json_path, "r", encoding="utf-8") as f:
            eintrag = json.load(f)
    except Exception as e:
        log(f"[❌] {json_path} → Fehler beim Einlesen: {e}")
        return

    # Sicherheitscheck & Defaults
    for field in ["Titel", "Datum", "Thema", "Drucksache", "Kurzbeschreibung"]:
        eintrag[field] = eintrag.get(field) or ""

    # 🧠 Embedding erzeugen
    try:
        embedding = client.embeddings.create(
            model="text-embedding-3-small",
            input=f"{eintrag['Titel']}\n{eintrag['Kurzbeschreibung']}"
        ).data[0].embedding
    except Exception as e:
        log(f"[❌] {eintrag['Drucksache']} → Fehler beim Embedding: {e}")
        return

    # Tabelle aus Dateipfad ableiten
    table_map = {
        "antraege": "antraege",
        "muendlich": "anfragen_muendlich",
        "klein": "anfragen_klein",
        "gross": "anfragen_gross"
    }
    tabelle = "antraege"  # Fallback
    for key in table_map:
        if key in json_path:
            tabelle = table_map[key]
            break

    # Prüfen auf Duplikat
    result = supabase.table(tabelle).select("*").eq("drucksache", eintrag["Drucksache"]).execute()
    if len(result.data) > 0:
        log(f"[⚠️] {eintrag['Drucksache']} → Übersprungen (Duplikat)")
        return

    # Einfügen in DB
    try:
        supabase.table(tabelle).insert({
            "id": str(uuid4()),
            "titel": eintrag["Titel"],
            "datum": eintrag["Datum"],
            "thema": eintrag["Thema"],
            "drucksache": eintrag["Drucksache"],
            "inhalt": eintrag["Kurzbeschreibung"],
            "embedding": embedding
        }).execute()
        log(f"[✓] {eintrag['Drucksache']} → Eingefügt")
    except Exception as e:
        log(f"[❌] {eintrag['Drucksache']} → Fehler beim Insert: {e}")

# ▶️ Scriptstart
if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("❌ Bitte Dateipfad zur JSON-Datei übergeben.")
        sys.exit(1)
    embed_and_insert(sys.argv[1])
