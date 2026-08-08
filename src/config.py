"""Chargement et validation des profils d'impression.

Un profil décrit le matériel et l'intention d'impression, jamais l'image. La
référence complète des champs est dans doc/config.md.

`load_profile` enchaîne : lecture du JSON, fusion d'un éventuel `config.json`
local au projet, application des surcharges CLI, valeurs par défaut,
validation, gel. La validation accumule **tous** les problèmes avant de lever,
pour ne pas imposer une correction du JSON erreur par erreur.
"""

from __future__ import annotations

import json
from collections.abc import Iterable, Sequence
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

import numpy as np

from .color import LUMA_COEFFS, ColorError, hex_to_linear, parse_hex
from .errors import ProfileError, UsageError

CONFIG_DIR = Path("config")

SEPARATION_METHODS = ("luminance", "duotone", "tritone", "cmyk", "density-lsq")
HALFTONE_METHODS = ("none", "clustered-dot", "blue-noise", "bayer")
DOT_SHAPES = ("round", "ellipse", "square", "line")
OUTPUT_FORMATS = ("png", "tiff")
BIT_DEPTHS = (8, 16)
MATRIX_SIZES = (4, 8, 16)

#: Nombre d'encres admis par méthode. Absent = quelconque.
INK_COUNTS = {"luminance": (1,), "duotone": (2,), "tritone": (3,), "cmyk": (3, 4)}

#: Écart minimal entre deux angles de trame avant avertissement de moiré.
MIN_ANGLE_SPREAD = 15.0

#: Rapport dpi/lpi en deçà duquel les dégradés montrent des bandes.
MIN_DPI_LPI_RATIO = 8.0


# --------------------------------------------------------------------------
# Structures


@dataclass(frozen=True, eq=False)
class Ink:
    name: str
    label: str
    color_hex: str
    color: np.ndarray  # (3,) sRVB linéaire
    order: int
    opacity: float
    screen_angle: float
    max_coverage: float


@dataclass(frozen=True, eq=False)
class Paper:
    color_hex: str
    color: np.ndarray  # (3,) sRVB linéaire
    label: str


@dataclass(frozen=True)
class SeparationCfg:
    method: str
    total_ink_limit: float
    black_generation: float
    preserve_highlights: bool
    curves: dict[str, tuple[tuple[float, float], ...]] | None


@dataclass(frozen=True)
class ToneCfg:
    gamma: float
    contrast: float
    black_point: float
    white_point: float
    desaturate: float

    @property
    def is_identity(self) -> bool:
        return (
            self.gamma == 1.0
            and self.contrast == 0.0
            and self.black_point == 0.0
            and self.white_point == 1.0
            and self.desaturate == 0.0
        )


@dataclass(frozen=True)
class HalftoneCfg:
    method: str
    lpi: int
    dot_shape: str
    matrix_size: int


@dataclass(frozen=True)
class OutputCfg:
    dpi: int
    format: str
    bit_depth: int
    invert: bool
    long_edge_mm: float
    registration_marks: bool
    margin_mm: float


@dataclass(frozen=True, eq=False)
class Profile:
    name: str
    description: str
    inks: tuple[Ink, ...]  # triées par `order`
    paper: Paper
    separation: SeparationCfg
    tone: ToneCfg
    halftone: HalftoneCfg
    output: OutputCfg
    warnings: tuple[str, ...]
    sources: tuple[str, ...]  # traçabilité : fichiers et surcharges appliqués

    def as_dict(self) -> dict:
        """Profil résolu, sérialisable — pour `run.json`.

        Les couleurs repartent en hexadécimal : c'est ce que l'utilisateur a
        écrit, et ce qu'il devra recopier pour reproduire le tirage.
        """
        return {
            "name": self.name,
            "description": self.description,
            "inks": [
                {
                    "name": ink.name,
                    "label": ink.label,
                    "color": ink.color_hex,
                    "order": ink.order,
                    "opacity": ink.opacity,
                    "screen_angle": ink.screen_angle,
                    "max_coverage": ink.max_coverage,
                }
                for ink in self.inks
            ],
            "paper": {"color": self.paper.color_hex, "label": self.paper.label},
            "separation": {
                "method": self.separation.method,
                "total_ink_limit": self.separation.total_ink_limit,
                "black_generation": self.separation.black_generation,
                "preserve_highlights": self.separation.preserve_highlights,
                "curves": (
                    {name: [list(p) for p in points]
                     for name, points in self.separation.curves.items()}
                    if self.separation.curves
                    else None
                ),
            },
            "tone": asdict(self.tone),
            "halftone": asdict(self.halftone),
            "output": asdict(self.output),
        }

    @property
    def darkest_ink(self) -> Ink:
        """L'encre la plus dense, celle qui porte le contraste.

        Sert de destination à la redistribution d'encrage et à la génération
        du noir. Départagée sur la luminance perçue et non sur la moyenne des
        canaux : un bleu soutenu est plus foncé qu'un jaune de même moyenne.
        """
        return min(self.inks, key=lambda i: float(np.dot(i.color, LUMA_COEFFS)))

    @property
    def lightest_ink(self) -> Ink:
        """L'encre la plus claire, celle qu'on imprime en premier par convention.

        Sert au `todo.md` à vérifier que l'ordre de passage déclaré suit bien
        l'usage clair → foncé.
        """
        return max(self.inks, key=lambda i: float(np.dot(i.color, LUMA_COEFFS)))


# --------------------------------------------------------------------------
# Accumulateur de validation


class _Report:
    """Collecte erreurs et avertissements plutôt que d'échouer au premier."""

    def __init__(self) -> None:
        self.errors: list[str] = []
        self.warnings: list[str] = []

    def error(self, message: str) -> None:
        self.errors.append(message)

    def warn(self, message: str) -> None:
        self.warnings.append(message)


def _number(
    data: dict,
    key: str,
    default: float,
    where: str,
    report: _Report,
    *,
    minimum: float | None = None,
    maximum: float | None = None,
    exclusive_min: float | None = None,
) -> float:
    raw = data.get(key, default)
    if isinstance(raw, bool) or not isinstance(raw, (int, float)):
        report.error(f"{where}.{key} : nombre attendu, reçu {raw!r}")
        return default
    value = float(raw)
    if minimum is not None and value < minimum:
        report.error(f"{where}.{key} : doit être ≥ {minimum}, reçu {value}")
        return default
    if maximum is not None and value > maximum:
        report.error(f"{where}.{key} : doit être ≤ {maximum}, reçu {value}")
        return default
    if exclusive_min is not None and value <= exclusive_min:
        report.error(f"{where}.{key} : doit être > {exclusive_min}, reçu {value}")
        return default
    return value


def _integer(
    data: dict, key: str, default: int, where: str, report: _Report, *, minimum: int = 1
) -> int:
    raw = data.get(key, default)
    if isinstance(raw, bool) or not isinstance(raw, int):
        report.error(f"{where}.{key} : entier attendu, reçu {raw!r}")
        return default
    if raw < minimum:
        report.error(f"{where}.{key} : doit être ≥ {minimum}, reçu {raw}")
        return default
    return raw


def _boolean(data: dict, key: str, default: bool, where: str, report: _Report) -> bool:
    raw = data.get(key, default)
    if not isinstance(raw, bool):
        report.error(f"{where}.{key} : booléen attendu, reçu {raw!r}")
        return default
    return raw


def _text(data: dict, key: str, default: str, where: str, report: _Report) -> str:
    raw = data.get(key, default)
    if not isinstance(raw, str):
        report.error(f"{where}.{key} : texte attendu, reçu {raw!r}")
        return default
    return raw


def _choice(
    data: dict,
    key: str,
    default: Any,
    allowed: Sequence[Any],
    where: str,
    report: _Report,
) -> Any:
    raw = data.get(key, default)
    if raw not in allowed:
        listed = ", ".join(repr(a) for a in allowed)
        report.error(f"{where}.{key} : valeur inconnue {raw!r}. Attendu : {listed}")
        return default
    return raw


def _section(data: dict, key: str, where: str, report: _Report) -> dict:
    raw = data.get(key, {})
    if not isinstance(raw, dict):
        report.error(f"{where}{key} : objet attendu, reçu {raw!r}")
        return {}
    return raw


def _unknown_keys(
    data: dict, known: Iterable[str], where: str, report: _Report
) -> None:
    extra = sorted(set(data) - set(known))
    if extra:
        report.warn(f"{where} : clé(s) ignorée(s) — {', '.join(extra)}")


# --------------------------------------------------------------------------
# Angles de trame par défaut


def default_screen_angles(count: int) -> list[float]:
    """Angles par défaut, indexés par ordre de passage.

    45° est le moins perceptible à l'œil : réservé à l'encre la plus foncée,
    donc au dernier passage. Avec quatre encres on ne peut plus tenir 30°
    d'écart partout ; 0° revient alors à l'encre la plus claire, celle sur
    laquelle un moiré résiduel se verra le moins. Voir doc/halftone.md.
    """
    table = {1: [45.0], 2: [15.0, 45.0], 3: [15.0, 75.0, 45.0], 4: [0.0, 15.0, 75.0, 45.0]}
    if count in table:
        return table[count]
    cycle = [15.0, 45.0, 75.0, 0.0]
    return [cycle[i % len(cycle)] for i in range(count)]


def angle_spread(a: float, b: float) -> float:
    """Écart entre deux angles de trame, en tenant compte de leur périodicité.

    Les trames se répètent tous les 90° : 5° et 95° sont le même angle.
    """
    diff = abs(a - b) % 90.0
    return min(diff, 90.0 - diff)


# --------------------------------------------------------------------------
# Construction des sections


def _build_inks(raw: Any, report: _Report) -> tuple[Ink, ...]:
    if raw is None:
        report.error("inks : champ requis manquant")
        return ()
    if not isinstance(raw, list) or not raw:
        report.error("inks : liste non vide attendue")
        return ()

    defaults = default_screen_angles(len(raw))
    entries: list[tuple[int, Ink]] = []
    seen_names: set[str] = set()

    for index, item in enumerate(raw):
        where = f"inks[{index}]"
        if not isinstance(item, dict):
            report.error(f"{where} : objet attendu, reçu {item!r}")
            continue

        _unknown_keys(
            item,
            ("name", "label", "color", "order", "opacity", "screen_angle", "max_coverage"),
            where,
            report,
        )

        name = item.get("name")
        if not isinstance(name, str) or not name.strip():
            report.error(f"{where}.name : champ requis manquant ou vide")
            name = f"<encre {index + 1}>"
        elif name in seen_names:
            report.error(f"{where}.name : nom d'encre dupliqué — {name!r}")
        else:
            seen_names.add(name)

        color_hex = "#000000"
        color = hex_to_linear(color_hex)
        if "color" not in item:
            report.error(f"{where}.color : champ requis manquant")
        else:
            try:
                color_hex = parse_hex(item["color"])
                color = hex_to_linear(color_hex)
            except ColorError as exc:
                report.error(f"{where}.color : {exc}")

        order = _integer(item, "order", index + 1, where, report, minimum=1)

        entries.append(
            (
                order,
                Ink(
                    name=name,
                    label=_text(item, "label", name, where, report),
                    color_hex=color_hex,
                    color=color,
                    order=order,
                    opacity=_number(
                        item, "opacity", 0.85, where, report, minimum=0.0, maximum=1.0
                    ),
                    screen_angle=_number(
                        item, "screen_angle", defaults[index], where, report
                    ),
                    max_coverage=_number(
                        item, "max_coverage", 1.0, where, report, minimum=0.0, maximum=1.0
                    ),
                ),
            )
        )

    orders = [order for order, _ in entries]
    if len(set(orders)) != len(orders):
        report.error(f"inks[].order : ordres de passage dupliqués — {sorted(orders)}")
    elif sorted(orders) != list(range(1, len(orders) + 1)):
        report.error(
            f"inks[].order : doit être contigu à partir de 1, reçu {sorted(orders)}"
        )

    return tuple(ink for _, ink in sorted(entries, key=lambda e: e[0]))


def _build_paper(raw: dict, report: _Report) -> Paper:
    _unknown_keys(raw, ("color", "label"), "paper", report)
    color_hex = "#FFFFFF"
    if "color" in raw:
        try:
            color_hex = parse_hex(raw["color"])
        except ColorError as exc:
            report.error(f"paper.color : {exc}")
    return Paper(
        color_hex=color_hex,
        color=hex_to_linear(color_hex),
        label=_text(raw, "label", "", "paper", report),
    )


def _build_curves(raw: Any, inks: Sequence[Ink], method: str, report: _Report):
    """Courbes de réponse par encre, requises pour `duotone` et `tritone`."""
    needs_curves = method in ("duotone", "tritone")

    if raw is None:
        if needs_curves:
            report.error(
                f"separation.curves : requis pour la méthode {method!r} "
                "(une courbe par encre)"
            )
        return None
    if not isinstance(raw, dict):
        report.error(f"separation.curves : objet attendu, reçu {raw!r}")
        return None

    known = {ink.name for ink in inks}
    curves: dict[str, tuple[tuple[float, float], ...]] = {}

    for ink_name, points in raw.items():
        where = f"separation.curves.{ink_name}"
        if ink_name not in known:
            report.error(f"{where} : aucune encre nommée {ink_name!r} dans le profil")
            continue
        parsed = _parse_curve_points(points, where, report)
        if parsed is not None:
            curves[ink_name] = parsed

    if needs_curves:
        for ink in inks:
            if ink.name not in raw:
                report.error(f"separation.curves : courbe manquante pour {ink.name!r}")

    return curves


def _parse_curve_points(points: Any, where: str, report: _Report):
    if not isinstance(points, list) or len(points) < 2:
        report.error(f"{where} : au moins deux points [luminance, couverture] attendus")
        return None

    parsed: list[tuple[float, float]] = []
    for point in points:
        if (
            not isinstance(point, list)
            or len(point) != 2
            or any(isinstance(c, bool) or not isinstance(c, (int, float)) for c in point)
        ):
            report.error(f"{where} : point mal formé {point!r}, attendu [x, y]")
            return None
        x, y = float(point[0]), float(point[1])
        if not (0.0 <= x <= 1.0) or not (0.0 <= y <= 1.0):
            report.error(f"{where} : point hors de [0, 1] — {point!r}")
            return None
        parsed.append((x, y))

    xs = [x for x, _ in parsed]
    if any(b <= a for a, b in zip(xs, xs[1:])):
        report.error(f"{where} : les luminances doivent être strictement croissantes")
        return None

    return tuple(parsed)


def _build_separation(raw: dict, inks: Sequence[Ink], report: _Report) -> SeparationCfg:
    _unknown_keys(
        raw,
        ("method", "total_ink_limit", "black_generation", "preserve_highlights", "curves"),
        "separation",
        report,
    )
    method = _choice(raw, "method", "density-lsq", SEPARATION_METHODS, "separation", report)

    expected = INK_COUNTS.get(method)
    if expected and inks and len(inks) not in expected:
        listed = " ou ".join(str(n) for n in expected)
        report.error(
            f"separation.method : {method!r} exige {listed} encre(s), "
            f"le profil en déclare {len(inks)}"
        )

    return SeparationCfg(
        method=method,
        total_ink_limit=_number(
            raw, "total_ink_limit", 2.4, "separation", report, minimum=0.0
        ),
        black_generation=_number(
            raw, "black_generation", 0.5, "separation", report, minimum=0.0, maximum=1.0
        ),
        preserve_highlights=_boolean(
            raw, "preserve_highlights", True, "separation", report
        ),
        curves=_build_curves(raw.get("curves"), inks, method, report),
    )


def _build_tone(raw: dict, report: _Report) -> ToneCfg:
    _unknown_keys(
        raw, ("gamma", "contrast", "black_point", "white_point", "desaturate"), "tone", report
    )
    black_point = _number(raw, "black_point", 0.0, "tone", report, minimum=0.0, maximum=1.0)
    white_point = _number(raw, "white_point", 1.0, "tone", report, minimum=0.0, maximum=1.0)
    if black_point >= white_point:
        report.error(
            f"tone : black_point ({black_point}) doit être < white_point ({white_point})"
        )
    return ToneCfg(
        gamma=_number(raw, "gamma", 1.0, "tone", report, exclusive_min=0.0),
        contrast=_number(raw, "contrast", 0.0, "tone", report, minimum=-1.0, maximum=1.0),
        black_point=black_point,
        white_point=white_point,
        desaturate=_number(raw, "desaturate", 0.0, "tone", report, minimum=0.0, maximum=1.0),
    )


def _build_halftone(raw: dict, report: _Report) -> HalftoneCfg:
    _unknown_keys(raw, ("method", "lpi", "dot_shape", "matrix_size"), "halftone", report)
    return HalftoneCfg(
        method=_choice(raw, "method", "clustered-dot", HALFTONE_METHODS, "halftone", report),
        lpi=_integer(raw, "lpi", 60, "halftone", report),
        dot_shape=_choice(raw, "dot_shape", "round", DOT_SHAPES, "halftone", report),
        matrix_size=_choice(raw, "matrix_size", 8, MATRIX_SIZES, "halftone", report),
    )


def _build_output(raw: dict, report: _Report) -> OutputCfg:
    _unknown_keys(
        raw,
        (
            "dpi",
            "format",
            "bit_depth",
            "invert",
            "long_edge_mm",
            "registration_marks",
            "margin_mm",
        ),
        "output",
        report,
    )
    return OutputCfg(
        dpi=_integer(raw, "dpi", 300, "output", report),
        format=_choice(raw, "format", "png", OUTPUT_FORMATS, "output", report),
        bit_depth=_choice(raw, "bit_depth", 8, BIT_DEPTHS, "output", report),
        invert=_boolean(raw, "invert", False, "output", report),
        long_edge_mm=_number(raw, "long_edge_mm", 297.0, "output", report, exclusive_min=0.0),
        registration_marks=_boolean(raw, "registration_marks", True, "output", report),
        margin_mm=_number(raw, "margin_mm", 5.0, "output", report, minimum=0.0),
    )


# --------------------------------------------------------------------------
# Avertissements transversaux


def _cross_checks(
    inks: Sequence[Ink],
    paper: Paper,
    separation: SeparationCfg,
    halftone: HalftoneCfg,
    output: OutputCfg,
    report: _Report,
) -> None:
    if halftone.method == "clustered-dot":
        for i, first in enumerate(inks):
            for second in inks[i + 1 :]:
                spread = angle_spread(first.screen_angle, second.screen_angle)
                if spread < MIN_ANGLE_SPREAD:
                    report.warn(
                        f"angles de trame : {first.name} ({first.screen_angle:g}°) et "
                        f"{second.name} ({second.screen_angle:g}°) sont écartés de "
                        f"{spread:g}° — risque de moiré, viser au moins "
                        f"{MIN_ANGLE_SPREAD:g}°"
                    )

        ratio = output.dpi / halftone.lpi if halftone.lpi else 0.0
        if ratio < MIN_DPI_LPI_RATIO:
            levels = int(ratio**2) + 1
            report.warn(
                f"dpi/lpi = {ratio:.1f} ({output.dpi} dpi pour {halftone.lpi} lpi) : "
                f"environ {levels} niveaux de gris seulement, les dégradés vont "
                f"montrer des bandes. Sortir à {int(halftone.lpi * MIN_DPI_LPI_RATIO)} dpi."
            )

    if separation.total_ink_limit > 2.4:
        report.warn(
            f"separation.total_ink_limit = {separation.total_ink_limit * 100:.0f} % : "
            "risque de saturation du papier et de séchage incomplet"
        )

    if output.bit_depth == 16 and halftone.method != "none":
        report.warn(
            "output.bit_depth = 16 sans effet : la sortie est binaire dès qu'un "
            "tramage est actif"
        )

    for ink in inks:
        if float(np.max(np.abs(ink.color - paper.color))) < 0.05:
            report.warn(
                f"encre {ink.name!r} ({ink.color_hex}) très proche de la couleur du "
                f"papier ({paper.color_hex}) : sa contribution sera quasi nulle"
            )


# --------------------------------------------------------------------------
# Chargement


def _deep_merge(base: dict, override: dict) -> dict:
    """Fusion récursive. Les listes sont remplacées, pas concaténées."""
    merged = dict(base)
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = _deep_merge(merged[key], value)
        else:
            merged[key] = value
    return merged


def resolve_config_path(spec: str, config_dir: Path = CONFIG_DIR) -> Path:
    """Résout `-c` : nom court, nom avec extension, ou chemin explicite."""
    if "/" in spec or "\\" in spec:
        path = Path(spec)
        if not path.is_file():
            raise UsageError(f"Profil introuvable : {spec}")
        return path

    for candidate in (config_dir / spec, config_dir / f"{spec}.json"):
        if candidate.is_file():
            return candidate

    available = sorted(p.stem for p in config_dir.glob("*.json"))
    listed = "\n".join(f"  - {name}" for name in available) or "  (aucun)"
    raise UsageError(f"Profil introuvable : {spec}\nProfils disponibles :\n{listed}")


def _read_json(path: Path) -> dict:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ProfileError(f"{path} : JSON invalide — {exc}") from exc
    except OSError as exc:
        raise UsageError(f"{path} : lecture impossible — {exc}") from exc
    if not isinstance(data, dict):
        raise ProfileError(f"{path} : objet JSON attendu à la racine")
    return data


def build_profile(data: dict, sources: Sequence[str] = ()) -> Profile:
    """Valide un dictionnaire déjà fusionné et produit un `Profile` figé."""
    report = _Report()
    _unknown_keys(
        data,
        ("name", "description", "inks", "paper", "separation", "tone", "halftone", "output"),
        "racine",
        report,
    )

    inks = _build_inks(data.get("inks"), report)
    paper = _build_paper(_section(data, "paper", "", report), report)
    separation = _build_separation(_section(data, "separation", "", report), inks, report)
    tone = _build_tone(_section(data, "tone", "", report), report)
    halftone = _build_halftone(_section(data, "halftone", "", report), report)
    output = _build_output(_section(data, "output", "", report), report)

    if not report.errors:
        _cross_checks(inks, paper, separation, halftone, output, report)

    if report.errors:
        raise ProfileError(
            f"Profil invalide — {len(report.errors)} problème(s) :", report.errors
        )

    return Profile(
        name=_text(data, "name", "(sans nom)", "racine", report),
        description=_text(data, "description", "", "racine", report),
        inks=inks,
        paper=paper,
        separation=separation,
        tone=tone,
        halftone=halftone,
        output=output,
        warnings=tuple(report.warnings),
        sources=tuple(sources),
    )


def load_profile(
    spec: str,
    *,
    project_dir: Path | None = None,
    overrides: dict | None = None,
    config_dir: Path = CONFIG_DIR,
) -> Profile:
    """Charge, fusionne, valide et gèle un profil.

    `project_dir` : si un `config.json` s'y trouve, il est fusionné par-dessus
    le profil, champ par champ en profondeur.
    `overrides` : surcharges CLI, appliquées en dernier.
    """
    path = resolve_config_path(spec, config_dir)
    data = _read_json(path)
    sources = [str(path)]

    if project_dir is not None:
        local = project_dir / "config.json"
        if local.is_file():
            data = _deep_merge(data, _read_json(local))
            sources.append(str(local))

    if overrides:
        data = _deep_merge(data, overrides)
        sources.append("surcharges CLI")

    return build_profile(data, sources)
