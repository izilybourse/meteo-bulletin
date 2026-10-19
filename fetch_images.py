#!/usr/bin/env python3
"""Relais des images « radar » et « carte de vigilance crues » pour le widget METEO LAB.

Le script ouvre les pages officielles dans un navigateur sans écran (Playwright / Chromium), comme le
ferait un visiteur, puis enregistre une image de la carte seule :
  - radar    : https://meteofrance.re/fr/images-radar        -> radar.png  (carte  #map_wrapper)
  - crues    : https://www.vigicrues-reunion.re/             -> crues.png  (carte  #carte)
Il écrit aussi images.json (heure de récupération, date affichée sur le radar).
Aucun jeton n'est lu ni copié : on enregistre simplement ce que la page affiche.

Usage : python3 fetch_images.py dossier_sortie [radar|crues]
Dépendance : pip install playwright && python -m playwright install chromium
"""
import json, os, sys
from datetime import datetime, timezone

RADAR_URL = os.environ.get("RADAR_URL", "https://meteofrance.re/fr/images-radar")
CRUES_URL = os.environ.get("CRUES_URL", "https://www.vigicrues-reunion.re/")


def maintenant():
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def refuser_cookies(page):
    """Bandeau de consentement : on choisit l'option la plus protectrice (continuer sans accepter)."""
    for txt in ("Continuer sans accepter", "Tout refuser", "Refuser"):
        try:
            loc = page.get_by_text(txt, exact=False).first
            if loc.is_visible(timeout=1500):
                loc.click(timeout=2000)
                page.wait_for_timeout(500)
                return
        except Exception:
            pass


def capturer_radar(page, dossier):
    page.goto(RADAR_URL, wait_until="domcontentloaded", timeout=60000)
    refuser_cookies(page)
    page.wait_for_selector("#map_wrapper", timeout=45000)
    # attend que les tuiles de la carte (fond + radar) soient chargées
    page.wait_for_function(
        "() => document.querySelectorAll('#map_wrapper .leaflet-tile-loaded').length >= 4", timeout=45000)
    page.wait_for_timeout(4000)   # laisse finir le chargement de la dernière image radar
    date_affichee = None
    try:
        date_affichee = page.locator("a.timecontrol-date").first.inner_text(timeout=3000).strip()
    except Exception:
        pass
    page.locator("#map_wrapper").screenshot(path=os.path.join(dossier, "radar.png"))
    return {"image": "radar.png", "date_affichee": date_affichee, "recupere": maintenant(), "source": RADAR_URL}


def capturer_crues(page, dossier):
    page.goto(CRUES_URL, wait_until="domcontentloaded", timeout=60000)
    page.wait_for_selector("#carte .highcharts-container svg", timeout=45000)
    page.wait_for_timeout(5000)   # laisse la carte se colorer (appel aux données de vigilance)
    page.locator("#carte").screenshot(path=os.path.join(dossier, "crues.png"))
    return {"image": "crues.png", "recupere": maintenant(), "source": CRUES_URL}


def main():
    dossier = sys.argv[1] if len(sys.argv) > 1 else "out"
    quoi = sys.argv[2:] or ["radar", "crues"]
    os.makedirs(dossier, exist_ok=True)
    meta_path = os.path.join(dossier, "images.json")
    meta = json.load(open(meta_path, encoding="utf-8")) if os.path.exists(meta_path) else {}
    from playwright.sync_api import sync_playwright
    erreurs = 0
    with sync_playwright() as p:
        b = p.chromium.launch()
        for nom, f in (("radar", capturer_radar), ("crues", capturer_crues)):
            if nom not in quoi:
                continue
            page = b.new_page(viewport={"width": 1280, "height": 1000}, locale="fr-FR")
            try:
                meta[nom] = f(page, dossier)
                print("OK", nom, meta[nom])
            except Exception as e:
                erreurs += 1
                print("ÉCHEC", nom, ":", repr(e)[:300])
                try:   # image de diagnostic : ce que la page affichait
                    page.screenshot(path=os.path.join(dossier, f"diag_{nom}.png"))
                except Exception:
                    pass
            page.close()
        b.close()
    with open(meta_path, "w", encoding="utf-8") as f:
        json.dump(meta, f, ensure_ascii=False, indent=1)
    sys.exit(1 if erreurs == len(quoi) else 0)


if __name__ == "__main__":
    main()
