"""Résolution du dossier projet et de son image source.

Un projet est un simple dossier dans `project/` contenant une image. Le
programme ne le crée jamais : sur une faute de frappe, on préfère une erreur
qui liste les projets existants à un dossier vide fabriqué en silence.

Voir doc/cli.md pour les règles de détection et d'écrasement.
"""

from __future__ import annotations

import shutil
from dataclasses import dataclass
from pathlib import Path

from .errors import RisoError, UsageError

PROJECT_DIR = Path("project")

SOURCE_EXTENSIONS = (".jpg", ".jpeg", ".png", ".tif", ".tiff")

OUTPUT_DIRNAME = "output"

#: Fichier écrit par le programme, qui atteste qu'`output/` lui appartient.
RUN_SIGNATURE = "run.json"


@dataclass(frozen=True)
class Project:
    name: str
    root: Path
    source: Path
    output_dir: Path


def find_source(root: Path) -> Path:
    """Identifie l'unique image source d'un dossier projet.

    Une seule image → c'est elle. Plusieurs, dont une nommée `source.*` →
    celle-là. Plusieurs sans `source.*` → erreur : le programme refuse de
    choisir à la place de l'utilisateur.
    """
    candidates = sorted(
        p
        for p in root.iterdir()
        if p.is_file() and p.suffix.lower() in SOURCE_EXTENSIONS
    )

    if not candidates:
        listed = ", ".join(SOURCE_EXTENSIONS)
        raise UsageError(
            f"Aucune image trouvée dans {root}\n"
            f"Déposer une image ({listed}) dans ce dossier."
        )

    if len(candidates) == 1:
        return candidates[0]

    named = [p for p in candidates if p.stem.lower() == "source"]
    if len(named) == 1:
        return named[0]

    listed = "\n".join(f"  - {p.name}" for p in candidates)
    raise UsageError(
        f"Plusieurs images dans {root} :\n{listed}\n"
        "Renommer celle à traiter en `source` ou retirer les autres."
    )


def resolve_project(name: str, base: Path = PROJECT_DIR) -> Project:
    """Localise un projet et son image source."""
    root = base / name

    if not root.is_dir():
        available = sorted(p.name for p in base.iterdir() if p.is_dir()) if base.is_dir() else []
        listed = "\n".join(f"  - {n}" for n in available) or "  (aucun)"
        raise UsageError(
            f"Projet introuvable : {root}\nProjets disponibles :\n{listed}"
        )

    return Project(
        name=name,
        root=root,
        source=find_source(root),
        output_dir=root / OUTPUT_DIRNAME,
    )


def prepare_output(project: Project, override: Path | None = None) -> Path:
    """Vide et recrée le dossier de sortie.

    Refuse de supprimer un dossier non vide dépourvu de `run.json` : sans cette
    signature, rien ne prouve que le programme en soit l'auteur, et l'écrasement
    est irréversible.
    """
    if override is None:
        output = project.output_dir
        # Garde-fou : ne jamais effacer autre chose que le `output/` du projet.
        if output.name != OUTPUT_DIRNAME or output.parent != project.root:
            raise RisoError(f"Dossier de sortie inattendu : {output}")
    else:
        output = _checked_override(override, project)

    if output.exists():
        if not output.is_dir():
            raise UsageError(f"{output} existe et n'est pas un dossier")

        existing = list(output.iterdir())
        if existing and not (output / RUN_SIGNATURE).is_file():
            raise UsageError(
                f"{output} contient des fichiers qui ne proviennent pas d'un run "
                f"précédent (pas de {RUN_SIGNATURE}).\n"
                "Le vider ou le renommer avant de relancer — le programme ne "
                "supprime pas un dossier qu'il n'a pas produit."
            )
        shutil.rmtree(output)

    output.mkdir(parents=True)
    return output


def _checked_override(override: Path, project: Project) -> Path:
    """Valide un dossier de sortie choisi par l'utilisateur.

    `--out` désigne un dossier que le programme va **vider**. Trois refus, qui
    couvrent les fautes de frappe capables de détruire du travail : la racine
    du système, un dossier qui contient le projet, et le projet lui-même. Le
    contrôle de signature `run.json` s'applique ensuite comme partout ailleurs.
    """
    output = override.resolve()
    root = project.root.resolve()

    if output.parent == output:
        raise UsageError(f"--out : {output} est la racine du système.")
    if output == root or output in root.parents:
        raise UsageError(
            f"--out : {output} contient le projet. Le vider effacerait la "
            "photo source."
        )
    return output
