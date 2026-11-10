# Mnémosyne — recherche historique locale

## Démarrer

Python 3.10 ou plus récent suffit ; aucune bibliothèque Python n’est à installer.

- Linux : `python3 app.py`
- Windows : `py app.py`

Ouvrir ensuite <http://127.0.0.1:8000>. Le serveur est réservé à cet ordinateur. Pour choisir un autre port : `python3 app.py --port 8080` (ou `py app.py --port 8080`). Arrêter le serveur avec Ctrl+C.

La base SQLite `mnemosyne.sqlite3`, créée au premier démarrage, conserve les recherches et leurs versions. Sauvegardez ce fichier pour archiver ou transférer vos dossiers.

## Contenu et limites

Recherchez une ville, éventuellement avec son département, sa région ou son pays. La page Wikipédia retenue est affichée afin de pouvoir vérifier qu’il s’agit de la bonne localité. Quand le réseau le permet, l’application interroge Gallica, Internet Archive, Wikipédia et Wikidata ; les autres portails sont présentés comme des liens de recherche, car leurs interfaces ne proposent pas toutes un service de recherche ouvert et stable. Le bouton Persée tente d’extraire les articles de sa page de résultats et donne aussi accès à la recherche complète.

La frise propose au plus 30 phrases datées extraites de la page Wikipédia retenue : ce ne sont ni 30 faits historiques validés ni une synthèse critique. Les personnes et les lieux proviennent de Wikidata et peuvent être incomplets, mal associés ou dotés de coordonnées imprécises. Aucun élément n’est inventé pour atteindre un nombre cible. Les liens vers des archives nationales étrangères sont sélectionnés selon une estimation de proximité avec leur capitale, qui n’établit aucun lien historique.

Complétez les traces disparues et les questions débattues à l’aide de sources et de références explicites. Le classement des lieux est une aide à la préparation d’une visite, non une évaluation patrimoniale. Les fonds peuvent être incomplets, payants ou soumis à des droits d’utilisation.

La carte nécessite Internet, OpenStreetMap et le chargement de Leaflet. Les fonds historiques du Géoportail/IGN ne sont affichés que si les couches et les adresses utilisées restent disponibles ; vérifiez leur couverture, leurs conditions d’accès et leur attribution auprès du fournisseur. Les fournisseurs de cartes peuvent recevoir votre adresse IP.

L’impression du navigateur propose « Enregistrer au format PDF ». Des exports Markdown, JSON et HTML sont également disponibles. Comparez deux versions archivées par siècle depuis l’onglet Comparer.

## Essais

```sh
python3 -m unittest discover -s tests
```

Les essais de base n’appellent pas les services Internet.
