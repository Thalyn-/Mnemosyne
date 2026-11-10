#!/usr/bin/env python3
"""Application locale de recherche historique, sans dépendance Python externe."""
import argparse
import concurrent.futures
import datetime as dt
import json
import math
import re
import sqlite3
import uuid
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from html.parser import HTMLParser
from pathlib import Path

import synthesis

ROOT = Path(__file__).resolve().parent
DATABASE = ROOT / "mnemosyne.sqlite3"
USER_AGENT = "Mnemosyne/1.0 (https://github.com/Thalyn-/Mnemosyne; application locale de recherche historique)"
MAX_BODY = 2_000_000


def connect():
    db = sqlite3.connect(DATABASE)
    db.row_factory = sqlite3.Row
    return db


def initialize():
    with connect() as db:
        db.execute("""CREATE TABLE IF NOT EXISTS versions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            dossier TEXT NOT NULL,
            cree_le TEXT NOT NULL,
            donnees TEXT NOT NULL
        )""")
        db.execute("CREATE INDEX IF NOT EXISTS versions_dossier ON versions(dossier, id)")


def fetch(url, params, accept="application/json"):
    request = urllib.request.Request(
        url + "?" + urllib.parse.urlencode(params, doseq=True),
        headers={"User-Agent": USER_AGENT, "Accept": accept},
    )
    with urllib.request.urlopen(request, timeout=15) as response:
        return response.read(4_000_000)


def locality(query):
    """Conserver les précisions pour le choix du lieu, mais chercher son nom dans les catalogues."""
    return query.split(",", 1)[0].strip()


def wikipedia(query):
    base = "https://fr.wikipedia.org/w/api.php"
    found = json.loads(fetch(base, {
        "action": "query", "list": "search", "srsearch": locality(query),
        "srlimit": 10, "format": "json",
    }))
    candidates = found.get("query", {}).get("search", [])
    if not candidates:
        raise ValueError("Aucune page Wikipédia correspondante.")
    city = query.split(",")[0].strip().casefold()
    chosen = next((p for p in candidates if p["title"].casefold() == city), candidates[0])
    response = json.loads(fetch(base, {
        "action": "query", "prop": "extracts|coordinates|pageprops|info",
        "inprop": "url", "explaintext": 1, "titles": chosen["title"],
        "format": "json", "formatversion": 2,
    }))
    page = response["query"]["pages"][0]
    coord = page.get("coordinates", [{}])[0]
    return {
        "title": page["title"], "url": page.get("fullurl", ""),
        "extract": page.get("extract", ""),
        "qid": page.get("pageprops", {}).get("wikibase_item"),
        "lat": coord.get("lat"), "lon": coord.get("lon"),
    }


def make_timeline(page):
    events = []
    seen = set()
    for sentence in re.split(r"(?<=[.!?])\s+|\n+", page.get("extract", "")):
        text = re.sub(r"\s+", " ", sentence).strip(" =")
        match = re.search(r"(?<!\d)(1[0-9]{3}|20[0-9]{2})(?!\d)", text)
        if not match or len(text) < 30 or len(text) > 400:
            continue
        year = int(match.group(1))
        if (year, text) not in seen:
            events.append({"year": year, "text": text, "source": page["url"]})
            seen.add((year, text))
        if len(events) == 30:
            break
    return sorted(events, key=lambda event: event["year"])


def textual_clues(page):
    """Extraire des passages attribués, sans inventer des débats ou des édifices."""
    traces, questions = [], []
    building = re.compile(
        r"\b(ch[aâ]teau|forteresse|fortifications?|remparts?|enceinte|"
        r"abbaye|[eé]glise|chapelle|porte|citadelle|fort|vestiges?|monast[eè]re)\b",
        re.IGNORECASE,
    )
    lost = re.compile(
        r"\b(d[eé]truit\w*|d[eé]moli\w*|dispar\w*|ras[eé]\w*|"
        r"ruin[eé]\w*|n'existe plus|ne subsiste|ne reste|vestiges?)\b",
        re.IGNORECASE,
    )
    dispute = re.compile(
        r"\b(d[eé]bat\w*|controvers\w*|contest[eé]\w*|discut[eé]\w*|"
        r"incertain\w*|hypoth[eè]ses?|divergent\w*|"
        r"les historiens ne s'accordent pas|origine inconnue)\b",
        re.IGNORECASE,
    )
    for raw in re.split(r"(?<=[.!?])\s+|\n+", page.get("extract", "")):
        text = re.sub(r"\s+", " ", raw).strip(" =")
        if not 30 <= len(text) <= 500:
            continue
        clue = {"text": text, "source": page.get("url", "")}
        if building.search(text) and lost.search(text) and clue not in traces:
            traces.append(clue)
        if dispute.search(text) and clue not in questions:
            questions.append(clue)
    return traces[:20], questions[:20]


def gallica(query):
    raw = fetch("https://gallica.bnf.fr/SRU", {
        "operation": "searchRetrieve", "version": "1.2",
        "query": 'dc.anywhere all "' + query.replace('"', "") + '"',
        "maximumRecords": 10, "startRecord": 1,
    }, "application/xml")
    root = ET.fromstring(raw)
    ns = {"srw": "http://www.loc.gov/zing/srw/",
          "dc": "http://purl.org/dc/elements/1.1/"}
    count_text = root.findtext("srw:numberOfRecords", namespaces=ns)
    if count_text is None:
        raise ValueError("Gallica n'a pas renvoyé de nombre de résultats.")
    count = int(count_text)
    records = []
    for record in root.findall(".//srw:recordData", ns):
        title = record.findtext(".//dc:title", default="Document sans titre", namespaces=ns)
        identifiers = [node.text for node in record.findall(".//dc:identifier", ns) if node.text]
        link = next((value for value in identifiers
                     if value.startswith(("https://gallica.bnf.fr/", "http://gallica.bnf.fr/"))), "")
        records.append({"title": title, "url": link})
    return {"count": count, "records": records}


def internet_archive(query):
    payload = json.loads(fetch("https://archive.org/advancedsearch.php", {
        "q": query, "fl[]": ["identifier", "title"], "rows": 10, "output": "json",
    }))
    response = payload["response"]
    return {
        "count": response["numFound"],
        "records": [
            {"title": doc.get("title", "Document sans titre"),
             "url": "https://archive.org/details/" + urllib.parse.quote(doc["identifier"], safe="")}
            for doc in response["docs"] if doc.get("identifier")
        ],
    }


def wikisource(query):
    data = json.loads(fetch("https://fr.wikisource.org/w/api.php", {
        "action": "query", "list": "search", "srsearch": query,
        "srlimit": 10, "format": "json",
    }))
    result = data["query"]
    return {
        "count": result.get("searchinfo", {}).get("totalhits", len(result["search"])),
        "records": [
            {"title": item["title"],
             "url": "https://fr.wikisource.org/wiki/" + urllib.parse.quote(item["title"].replace(" ", "_"))}
            for item in result["search"]
        ],
    }


def congress(query):
    payload = json.loads(fetch("https://www.loc.gov/search/", {"q": query, "fo": "json", "c": 10}))
    return {
        "count": payload.get("pagination", {}).get("total", len(payload.get("results", []))),
        "records": [{"title": item.get("title") or "Document sans titre", "url": item["id"]}
                    for item in payload.get("results", []) if item.get("id")],
    }


class PerseeParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.articles = []
        self.current = None

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == "a" and attrs.get("href", "").startswith("/doc/"):
            self.current = {"url": "https://www.persee.fr" + attrs["href"], "title": ""}

    def handle_data(self, data):
        if self.current is not None:
            self.current["title"] += data

    def handle_endtag(self, tag):
        if tag == "a" and self.current is not None:
            title = re.sub(r"\s+", " ", self.current["title"]).strip()
            if title and self.current not in self.articles:
                self.current["title"] = title
                self.articles.append(self.current)
            self.current = None


def persee(query):
    url = "https://www.persee.fr/search?" + urllib.parse.urlencode({"q": query, "ta": "article"})
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(request, timeout=15) as response:
        page = response.read(2_000_000).decode("utf-8", "replace")
    parser = PerseeParser()
    parser.feed(page)
    return {"count": len(parser.articles), "records": parser.articles[:30], "url": url}


def wikidata(qid):
    if not qid or not re.fullmatch(r"Q[1-9]\d*", qid):
        raise ValueError("Cette page n'a pas d'identifiant Wikidata.")
    query = """PREFIX wd: <http://www.wikidata.org/entity/>
    PREFIX wdt: <http://www.wikidata.org/prop/direct/>
    PREFIX wikibase: <http://wikiba.se/ontology#>
    PREFIX bd: <http://www.bigdata.com/rdf#>
    SELECT ?item ?itemLabel ?kind ?coord ?date WHERE {
      { SELECT DISTINCT ?item ?kind ?date WHERE {
          ?item wdt:P19 wd:%s; wdt:P31 wd:Q5.
          BIND("person" AS ?kind) OPTIONAL { ?item wdt:P569 ?date. }
        } LIMIT 30 }
      UNION
      { SELECT DISTINCT ?item ?kind ?coord WHERE {
          ?item wdt:P131 wd:%s; wdt:P31/wdt:P279* wd:Q811979.
          BIND("place" AS ?kind) OPTIONAL { ?item wdt:P625 ?coord. }
        } LIMIT 30 }
      SERVICE wikibase:label { bd:serviceParam wikibase:language "fr,en". }
    }""" % (qid, qid)
    data = json.loads(fetch("https://query.wikidata.org/sparql", {
        "query": query, "format": "json",
    }))
    people, places, seen = [], [], set()
    for row in data["results"]["bindings"]:
        item_url = row["item"]["value"]
        if item_url in seen:
            continue
        seen.add(item_url)
        name = row.get("itemLabel", {}).get("value", item_url)
        if row["kind"]["value"] == "person":
            born = row.get("date", {}).get("value", "")[:4]
            people.append({
                "name": name,
                "detail": "Naissance : " + born if born else "Né(e) dans la commune",
                "source": item_url,
            })
        else:
            coord = row.get("coord", {}).get("value", "")
            match = re.fullmatch(r"Point\(([-\d.]+) ([-\d.]+)\)", coord)
            places.append({
                "name": name, "detail": "Lieu patrimonial à vérifier",
                "category": "recommandé", "source": item_url,
                "lat": float(match.group(2)) if match else None,
                "lon": float(match.group(1)) if match else None,
            })
    return people[:30], places[:30]


ARCHIVES = [
    ("Royaume-Uni", 51.5072, -0.1276, "The National Archives", "https://discovery.nationalarchives.gov.uk/"),
    ("Belgique", 50.8503, 4.3517, "Archives de l’État en Belgique", "https://search.arch.be/"),
    ("Luxembourg", 49.6116, 6.1319, "Archives nationales de Luxembourg", "https://anlux.public.lu/"),
    ("Allemagne", 52.52, 13.405, "Bundesarchiv", "https://www.bundesarchiv.de/"),
    ("Pays-Bas", 52.3676, 4.9041, "Nationaal Archief", "https://www.nationaalarchief.nl/"),
    ("Suisse", 46.9480, 7.4474, "Archives fédérales suisses", "https://www.bar.admin.ch/"),
    ("Italie", 41.9028, 12.4964, "Archivio Centrale dello Stato", "https://acs.cultura.gov.it/"),
    ("Espagne", 40.4168, -3.7038, "Portal de Archivos Españoles", "https://pares.cultura.gob.es/"),
]


def haversine(lat1, lon1, lat2, lon2):
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp, dl = p2 - p1, math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 6371 * 2 * math.asin(min(1, math.sqrt(a)))


def catalogue(query, page):
    q = urllib.parse.quote(query)
    gallica_query = urllib.parse.quote('dc.anywhere all "' + query.replace('"', "") + '"')
    sources = [
        ("Gallica · BnF", "Bibliothèque numérique",
         "https://gallica.bnf.fr/SRU?operation=searchRetrieve&version=1.2&query=" + gallica_query, "automatique"),
        ("Persée", "Articles scientifiques", "https://www.persee.fr/search?q=" + q, "lien"),
        ("Archives départementales · FranceArchives", "Archives locales", "https://francearchives.gouv.fr/fr/search?text=" + q, "lien"),
        ("Cairn", "Publications scientifiques", "https://shs.cairn.info/resultats_recherche?searchTerm=" + q, "lien"),
        ("OpenEdition", "Revues et livres", "https://search.openedition.org/?q=" + q, "lien"),
        ("HAL", "Travaux académiques", "https://hal.science/search/index/?q=" + q, "lien"),
        ("Wikisource", "Textes historiques", "https://fr.wikisource.org/w/index.php?search=" + q, "automatique"),
        ("Internet Archive", "Livres et archives", "https://archive.org/search?query=" + q, "automatique"),
        ("Bibliothèque du Congrès", "Collections américaines", "https://www.loc.gov/search/?q=" + q, "automatique"),
        ("Franklin Papers", "Correspondances historiques", "https://franklinpapers.org/", "lien"),
        ("Founders Online", "Correspondances historiques", "https://founders.archives.gov/?q=" + q, "lien"),
        ("Wikipédia", "Synthèse et pistes",
         page.get("url") or "https://fr.wikipedia.org/w/index.php?search=" + q, "automatique"),
        ("Wikidata", "Données patrimoniales",
         "https://www.wikidata.org/wiki/" + page["qid"] if page.get("qid")
         else "https://www.wikidata.org/w/index.php?search=" + q, "automatique"),
    ]
    result = [{"name": name, "type": kind, "url": url, "mode": mode}
              for name, kind, url, mode in sources]
    if page.get("lat") is not None and page.get("lon") is not None:
        near = sorted(
            (haversine(page["lat"], page["lon"], lat, lon), country, name, url)
            for country, lat, lon, name, url in ARCHIVES
        )
        for km, country, name, url in near:
            if km <= 700:
                result.append({
                    "name": name,
                    "type": f"Archives étrangères · {country} (capitale à environ {round(km)} km)",
                    "url": url, "mode": "lien",
                })
    return result


def research(query):
    errors, outcomes, status = [], {}, {}
    city = locality(query)
    with concurrent.futures.ThreadPoolExecutor(max_workers=5) as pool:
        jobs = {
            "Wikipédia": pool.submit(wikipedia, query),
            "Gallica": pool.submit(gallica, city),
            "Internet Archive": pool.submit(internet_archive, city),
            "Wikisource": pool.submit(wikisource, city),
            "Bibliothèque du Congrès": pool.submit(congress, city),
        }
        for name, job in jobs.items():
            try:
                outcomes[name] = job.result()
                status[name] = "ok"
            except Exception as error:
                errors.append(f"{name} : {error}")
                status[name] = "error"
    page = outcomes.get("Wikipédia", {})
    people, places = [], []
    if page:
        try:
            people, places = wikidata(page.get("qid"))
            status["Wikidata"] = "ok"
        except Exception as error:
            errors.append(f"Wikidata : {error}")
            status["Wikidata"] = "error"
    else:
        status["Wikidata"] = "skipped"
    traces, questions = textual_clues(page)
    synthesis_status = "source_absente"
    synthesis_detail = "La page nécessaire à l'analyse n'a pas été obtenue."
    if page.get("extract") and page.get("url"):
        try:
            model, generated = synthesis.synthesize(query, page)
            synthesis_status = "ok" if any(generated.values()) else "empty"
            synthesis_detail = (
                f"Synthèse locale : {model}. Chaque citation doit être vérifiée."
                if synthesis_status == "ok" else
                f"Le modèle local {model} n'a fourni aucune proposition avec citation exploitable."
            )
            timeline = generated["events"] or make_timeline(page)
            for person in generated["people"]:
                if not any(existing["name"].casefold() == person["name"].casefold() for existing in people):
                    people.append({"name": person["name"], "detail": person["text"],
                                   "source": person["source"], "evidence": person["evidence"]})
            for place in generated["places"]:
                if not any(existing["name"].casefold() == place["name"].casefold() for existing in places):
                    places.append({"name": place["name"], "detail": place["text"],
                                   "category": place["category"], "source": place["source"],
                                   "evidence": place["evidence"], "lat": None, "lon": None})
            traces = generated["traces"] or traces
            questions = generated["questions"] or questions
        except (OSError, ValueError, KeyError, TypeError) as error:
            timeline = make_timeline(page)
            synthesis_status = "unavailable"
            synthesis_detail = (
                f"Analyse locale indisponible : {error}. "
                "Voir la section « Analyse locale facultative » du guide."
            )
    else:
        timeline = make_timeline(page) if page else []
    return {
        "query": query,
        "page": {key: value for key, value in page.items() if key != "extract"},
        "sources": catalogue(city, page),
        "results": {key: value for key, value in outcomes.items() if key != "Wikipédia"},
        "timeline": sorted(timeline, key=lambda event: event["year"]),
        "people": people[:30], "places": places[:30],
        "traces": [], "questions": [], "persee": [],
        "trace_clues": traces, "question_clues": questions,
        "source_status": status,
        "synthesis_status": synthesis_status, "synthesis_detail": synthesis_detail,
        "errors": errors,
    }


def persist(data, dossier=None):
    dossier = dossier or str(uuid.uuid4())
    created = dt.datetime.now(dt.timezone.utc).isoformat()
    with connect() as db:
        cursor = db.execute(
            "INSERT INTO versions (dossier, cree_le, donnees) VALUES (?, ?, ?)",
            (dossier, created, json.dumps(data, ensure_ascii=False)),
        )
        return cursor.lastrowid


def version(version_id):
    with connect() as db:
        row = db.execute("SELECT * FROM versions WHERE id = ?", (version_id,)).fetchone()
    if row is None:
        return None
    return {"id": row["id"], "dossier": row["dossier"], "cree_le": row["cree_le"],
            "data": json.loads(row["donnees"])}


class Handler(BaseHTTPRequestHandler):
    def reply(self, status, data, content_type="application/json; charset=utf-8"):
        body = json.dumps(data, ensure_ascii=False).encode("utf-8") if content_type.startswith("application/json") else data
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("X-Content-Type-Options", "nosniff")
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        path = urllib.parse.urlsplit(self.path).path
        if path == "/api/versions":
            with connect() as db:
                rows = db.execute("SELECT id, dossier, cree_le, donnees FROM versions ORDER BY id DESC").fetchall()
            return self.reply(200, [
                {"id": row["id"], "dossier": row["dossier"], "cree_le": row["cree_le"],
                 "query": json.loads(row["donnees"]).get("query", "")}
                for row in rows
            ])
        if path == "/api/persee":
            query = urllib.parse.parse_qs(urllib.parse.urlsplit(self.path).query).get("q", [""])[0].strip()
            if not query or len(query) > 200:
                return self.reply(400, {"error": "La recherche Persée doit contenir de 1 à 200 caractères."})
            try:
                return self.reply(200, persee(query))
            except Exception as error:
                return self.reply(502, {"error": f"Persée ne répond pas : {error}",
                                        "url": "https://www.persee.fr/search?" + urllib.parse.urlencode({"q": query})})
        match = re.fullmatch(r"/api/versions/(\d+)", path)
        if match:
            item = version(int(match.group(1)))
            return self.reply(200 if item else 404, item or {"error": "Version introuvable."})
        files = {
            "/": ("index.html", "text/html; charset=utf-8"),
            "/app.js": ("app.js", "text/javascript; charset=utf-8"),
            "/style.css": ("style.css", "text/css; charset=utf-8"),
        }
        if path in files:
            name, content_type = files[path]
            return self.reply(200, (ROOT / "static" / name).read_bytes(), content_type)
        self.reply(404, {"error": "Page introuvable."})

    def do_POST(self):
        path = urllib.parse.urlsplit(self.path).path
        try:
            length = int(self.headers.get("Content-Length", "0"))
            if not 0 < length <= MAX_BODY:
                raise ValueError("Taille de requête invalide.")
            payload = json.loads(self.rfile.read(length))
            if path == "/api/research":
                query = payload.get("query", "").strip()
                if not query or len(query) > 200:
                    raise ValueError("La recherche doit contenir de 1 à 200 caractères.")
                data = research(query)
                return self.reply(201, version(persist(data)))
            match = re.fullmatch(r"/api/versions/(\d+)/(refresh|save)", path)
            if not match:
                return self.reply(404, {"error": "Action introuvable."})
            old = version(int(match.group(1)))
            if not old:
                return self.reply(404, {"error": "Version introuvable."})
            if match.group(2) == "refresh":
                data = research(old["data"]["query"])
                for key in ("traces", "questions", "persee", "perseeCount", "perseeUrl"):
                    data[key] = old["data"].get(key, [])
                old_places = {place.get("name"): place for place in old["data"].get("places", [])}
                for place in data.get("places", []):
                    previous = old_places.get(place.get("name"), {})
                    if previous.get("category") in {"indispensable", "recommandé", "en bonus"}:
                        place["category"] = previous["category"]
                return self.reply(201, version(persist(data, old["dossier"])))
            data = payload.get("data")
            if not isinstance(data, dict) or data.get("query") != old["data"].get("query"):
                raise ValueError("Dossier invalide.")
            with connect() as db:
                db.execute("UPDATE versions SET donnees = ? WHERE id = ?",
                           (json.dumps(data, ensure_ascii=False), old["id"]))
            return self.reply(200, version(old["id"]))
        except (ValueError, TypeError, json.JSONDecodeError) as error:
            return self.reply(400, {"error": str(error)})

    def log_message(self, fmt, *args):
        print(f"{self.address_string()} - {fmt % args}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Lancer Mnémosyne sur cet ordinateur.")
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument("--diagnostic", action="store_true",
                        help="Vérifier les services sans créer de dossier ni démarrer le serveur.")
    parser.add_argument("--ville", default="Laon", help="Lieu recherché pour le diagnostic.")
    args = parser.parse_args()
    if args.diagnostic:
        import diagnostic
        try:
            print("\n".join(diagnostic.run(args.ville)))
        except ValueError as error:
            parser.error(str(error))
        raise SystemExit(0)
    initialize()
    server = ThreadingHTTPServer(("127.0.0.1", args.port), Handler)
    print(f"Mnémosyne est disponible sur http://127.0.0.1:{args.port}", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        server.server_close()
