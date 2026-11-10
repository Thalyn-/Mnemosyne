import json
import socket
import tempfile
import threading
import unittest
from pathlib import Path
from urllib.request import Request, urlopen
from urllib.error import URLError
from unittest.mock import patch
from http.server import ThreadingHTTPServer

import app
import diagnostic
import synthesis


class HistoricalResearchTests(unittest.TestCase):
    def test_timeline_extracts_distinct_years_and_preserves_source(self):
        page = {
            "url": "https://fr.wikipedia.org/wiki/Laon",
            "extract": (
                "La ville est mentionnée pour la première fois dans les textes conservés en 1200. "
                "Une autre phrase historique décrit le développement du territoire en 1345. "
                "Une autre phrase historique décrit le développement du territoire en 1345."
            ),
        }
        events = app.make_timeline(page)
        self.assertEqual([event["year"] for event in events], [1200, 1345])
        self.assertTrue(all(event["source"] == page["url"] for event in events))

    def test_archive_catalogue_includes_nearby_foreign_archives_only(self):
        sources = app.catalogue("Laon", {"lat": 49.56, "lon": 3.62})
        countries = [source["type"] for source in sources]
        self.assertTrue(any("Belgique" in country for country in countries))
        self.assertFalse(any("Espagne" in country for country in countries))
        self.assertTrue(any(source["name"] == "Persée" for source in sources))

    def test_persee_parser_extracts_article_links_and_titles(self):
        parser = app.PerseeParser()
        parser.feed(
            '<a href="/doc/abc_0000-0000_1984_num_1_1_1234">Article historique</a>'
        )
        self.assertEqual(len(parser.articles), 1)
        self.assertEqual(parser.articles[0]["title"], "Article historique")
        self.assertEqual(
            parser.articles[0]["url"],
            "https://www.persee.fr/doc/abc_0000-0000_1984_num_1_1_1234",
        )

    def test_gallica_reads_records_from_sru_response(self):
        xml = b"""<?xml version="1.0"?>
        <searchRetrieveResponse xmlns="http://www.loc.gov/zing/srw/">
          <numberOfRecords>1</numberOfRecords><records><record><recordData>
            <srw_dc:dc xmlns:srw_dc="info:srw/schema/1/dc-schema"
              xmlns:dc="http://purl.org/dc/elements/1.1/">
              <dc:title>Laon et son histoire</dc:title>
              <dc:identifier>https://gallica.bnf.fr/ark:/12148/bpt6k123</dc:identifier>
            </srw_dc:dc>
          </recordData></record></records></searchRetrieveResponse>"""
        with patch.object(app, "fetch", return_value=xml):
            result = app.gallica("Laon")
        self.assertEqual(result["count"], 1)
        self.assertEqual(result["records"][0]["title"], "Laon et son histoire")
        self.assertTrue(result["records"][0]["url"].startswith("https://gallica.bnf.fr/"))

    def test_wikisource_and_congress_convert_search_results_to_document_links(self):
        wiki_response = json.dumps({"query": {"searchinfo": {"totalhits": 12}, "search": [
            {"title": "Histoire de Laon"},
        ]}}).encode()
        congress_response = json.dumps({"pagination": {"total": 3}, "results": [
            {"title": "A history", "id": "https://www.loc.gov/item/123/"},
        ]}).encode()
        with patch.object(app, "fetch", return_value=wiki_response):
            wiki = app.wikisource("Laon")
        with patch.object(app, "fetch", return_value=congress_response):
            congress = app.congress("Laon")
        self.assertEqual(wiki["count"], 12)
        self.assertEqual(wiki["records"][0]["url"], "https://fr.wikisource.org/wiki/Histoire_de_Laon")
        self.assertEqual(congress["count"], 3)
        self.assertEqual(congress["records"][0]["url"], "https://www.loc.gov/item/123/")

    def test_wikidata_returns_both_people_and_coordinates(self):
        response = {"results": {"bindings": [
            {"item": {"value": "https://www.wikidata.org/entity/Q2"},
             "itemLabel": {"value": "Personnalité"}, "kind": {"value": "person"},
             "date": {"value": "1200-01-01T00:00:00Z"}},
            {"item": {"value": "https://www.wikidata.org/entity/Q3"},
             "itemLabel": {"value": "Monument"}, "kind": {"value": "place"},
             "coord": {"value": "Point(3.62 49.56)"}},
        ]}}
        with patch.object(app, "fetch", return_value=json.dumps(response).encode()) as fetch:
            people, places = app.wikidata("Q154445")
        self.assertEqual(people[0]["name"], "Personnalité")
        self.assertEqual(people[0]["detail"], "Naissance : 1200")
        self.assertEqual((places[0]["lat"], places[0]["lon"]), (49.56, 3.62))
        self.assertIn("LIMIT 30", fetch.call_args.args[1]["query"])

    def test_extracts_only_sourced_clues_from_text(self):
        page = {
            "url": "https://fr.wikipedia.org/wiki/Laon",
            "extract": (
                "Les remparts ont été détruits pendant les combats du dix-neuvième siècle. "
                "L'origine de cette tradition fait encore débat parmi les historiens. "
                "Le climat est océanique et les températures demeurent modérées."
            ),
        }
        traces, questions = app.textual_clues(page)
        self.assertEqual(len(traces), 1)
        self.assertEqual(len(questions), 1)
        self.assertIn("remparts", traces[0]["text"])
        self.assertEqual(questions[0]["source"], page["url"])
        self.assertEqual(app.textual_clues({}), ([], []))

    def test_research_queries_city_and_reports_individual_failures(self):
        page = {
            "title": "Laon", "url": "https://fr.wikipedia.org/wiki/Laon",
            "lat": 49.56, "lon": 3.62, "qid": "Q154445",
            "extract": "La cathédrale fut consacrée en 1215 après une longue période de travaux.",
        }
        result = {"count": 1, "records": [{"title": "Document", "url": "https://example.org/doc"}]}
        with patch.object(app, "wikipedia", return_value=page) as wiki, \
             patch.object(app, "gallica", return_value=result) as gallica, \
             patch.object(app, "internet_archive", side_effect=OSError("réseau inaccessible")) as archive, \
             patch.object(app, "wikisource", return_value=result) as wiki_source, \
             patch.object(app, "congress", return_value=result) as congress, \
             patch.object(app, "wikidata", return_value=([], [])):
            dossier = app.research("Laon, Aisne, France")
        wiki.assert_called_once_with("Laon, Aisne, France")
        for mock in (gallica, archive, wiki_source, congress):
            mock.assert_called_once_with("Laon")
        self.assertEqual(dossier["source_status"]["Gallica"], "ok")
        self.assertEqual(dossier["source_status"]["Internet Archive"], "error")
        self.assertEqual(dossier["source_status"]["Wikidata"], "ok")
        self.assertEqual(dossier["results"]["Gallica"]["count"], 1)
        self.assertEqual(dossier["timeline"][0]["year"], 1215)
        self.assertTrue(any("Internet Archive" in error for error in dossier["errors"]))

    def test_wikipedia_search_uses_locality_not_full_address(self):
        search = json.dumps({"query": {"search": [{"title": "Laon"}]}}).encode()
        article = json.dumps({"query": {"pages": [{
            "title": "Laon", "fullurl": "https://fr.wikipedia.org/wiki/Laon",
            "extract": "Un texte.", "coordinates": [{"lat": 49.56, "lon": 3.62}],
            "pageprops": {"wikibase_item": "Q154445"},
        }]}}).encode()
        with patch.object(app, "fetch", side_effect=[search, article]) as fetch:
            page = app.wikipedia("Laon, Aisne, France")
        self.assertEqual(fetch.call_args_list[0].args[1]["srsearch"], "Laon")
        self.assertEqual(page["title"], "Laon")
        self.assertEqual(page["qid"], "Q154445")

    def test_research_integrates_source_backed_local_synthesis(self):
        page = {"title": "Laon", "url": "https://example.org/page", "qid": "Q154445",
                "lat": 49.56, "lon": 3.62, "extract": "Texte source de la ville à analyser."}
        generated = {
            "events": [{"year": 1215, "text": "Consécration de la cathédrale.",
                        "evidence": "Extrait daté de la source", "source": page["url"]}],
            "people": [{"name": "Une personnalité", "text": "Personnalité liée à la commune.",
                        "evidence": "Une personnalité et son histoire", "source": page["url"]}],
            "places": [{"name": "Cathédrale", "text": "Monument de la ville.",
                        "category": "indispensable", "evidence": "La cathédrale ancienne", "source": page["url"]}],
            "traces": [{"text": "Un ancien rempart détruit.", "evidence": "Extrait de la source", "source": page["url"]}],
            "questions": [{"text": "L'origine est-elle connue ?", "evidence": "Extrait de la source", "source": page["url"]}],
        }
        documents = {"count": 0, "records": []}
        with patch.object(app, "wikipedia", return_value=page), \
             patch.object(app, "gallica", return_value=documents), \
             patch.object(app, "internet_archive", return_value=documents), \
             patch.object(app, "wikisource", return_value=documents), \
             patch.object(app, "congress", return_value=documents), \
             patch.object(app, "wikidata", return_value=([], [])), \
             patch.object(app.synthesis, "synthesize", return_value=("local", generated)):
            data = app.research("Laon")
        self.assertEqual(data["synthesis_status"], "ok")
        self.assertEqual(data["timeline"][0]["year"], 1215)
        self.assertEqual(data["people"][0]["name"], "Une personnalité")
        self.assertEqual(data["places"][0]["category"], "indispensable")
        self.assertEqual(data["trace_clues"][0]["source"], page["url"])
        self.assertEqual(len(data["question_clues"]), 1)


class SynthesisTests(unittest.TestCase):
    def test_validate_rejects_unsupported_events_people_and_controversies(self):
        source_text = (
            "La cathédrale fut consacrée en 1215 après de nombreux travaux. "
            "Son origine fait débat parmi les historiens depuis plusieurs décennies. "
            "Les remparts ont été détruits pendant les combats du dix-neuvième siècle."
        )
        data = {
            "events": [
                {"year": 1215, "text": "Consécration de la cathédrale.",
                 "evidence": "La cathédrale fut consacrée en 1215 après de nombreux travaux."},
                {"year": 1250, "text": "Une date inventée.", "evidence": "La cathédrale fut consacrée en 1215 après de nombreux travaux."},
            ],
            "people": [{"name": "Un personnage inventé", "text": "Personnalité liée à la ville.",
                        "evidence": "La cathédrale fut consacrée en 1215 après de nombreux travaux."}],
            "places": [],
            "traces": [{"text": "Les remparts ont disparu après les combats.",
                        "evidence": "Les remparts ont été détruits pendant les combats du dix-neuvième siècle."}],
            "questions": [
                {"text": "Quelle est l'origine de cet édifice ?",
                 "evidence": "Son origine fait débat parmi les historiens depuis plusieurs décennies."},
                {"text": "L'année serait-elle controversée ?",
                 "evidence": "La cathédrale fut consacrée en 1215 après de nombreux travaux."},
            ],
        }
        result = synthesis.validate(data, source_text, "https://example.org/source")
        self.assertEqual(len(result["events"]), 1)
        self.assertEqual(result["events"][0]["year"], 1215)
        self.assertEqual(result["people"], [])
        self.assertEqual(len(result["traces"]), 1)
        self.assertEqual(len(result["questions"]), 1)
        self.assertEqual(result["questions"][0]["source"], "https://example.org/source")

    def test_model_request_uses_source_and_local_model(self):
        payload = {"events": [], "people": [], "places": [], "traces": [], "questions": []}
        page = {"extract": "La cathédrale fut consacrée en 1215 après de nombreux travaux.",
                "url": "https://example.org/source"}
        with patch.object(synthesis, "installed_model", return_value="modele-local"), \
             patch.object(synthesis, "local_request", return_value={"response": json.dumps(payload)}) as request:
            model, result = synthesis.synthesize("Laon", page)
        self.assertEqual(model, "modele-local")
        self.assertEqual(result["events"], [])
        self.assertEqual(request.call_args.args[0], "/api/generate")
        self.assertEqual(request.call_args.args[1]["model"], "modele-local")
        self.assertIn(page["extract"], request.call_args.args[1]["prompt"])

    def test_invalid_synthesis_shape_fails_explicitly(self):
        with self.assertRaises(ValueError):
            synthesis.validate({"events": []}, "Un texte source suffisamment long.", "https://example.org")


class DiagnosticTests(unittest.TestCase):
    def test_reports_independent_failures_and_wikidata_counts(self):
        page = {"title": "Laon", "qid": "Q154445", "lat": 49.56, "lon": 3.62}
        result = {"count": 2, "records": []}
        with patch.object(app, "wikipedia", return_value=page), \
             patch.object(app, "gallica", side_effect=URLError(socket.gaierror("nom inconnu"))), \
             patch.object(app, "internet_archive", return_value=result), \
             patch.object(app, "wikisource", return_value=result), \
             patch.object(app, "congress", return_value=result), \
             patch.object(app, "wikidata", return_value=([{}], [{}, {}])), \
             patch.object(synthesis, "installed_model", side_effect=ConnectionRefusedError()):
            lines = diagnostic.run("Laon, Aisne, France")
        self.assertIn("Wikipédia : page « Laon », coordonnées disponibles.", lines)
        self.assertIn("Gallica : Nom du service introuvable (DNS).", lines)
        self.assertIn("Analyse locale : Connexion refusée.", lines)
        self.assertIn("Wikidata : réponse reçue, 1 personnalité(s), 2 lieu(x).", lines)

    def test_does_not_expose_connection_error_text(self):
        message = diagnostic.describe_error(URLError("données privées dans une erreur"))
        self.assertNotIn("données privées", message)


class VersionStorageTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.database = Path(self.temp.name) / "test.sqlite3"
        self.patch = patch.object(app, "DATABASE", self.database)
        self.patch.start()
        app.initialize()

    def tearDown(self):
        self.patch.stop()
        self.temp.cleanup()

    def test_refresh_creates_another_version_without_replacing_previous(self):
        first = app.persist({"query": "Laon", "traces": ["Ancienne porte"]})
        second = app.persist({"query": "Laon", "traces": ["Ancienne porte"]},
                             app.version(first)["dossier"])
        self.assertEqual(app.version(first)["data"]["traces"], ["Ancienne porte"])
        self.assertEqual(app.version(second)["dossier"], app.version(first)["dossier"])
        self.assertNotEqual(first, second)
        self.assertEqual(app.version(second)["data"]["query"], "Laon")

    def test_research_endpoint_creates_a_populated_version_from_service_responses(self):
        page = {
            "title": "Laon", "url": "https://fr.wikipedia.org/wiki/Laon", "qid": "Q154445",
            "lat": 49.56, "lon": 3.62,
            "extract": (
                "La cathédrale fut consacrée en 1215 après une longue période de travaux. "
                "Les remparts ont été détruits pendant les combats du dix-neuvième siècle. "
                "L'origine de cette tradition fait encore débat parmi les historiens."
            ),
        }
        documents = {"count": 1, "records": [{"title": "Histoire", "url": "https://example.org/histoire"}]}
        people = [{"name": "Personnalité", "detail": "Naissance : 1200", "source": "https://example.org/personne"}]
        places = [{"name": "Cathédrale", "detail": "Monument", "category": "recommandé",
                   "source": "https://example.org/lieu", "lat": 49.56, "lon": 3.62}]
        server = ThreadingHTTPServer(("127.0.0.1", 0), app.Handler)
        thread = threading.Thread(target=server.serve_forever)
        thread.start()
        try:
            request = Request(f"http://127.0.0.1:{server.server_port}/api/research",
                              data=json.dumps({"query": "Laon, Aisne, France"}).encode(),
                              headers={"Content-Type": "application/json"}, method="POST")
            with patch.object(app, "wikipedia", return_value=page), \
                 patch.object(app, "gallica", return_value=documents), \
                 patch.object(app, "internet_archive", return_value=documents), \
                 patch.object(app, "wikisource", return_value=documents), \
                 patch.object(app, "congress", return_value=documents), \
                 patch.object(app, "wikidata", return_value=(people, places)):
                with urlopen(request) as response:
                    dossier = json.loads(response.read())
            data = dossier["data"]
            self.assertEqual(data["timeline"][0]["year"], 1215)
            self.assertEqual(data["people"][0]["name"], "Personnalité")
            self.assertEqual(data["places"][0]["lat"], 49.56)
            self.assertEqual(len(data["trace_clues"]), 1)
            self.assertEqual(len(data["question_clues"]), 1)
            self.assertEqual(data["results"]["Gallica"]["records"][0]["title"], "Histoire")
            self.assertEqual(app.version(dossier["id"])["data"], data)
        finally:
            server.shutdown()
            thread.join()
            server.server_close()

    def test_refresh_endpoint_preserves_annotations_and_creates_history(self):
        original = {
            "query": "Laon", "traces": ["Ancienne porte"], "questions": ["Question à vérifier"],
            "places": [{"name": "Cathédrale", "category": "indispensable"}],
        }
        first = app.persist(original)
        server = ThreadingHTTPServer(("127.0.0.1", 0), app.Handler)
        thread = threading.Thread(target=server.serve_forever)
        thread.start()
        try:
            refreshed = {
                "query": "Laon", "traces": [], "questions": [], "persee": [],
                "people": [], "timeline": [], "sources": [],
                "places": [{"name": "Cathédrale", "category": "recommandé"},
                           {"name": "Nouvel édifice", "category": "recommandé"}],
            }
            request = Request(
                f"http://127.0.0.1:{server.server_port}/api/versions/{first}/refresh",
                data=b"{}", headers={"Content-Type": "application/json"},
                method="POST",
            )
            with patch.object(app, "research", return_value=refreshed):
                with urlopen(request) as response:
                    result = json.loads(response.read())
            self.assertEqual(result["data"]["traces"], ["Ancienne porte"])
            self.assertEqual(result["data"]["questions"], ["Question à vérifier"])
            self.assertEqual(result["data"]["places"][0]["category"], "indispensable")
            self.assertEqual(len(result["data"]["places"]), 2)
            self.assertNotEqual(result["id"], first)
            self.assertEqual(app.version(first)["data"]["places"][0]["category"], "indispensable")
        finally:
            server.shutdown()
            thread.join()
            server.server_close()


if __name__ == "__main__":
    unittest.main()
