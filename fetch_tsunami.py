#!/usr/bin/env python3
"""Relais des séismes et alertes tsunami du BMKG (Indonésie, InaTEWS) -> tsunami.json (onglet « Tsunami »).

Données publiques lues exactement comme le fait le site https://inatews.bmkg.go.id :
  https://cdn.bmkg.go.id/live30event.xml          derniers séismes détectés (heure UTC)
  https://cdn.bmkg.go.id/last30tsunamievent.xml   30 derniers bulletins d'alerte tsunami (heure WIB, UTC+7)
Aucun jeton, aucune connexion. Sortie : JSON compact lisible par le navigateur (CORS ouvert sur raw.githubusercontent.com).

Usage : python3 fetch_tsunami.py sortie.json [dossier_local_avec_les_2_xml]
"""
import json, re, sys, urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime, timezone, timedelta

BASE = "https://cdn.bmkg.go.id/"
WIB = timezone(timedelta(hours=7))
MAX_SEISMES = 250


def lire(nom, local=None):
    if local:
        return open(local.rstrip("/") + "/" + nom, "rb").read()
    req = urllib.request.Request(BASE + nom, headers={"User-Agent": "Mozilla/5.0 (meteo-relay)"})
    with urllib.request.urlopen(req, timeout=30) as r:
        return r.read()


def txt(e, tag):
    for c in e.iter():
        if c.tag.split("}")[-1] == tag:
            return (c.text or "").strip()
    return ""


def seismes(raw):
    root = ET.fromstring(raw)
    out = []
    for g in root.iter("gempa"):
        try:
            t = datetime.strptime(re.sub(r"\s+", " ", txt(g, "waktu")).split(".")[0], "%Y/%m/%d %H:%M:%S").replace(tzinfo=timezone.utc)
            out.append({"id": txt(g, "eventid"), "t": t.strftime("%Y-%m-%dT%H:%M:%SZ"), "lat": float(txt(g, "lintang")),
                        "lon": float(txt(g, "bujur")), "mag": float(txt(g, "mag")), "prof": float(txt(g, "dalam") or 0),
                        "zone": txt(g, "area"), "statut": txt(g, "status")})
        except Exception:
            continue
    out.sort(key=lambda x: x["t"], reverse=True)
    return out[:MAX_SEISMES]


def tsunamis(raw):
    root = ET.fromstring(raw)
    out = []
    for info in root.iter():
        if info.tag.split("}")[-1] != "info":
            continue
        ts = txt(info, "timesent")
        m = re.match(r"(\d{2})/(\d{2})/(\d{4}) (\d{2}):(\d{2}):(\d{2})", ts)
        envoi = None
        if m:
            d, mo, y, h, mi, s = map(int, m.groups())
            envoi = datetime(y, mo, d, h, mi, s, tzinfo=WIB).astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        try:
            mag = float(txt(info, "magnitude"))
        except ValueError:
            mag = None
        coords = txt(info, "coordinates").split(",")
        out.append({"event": txt(info, "eventid"), "envoi": envoi, "sujet": txt(info, "subject"), "titre": txt(info, "headline"),
                    "mag": mag, "origine": txt(info, "date") + " " + txt(info, "time"), "zone": txt(info, "area"),
                    "prof": txt(info, "depth"), "potentiel": txt(info, "potential"),
                    "lon": float(coords[0]) if len(coords) == 2 else None, "lat": float(coords[1]) if len(coords) == 2 else None})
    out.sort(key=lambda x: x["envoi"] or "", reverse=True)
    return out


def main():
    dest = sys.argv[1] if len(sys.argv) > 1 else "tsunami.json"
    local = sys.argv[2] if len(sys.argv) > 2 else None
    res = {"source": "https://inatews.bmkg.go.id", "recupere": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
           "seismes": [], "tsunamis": [], "erreurs": {}}
    for cle, nom, f in (("seismes", "live30event.xml", seismes), ("tsunamis", "last30tsunamievent.xml", tsunamis)):
        try:
            res[cle] = f(lire(nom, local))
        except Exception as e:
            res["erreurs"][cle] = repr(e)[:200]
            print("ÉCHEC", cle, repr(e)[:200])
    if not res["seismes"] and not res["tsunamis"]:
        raise SystemExit("aucune donnée BMKG récupérée")
    with open(dest, "w", encoding="utf-8") as f:
        json.dump(res, f, ensure_ascii=False, separators=(",", ":"))
    print("OK", len(res["seismes"]), "séismes,", len(res["tsunamis"]), "bulletins tsunami")


if __name__ == "__main__":
    main()
