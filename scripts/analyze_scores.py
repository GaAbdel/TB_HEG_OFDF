#!/usr/bin/env python3
"""Distribution des scores de suspicion, marge de séparation.

Lit data/eval/results.json + dataset_manifest.json et montre à quel point les
annonces licites et illicites sont SÉPARÉES par le score : histogramme,
statistiques par groupe et par niveau, et surtout la marge de séparation
(écart entre le plus haut score licite et le plus bas score illicite).


Usage :
    docker compose exec app python scripts/analyze_scores.py
"""

from __future__ import annotations

import json
from pathlib import Path

EVAL_DIR = Path("/app/data/eval")


def _load(name: str):
    return json.loads((EVAL_DIR / name).read_text(encoding="utf-8"))


def _stats(scores: list[float]) -> dict:
    if not scores:
        return {"n": 0}
    s = sorted(scores)
    n = len(s)
    return {"n": n, "min": round(min(s), 3), "max": round(max(s), 3),
            "moyenne": round(sum(s) / n, 3), "mediane": round(s[n // 2], 3)}


def main() -> None:
    results = _load("results.json")
    labels = _load("dataset_manifest.json")["labels"]

    illicites: list[float] = []
    licites: list[float] = []
    pieges: list[float] = []
    par_diff: dict[str, list[float]] = {"explicite": [], "implicite": [], "piege": [], "aucune": []}

    for lid, res in results.items():
        gt = labels.get(lid)
        if not gt:
            continue
        sc = float(res["llm_score"])
        (illicites if gt["suspect"] else licites).append(sc)
        if gt.get("piege"):
            pieges.append(sc)
        par_diff.setdefault(gt["difficulte"], []).append(sc)

    # Histogramme (10 paliers de 0.1)
    hist_ill = [0] * 10
    hist_lic = [0] * 10
    for x in illicites:
        hist_ill[min(9, int(x * 10))] += 1
    for x in licites:
        hist_lic[min(9, int(x * 10))] += 1

    print("Distribution des scores  (◼ illicites, ◻ licites)")
    for b in range(10):
        bar = "◼" * hist_ill[b] + "◻" * hist_lic[b]
        print(f"  [{b/10:.1f}–{(b+1)/10:.1f})  {bar}  (ill={hist_ill[b]}, lic={hist_lic[b]})")

    print("\nStatistiques par groupe")
    for nom, grp in (("Illicites", illicites), ("Licites", licites), ("dont Pièges", pieges)):
        print(f"  {nom:14} {_stats(grp)}")

    print("\nScore moyen par niveau")
    for d in ("explicite", "implicite", "piege", "aucune"):
        st = _stats(par_diff.get(d, []))
        if st["n"]:
            print(f"  {d:10} moyenne={st['moyenne']}  (min={st['min']}, max={st['max']}, n={st['n']})")

    if illicites and licites:
        gap = round(min(illicites) - max(licites), 3)
        print(f"\nPlus haut score LICITE  : {max(licites):.3f}")
        print(f"Plus bas score ILLICITE : {min(illicites):.3f}")
        if gap > 0:
            print(f"=> Marge de séparation NETTE : {gap:.3f}  (aucun chevauchement)")
        else:
            print(f"=> Chevauchement de {-gap:.3f}  (séparation imparfaite)")

    out = {
        "illicites": _stats(illicites),
        "licites": _stats(licites),
        "pieges": _stats(pieges),
        "par_niveau": {d: _stats(v) for d, v in par_diff.items()},
        "hist_illicites": hist_ill,
        "hist_licites": hist_lic,
    }
    (EVAL_DIR / "score_distribution.json").write_text(
        json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\nÉcrit : {EVAL_DIR / 'score_distribution.json'}")


if __name__ == "__main__":
    main()