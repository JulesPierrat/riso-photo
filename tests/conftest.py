"""Fixtures partagées."""

from __future__ import annotations

import json
from pathlib import Path

import pytest


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
    (tmp_path / "config").mkdir()
    (tmp_path / "config" / "test.json").write_text(
        json.dumps(profile_data), encoding="utf-8"
    )

    demo = tmp_path / "project" / "demo"
    demo.mkdir(parents=True)
    (demo / "source.jpg").write_bytes(b"")

    return tmp_path
