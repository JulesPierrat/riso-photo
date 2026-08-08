"""Fixtures partagées."""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pytest
from PIL import Image


@pytest.fixture
def profile_data() -> dict:
    """Profil minimal valide, à muter dans les tests de validation."""
    return {
        "name": "Test duotone",
        "inks": [
            {"name": "pink", "color": "#FF48B0", "order": 1, "screen_angle": 15},
            {"name": "black", "color": "#000000", "order": 2, "screen_angle": 45},
        ],
        "paper": {"color": "#FFFFFF"},
        "separation": {
            "method": "duotone",
            "total_ink_limit": 1.7,
            "curves": {
                "pink": [[0.0, 0.0], [0.5, 0.9], [1.0, 0.0]],
                "black": [[0.0, 1.0], [0.5, 0.4], [1.0, 0.0]],
            },
        },
        "halftone": {"method": "clustered-dot", "lpi": 60},
        "output": {"dpi": 600},
    }


@pytest.fixture
def workspace(tmp_path: Path, profile_data: dict) -> Path:
    """Arborescence complète `config/` + `project/demo/`, prête à l'emploi."""
    # Format volontairement minuscule : les tests CLI font tourner le pipeline
    # complet, et un A4 à 600 dpi représenterait 37 Mpx par test.
    small = {**profile_data, "output": {**profile_data["output"], "long_edge_mm": 12}}

    (tmp_path / "config").mkdir()
    (tmp_path / "config" / "test.json").write_text(json.dumps(small), encoding="utf-8")

    demo = tmp_path / "project" / "demo"
    demo.mkdir(parents=True)
    build_image(400, 300).save(demo / "source.jpg", quality=95)

    return tmp_path


@pytest.fixture
def make_image():
    """Fabrique de mires, exposée en fixture pour éviter un import entre tests."""
    return build_image


def build_image(width: int, height: int) -> Image.Image:
    """Mire déterministe : rampe de luminance horizontale, teinte verticale.

    Couvre les cas où les erreurs de colorimétrie se voient — extrêmes purs,
    dégradés doux, canaux dissociés — sans embarquer de binaire dans le dépôt.
    """
    x = np.linspace(0.0, 1.0, width, dtype=np.float32)[np.newaxis, :]
    y = np.linspace(0.0, 1.0, height, dtype=np.float32)[:, np.newaxis]

    red = x
    green = x * (1.0 - 0.5 * y)
    blue = x * y

    rgb = np.stack(np.broadcast_arrays(red, green, blue), axis=-1)
    return Image.fromarray((rgb * 255.0).round().astype(np.uint8), mode="RGB")
