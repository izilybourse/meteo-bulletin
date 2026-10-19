#!/usr/bin/env python3
"""Relais du "BULLETIN DE PREVISIONS MARINE pour la zone ACK (Amsterdam-Crozet-Kerguelen)"
de https://meteofrance.re/fr/marine/ack vers un fichier JSON lisible par le widget METEO LAB.

La page n'a pas le bulletin dans son HTML : il est ajouté par JavaScript après le chargement.
Le script ouvre donc la page dans un navigateur sans écran (Playwright / Chromium), comme le ferait
un visiteur, puis lit le bloc affiché  #bmr .xml_details  (aucun jeton, aucune API privée).

Usage : python3 fetch_ack.py [sortie.json] [page_html_de_test]
Dépendance : pip install playwright && python -m playwright install chromium
"""
import json, re, sys
from datetime import datetime, timezone

URL = "https://meteofrance.re/fr/marine/ack"
MOIS = {"janvier":1,"février":2,"fevrier":2,"mars":3,"avril":4,"mai":5,"juin":6,"juillet":7,
        "août":8,"aout":8,"septembre":9,"octobre":10,"novembre":11,"décembre":12,"decembre":12}

# Lit les titres (h2/h3) et paragraphes (p) du bloc, dans l'ordre d'affichage.
JS_EXTRACT = """() => [...document.querySelectorAll('#bmr .xml_details h2, #bmr .xml_details h3, #bmr .xml_details p')]
  .map(e => [e.tagName.toLowerCase(), (e.innerText || e.textContent || '').replace(/\\s+/g, ' ').trim()])
  .filter(x => x[1])"""


def build(items):
    """items = [(balise, texte), ...] -> dictionnaire JSON du bulletin."""
    title, issued, notes, sections = "", "", [], []
    for tag, txt in items:
        if tag == "h2" and not title:
            title = txt
        elif tag == "h3" and re.match(r"bulletin r[ée]dig[ée]", txt, re.I):
            issued = txt
        elif tag == "h3":
            sections.append({"titre": txt, "paragraphes": []})
        elif tag == "p":
            (sections[-1]["paragraphes"] if sections else notes).append(txt)
    if not title or not sections:
        raise RuntimeError("bulletin ACK introuvable ou vide (« Aucun BMR en cours » ? structure modifiée ?)")
    iso = None
    m = re.search(r"le \w+ (\d{1,2}) (\w+) (\d{4}) à (\d{1,2})\s*UTC", issued, re.I)
    if m and m.group(2).lower() in MOIS:
        iso = datetime(int(m.group(3)), MOIS[m.group(2).lower()], int(m.group(1)), int(m.group(4)), 0, tzinfo=timezone.utc).isoformat()
    return {"source": URL, "titre": title, "emission": issued, "emission_iso": iso, "notes": notes,
            "recupere": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"), "sections": sections}


def fetch(test_html=None):
    from playwright.sync_api import sync_playwright
    with sync_playwright() as p:
        b = p.chromium.launch()
        pg = b.new_page(locale="fr-FR")
        if test_html:
            pg.set_content(open(test_html, encoding="utf-8").read())
        else:
            pg.goto(URL, wait_until="domcontentloaded", timeout=60000)
        pg.wait_for_selector("#bmr .xml_details h2", timeout=45000)
        items = pg.evaluate(JS_EXTRACT)
        b.close()
    return build(items)


def main():
    out = sys.argv[1] if len(sys.argv) > 1 else "ack.json"
    data = fetch(sys.argv[2] if len(sys.argv) > 2 else None)
    with open(out, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=1)
    print("OK", data["emission"], "-", len(data["sections"]), "sections")


if __name__ == "__main__":
    main()
