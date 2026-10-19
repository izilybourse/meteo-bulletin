#!/usr/bin/env python3
"""Relais du "BULLETIN DE PREVISIONS METEOROLOGIQUES" de https://meteofrance.re/fr
vers un fichier JSON lisible par le widget METEO LAB (izilyfire.fr).

Usage : python3 fetch_bulletin.py [sortie.json] [fichier_html_de_test]
Sans dépendance (bibliothèque standard uniquement).
"""
import json, re, sys, urllib.request
from datetime import datetime, timezone, timedelta
from html.parser import HTMLParser

URL = "https://meteofrance.re/fr"
MOIS = {"janvier":1,"février":2,"fevrier":2,"mars":3,"avril":4,"mai":5,"juin":6,"juillet":7,
        "août":8,"aout":8,"septembre":9,"octobre":10,"novembre":11,"décembre":12,"decembre":12}


class Bulletin(HTMLParser):
    """Collecte h2/h3/p du bloc <div class="zone-bulletin-details">."""
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.on = False; self.depth = 0; self.cur = None; self.buf = []; self.items = []

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if tag == "div":
            if not self.on and "zone-bulletin-details" in (a.get("class") or "").split():
                self.on = True; self.depth = 1; return
            if self.on: self.depth += 1
        if self.on and tag in ("h2", "h3", "p"):
            self.cur = tag; self.buf = []
        if self.on and tag == "br" and self.cur:
            self.buf.append(" ")

    def handle_endtag(self, tag):
        if self.on and self.cur == tag and tag in ("h2", "h3", "p"):
            txt = " ".join("".join(self.buf).split())
            if txt: self.items.append((tag, txt))
            self.cur = None
        if tag == "div" and self.on:
            self.depth -= 1
            if self.depth == 0: self.on = False

    def handle_data(self, d):
        if self.cur: self.buf.append(d)


def parse(html):
    p = Bulletin(); p.feed(html)
    if not p.items:
        raise RuntimeError("bloc bulletin introuvable (structure de la page modifiée ?)")
    title, issued_txt, sections = "", "", []
    for tag, txt in p.items:
        if tag == "h2" and not title: title = txt
        elif tag == "h3" and txt.lower().startswith("bulletin émis"): issued_txt = txt
        elif tag == "h3": sections.append({"titre": txt, "paragraphes": []})
        elif tag == "p" and sections: sections[-1]["paragraphes"].append(txt)
    if not sections:
        raise RuntimeError("bulletin sans section")
    issued_iso = None
    m = re.search(r"émis le \w+ (\d{1,2}) (\w+) (\d{4}) à (\d{1,2})", issued_txt, re.I)
    if m and m.group(2).lower() in MOIS:
        tz = timezone(timedelta(hours=4))
        issued_iso = datetime(int(m.group(3)), MOIS[m.group(2).lower()], int(m.group(1)), int(m.group(4)), 0, tzinfo=tz).isoformat()
    return {"source": URL, "titre": title, "emission": issued_txt, "emission_iso": issued_iso,
            "recupere": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"), "sections": sections}


def main():
    out = sys.argv[1] if len(sys.argv) > 1 else "bulletin.json"
    if len(sys.argv) > 2:
        html = open(sys.argv[2], encoding="utf-8").read()
    else:
        req = urllib.request.Request(URL, headers={"User-Agent": "Mozilla/5.0 (compatible; meteo-lab-relay)", "Accept-Language": "fr"})
        html = urllib.request.urlopen(req, timeout=30).read().decode("utf-8", "replace")
    data = parse(html)
    with open(out, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=1)
    print("OK", data["emission"], "-", len(data["sections"]), "sections")


if __name__ == "__main__":
    main()
