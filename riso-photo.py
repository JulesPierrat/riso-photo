#!/usr/bin/env python3
"""Point d'entrée. Toute la logique vit dans `src/`, pour rester testable
sans passer par la ligne de commande."""

import sys

from src.cli import main

if __name__ == "__main__":
    sys.exit(main())
