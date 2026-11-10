# Mnémosyne — recherche historique locale

## Démarrer

Python 3.10 ou plus récent suffit ; aucune bibliothèque Python n’est à installer.

- Linux : `python3 app.py`
- Windows : `py app.py`

Ouvrir ensuite <http://127.0.0.1:8000>. Le serveur est réservé à cet ordinateur. Pour choisir un autre port : `python3 app.py --port 8080` (ou `py app.py --port 8080`). Arrêter le serveur avec Ctrl+C.

La base SQLite `mnemosyne.sqlite3`, créée au premier démarrage, conserve les recherches et leurs versions. Sauvegardez ce fichier pour archiver ou transférer vos dossiers.

## Diagnostiquer les services

Sur l’ordinateur qui exécute l’application, lancez `python3 app.py --diagnostic --ville "Laon, Aisne, France"` (ou, sous Windows, `py app.py --diagnostic --ville "Laon, Aisne, France"`). La commande teste les services documentaires et la disponibilité d’un modèle local sans créer de dossier. Elle n’affiche ni les paramètres réseau ni les identifiants. Le résultat ne vérifie pas l’accès du navigateur aux calques cartographiques.

## Contenu et limites

Recherchez une ville, éventuellement avec son département, sa région ou son pays. Les catalogues sont interrogés avec le nom avant la première virgule ; la page Wikipédia retenue doit être vérifiée pour distinguer les homonymes. Quand le réseau le permet, l’application interroge Gallica, Internet Archive, Wikisource, la Bibliothèque du Congrès, Wikipédia et Wikidata ; les autres portails sont présentés comme des liens de recherche, car leurs interfaces ne proposent pas toutes un service de recherche ouvert et stable. Le bouton Persée tente d’extraire les articles de sa page de résultats et donne aussi accès à la recherche complète. Chaque source indique si elle a répondu ou échoué ; une réponse ne garantit pas la présence de résultats pertinents.

Sans moteur d’analyse, la frise propose au plus 30 phrases datées extraites de la page Wikipédia retenue ; les personnes et les lieux proviennent de Wikidata. Avec le moteur local facultatif décrit ci-dessous, l’application tente aussi de produire une synthèse à partir du texte Wikipédia récupéré. Les deux approches peuvent être incomplètes, mal associées ou dotées de coordonnées imprécises. Elles ne constituent pas une recherche historienne vérifiée. Les liens vers des archives nationales étrangères sont sélectionnés selon une estimation de proximité avec leur capitale, qui n’établit aucun lien historique.

L’application relève dans le texte Wikipédia des passages comportant des termes de disparition ou d’incertitude et indique leur source. Cette détection ne démontre ni l’existence d’un débat scientifique, ni l’emplacement exact d’un vestige, et ne remplace pas l’analyse de publications. Elle peut ne rien trouver même lorsqu’il existe des débats ou des traces. Complétez-les à l’aide de sources et de références explicites. Le classement des lieux est une aide à la préparation d’une visite, non une évaluation patrimoniale. Les fonds peuvent être incomplets, payants ou soumis à des droits d’utilisation.

### Analyse locale facultative

Si Ollama fonctionne sur `127.0.0.1:11434` avec au moins un modèle déjà installé, l’application utilise automatiquement le premier modèle annoncé pour proposer des dates, personnes, lieux, traces et questions à partir de la page Wikipédia obtenue. La recherche et le texte sont envoyés **uniquement à ce service local**, sans transmission à un service d’intelligence artificielle distant. Un modèle est généralement volumineux et peut prendre plusieurs minutes à répondre. Aucune installation ni aucun téléchargement de modèle ne sont effectués automatiquement. Si Ollama n’est pas disponible, le dossier indique cette limite et utilise les extractions simples.

La synthèse est filtrée : les citations doivent apparaître dans la page consultée, les années et noms doivent figurer dans leurs citations, et les pistes de débats ou de disparitions doivent comporter un indice textuel correspondant. Ces contrôles ne prouvent pas que la formulation proposée interprète correctement la citation ; vérifiez systématiquement les faits et les désaccords dans les publications pertinentes. **Le texte intégral des documents des autres archives n’est pas encore analysé**, et il n’est pas garanti d’obtenir 20 à 30 éléments pour chaque rubrique.

La carte nécessite Internet, OpenStreetMap et le chargement de Leaflet. Les fonds historiques du Géoportail/IGN ne sont affichés que si les couches et les adresses utilisées restent disponibles ; vérifiez leur couverture, leurs conditions d’accès et leur attribution auprès du fournisseur. Les fournisseurs de cartes peuvent recevoir votre adresse IP.

L’impression du navigateur propose « Enregistrer au format PDF ». Des exports Markdown, JSON et HTML sont également disponibles. Comparez deux versions archivées par siècle depuis l’onglet Comparer.

## Essais

```sh
python3 -m unittest discover -s tests
```

Les essais de base n’appellent pas les services Internet.
