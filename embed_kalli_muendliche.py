
import json
import os
from openai import OpenAI
from supabase import create_client
from dotenv import load_dotenv
from tqdm import tqdm

# ⏬ Erst Umgebungsvariablen laden
load_dotenv()

# 🔧 Dann auf Umgebungsvariablen zugreifen
SUPABASE_URL = os.environ["SUPABASE_URL"]
SUPABASE_KEY = os.environ["SUPABASE_SERVICE_ROLE"]
OPENAI_KEY = os.environ["OPENAI_API_KEY"]

SUPABASE_TABLE_NAME = "anfragen_muendlich"
JSON_PATH = "kalli_anfragen_muendlich_full.json"
EMBEDDING_MODEL = "text-embedding-3-small"



openai_client = OpenAI(api_key=OPENAI_KEY)
supabase = create_client(SUPABASE_URL, SUPABASE_KEY)

# 📄 JSON laden
with open(JSON_PATH, "r", encoding="utf-8") as f:
    daten = json.load(f)

# 🧠 Einträge einbetten und speichern
for eintrag in tqdm(daten, desc="Einträge einbetten"):
    text = f"{eintrag['titel']}\n\n{eintrag['text']}"
    response = openai_client.embeddings.create(
        model="text-embedding-3-small",
        input=text
    )
    embedding = response.data[0].embedding

    supabase.table(SUPABASE_TABLE_NAME).insert({
        "titel": eintrag.get("titel"),
        "text": eintrag.get("text"),
        "datum": eintrag.get("datum"),
        "kategorie": eintrag.get("kategorie"),
        "embedding": embedding
    }).execute()

print(f"✅ Hochgeladen: {len(daten)} Datensätze in Tabelle '{SUPABASE_TABLE_NAME}'")
