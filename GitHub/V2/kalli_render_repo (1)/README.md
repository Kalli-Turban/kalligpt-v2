# KalliGPT Polit-Frontend

Dies ist das semantische Frontend für BVV-Dokumente von Kalli, bereit für Render.com-Deployment.

## Features

- Fragen an Kalli mit KI-gestützter Embedding-Suche
- Polit-Viewer mit Lazy Loading
- Supabase-Integration
- OpenAI-API für Embeddings
- Diagnose-Tab für Systemchecks

## Deployment auf Render

1. **Repository forken oder hochladen** auf GitHub
2. **Neuen Web Service auf [https://render.com](https://render.com) erstellen**
3. **Environment Variables** eintragen:
   - `SUPABASE_URL`
   - `SUPABASE_SERVICE_ROLE`
   - `OPENAI_API_KEY`
4. **Start Command:**
   ```bash
   python kalli_frontend_render_v2.py
   ```

## Lokaler Start

```bash
pip install -r requirements.txt
python kalli_frontend_render_v2.py
```