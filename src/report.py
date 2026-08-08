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


TODO_FILENAME = "todo.md"

MM_PER_INCH = 25.4

#: Temps de séchage minimal entre deux passages, en heures. Une encre encore
#: humide n'accroche pas comme du papier nu et macule le tambour suivant.
DRYING_HOURS = 2

#: Formats ISO reconnus, en millimètres (petit côté, grand côté).
ISO_FORMATS = {
    "A6": (105, 148),
    "A5": (148, 210),
    "A4": (210, 297),
    "A3": (297, 420),
    "A2": (420, 594),
    "A1": (594, 841),
}

#: Tolérance de reconnaissance d'un format, en millimètres.
_FORMAT_TOLERANCE = 2.0

#: En deçà, un passage machine ne se justifie plus vraiment.
_NEGLIGIBLE_COVERAGE = 0.03


@dataclass(frozen=True)
class LayerStats:
    file: str
    ink: str
    order: int
    coverage_mean: float
    coverage_max: float
    capped_fraction: float


def layer_stats(profile: Profile, coverage: np.ndarray) -> list[LayerStats]:
    """Couvertures mesurées, un enregistrement par passage."""
    stats = []
    for index, ink in enumerate(profile.inks):
        layer = coverage[index]
        stats.append(
            LayerStats(
                file=layer_filename(ink, profile.output),
                ink=ink.name,
                order=ink.order,
                coverage_mean=float(layer.mean()),
                coverage_max=float(layer.max()),
                capped_fraction=float(
                    np.count_nonzero(layer >= ink.max_coverage - 1e-4)
                )
                / layer.size,
            )
        )
    return stats


def physical_size_mm(output_px: tuple[int, int], dpi: int) -> tuple[float, float]:
    return (output_px[0] / dpi * MM_PER_INCH, output_px[1] / dpi * MM_PER_INCH)


def format_name(width_mm: float, height_mm: float) -> str | None:
    """Nom du format ISO correspondant, s'il y en a un.

    Le grand côté vient du profil, le petit suit le ratio de la photo : il n'y
    a donc aucune garantie de tomber sur un format normalisé. Quand c'est le
    cas, le dire évite à l'imprimeur de mesurer.
    """
    short, long = sorted((width_mm, height_mm))
    for name, (ref_short, ref_long) in ISO_FORMATS.items():
        if (
            abs(short - ref_short) <= _FORMAT_TOLERANCE
            and abs(long - ref_long) <= _FORMAT_TOLERANCE
        ):
            return f"{name} {'portrait' if height_mm >= width_mm else 'paysage'}"
    return None


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


# --------------------------------------------------------------------------
# todo.md


def _layer_notes(profile: Profile, index: int, layer: LayerStats) -> list[str]:
    """Remarques déduites du rôle réel de l'encre dans cette séparation."""
    ink = profile.inks[index]
    notes: list[str] = []
    multipass = len(profile.inks) > 1

    if multipass and index == 0:
        if ink is profile.lightest_ink:
            notes.append(
                "encre la plus claire imprimée en premier : limite le maculage "
                "au passage suivant."
            )
        else:
            notes.append(
                f"⚠️ ce premier passage n'est pas l'encre la plus claire "
                f"({profile.lightest_ink.label} l'est). L'usage est d'imprimer "
                "du plus clair au plus foncé ; vérifier que l'ordre est voulu."
            )

    if multipass and ink is profile.darkest_ink:
        notes.append("encre la plus dense : c'est elle qui porte le contraste.")

    if layer.coverage_mean < _NEGLIGIBLE_COVERAGE:
        notes.append(
            f"⚠️ couverture moyenne de {layer.coverage_mean * 100:.1f} % seulement — "
            "ce passage machine apporte peu, envisager de le supprimer du profil."
        )

    if layer.capped_fraction > 0.01:
        surface = f"{layer.capped_fraction * 100:.1f} % de l'image"
        if ink.max_coverage < 1.0:
            notes.append(
                f"⚠️ plafond de {ink.max_coverage * 100:.0f} % atteint sur {surface} : "
                "le détail y est aplati. Relever `max_coverage` pour le récupérer."
            )
        else:
            notes.append(
                f"encre à fond sur {surface} : c'est la densité maximale qu'elle "
                "puisse donner, le détail y est nécessairement aplati."
            )

    return notes


def _screen_line(profile: Profile, index: int, halftoned: bool) -> str:
    halftone = profile.halftone

    if not halftoned or halftone.method == "none":
        return "ton continu — trame à appliquer par le pilote de la machine"
    if halftone.method == "clustered-dot":
        return (
            f"points agglomérés {halftone.dot_shape}, {halftone.lpi} lpi, "
            f"{profile.inks[index].screen_angle:g}°"
        )
    if halftone.method == "bayer":
        return f"tramage ordonné Bayer {halftone.matrix_size}×{halftone.matrix_size}"
    return "diffusion d'erreur (trame stochastique, insensible au moiré)"


def _vigilance(
    profile: Profile, halftoned: bool, warnings: Sequence[str], ink_stats: dict
) -> list[str]:
    points: list[str] = []
    output = profile.output

    limited = ink_stats.get("limited_fraction", 0.0)
    if limited > 0.05:
        points.append(
            f"L'encrage total a été plafonné sur {limited * 100:.0f} % de l'image, "
            f"avec report vers {profile.darkest_ink.label}. Au-delà d'un tiers de "
            "la surface, c'est le signe que `total_ink_limit` bride la séparation "
            "plus que le papier ne l'exige."
        )

    if len(profile.inks) > 1:
        points.append(
            f"Laisser sécher **au moins {DRYING_HOURS} h** entre chaque passage."
        )
        points.append(
            "Repérage : tolérance risographe ≈ 1 à 2 mm."
            + (
                f" Les repères de calage sont inclus dans la marge de "
                f"{output.margin_mm:g} mm — ne pas massicoter avant vérification."
                if output.registration_marks
                else " Aucun repère de calage dans ce profil "
                "(`registration_marks` désactivé) : le calage se fera à vue."
            )
        )
        points.append(
            "Charger tout le papier en une seule fois, dans le même sens, pour "
            "tous les passages."
        )

    if halftoned and profile.halftone.method == "clustered-dot" and len(profile.inks) > 1:
        if not any("moiré" in w for w in warnings):
            points.append(
                "Angles de trame suffisamment écartés : pas de risque de moiré."
            )

    points.extend(warnings)
    return points


def render_todo(
    *,
    project: Project,
    profile: Profile,
    layers: Sequence[LayerStats],
    source_px: tuple[int, int],
    output_px: tuple[int, int],
    ink_stats: dict,
    warnings: Sequence[str] = (),
    halftoned: bool = True,
) -> str:
    """Plan d'impression, destiné à être imprimé ou envoyé au prestataire.

    Entièrement dérivé des mesures du run — couvertures réelles, dimensions
    effectives, avertissements accumulés — et non d'un gabarit figé.
    """
    output = profile.output
    limit = profile.separation.total_ink_limit
    reached = ink_stats["total_ink_max"]

    width_mm, height_mm = physical_size_mm(output_px, output.dpi)
    iso = format_name(width_mm, height_mm)
    size = (
        f"{output_px[0]} × {output_px[1]} px @ {output.dpi} dpi "
        f"({width_mm:.0f} × {height_mm:.0f} mm"
        + (f", {iso})" if iso else ")")
    )

    lines = [
        f"# {project.name} — plan d'impression",
        "",
        f"Profil : {profile.name}",
        f"Source : {project.source.name} ({source_px[0]} × {source_px[1]}) → sortie {size}",
        f"Papier : {profile.paper.label or profile.paper.color_hex}",
        f"Encrage total maximum atteint : {reached * 100:.0f} % "
        f"(limite du profil : {limit * 100:.0f} %) "
        f"{'✅' if reached <= limit + 1e-3 else '⚠️'}",
        "",
        "## Ordre de passage",
    ]

    for index, layer in enumerate(layers):
        ink = profile.inks[index]
        lines += [
            "",
            f"### Passage {ink.order} — {ink.label}",
            f"- Encre : {ink.color_hex}, opacité {ink.opacity:.2f}",
            f"- Fichier : `{layer.file}`",
            f"- Trame : {_screen_line(profile, index, halftoned)}",
            f"- Couverture moyenne : {layer.coverage_mean * 100:.0f} % "
            f"· maximum : {layer.coverage_max * 100:.0f} %",
        ]
        lines += [f"- Note : {note}" for note in _layer_notes(profile, index, layer)]

    points = _vigilance(profile, halftoned, warnings, ink_stats)
    if points:
        lines += ["", "## Points de vigilance", ""]
        lines += [f"- {point}" for point in points]

    lines += [
        "",
        "---",
        "",
        f"Produit par riso-photo {__version__}. Paramètres exacts dans `run.json`.",
    ]

    return "\n".join(lines) + "\n"


def write_todo(path: Path, **kwargs) -> None:
    try:
        path.write_text(render_todo(**kwargs), encoding="utf-8")
    except OSError as exc:
        raise RisoError(f"{path} : écriture impossible — {exc}") from exc
