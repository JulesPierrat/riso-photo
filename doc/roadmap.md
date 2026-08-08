# Roadmap

## État d'avancement

- [x] Cahier des charges
- [ ] Squelette CLI + résolution projet/config
- [ ] Chargement image, colorimétrie, courbes tonales
- [ ] Séparations `luminance` et `duotone`
- [ ] Aperçu de surimpression
- [ ] Séparation `density-lsq`
- [ ] Tramage
- [ ] Génération du `todo.md` et du `run.json`
- [ ] Profils d'exemple dans `config/`

## Jalons

### v0.1 — Chaîne complète minimale

`luminance` et `duotone`, sortie en ton continu, `todo.md` basique. Le but est d'avoir un tirage papier le plus tôt possible : c'est la seule façon de caler les couleurs d'encre du profil, et tout le reste en dépend.

Ordre volontaire : l'**aperçu avant `density-lsq`**. Sans aperçu, impossible de savoir si une séparation est juste — on développerait l'algorithme le plus délicat à l'aveugle.

### v0.2 — Séparation générale

`density-lsq` avec solveur SciPy et repli intégré, limitation d'encrage avec redistribution, pondération perceptuelle. C'est ce qui rend le programme utilisable avec des jeux d'encres arbitraires.

### v0.3 — Tramage

`clustered-dot` avec angles, `error-diffusion`, `bayer`. Avertissements de moiré et de rapport DPI/LPI. À ce stade les fichiers partent directement en machine.

### v0.4 — Finitions

Repères de calage, marges, `cmyk`, `tritone`, profil local au projet, `--preview-halftoned`.

## Pistes ultérieures

Non engagées, à trancher une fois la chaîne éprouvée sur de vrais tirages.

- **Calibration à partir d'un nuancier scanné** — générer une planche d'aplats et de dégradés, la faire imprimer, la scanner, et en déduire automatiquement les `color` et courbes de réponse réelles des encres. C'est ce qui ferait le plus progresser la justesse des séparations.
- **Correction Yule-Nielsen** — modéliser la diffusion optique du papier pour rapprocher l'aperçu du tirage réel.
- **Sortie PDF multipage** — un fichier unique, une page par calque, avec repères et cartouche.
- **Choix automatique du jeu d'encres** — proposer, parmi un stock d'encres disponibles, la combinaison de N encres qui reproduit le mieux une photo donnée.
- **Traitement par lot** — séparer tout un dossier de photos avec le même profil.
