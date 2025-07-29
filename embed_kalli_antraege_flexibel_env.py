
import sys
import os
import json
from datetime import datetime
import uuid
import requests
from openai import OpenAI
from dotenv import load_dotenv

# === .env laden ===
load_dotenv()

# === KONFIGURATION ===
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_API_KEY = os.getenv("SUPABASE_SERVICE_ROLE")
SUPABASE_TABLE = "antraege"
EMBEDDING_MODEL = "text-embedding-3-small"

client = OpenAI(api_key=OPENAI_API_KEY)

HEADERS = {
    "apikey": SUPABASE_API_KEY,
    "Authorization": f"Bearer {SUPABASE_API_KEY}",
    "Content-Type": "application/json"
}

# === JSON-Dateipfad über Kommandozeile ===
if len(sys.argv) < 2:
    print("❌ Fehler: Bitte JSON-Dateipfad angeben.")
    print("▶️ Beispiel: python embed_kalli_antraege_flexibel.py json/antraege.json")
    sys.exit(1)

json_path = sys.argv[1]

if not os.path.exists(json_path):
    print(f"❌ Datei nicht gefunden: {json_path}")
    sys.exit(1)

with open(json_path, encoding="utf-8") as f:
    daten = json.load(f)

def generate_embedding(text):
    try:
        response = client.embeddings.create(
            input=text,
            model=EMBEDDING_MODEL
        )
        return response.data[0].embedding
    except Exception as e:
        print(f"❌ Fehler bei Embedding: {e}")
        return None

def upload_to_supabase(eintrag, embedding):
    payload = {
        "id": str(uuid.uuid4()),
        "titel": eintrag["Titel"],
        "datum": datetime.strptime(eintrag["Datum"], "%d.%m.%Y").date().isoformat(),
        "thema": eintrag["Thema"],
        "drucksache": eintrag["Drucksache"],
        "inhalt": eintrag["Kurzbeschreibung"],
        "embedding": embedding
    }

    response = requests.post(f"{SUPABASE_URL}/rest/v1/{SUPABASE_TABLE}", headers=HEADERS, json=payload)

    if response.status_code == 201:
        print(f"✅ Hochgeladen: {eintrag['Titel']}")
    else:
        print(f"❌ Fehler bei: {eintrag['Titel']} → {response.status_code}: {response.text}")

# === Hauptlauf ===
for eintrag in daten:
    print(f"➡️ Verarbeite: {eintrag['Titel']}")
    embedding = generate_embedding(eintrag["Kurzbeschreibung"])
    if embedding:
        upload_to_supabase(eintrag, embedding)
