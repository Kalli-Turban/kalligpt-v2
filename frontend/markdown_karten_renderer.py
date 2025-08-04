
def format_card_entry(entry: dict) -> str:
    """Formatiert einen Eintrag im Kartenstil für Markdown-Anzeige"""
    datum = f"📅 {entry.get('datum', 'Unbekannt')}"
    titel = f"📄 {entry.get('titel', 'Kein Titel')}"
    drucksache = entry.get("drucksache")
    drucksache_line = f"📌 Drucksache: {drucksache}" if drucksache else "📌 Drucksache: –"

    pdf_url = entry.get("pdf_url")
    if isinstance(pdf_url, str) and pdf_url.startswith("http"):
        pdf_line = f"📎 [PDF öffnen]({pdf_url})"
    else:
        pdf_line = "🚫 Kein PDF-Link vorhanden"

    return f"**{titel}**  \n{datum}  \n{drucksache_line}  \n{pdf_line}  \n\n---\n"


def render_markdown_kartenansicht(eintraege: list) -> str:
    """Wandelt eine Liste von Einträgen in Markdown-Kartenansicht um"""
    return "\n".join(format_card_entry(e) for e in eintraege)
