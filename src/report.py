"""Rapports du run : `run.json` et, à partir du lot 5, `todo.md`.

Ne recalcule rien — agrège ce que les étapes précédentes ont mesuré.

`run.json` a deux usages (doc/sorties.md) : reproduire à l'identique un tirage
réussi plusieurs mois plus tard, et servir de signature du dossier. Sa présence
atteste que `output/` a été produit par le programme et peut être écrasé sans
risque ; c'est pourquoi il est écrit dès le lot 4, avant le `todo.md`.
"""

from __future__ import annotations

import json
from collections.abc import Sequence
from dataclasses import asdict, dataclass
from pathlib import Path

import numpy as np

from . import __version__
from .config import Profile
from .errors import RisoError
from .output import layer_filename
from .project import Project


@dataclass(frozen=True)
class LayerStats:
    file: str
    ink: str
    order: int
    coverage_mean: float
    coverage_max: float


def layer_stats(profile: Profile, coverage: np.ndarray) -> list[LayerStats]:
    """Couvertures mesurées, un enregistrement par passage."""
    return [
        LayerStats(
            file=layer_filename(ink, profile.output),
            ink=ink.name,
            order=ink.order,
            coverage_mean=float(coverage[index].mean()),
            coverage_max=float(coverage[index].max()),
        )
        for index, ink in enumerate(profile.inks)
    ]


def write_run_json(
    path: Path,
    *,
    project: Project,
    profile: Profile,
    layers: Sequence[LayerStats],
    source_px: tuple[int, int],
    output_px: tuple[int, int],
    ink_stats: dict,
    warnings: Sequence[str],
) -> None:
    """Trace exhaustive du run."""
    payload = {
        "riso_photo_version": __version__,
        "project": project.name,
        "config_sources": list(profile.sources),
        "source_image": project.source.name,
        "source_size_px": list(source_px),
        "output_size_px": list(output_px),
        "profile": profile.as_dict(),
        "layers": [asdict(layer) for layer in layers],
        "total_ink_max": ink_stats["total_ink_max"],
        "total_ink_mean": ink_stats["total_ink_mean"],
        "limited_fraction": ink_stats["limited_fraction"],
        "warnings": list(warnings),
    }

    try:
        path.write_text(
            json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
        )
    except OSError as exc:
        raise RisoError(f"{path} : écriture impossible — {exc}") from exc
