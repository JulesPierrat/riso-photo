# Roadmap

Vue produit : où en est le projet et où il va. Pour le découpage du développement — contrats des modules, critères de fin, tests — voir [plan.md](plan.md).

## État d'avancement

- [x] Cahier des charges et documentation technique
- [x] Plan d'implémentation
- [x] **Lot 0** — socle, hiérarchie d'erreurs, harnais de tests
- [x] **Lot 1** — résolution projet/profil, validation du JSON
- [x] **Lot 2** — chaîne image, colorimétrie, courbes tonales
- [x] **Lot 3** — encres, séparations `luminance` et `duotone`
- [x] **Lot 4** — aperçu de surimpression, écriture des calques, `run.json`
- [x] **Lot 5** — `todo.md` → **v0.1** ✅ *chaîne complète, prête pour le premier tirage*
- [ ] **Lot 6** — séparation `density-lsq` → **v0.2**
- [ ] **Lot 7** — tramage → **v0.3**
- [ ] **Lot 8** — repères de calage, `cmyk`, `tritone` → **v0.4**

## Jalons

**v0.1 — chaîne complète minimale.** `luminance` et `duotone`, sortie en ton continu, rapports générés. Le but n'est pas la qualité mais le **premier tirage papier** : c'est la seule façon de caler les couleurs d'encre des profils, et toute la justesse du programme en dépend.

**v0.2 — séparation générale.** `density-lsq` rend le programme utilisable avec des jeux d'encres arbitraires, ce qui est sa raison d'être.

**v0.3 — tramage.** Les fichiers partent directement en machine sans passer par le pilote pour la trame.

**v0.4 — finitions.** Repères de calage, méthodes restantes, profil local au projet.

## Pistes ultérieures

Non engagées, à trancher une fois la chaîne éprouvée sur de vrais tirages.

- **Calibration à partir d'un nuancier scanné** — générer une planche d'aplats et de dégradés, la faire imprimer, la scanner, et en déduire automatiquement les `color` et courbes de réponse réelles des encres. C'est ce qui ferait le plus progresser la justesse des séparations, davantage que n'importe quel raffinement du solveur.
- **Correction Yule-Nielsen** — modéliser la diffusion optique du papier pour rapprocher l'aperçu du tirage réel.
- **Sortie PDF multipage** — un fichier unique, une page par calque, avec repères et cartouche.
- **Choix automatique du jeu d'encres** — proposer, parmi un stock d'encres disponibles, la combinaison de N encres qui reproduit le mieux une photo donnée.
- **Traitement par lot** — séparer tout un dossier de photos avec le même profil.
