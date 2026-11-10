import json
import tempfile
import threading
import unittest
from pathlib import Path
from urllib.request import Request, urlopen
from unittest.mock import patch
from http.server import ThreadingHTTPServer

import app


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
