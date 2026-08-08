# Référence de la ligne de commande

## Synopsis

```
python riso-photo.py <nom_projet> -c <config> [options]
```

## Arguments

| Argument | Obligatoire | Rôle |
|---|---|---|
| `nom_projet` | oui | Nom du sous-dossier dans `project/`. Doit exister et contenir une image source. |
| `-c, --config` | oui | Profil d'impression. Nom court résolu dans `config/`, ou chemin explicite. |

## Options

| Option | Défaut | Rôle |
|---|---|---|
| `--dpi N` | valeur du profil | Force la résolution de sortie. Surcharge `output.dpi`. |
| `--preview-only` | — | Ne génère que `preview.png`. Aucun calque, pas de tramage : itération rapide sur les réglages `tone`. |
| `--preview-halftoned` | — | L'aperçu est calculé à partir des calques tramés au lieu des couvertures continues. Plus fidèle, nettement plus lent. |
| `--no-halftone` | — | Sortie en ton continu. Équivaut à forcer `halftone.method = "none"`. |
| `--dry-run` | — | Exécute le calcul et affiche le plan d'impression sur la sortie standard sans rien écrire sur disque. |
| `--out CHEMIN` | `project/<nom>/output` | Redirige les fichiers produits ailleurs. |
| `-v, --verbose` | — | Détaille chaque étape : dimensions, couverture par encre, temps de calcul. |
| `-h, --help` | — | Aide. |

## Résolution du profil

L'argument `-c` accepte trois formes, testées dans cet ordre :

1. **Nom court** — `-c duotone-rose-noir` cherche `config/duotone-rose-noir.json`.
2. **Nom avec extension** — `-c duotone-rose-noir.json`, même dossier.
3. **Chemin** — dès que la valeur contient un séparateur (`./essais/test.json`, `/abs/chemin.json`), elle est traitée comme un chemin, relatif au répertoire courant.

Un profil introuvable produit une erreur listant les profils disponibles dans `config/`.

### Profil local au projet

Si `project/<nom_projet>/config.json` existe, il est fusionné **par-dessus** le profil passé en `-c`, champ par champ en profondeur. Cela permet de garder un profil d'atelier partagé et de ne surcharger localement que ce qui change — typiquement `tone` et `output.long_edge_mm`. La fusion est signalée dans la sortie et tracée dans `run.json`.

## Résolution du projet

Le dossier `project/<nom_projet>/` doit exister — le programme ne le crée pas, pour éviter de fabriquer un dossier vide sur une faute de frappe. Un nom inexistant produit une erreur listant les projets disponibles.

### Détection de l'image source

Le programme cherche dans `project/<nom_projet>/`, sans descendre dans les sous-dossiers, les fichiers d'extension `.jpg`, `.jpeg`, `.png`, `.tif`, `.tiff` :

- **Un seul fichier** → c'est la source.
- **Plusieurs fichiers, dont un nommé `source.*`** → `source.*` gagne.
- **Plusieurs fichiers, aucun `source.*`** → erreur. Le programme refuse de choisir à ta place et liste les candidats.
- **Aucun fichier** → erreur.

Le dossier `output/` est ignoré par la détection.

## Comportement d'écrasement

À chaque exécution, `output/` est **vidé puis régénéré intégralement**. Il n'y a pas d'historique : un run remplace le précédent.

La contrepartie est que `output/` ne doit jamais contenir de travail manuel. Tout ce qui doit survivre à un run se met à la racine du projet, qui n'est jamais touchée — l'image source, des notes, des essais retouchés à la main.

Si `output/` contient des fichiers qui ne portent pas la signature d'un run précédent (absence de `run.json`), le programme s'arrête et demande confirmation plutôt que d'effacer aveuglément un dossier qu'il n'a pas créé.

## Codes de sortie

| Code | Cas |
|---|---|
| `0` | Succès, éventuellement avec des avertissements. |
| `1` | Erreur d'usage : projet ou profil introuvable, source absente ou ambiguë. |
| `2` | Profil invalide. |
| `3` | Erreur de traitement : image illisible, écriture impossible. |

## Exemples

```bash
# Run standard
python riso-photo.py portrait-anna -c duotone-rose-noir

# Régler les courbes tonales sans attendre le tramage
python riso-photo.py portrait-anna -c duotone-rose-noir --preview-only

# Vérifier le plan d'impression avant de produire quoi que ce soit
python riso-photo.py portrait-anna -c trichro-cmj --dry-run

# Sortie haute résolution pour un tramage AM fin
python riso-photo.py affiche-fete -c quadri-riso --dpi 600

# Profil d'essai hors du dossier config/
python riso-photo.py test-encres -c ./essais/rose-seul.json -v
```
