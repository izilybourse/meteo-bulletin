#!/usr/bin/env python3
"""Relais des bulletins marine de Météo-France La Réunion -> marine.json (pour l'onglet « Mer » du widget).

Pages lues (affichées comme pour un visiteur, via Playwright / Chromium) :
  https://meteofrance.re/fr/marine/cote         bulletin des zones côtières
  https://meteofrance.re/fr/marine/large        bulletin « large »
  https://meteofrance.re/fr/marine/grand-large  bulletin « grand large »
  https://meteofrance.re/fr/marine              avis de houle / bulletins spéciaux en cours
Le bulletin est ajouté par JavaScript dans  #bmr .xml_details  (même structure que la page ACK) ;
un éventuel bulletin spécial est dans  #bms .xml_details.

Usage : python3 fetch_marine.py sortie.json [page_html_de_test]
"""
import json, re, sys
from datetime import datetime, timezone

BASE = "https://meteofrance.re/fr/marine"
ZONES = [("cote", "Côte (20 milles)"), ("large", "Large"), ("grand-large", "Grand large")]

JS_ITEMS = """(sel) => [...document.querySelectorAll(sel + ' h2, ' + sel + ' h3, ' + sel + ' p')]
  .map(e => [e.tagName.toLowerCase(), (e.innerText || e.textContent || '').replace(/\\s+/g, ' ').trim()])
  .filter(x => x[1])"""
JS_AVIS = """() => {
  const h = [...document.querySelectorAll('h1,h2,h3,h4')].find(e => /bulletins m[ée]t[ée]orologiques sp[ée]ciaux/i.test(e.textContent));
  if (!h) return null;
  let e = h.nextElementSibling, t = '';
  while (e && t.length < 400) { t += ' ' + (e.innerText || ''); e = e.nextElementSibling; if (/^H[1-4]$/.test(e ? e.tagName : '')) break; }
  return t.replace(/\\s+/g, ' ').trim() || null;
}"""


def build(items, url, titre_zone):
    title, issued, notes, sections = "", "", [], []
    for tag, txt in items:
        if tag == "h2" and not title:
            title = txt
        elif tag == "h3" and re.match(r"bulletin (r[ée]dig[ée]|[ée]mis)", txt, re.I):
            issued = txt
        elif tag == "h3":
            sections.append({"titre": txt, "paragraphes": []})
        elif tag == "p":
            (sections[-1]["paragraphes"] if sections else notes).append(txt)
    if not title or not sections:
        raise RuntimeError("bulletin %s introuvable ou vide" % titre_zone)
    return {"source": url, "zone": titre_zone, "titre": title, "emission": issued, "notes": notes, "sections": sections}


def fetch(test_html=None):
    from playwright.sync_api import sync_playwright
    out = {"recupere": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"), "source": BASE,
           "avis_houle": None, "zones": {}, "erreurs": {}}
    with sync_playwright() as p:
        b = p.chromium.launch()
        for cle, nom in [("_avis", "")] + ZONES:
            pg = b.new_page(locale="fr-FR")
            url = BASE if cle == "_avis" else BASE + "/" + cle
            try:
                if test_html:
                    pg.set_content(open(test_html, encoding="utf-8").read())
                else:
                    pg.goto(url, wait_until="domcontentloaded", timeout=60000)
                if cle == "_avis":
                    pg.wait_for_timeout(3000)
                    out["avis_houle"] = pg.evaluate(JS_AVIS)
                else:
                    pg.wait_for_selector("#bmr .xml_details h2", timeout=45000)
                    out["zones"][cle] = build(pg.evaluate(JS_ITEMS, "#bmr .xml_details"), url, nom)
                    try:
                        sp = [t for tag, t in pg.evaluate(JS_ITEMS, "#bms .xml_details") if tag == "p"]
                        out["zones"][cle]["bulletin_special"] = " ".join(sp) or None
                    except Exception:
                        pass
            except Exception as e:
                out["erreurs"][cle] = repr(e)[:200]
                print("ÉCHEC", cle, repr(e)[:200])
            pg.close()
        b.close()
    if not out["zones"]:
        raise SystemExit("aucun bulletin marine récupéré")
    return out


def main():
    dest = sys.argv[1] if len(sys.argv) > 1 else "marine.json"
    data = fetch(sys.argv[2] if len(sys.argv) > 2 else None)
    with open(dest, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=1)
    print("OK", list(data["zones"]), "avis:", data["avis_houle"])


if __name__ == "__main__":
    main()
