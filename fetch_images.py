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
CYCLONE_MF_URL = os.environ.get("CYCLONE_MF_URL", "https://meteofrance.re/fr/cyclone")
WEATHERLAB_URL = os.environ.get("WEATHERLAB_URL", "https://deepmind.google.com/science/weatherlab")
WEATHERLAB_LIEU = os.environ.get("WEATHERLAB_LIEU", "La Réunion")   # lieu sur lequel recentrer la carte ("" = vue par défaut)


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
    """Carte Highmaps construite côté navigateur à partir de 5 appels php (stations, tronçons, vigilance...).
    On attend que les tronçons colorés soient réellement dessinés, puis on enregistre #carte."""
    reponses = []
    page.on("response", lambda r: reponses.append((r.status, r.url.split("/")[-1])) if "/assets/php/" in r.url else None)
    page.goto(CRUES_URL, wait_until="load", timeout=60000)
    try:
        page.wait_for_load_state("networkidle", timeout=20000)
    except Exception:
        pass
    page.wait_for_selector("#carte .highcharts-container svg", timeout=45000)
    # tronçons dessinés = beaucoup de <path> colorés (vert/jaune/orange/rouge) dans la carte
    page.wait_for_function(
        "() => document.querySelectorAll('#carte svg path[stroke]:not([stroke=\"none\"])').length >= 20",
        timeout=45000)
    page.wait_for_timeout(3000)
    for sel in ("#loader",):   # écran d'attente éventuel
        try:
            page.wait_for_function("(s)=>{const e=document.querySelector(s);return !e||getComputedStyle(e).display==='none'}", arg=sel, timeout=10000)
        except Exception:
            pass
    el = page.locator("#carte")
    el.scroll_into_view_if_needed()
    try:
        el.screenshot(path=os.path.join(dossier, "crues.png"))
    except Exception:   # repli : zone de la carte découpée dans la page
        bb = el.bounding_box()
        page.screenshot(path=os.path.join(dossier, "crues.png"), full_page=True, clip=bb)
    print("  appels php:", reponses)
    return {"image": "crues.png", "recupere": maintenant(), "source": CRUES_URL}


def capturer_cyclone_mf(page, dossier):
    """Carte « Cyclone et activité cyclonique » de Météo-France La Réunion (Leaflet, #map)."""
    page.goto(CYCLONE_MF_URL, wait_until="domcontentloaded", timeout=60000)
    refuser_cookies(page)
    page.wait_for_selector("#map .leaflet-container, #map.leaflet-container", timeout=45000)
    page.wait_for_function(
        "() => document.querySelectorAll('#map .leaflet-tile-loaded').length >= 4", timeout=45000)
    page.wait_for_timeout(4000)   # trajectoires / zones perturbées
    date_affichee = None
    try:
        t = page.locator("#mf_cyclone").first.inner_text(timeout=3000)
        import re
        m = re.search(r"Carte publiée le[^\n]*", t)
        date_affichee = m.group(0) if m else None
    except Exception:
        pass
    page.locator("#map").screenshot(path=os.path.join(dossier, "cyclone_mf.png"))
    return {"image": "cyclone_mf.png", "date_affichee": date_affichee, "recupere": maintenant(), "source": CYCLONE_MF_URL}


def capturer_weatherlab(page, dossier):
    """Google Weather Lab (carte Google Maps WebGL). La page affiche deux messages d'accueil (conditions
    d'usage + cookies) qu'il faut fermer pour voir la carte ; la vue est recentrée par la recherche de lieu."""
    page.goto(WEATHERLAB_URL, wait_until="domcontentloaded", timeout=60000)
    page.wait_for_selector("weatherlab-map", timeout=45000)
    page.wait_for_timeout(4000)
    for txt in ("OK, got it", "Accept and use"):
        try:
            b = page.get_by_role("button", name=txt).first
            if b.is_visible(timeout=3000):
                b.click(timeout=3000)
                page.wait_for_timeout(800)
        except Exception:
            pass
    if WEATHERLAB_LIEU:
        try:
            champ = page.locator("weatherlab-location-search input").first
            champ.click(timeout=5000)
            champ.fill(WEATHERLAB_LIEU)
            page.wait_for_timeout(2000)
            champ.press("ArrowDown")
            champ.press("Enter")
            page.wait_for_timeout(2500)
        except Exception as e:
            print("  recentrage impossible :", repr(e)[:150])
    page.wait_for_timeout(8000)   # tuiles de carte + couches de prévision
    page.locator("weatherlab-map").screenshot(path=os.path.join(dossier, "weatherlab.png"))
    return {"image": "weatherlab.png", "recupere": maintenant(), "source": WEATHERLAB_URL}


CAPTURES = (("radar", capturer_radar), ("crues", capturer_crues),
            ("cyclone_mf", capturer_cyclone_mf), ("weatherlab", capturer_weatherlab))
UA = ("Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) "
      "Chrome/124.0.0.0 Safari/537.36")


def main():
    dossier = sys.argv[1] if len(sys.argv) > 1 else "out"
    quoi = sys.argv[2:] or [n for n, _ in CAPTURES]
    os.makedirs(dossier, exist_ok=True)
    meta_path = os.path.join(dossier, "images.json")
    meta = json.load(open(meta_path, encoding="utf-8")) if os.path.exists(meta_path) else {}
    from playwright.sync_api import sync_playwright
    erreurs = 0
    with sync_playwright() as p:
        # options graphiques logicielles : la carte Weather Lab utilise WebGL
        b = p.chromium.launch(args=["--use-gl=angle", "--use-angle=swiftshader",
                                    "--enable-unsafe-swiftshader", "--ignore-gpu-blocklist"])
        for nom, f in CAPTURES:
            if nom not in quoi:
                continue
            page = b.new_page(viewport={"width": 1280, "height": 1000}, locale="fr-FR", user_agent=UA)
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
    sys.exit(1 if erreurs == len(quoi) else 0)   # 0 si au moins une capture a réussi


if __name__ == "__main__":
    main()
