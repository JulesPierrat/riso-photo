"""Interface en ligne de commande.

Ne contient aucun calcul : parsing des arguments, enchaînement des étapes,
affichage. La référence des options est dans doc/cli.md.
"""

from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence
from pathlib import Path

from . import __version__
from .config import CONFIG_DIR, Profile, load_profile
from .errors import NotImplementedYet, RisoError
from .image import resolution_warning, source_size, target_long_edge_px
from .project import PROJECT_DIR, Project, resolve_project


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="riso-photo",
        description=(
            "Sépare une photographie en calques monochromes pour l'impression "
            "risographique."
        ),
        epilog="Documentation complète : doc/",
    )
    parser.add_argument("project", metavar="nom_projet", help=f"sous-dossier de {PROJECT_DIR}/")
    parser.add_argument(
        "-c",
        "--config",
        required=True,
        metavar="PROFIL",
        help=f"nom court résolu dans {CONFIG_DIR}/, ou chemin vers un fichier JSON",
    )

    parser.add_argument("--dpi", type=int, metavar="N", help="force la résolution de sortie")
    parser.add_argument(
        "--preview-only", action="store_true", help="ne produire que l'aperçu"
    )
    parser.add_argument(
        "--preview-halftoned",
        action="store_true",
        help="calculer l'aperçu à partir des calques tramés (plus fidèle, plus lent)",
    )
    parser.add_argument(
        "--no-halftone", action="store_true", help="sortie en ton continu, sans tramage"
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="afficher le plan sans rien écrire sur disque",
    )
    parser.add_argument(
        "--out", metavar="CHEMIN", type=Path, help="dossier de sortie (défaut : output/ du projet)"
    )
    parser.add_argument("-v", "--verbose", action="store_true", help="détailler chaque étape")
    parser.add_argument("--version", action="version", version=f"riso-photo {__version__}")

    return parser


def cli_overrides(args: argparse.Namespace) -> dict:
    """Traduit les options CLI en surcharges de profil.

    Elles sont appliquées à la construction du profil, jamais après : le
    `Profile` doit refléter l'état effectif du run (doc/architecture.md).
    """
    overrides: dict = {}
    if args.dpi is not None:
        overrides["output"] = {"dpi": args.dpi}
    if args.no_halftone:
        overrides["halftone"] = {"method": "none"}
    return overrides


def render_summary(
    project: Project,
    profile: Profile,
    *,
    source_px: tuple[int, int] | None = None,
    warnings: Sequence[str] | None = None,
    verbose: bool = False,
) -> str:
    """Résumé du run, affiché avant traitement et par `--dry-run`."""
    out = profile.output
    sep = profile.separation
    half = profile.halftone
    warnings = profile.warnings if warnings is None else warnings

    source = project.source.name
    if source_px is not None:
        source += f" ({source_px[0]} × {source_px[1]})"

    lines = [
        f"Projet     : {project.name}",
        f"Source     : {source}",
        f"Profil     : {profile.name}",
    ]
    if profile.description:
        lines.append(f"             {profile.description}")

    paper = profile.paper.label or "non précisé"
    lines += [
        f"Papier     : {paper} ({profile.paper.color_hex})",
        f"Séparation : {sep.method}, encrage max {sep.total_ink_limit * 100:.0f} %"
        + (f", GCR {sep.black_generation:.2f}" if sep.method in ("cmyk", "density-lsq") else ""),
    ]

    if half.method == "none":
        lines.append("Trame      : aucune (ton continu)")
    elif half.method == "clustered-dot":
        lines.append(f"Trame      : points agglomérés {half.dot_shape}, {half.lpi} lpi")
    elif half.method == "bayer":
        lines.append(f"Trame      : Bayer {half.matrix_size}×{half.matrix_size}")
    else:
        lines.append("Trame      : diffusion d'erreur")

    long_edge = target_long_edge_px(out.long_edge_mm, out.dpi)
    lines.append(
        f"Sortie     : {out.long_edge_mm:g} mm au grand côté @ {out.dpi} dpi "
        f"→ {long_edge} px, marge {out.margin_mm:g} mm, "
        f"{out.format.upper()} {out.bit_depth} bits"
        + ("" if out.invert else ", noir = 100 % d'encre")
    )

    lines.append("")
    lines.append("Passages :")
    for ink in profile.inks:
        angle = (
            f"trame {ink.screen_angle:g}°"
            if half.method == "clustered-dot"
            else "trame n/a"
        )
        lines.append(
            f"  {ink.order}. {ink.label:<20} {ink.color_hex}  "
            f"opacité {ink.opacity:.2f}  {angle}  plafond {ink.max_coverage * 100:.0f} %"
        )

    if verbose:
        tone = profile.tone
        lines += [
            "",
            "Tons       : "
            + (
                "aucune correction"
                if tone.is_identity
                else (
                    f"gamma {tone.gamma:g}, contraste {tone.contrast:+g}, "
                    f"niveaux [{tone.black_point:g} – {tone.white_point:g}], "
                    f"désaturation {tone.desaturate:g}"
                )
            ),
            "Profil issu de : " + ", ".join(profile.sources),
        ]

    if warnings:
        lines.append("")
        lines.append(f"Avertissements ({len(warnings)}) :")
        lines += [f"  ! {w}" for w in warnings]

    return "\n".join(lines)


def run(args: argparse.Namespace) -> int:
    project = resolve_project(args.project)
    profile = load_profile(
        args.config, project_dir=project.root, overrides=cli_overrides(args)
    )

    # Lecture de l'en-tête seulement : la sous-résolution se détecte sans
    # décoder les pixels, donc avant tout calcul.
    source_px = source_size(project.source)
    warnings = list(profile.warnings)
    under = resolution_warning(
        max(source_px), target_long_edge_px(profile.output.long_edge_mm, profile.output.dpi)
    )
    if under:
        warnings.append(under)

    print(
        render_summary(
            project,
            profile,
            source_px=source_px,
            warnings=warnings,
            verbose=args.verbose,
        )
    )

    if args.dry_run:
        return 0

    raise NotImplementedYet(
        "La séparation n'est pas encore écrite (lots 3 à 5, voir doc/plan.md).\n"
        "Le projet, le profil et la source sont valides : `--dry-run` affiche "
        "le plan complet."
    )


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        return run(args)
    except RisoError as exc:
        print(f"\nErreur : {exc}", file=sys.stderr)
        return exc.code
