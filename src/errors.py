"""Hiérarchie d'exceptions et codes de sortie.

Chaque exception porte le code de sortie que la CLI doit retourner. Voir
doc/cli.md pour la convention.
"""

from __future__ import annotations

from collections.abc import Sequence


class RisoError(Exception):
    """Erreur de traitement : image illisible, écriture impossible."""

    code = 3


class UsageError(RisoError):
    """Erreur d'usage : projet ou profil introuvable, source absente ou ambiguë."""

    code = 1


class NotImplementedYet(RisoError):
    """Fonctionnalité prévue par la spécification mais pas encore écrite.

    Un lot en cours ne doit jamais planter : il s'arrête sur un message
    explicite. Voir doc/plan.md.
    """

    code = 3


class ProfileError(RisoError):
    """Profil invalide.

    Porte la liste complète des champs fautifs plutôt que le premier
    rencontré : corriger un JSON erreur par erreur est pénible.
    """

    code = 2

    def __init__(self, message: str, problems: Sequence[str] = ()) -> None:
        self.problems = tuple(problems)
        super().__init__(message)

    def __str__(self) -> str:
        head = super().__str__()
        if not self.problems:
            return head
        return "\n".join([head, *(f"  - {p}" for p in self.problems)])
