#!/usr/bin/env python3
"""Figure — séparation des scores licites / illicites.

Lit data/eval/results.json + data/eval/dataset_manifest.json et produit un
nuage de points (chaque annonce = un point placé selon son score, jitter
vertical, couleur selon la classe), avec la bande de séparation ombrée.
Sorties : figures/separation_scores.png (300 dpi) et .pdf (vectoriel).

À lancer EN LOCAL (hors Docker), depuis la racine du dépôt :
    pip install matplotlib        # dans ton .venv
    python scripts/plot_scores.py
"""

from __future__ import annotations

import json
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402

EVAL = Path("data/eval")
OUT = Path("figures")
OUT.mkdir(exist_ok=True)

VERT = "#1baf7a"   # licites
ROUGE = "#e34948"  # illicites


def _load(name: str):
    return json.loads((EVAL / name).read_text(encoding="utf-8"))


def main() -> None:
    results = _load("results.json")
    labels = _load("dataset_manifest.json")["labels"]

    lic: list[float] = []
    ill: list[float] = []
    for lid, r in results.items():
        gt = labels.get(lid)
        if not gt:
            continue
        (ill if gt["suspect"] else lic).append(float(r["llm_score"]))

    rng = np.random.default_rng(42)  # jitter reproductible
    fig, ax = plt.subplots(figsize=(7, 3.6))

    if lic and ill:
        ax.axvspan(max(lic), min(ill), color="#9a9a9a", alpha=0.15, zorder=0)

    ax.scatter(lic, rng.uniform(0, 1, len(lic)), s=22, c=VERT, alpha=0.6,
               edgecolors="none", label=f"Licites (n={len(lic)})", zorder=2)
    ax.scatter(ill, rng.uniform(0, 1, len(ill)), s=22, c=ROUGE, alpha=0.8,
               edgecolors="none", label=f"Illicites (n={len(ill)})", zorder=3)

    ax.set_xlim(-0.02, 1.02)
    ax.set_ylim(-0.15, 1.15)
    ax.set_yticks([])
    ax.set_xlabel("Score de suspicion")
    ax.spines[["top", "right", "left"]].set_visible(False)
    ax.legend(frameon=False, loc="upper center", ncol=2, bbox_to_anchor=(0.5, 1.12))

    if lic and ill:
        marge = min(ill) - max(lic)
        ax.text(0.5 * (max(lic) + min(ill)), -0.10, f"marge = {marge:.2f}",
                ha="center", va="top", fontsize=9, color="#5f5e5a")

    fig.tight_layout()
    fig.savefig(OUT / "separation_scores.png", dpi=300, bbox_inches="tight")
    fig.savefig(OUT / "separation_scores.pdf", bbox_inches="tight")
    print(f"Écrit : {OUT/'separation_scores.png'} et {OUT/'separation_scores.pdf'}")


if __name__ == "__main__":
    main()