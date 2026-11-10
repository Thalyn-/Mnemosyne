"""Vérification des services sans modifier les dossiers archivés."""
import concurrent.futures
import socket
import ssl
import urllib.error
import xml.etree.ElementTree as ET


def describe_error(error):
    if isinstance(error, urllib.error.HTTPError):
        return f"Échec HTTP {error.code}."
    reason = error.reason if isinstance(error, urllib.error.URLError) else error
    if isinstance(reason, socket.gaierror):
        return "Nom du service introuvable (DNS)."
    if isinstance(reason, (TimeoutError, socket.timeout)):
        return "Délai de connexion dépassé."
    if isinstance(reason, ssl.SSLError):
        return "Échec de la connexion sécurisée (TLS)."
    if isinstance(reason, ConnectionRefusedError):
        return "Connexion refusée."
    if isinstance(error, (ValueError, KeyError, TypeError, ET.ParseError)):
        return "Réponse absente ou non exploitable."
    return f"Erreur de connexion ou de réponse ({type(reason).__name__})."


def run(query):
    import app
    import synthesis

    city = app.locality(query)
    if not city or len(query) > 200:
        raise ValueError("Indiquez un lieu de 1 à 200 caractères.")
    checks = [
        ("Wikipédia", lambda: app.wikipedia(query)),
        ("Gallica", lambda: app.gallica(city)),
        ("Internet Archive", lambda: app.internet_archive(city)),
        ("Wikisource", lambda: app.wikisource(city)),
        ("Bibliothèque du Congrès", lambda: app.congress(city)),
        ("Analyse locale", synthesis.installed_model),
    ]
    results = {}
    with concurrent.futures.ThreadPoolExecutor(max_workers=len(checks)) as pool:
        jobs = [(name, pool.submit(fn)) for name, fn in checks]
        for name, job in jobs:
            try:
                results[name] = (True, job.result())
            except (OSError, ValueError, KeyError, TypeError, ET.ParseError) as error:
                results[name] = (False, describe_error(error))
    lines = []
    for name, _ in checks:
        ok, value = results[name]
        if not ok:
            lines.append(f"{name} : {value}")
        elif name == "Wikipédia":
            coordinate = "coordonnées disponibles" if value.get("lat") is not None and value.get("lon") is not None else "coordonnées absentes"
            lines.append(f"Wikipédia : page « {value.get('title', '?')} », {coordinate}.")
        elif name == "Analyse locale":
            lines.append("Analyse locale : un modèle est disponible.")
        else:
            lines.append(f"{name} : réponse reçue, {value.get('count', 0)} résultat(s).")
    page_ok, page = results["Wikipédia"]
    if page_ok and page.get("qid"):
        try:
            people, places = app.wikidata(page["qid"])
            lines.append(f"Wikidata : réponse reçue, {len(people)} personnalité(s), {len(places)} lieu(x).")
        except (OSError, ValueError, KeyError, TypeError, ET.ParseError) as error:
            lines.append("Wikidata : " + describe_error(error))
    else:
        lines.append("Wikidata : non interrogé (identifiant de la commune absent).")
    return lines
