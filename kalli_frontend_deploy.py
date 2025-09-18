# ============================================================
#  BVV-Frontend 
#   v1.5 (bereinigte SQL-Views)
#   v1.4 (bereinigter View)
#   v1.3 (kombiniertes Suchfeld, semantische Suche)
#   v1.2 (IDLE für Suche, leer nicht erlaubt)
#   v1.1 (Date-Picker via CSS)
#   v1.0 (Unified Search & Filters, PDF Download)
#
#  – Architektur nach Events_app-Vorbild
#  – Einheitliche Sicht über alle Vorgang-Tabellen
#  – Filters + Pagination + (optional) Volltext
#  – Sicheres Frontend (ANON-Key statt Service Role!)
#  – Beibehaltener Disclaimer + Logo-Platzhalter
#
#  Autoren: KI + Kalli
#  Stand: 2025-09-18
# ============================================================
# =============================
# BLOCK 1 — Imports & Setup
# =============================

import os
from datetime import datetime
import gradio as gr

# --- oben bei den Imports: genau einmal laden ---
from dotenv import load_dotenv
load_dotenv()

from supabase import create_client, Client
from urllib.parse import urlparse # DPF-Download der Drucksachen
from openai import OpenAI
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")  # kein KeyError bei leerer .env
openai_client = OpenAI(api_key=OPENAI_API_KEY) if OPENAI_API_KEY else None


APP_TITLE = "BVV – Vorgänge (Suche & Übersicht)"
__APP_VERSION__ = "Version 1.5"
LOGO_PATH = os.environ.get("KALLI_LOGO_PATH", "assets/logo_160_80.png")
PAGE_SIZE = 10
MIN_LEN = 2         # mind. Länge Suchstring

# 🔐 WICHTIG: Im Frontend NIEMALS den Service-Role-Key verwenden!
# Nutze den ANON-Key. Schreibvorgänge (z.B. Logs) erfordern passende RLS-Policies.
# ----- Supabase Setup -----

SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_ANON_KEY") or os.getenv("SUPABASE_SERVICE_ROLE")

sb: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

# =============================
# BLOCK 2 — CSS
# =============================

CUSTOM_CSS = """
#footer, footer { display:none !important; }
.kalli-header { display:flex; align-items:center; gap:12px; padding:10px 12px;
  border-radius:12px; background:#87CEEB; overflow-x:visible; white-space:normal; }
.kalli-title { font-weight:700; font-size:1.05rem; color:#000; }
.kalli-subtitle { font-weight:500; font-size:0.9rem; opacity:0.8; }
.logo img { width:160px; height:80px; border-radius:10%; object-fit:cover; }
.kalli-disclaimer { display:flex; align-items:center; gap:14px; background:#ffebcc; color:#333; padding:10px 14px; border:1px solid #e6c07b; border-radius:8px; }
@media (max-width:700px){ .kalli-disclaimer { flex-direction:column; align-items:stretch; } }
@media print {
  body * { visibility: hidden !important; }
  #results, #results * { visibility: visible !important; }
  #results { position:absolute !important; left:0; top:0; width:100%; background:#fff !important; }
}
"""
# =============================
# Helper Funktionen
# =============================

# Filter gesetzt? Suchstring lang genug?
def _has_any_filter(typ, status, von, bis) -> bool:
    return bool(typ) or bool(status) or bool(von) or bool(bis)

def _can_search(q, typ, status, von, bis) -> bool:
    q = (q or "").strip()
    if len(q) >= MIN_LEN:
        return True
    if _has_any_filter(typ, status, von, bis):
        return True
    return False

# semantische Suche
def _embed_query(text: str) -> list[float]:
    txt = (text or "").strip()  #leere Eingaben abgefangen
    if not txt:
        return []
    if not openai_client:
        raise RuntimeError("OPENAI_API_KEY fehlt – Embedding nicht möglich.")
    resp = openai_client.embeddings.create(
        model="text-embedding-3-small",
        input=txt
    )
    return resp.data[0].embedding  #Liste von 1536 Gleitkommazahlen (float)


def do_search_sem_db(q, typ, status, von, bis, page, sort):
    """
    Semantische Suche auf bvv_dokumente.
    Parameter:
      q: Suchtext (String)
      typ: Liste Typen (oder [])
      status: aktuell ungenutzt für semantische Suche
      von/bis: Datumsfilter
      page: Pager (hier ignoriert, weil semantisch immer Top-N)
      sort: Sortierung (wird von similarity übersteuert)
    """

    # Guard: Nur ausführen, wenn Text oder Filter gesetzt
    if not ((q or "").strip() or _has_any_filter(typ, status, von, bis)):
        gr.Warning("Bitte Suchbegriff eingeben ODER mind. einen Filter setzen.")
        return gr.update(), gr.update(), gr.update(), gr.update(), gr.update()

    try:
        q_vec = _embed_query(q or "BVV Berlin Vorgänge allgemein")
    except Exception as e:
        gr.Warning(f"Embedding fehlgeschlagen: {e}")
        return gr.update(), gr.update(), gr.update(), gr.update(), gr.update()
    
    limit = max(STATE["limit"], 20)
    typ_arg = typ or None
    von_arg = von or None
    bis_arg = bis or None

    try:
        rpc = sb.rpc("match_bvv_dokumente", {
            "query_embedding": q_vec,
            "match_count": limit,
            "match_threshold": 0.3, 
            "typ_filter": typ_arg,
            "von": von_arg,
            "bis": bis_arg,
            "published_only": False   # erstmal AUS, bis Datenlage sauber
        }).execute()
        hits = rpc.data or []
        gr.Info(f"RPC: {len(hits)} Treffer (semantisch)")
    except Exception as e:
        gr.Warning(f"Vektor-Suche fehlgeschlagen: {e}")
        hits = []

    # IDs + Similarity-Map
    ids = [h["id"] for h in hits]
    sim = {h["id"]: h.get("similarity", 0.0) for h in hits}

    # Vollständige Datensätze holen
    rows = sb.table("bvv_dokumente").select("*").in_("id", ids).execute().data or []
    rows.sort(key=lambda r: sim.get(r["id"], 0), reverse=True)

    # Render wie in klassischer Suche
    body = []
    for row in rows:
        preview = (row.get("inhalt") or "")[:220]
        pdf_md = _pdf_link(row.get("pdf_url"))
        s = sim.get(row.get("id"), 0.0)
        body.append(
            f"📄 **{row.get('titel','(ohne Titel)')}**  \n"
            f"— {row.get('typ','?')} · {row.get('status','?')} · {row.get('datum','?')} · {row.get('fraktion','')}  \n"
            f"{preview}…  \n"
            f"Ähnlichkeit: {s:.2f}  \n"
            f"ID: `{row.get('id','?')}`{pdf_md}"
        )

    total = len(rows)
    start, end = (1 if total else 0), total
    out_md = f"**{start}–{end} von {total} (semantisch)**\n\n" + ("\n\n---\n\n".join(body))

    # Pager bleibt aus – wir holen nur Top-N
    return out_md, gr.update(interactive=False), gr.update(interactive=False), 1, f"{start}–{end} / {total}"


# =============================
# BLOCK 3 — Data Layer
# =============================

def _apply_filters(query, *, q: str | None, typ: list[str] | None, status: list[str] | None,
                   von: str | None, bis: str | None):
    """Gemeinsame Filter auf eine Supabase-Query anwenden (ilike-Variante)."""
    if typ:
        query = query.in_("typ", typ)
    if status:
        query = query.in_("status", status)
    if von:
        query = query.gte("datum", von)
    if bis:
        query = query.lte("datum", bis)
    if q:
        # ilike auf mehreren Spalten (einfach, robust)
        like = f"%{q}%"
        query = query.or_(
            ",".join([
                f"titel.ilike.{like}",
                f"inhalt.ilike.{like}",
                f"drucksache.ilike.{like}",
                f"fraktion.ilike.{like}",
            ])
        )
    return query


def clear_filters_keep_results():
    gr.Info("🧹 Filter zurückgesetzt.")
    return "", [], [], None, None, "datum:desc", 1, gr.update()

def list_vorgaenge(*, q: str = "", typ: list[str] | None = None, status: list[str] | None = None,
                   datum_von: str | None = None, datum_bis: str | None = None,
                   limit: int = 20, offset: int = 0, sort: str = "datum:desc"):
    base = "bvv_dokumente"  # Supabase View
    col, direction = (sort.split(":") + ["asc"])[:2]

    query = sb.table(base).select("*")
    query = _apply_filters(query, q=q, typ=typ, status=status, von=datum_von, bis=datum_bis)
    query = query.order(col, desc=(direction.lower() == "desc"))
    query = query.range(offset, offset + limit - 1)
    res = query.execute()
    return res.data or []


def count_vorgaenge(*, q: str = "", typ: list[str] | None = None, status: list[str] | None = None,
                    datum_von: str | None = None, datum_bis: str | None = None) -> int:
    base = "bvv_dokumente"
    query = sb.table(base).select("id", count="exact")
    query = _apply_filters(query, q=q, typ=typ, status=status, von=datum_von, bis=datum_bis)
    res = query.execute()
    return int(res.count or 0)


def get_vorgang_detail(typ: str, id_):
    table = {
        "antrag": "antraege",
        "anfrage_muendlich": "anfragen_muendlich",
        "anfrage_klein": "anfragen_klein",
        "anfrage_gross": "anfragen_gross",
    }.get(typ)
    if not table:
        return None
    res = sb.table(table).select("*").eq("id", id_).single().execute()
    return res.data


def log_action(action: str, query: dict | None = None, vorgang_id=None):
    try:
        sb.table("zugriffslog_bvv").insert({
            "action": action,
            "query": query and str(query),
            "vorgang_id": vorgang_id,
        }).execute()
    except Exception:
        # still be silent in frontend
        pass

# =============================
# BLOCK 4 — UI Actions
# =============================

STATE = {"limit": 10}

def _pdf_link(url: str | None) -> str:
    if not url:
        return ""  # leer oder None -> nix anzeigen
    u = str(url).strip()
    if not u or not (u.startswith("http://") or u.startswith("https://")):
        return ""  # nur gültige Links
    host = urlparse(u).netloc or "PDF"
    return f"\n[🔗 Original-PDF ({host})]({u})"

def do_search(q, typ, status, von, bis, page, sort):
    # ---- Guard: nur suchen, wenn sinnvoll ----
    if not _can_search(q, typ, status, von, bis):
        gr.Warning("Bitte Suchbegriff eingeben ODER mindestens einen Filter setzen (z. B. Typ).")
        # Nichts ändern: alle Outputs unverändert lassen
        return gr.update(), gr.update(), gr.update(), gr.update(), gr.update()


    page = max(1, int(page or 1))
    limit = STATE["limit"]
    offset = (page - 1) * limit
    items = list_vorgaenge(
        q=q or "",
        typ=typ or None,
        status=status or None,
        datum_von=von or None,
        datum_bis=bis or None,
        limit=limit,
        offset=offset,
        sort=sort or "datum:desc",
    )
    total = count_vorgaenge(
        q=q or "",
        typ=typ or None,
        status=status or None,
        datum_von=von or None,
        datum_bis=bis or None,
    )

    start = 0 if total == 0 else offset + 1
    end = min(offset + limit, total)

    body = []
    for row in items:


        preview = (row.get("inhalt") or "")[:220]
        pdf_md = _pdf_link(row.get("pdf_url"))
        body.append(
            f"📄 **{row.get('titel','(ohne Titel)')}**  \n"
            f"— {row.get('typ','?')} · {row.get('status','?')} · {row.get('datum','?')} · {row.get('fraktion','')}  \n"
            f"{preview}…  \n"
            f"ID: `{row.get('id','?')}`{pdf_md}"
        )


    header = f"**{start}–{end} von {total} Einträgen**\n\n"
    out_md = header + ("\n\n---\n\n".join(body) if body else "_Keine Treffer._")

    # Toggle Pager-Buttons
    has_prev = page > 1
    has_next = end < total

    log_action("list", {"q": q, "typ": typ, "status": status, "von": von, "bis": bis, "page": page, "sort": sort})
    return out_md, gr.update(interactive=has_prev), gr.update(interactive=has_next), page, f"{start}–{end} / {total}"


def next_page(q, typ, status, von, bis, page, sort):
    return do_search(q, typ, status, von, bis, (int(page or 1) + 1), sort)

def prev_page(q, typ, status, von, bis, page, sort):
    return do_search(q, typ, status, von, bis, (max(1, int(page or 1) - 1)), sort)


def show_detail(typ, id_):
    d = get_vorgang_detail(typ, id_)
    if not d:
        return "Nicht gefunden."
    log_action("detail", {"typ": typ}, id_)

    pdf_url = (d.get("pdf_url") or "").strip()
    pdf_line = ""
    if pdf_url and pdf_url.startswith(("http://","https://")):
        pdf_line = f"\n**PDF:** [🔗 Original-PDF]({pdf_url})"

    return (
    f"### {d.get('titel','(ohne Titel)')}\n"
    f"**Typ:** {typ}  \n"
    f"**Status:** {d.get('status','')}  \n"
    f"**Fraktion:** {d.get('fraktion','')}  \n"
    f"**Datum:** {d.get('datum','')}\n\n"
    f"**Inhalt:**\n{d.get('inhalt') or ''}\n\n"
    f"**Drucksache:** {d.get('drucksache','-')}  \n"
    f"{pdf_line}\n"
    )


def export_pdf_placeholder():
    # Platzhalter – hier später HTML->PDF (weasyprint/wkhtmltopdf) einbauen
    return "🖨️ PDF-Export kommt als nächster Schritt (HTML-Render + PDF)."

# =============================
# BLOCK 5 — Gradio UI
# =============================

CUSTOM_CSS += """

/* Row darf umbrechen + kleiner Abstand */
.row-dates { flex-wrap: wrap; gap: 8px; align-items: end; }

/* iPad-Hochformat & schmale Screens: Date-Picker jeweils volle Breite */
@media (max-width: 900px) {
  .row-dates .gr-column { flex: 1 1 100% !important; }
  #dp_von, #dp_bis { width: 100% !important; min-width: 100% !important; }
}
"""


def greet_on_load():
    gr.Info("👋 Willkommen im BVV-Frontend des Abgeordneten K.-H. Turban!")


with gr.Blocks(css=CUSTOM_CSS, title=f"{APP_TITLE} · {__APP_VERSION__}") as demo:
    # Disclaimer
    with gr.Row(visible=True, elem_classes="kalli-disclaimer") as disclaimer_box:
        gr.HTML("⚠️ Hinweis: Diese Anwendung lädt ggf. externe Ressourcen (z. B. Fonts). Wenn du das nicht möchtest, nutze die App nicht weiter.")
        understood = gr.Checkbox(label="Verstanden (nicht mehr anzeigen)")

    def _toggle_disclaimer(checked: bool):
        return gr.update(visible=not checked)

    understood.change(_toggle_disclaimer, inputs=understood, outputs=disclaimer_box)
    demo.load(fn=greet_on_load, inputs=[], outputs=[])

    # ----- Header -----
    with gr.Row(elem_classes="kalli-header"):
        if os.path.exists(LOGO_PATH):
            gr.Image(
                LOGO_PATH,
                show_label=False,
                container=False,
                interactive=False,  
                show_download_button=False, # keine Buttons mehr
                show_fullscreen_button=False,
                elem_classes="logo"
            )

        gr.HTML(f"""
            <div class="kalli-header-text">
                <div class="kalli-title">{APP_TITLE}</div>
                <div class="kalli-title">{__APP_VERSION__}</div>
            </div>
        """)


    with gr.Tabs():
        with gr.TabItem("Suche"):
            with gr.Row():
                q = gr.Textbox(placeholder="Suche (Titel, Text)…", label="Volltext -einfach/semantisch)", scale=3)
                typ = gr.CheckboxGroup(choices=["antrag","anfrage_muendlich","anfrage_klein","anfrage_gross"], label="Typ", scale=2)
                status = gr.CheckboxGroup(choices=["eingereicht von","Fraktion","Status"], label="noch Dummy!", scale=2)
            #with gr.Row():
            with gr.Row(elem_classes="filters"):
                with gr.Column(scale=1, min_width=160):
                    sort = gr.Dropdown(choices=["datum:desc","datum:asc"], value="datum:desc", label="Sortierung")
                with gr.Column(scale=1, min_width=120):
                    page = gr.Number(value=1, label="Seite", precision=0)


            # --- nur die Datumsfelder ---
            with gr.Row(elem_classes="row-dates"):
                with gr.Column(min_width=260):
                    von = gr.DateTime(label="Von", include_time=False, type="string", elem_id="dp_von")
                with gr.Column(min_width=260):
                    bis = gr.DateTime(label="Bis", include_time=False, type="string", elem_id="dp_bis")


            with gr.Row():
                btn_search = gr.Button("🔎 Suche-klassisch", variant="primary")
                btn_prev = gr.Button("◀️ Zurück", interactive=False)
                btn_next = gr.Button("Weiter ▶️", interactive=False)
                pager_info = gr.Markdown("1–0 / 0")
                btn_sem   = gr.Button("🧠 Suche-semantisch", variant="primary") 
                btn_export = gr.Button("🖨️ Export PDF")
                btn_clear = gr.Button("🧹 Filter zurücksetzen", variant="secondary")
     
      

            results = gr.Markdown(elem_id="results")

            # Hier – nach Button-Definition:
            btn_clear.click(
                fn=clear_filters_keep_results,
                inputs=[],
                outputs=[q, typ, status, von, bis, sort, page, results]
            )

            btn_search.click(do_search, [q, typ, status, von, bis, page, sort], [results, btn_prev, btn_next, page, pager_info])
            btn_next.click(next_page, [q, typ, status, von, bis, page, sort], [results, btn_prev, btn_next, page, pager_info])
            btn_prev.click(prev_page, [q, typ, status, von, bis, page, sort], [results, btn_prev, btn_next, page, pager_info])
            btn_export.click(lambda: export_pdf_placeholder(), [], [results])
            btn_sem.click(
                do_search_sem_db,
                inputs=[q, typ, status, von, bis, page, sort],
                outputs=[results, btn_prev, btn_next, page, pager_info]
            )


        #with gr.TabItem("Detail"):
        #    with gr.Row():
        #        in_typ = gr.Dropdown(choices=["antrag","anfrage_muendlich","anfrage_klein","anfrage_gross"], label="Typ")
        #        in_id = gr.Textbox(label="ID")
                #btn_detail = gr.Button("➡️ Laden")
            #detail = gr.Markdown()
            #btn_detail.click()

if __name__ == "__main__":
    # Für Deployment (Render, Docker etc.):
    demo.launch(server_name="0.0.0.0", server_port=int(os.environ.get("PORT", 7860)))

    # Für lokalen Test:
    #demo.launch()


