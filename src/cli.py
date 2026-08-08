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
from .image import (
    apply_tone,
    load_linear,
    resize_to,
    resolution_warning,
    source_size,
    target_long_edge_px,
)
from .output import PREVIEW_FILENAME, write_layer, write_preview
from .preview import composite
from .project import PROJECT_DIR, RUN_SIGNATURE, Project, prepare_output, resolve_project
from .report import TODO_FILENAME, layer_stats, write_run_json, write_todo
from .separation import separate


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


def render_coverage(profile: Profile, coverage, stats: dict) -> str:
    """Encrage mesuré, une ligne par passage.

    C'est ce qui permet de juger une séparation sans ouvrir les fichiers : une
    encre à 5 % de couverture moyenne ne justifie pas un passage machine.
    """
    limit = profile.separation.total_ink_limit
    lines = ["", "Couvertures :"]

    for index, ink in enumerate(profile.inks):
        layer = coverage[index]
        lines.append(
            f"  {ink.order}. {ink.label:<20} moyenne {float(layer.mean()) * 100:5.1f} %"
            f"   maximum {float(layer.max()) * 100:5.1f} %"
        )

    verdict = "✅" if stats["total_ink_max"] <= limit + 1e-3 else "⚠️"
    lines.append(
        f"  Encrage total : maximum {stats['total_ink_max'] * 100:.0f} %, "
        f"moyenne {stats['total_ink_mean'] * 100:.0f} % "
        f"(limite {limit * 100:.0f} %) {verdict}"
    )
    if stats["limited_fraction"] > 0.0:
        lines.append(
            f"  La limite a mordu sur {stats['limited_fraction'] * 100:.1f} % "
            "des pixels, redistribués vers l'encre la plus foncée."
        )

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

    if args.out is not None:
        raise NotImplementedYet(
            "`--out` n'est pas encore là (lot 8, voir doc/plan.md). La sortie "
            "va dans le dossier `output/` du projet."
        )
    if args.preview_halftoned:
        raise NotImplementedYet(
            "`--preview-halftoned` attend le tramage (lot 7, voir doc/plan.md)."
        )

    print("\nTraitement…")
    img = load_linear(project.source)
    img = resize_to(
        img, target_long_edge_px(profile.output.long_edge_mm, profile.output.dpi)
    )
    img = apply_tone(img, profile.tone)
    output_px = (img.shape[1], img.shape[0])
    if args.verbose:
        print(f"  image      : {output_px[0]} × {output_px[1]} px")

    coverage, ink_stats = separate(img, profile)
    del img  # 440 Mo sur un A4 à 600 dpi, dont l'aperçu n'a plus besoin

    print(render_coverage(profile, coverage, ink_stats))

    if profile.halftone.method != "none":
        warnings.append(
            f"tramage {profile.halftone.method!r} demandé mais pas encore écrit "
            "(lot 7) : les calques sortent en ton continu, à tramer par le "
            "pilote de la machine."
        )

    output_dir = prepare_output(project)
    written = []

    preview_path = output_dir / PREVIEW_FILENAME
    write_preview(composite(coverage, profile), preview_path, profile.output)
    written.append(preview_path)

    layers = layer_stats(profile, coverage)
    reports = dict(
        project=project,
        profile=profile,
        layers=layers,
        source_px=source_px,
        output_px=output_px,
        ink_stats=ink_stats,
        warnings=warnings,
    )

    if not args.preview_only:
        for index in range(len(profile.inks)):
            path = output_dir / layers[index].file
            write_layer(coverage[index], path, profile.output)
            written.append(path)

        todo_path = output_dir / TODO_FILENAME
        # `halftoned=False` tant que le lot 7 n'est pas là : le plan doit dire
        # ce qui est réellement dans les fichiers, pas ce que le profil demande.
        write_todo(todo_path, **reports, halftoned=False)
        written.append(todo_path)

    write_run_json(output_dir / RUN_SIGNATURE, **reports)

    print(f"\nÉcrit dans {output_dir}/ :")
    for path in sorted(written):
        print(f"  {path.name}")
    if args.preview_only:
        print("  (--preview-only : calques non produits)")

    if warnings:
        print(f"\nAvertissements ({len(warnings)}) :")
        for warning in warnings:
            print(f"  ! {warning}")

    return 0


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        return run(args)
    except RisoError as exc:
        print(f"\nErreur : {exc}", file=sys.stderr)
        return exc.code
