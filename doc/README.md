# Documentation technique — riso-photo

Spécification complète du programme. Pour l'installation et un premier run, voir le [README racine](../README.md).

## Spécification

| Document | Contenu |
|---|---|
| [architecture.md](architecture.md) | Arborescence, rôle de chaque module, pipeline de traitement étape par étape, conventions internes. |
| [cli.md](cli.md) | Référence de la ligne de commande : arguments, options, résolution des chemins, codes de sortie. |
| [config.md](config.md) | Référence exhaustive du profil JSON, champ par champ, et règles de validation. |
| [separation.md](separation.md) | Le cœur du programme : modèle colorimétrique et les quatre méthodes de séparation. |
| [halftone.md](halftone.md) | Tramage : méthodes, LPI, angles de trame, moiré, relation avec le DPI de sortie. |
| [sorties.md](sorties.md) | Fichiers produits : calques, aperçu, `run.json`, `todo.md`, repères de calage. |

## Développement

| Document | Contenu |
|---|---|
| [plan.md](plan.md) | Plan d'implémentation : contrats des modules, lots de développement, critères de fin, stratégie de test, risques. |
| [roadmap.md](roadmap.md) | État d'avancement, jalons, pistes ultérieures. |

## Ordre de lecture conseillé

**Comprendre le programme** — `architecture` → `separation` → `halftone` → `sorties`.

**Écrire un profil d'impression** — `config` seul suffit, avec `separation` en appui pour choisir la méthode.

**Se mettre à coder** — `plan` d'abord, il renvoie vers le reste au fil des lots.
