#!/usr/bin/env python3
"""Relais des prévisions AROME Outre-mer (domaine Réunion-Mayotte, 0,025° ≈ 2,5 km) pour le widget METEO LAB.

Source : données publiques de Météo-France (Licence Ouverte 2.0), dépôt PNT sur data.gouv.fr :
  https://files.data.gouv.fr/meteofrance-pnt/pnt/<cycle>/arome-om/INDIEN/0025/<paquet>/arome-om-INDIEN__0025__<paquet>__<HHH>H__<cycle>.grib2
Aucun compte, aucune clé.

Le script :
  1. choisit le dernier cycle COMPLET (00, 06, 12 ou 18 UTC) ;
  2. télécharge les paquets contenant pression, vent, rafales, précipitations, température ;
  3. extrait, pour chaque lieu du widget, le point de grille le plus proche (échéances horaires) ;
  4. écrit arome.json (petit fichier) lu par le widget.
Si le cycle est déjà celui du fichier précédent, rien n'est retéléchargé.

Usage : python3 fetch_arome.py sortie.json [--prev ancien_arome.json] [--local dossier_grib]
Dépendances : pip install eccodes numpy
"""
import json, os, re, sys, tempfile, urllib.request, urllib.parse
from datetime import datetime, timedelta, timezone

BASE = "https://files.data.gouv.fr/meteofrance-pnt/pnt/"
DOMAINE, GRILLE = "INDIEN", "0025"
PAQUETS = ["SP1", "SP2", "SP3"]          # paquets « surface » : on garde ceux qui contiennent les paramètres utiles
ECH_MIN_COMPLET = 42                      # un cycle est complet quand la dernière échéance publiée est >= à cette valeur
LIEUX = [("Saint-Denis", -20.88, 55.45), ("Le Port", -20.94, 55.29),
         ("Saint-Pierre", -21.34, 55.48), ("Saint-Benoît", -21.03, 55.71)]   # mêmes lieux que le widget

# Paramètres recherchés : liste de (shortName possibles, typeOfLevel possibles, niveau)
WANT = {
    "p":  (["prmsl", "msl", "pmsl"], None, None),                       # pression réduite au niveau de la mer (Pa)
    "t":  (["2t", "t"], ["heightAboveGround"], 2),                      # température à 2 m (K)
    "u":  (["10u", "u10", "u"], ["heightAboveGround"], 10),            # vent moyen 10 m, composante est (m/s)
    "v":  (["10v", "v10", "v"], ["heightAboveGround"], 10),
    "g":  (["10fg", "i10fg", "fg10", "gust", "wgust"], ["heightAboveGround"], 10),   # rafale 10 m (m/s)
    "ug": (["ugst", "u10fg"], ["heightAboveGround"], 10),              # rafale par composantes (variante)
    "vg": (["vgst", "v10fg"], ["heightAboveGround"], 10),
    "tp": (["tp", "prec", "precip"], None, None),                       # précipitations cumulées (kg/m² = mm)
    "pr": (["tprate", "prate"], None, None),                            # taux de précipitations (kg/m²/s), variante
}
MS_KT = 1.943844


def log(*a):
    print(*a, flush=True)


def http_get(url, dest=None, timeout=120):
    req = urllib.request.Request(url, headers={"User-Agent": "meteo-lab-relay (usage personnel)"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        if dest is None:
            return r.read().decode("utf-8", "replace")
        with open(dest, "wb") as f:
            while True:
                b = r.read(1 << 20)
                if not b:
                    break
                f.write(b)


def lister(url):
    """Liens d'une page d'index (dossiers/fichiers)."""
    return [urllib.parse.unquote(h) for h in re.findall(r'href="([^"]+)"', http_get(url)) if not h.startswith("..")]


def cycles_recents():
    liens = lister(BASE)
    cyc = sorted({re.search(r"(\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z)", l).group(1) for l in liens if re.search(r"\d{4}-\d{2}-\d{2}T", l)}, reverse=True)
    return [c for c in cyc if c[11:13] in ("00", "06", "12", "18")]


def echeances(cycle, paquet):
    url = f"{BASE}{urllib.parse.quote(cycle)}/arome-om/{DOMAINE}/{GRILLE}/{paquet}/"
    try:
        liens = lister(url)
    except Exception:
        return []
    return sorted(int(m.group(1)) for l in liens for m in [re.search(r"__(\d{3})H__", l)] if m)


def nom_fichier(cycle, paquet, h):
    return f"arome-om-{DOMAINE}__{GRILLE}__{paquet}__{h:03d}H__{cycle}.grib2"


def url_fichier(cycle, paquet, h):
    return f"{BASE}{urllib.parse.quote(cycle)}/arome-om/{DOMAINE}/{GRILLE}/{paquet}/{nom_fichier(cycle, paquet, h)}"


# ---------------------------------------------------------------- lecture GRIB2
def messages(path):
    import eccodes as ec
    with open(path, "rb") as f:
        while True:
            gid = ec.codes_grib_new_from_file(f)
            if gid is None:
                return
            yield gid


def cle_message(ec, gid):
    g = lambda k, d=None: ec.codes_get(gid, k) if ec.codes_is_defined(gid, k) else d
    return {"sn": g("shortName"), "tl": g("typeOfLevel"), "lv": g("level"), "st": g("stepType"),
            "s0": g("startStep"), "s1": g("endStep"), "name": g("name")}


def classer(k):
    """Renvoie le code de variable (p, t, u, v, g, ug, vg, tp, pr) pour un message, ou None."""
    for code, (sns, tls, lv) in WANT.items():
        if k["sn"] in sns and (tls is None or k["tl"] in tls) and (lv is None or k["lv"] == lv):
            return code
    return None


def inventaire(path):
    import eccodes as ec
    out = []
    for gid in messages(path):
        k = cle_message(ec, gid)
        out.append(f'{k["sn"]}|{k["tl"]}|{k["lv"]}|{k["st"]}|{k["name"]}')
        ec.codes_release(gid)
    return sorted(set(out))


class Extracteur:
    def __init__(self):
        self.idx = None   # index du point de grille le plus proche pour chaque lieu
        self.vals = {}    # (lieu, code, echeance) -> valeur
        self.accum_depuis_debut = {}

    def lire(self, path, echeance):
        import eccodes as ec
        trouve = set()
        for gid in messages(path):
            k = cle_message(ec, gid)
            code = classer(k)
            if code is None:
                ec.codes_release(gid)
                continue
            if self.idx is None:
                self.idx = []
                for (_, lat, lon) in LIEUX:
                    near = ec.codes_grib_find_nearest(gid, lat, lon, False, 1)[0]
                    self.idx.append((int(near["index"]), near["lat"], near["lon"]))
            vals = ec.codes_get_values(gid)
            dt = max(1, (k["s1"] or 0) - (k["s0"] or 0))
            for i, (lieu, _, _) in enumerate(LIEUX):
                v = float(vals[self.idx[i][0]])
                if code == "tp":
                    # cumul depuis le début (startStep=0) -> on garde le cumul, la différence est faite plus tard ;
                    # sinon cumul sur l'intervalle -> ramené à 1 h
                    if (k["s0"] or 0) == 0:
                        self.accum_depuis_debut[(lieu, echeance)] = v
                    else:
                        self.vals[(lieu, "tp1h", echeance)] = v / dt
                else:
                    self.vals[(lieu, code, echeance)] = v
            trouve.add(code)
            ec.codes_release(gid)
        return trouve


def serie(ex, lieu, cycle_dt, echs):
    """Séries horaires du lieu : p (hPa), t (°C), w/g (kt), r (mm)."""
    g = lambda c, h: ex.vals.get((lieu, c, h))
    out = {"p": [], "t": [], "w": [], "g": [], "r": []}
    for h in echs:
        p, t, u, v = g("p", h), g("t", h), g("u", h), g("v", h)
        gg = g("g", h)
        if gg is None and g("ug", h) is not None and g("vg", h) is not None:
            gg = (g("ug", h) ** 2 + g("vg", h) ** 2) ** 0.5
        out["p"].append(None if p is None else round(p / 100.0, 1))
        out["t"].append(None if t is None else round(t - 273.15, 1))
        out["w"].append(None if u is None or v is None else round((u * u + v * v) ** 0.5 * MS_KT, 1))
        out["g"].append(None if gg is None else round(gg * MS_KT, 1))
        # précipitations horaires
        r = g("tp1h", h)
        if r is None and (lieu, h) in ex.accum_depuis_debut:
            prec = ex.accum_depuis_debut.get((lieu, h - 1), 0.0 if h == 1 else None)   # cumul à H0 = 0
            if h == 0:
                r = None
            elif prec is not None:
                r = max(0.0, ex.accum_depuis_debut[(lieu, h)] - prec)
        if r is None and g("pr", h) is not None:
            r = g("pr", h) * 3600.0
        out["r"].append(None if r is None else round(r, 2))
    return out


# ---------------------------------------------------------------- programme principal
def choisir_cycle():
    for c in cycles_recents()[:8]:
        ech = echeances(c, "SP1")
        if ech and max(ech) >= ECH_MIN_COMPLET:
            return c, ech
        log("cycle", c, "incomplet" if ech else "absent", "(dernière échéance :", max(ech) if ech else "—", ")")
    raise RuntimeError("aucun cycle AROME-OM complet trouvé")


def main():
    args = sys.argv[1:]
    out = args[0] if args and not args[0].startswith("--") else "arome.json"
    prev = args[args.index("--prev") + 1] if "--prev" in args else None
    local = args[args.index("--local") + 1] if "--local" in args else None

    if local:   # mode test : dossier de fichiers déjà présents
        fichiers = sorted(os.listdir(local))
        cycle = re.search(r"(\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z)", fichiers[0]).group(1)
        paquets = {}
        for f in fichiers:
            m = re.search(r"__(\w{3})__(\d{3})H__", f)
            paquets.setdefault(m.group(1), {})[int(m.group(2))] = os.path.join(local, f)
        echs_all = sorted(next(iter(paquets.values())).keys())
    else:
        cycle, echs_all = choisir_cycle()
        log("cycle choisi :", cycle, "échéances", min(echs_all), "à", max(echs_all))
        if prev and os.path.exists(prev):
            try:
                if json.load(open(prev, encoding="utf-8")).get("cycle") == cycle:
                    log("même cycle que le fichier précédent : rien à retélécharger")
                    if prev != out:
                        open(out, "w", encoding="utf-8").write(open(prev, encoding="utf-8").read())
                    return
            except Exception:
                pass
        paquets = None

    tmp = None if local else tempfile.mkdtemp(prefix="arome_")
    cycle_dt = datetime.strptime(cycle, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)

    def chemin(paquet, h):
        if local:
            return paquets.get(paquet, {}).get(h)
        dest = os.path.join(tmp, nom_fichier(cycle, paquet, h))
        http_get(url_fichier(cycle, paquet, h), dest)
        return dest

    # 1) inventaire sur l'échéance 1 de chaque paquet : où se trouve chaque paramètre ?
    ech_ref = 1 if 1 in echs_all else echs_all[0]
    ou = {}              # code -> paquet
    inv_log = {}
    for pq in PAQUETS:
        if local and pq not in paquets:
            continue
        if not local and not echeances(cycle, pq):
            continue
        p = chemin(pq, ech_ref)
        inv_log[pq] = inventaire(p)
        for ligne in inv_log[pq]:
            sn, tl, lv, st, nm = ligne.split("|")
            c = classer({"sn": sn, "tl": tl, "lv": int(lv) if lv.lstrip("-").isdigit() else lv, "st": st, "name": nm})
            if c and c not in ou:
                ou[c] = pq
        if not local:
            os.remove(p)
    log("paramètres trouvés :", {c: pq for c, pq in ou.items()})
    besoin = ["p", "u", "v"]
    if not all(c in ou for c in besoin):
        log("INVENTAIRE DES MESSAGES (pour diagnostic) :")
        for pq, lst in inv_log.items():
            for l in lst:
                log("  ", pq, l)
        raise RuntimeError("paramètres de base (pression, vent 10 m) introuvables dans les paquets : voir l'inventaire ci-dessus")

    # 2) lecture de toutes les échéances des paquets utiles
    utiles = sorted(set(ou.values()))
    ex = Extracteur()
    echs_ok = []
    for h in echs_all:
        trouve = set()
        ok = True
        for pq in utiles:
            try:
                p = chemin(pq, h)
            except Exception as e:
                log("échéance", h, pq, "indisponible :", e)
                ok = False
                continue
            if p is None:
                ok = False
                continue
            trouve |= ex.lire(p, h)
            if not local:
                os.remove(p)
        if ok:
            echs_ok.append(h)
    if not echs_ok:
        raise RuntimeError("aucune échéance lue")

    echs = [h for h in echs_ok if h <= 48]
    heures = [(cycle_dt + timedelta(hours=h)).strftime("%Y-%m-%dT%H:%M:%SZ") for h in echs]
    manquants = sorted({c for c in ("p", "u", "v", "t") if c not in ou} | ({"g"} if not ({"g"} <= set(ou) or {"ug", "vg"} <= set(ou)) else set())
                       | ({"r"} if not ({"tp"} <= set(ou) or {"pr"} <= set(ou)) else set()))
    data = {
        "source": "Météo-France AROME Outre-mer (domaine Réunion-Mayotte, 0,025°), données ouvertes data.gouv.fr (Licence Ouverte 2.0)",
        "cycle": cycle, "echeance_max": max(echs), "recupere": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "temps": heures, "manquants": manquants,
        "lieux": [{"n": LIEUX[i][0], "lat": LIEUX[i][1], "lon": LIEUX[i][2],
                   "grille_lat": round(ex.idx[i][1], 3), "grille_lon": round(ex.idx[i][2], 3)} for i in range(len(LIEUX))],
        "series": {LIEUX[i][0]: serie(ex, LIEUX[i][0], cycle_dt, echs) for i in range(len(LIEUX))},
    }
    with open(out, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, separators=(",", ":"))
    log("OK cycle", cycle, "-", len(heures), "échéances jusqu'à +", max(echs), "h - manquants :", manquants or "aucun")


if __name__ == "__main__":
    main()
