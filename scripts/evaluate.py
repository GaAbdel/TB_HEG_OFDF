#!/usr/bin/env python3
"""Évaluation du pipeline d'analyse sur le jeu gradué.

Score les 284 annonces (LLM + RAG), compare à la vérité terrain aveugle
(dataset_manifest.json), calcule précision/rappel/F1 globaux ET par niveau de
difficulté (explicite / implicite / piège), et confronte le tout à une
référence naïve par mots-clés.

- Le pipeline ne voit QUE listings.json ; le manifest sert uniquement à corriger.
- La référence mots-clés est gratuite (aucun appel API).
- Run long (~1 h : 284 appels, limite de débit). REPRENABLE : relancer reprend
  où le run s'est arrêté (results.json sert de point de reprise).

Usage :
    docker compose exec app python scripts/evaluate.py
"""

from __future__ import annotations

import json
import time
from pathlib import Path

from osint.analyse.retriever import QdrantRuleRetriever
from osint.analyse.scorer import score_listing
from osint.config import get_config

EVAL_DIR = Path("/app/data/eval")
LISTINGS = EVAL_DIR / "listings.json"
MANIFEST = EVAL_DIR / "dataset_manifest.json"
RESULTS = EVAL_DIR / "results.json"
METRICS = EVAL_DIR / "metrics.json"

THRESHOLD = 0.5          # score >= seuil => annonce signalée
SLEEP_SECONDS = 0       # 

# Référence naïve : un détecteur par mots-clés (volontairement simple).
KEYWORDS = {
    "tabac": ["cigarette", "cigarettes", "tabac", "cartouche", "cartouches", "cigare", "cigares"],
    "alcool": ["alcool", "spiritueux", "gnole", "gnôle", "eau-de-vie", "whisky", "vodka", "absinthe", "vin"],
    "cites": ["ivoire", "corne", "écaille", "ecaille", "caviar", "tortue", "python", "corail"],
    "viande": ["viande", "foie gras", "jambon", "saucisse", "charcuterie"],
    "contrefacon": ["copie", "réplique", "replique", "contrefac", "faux", "imitation"],
    "arme": ["arme", "armes", "pistolet", "couteau", "munition", "matraque", "poignard", "revolver"],
}


def keyword_predict(text: str) -> tuple[bool, str]:
    t = text.lower()
    for cat, words in KEYWORDS.items():
        if any(w in t for w in words):
            return True, cat
    return False, "aucune"


def _annonce(listing: dict) -> dict:
    return {
        "title": listing.get("title"),
        "description": listing.get("description"),
        "price_amount": listing.get("price"),
        "price_currency": listing.get("currency"),
        "location": listing.get("location"),
    }


def _load(path: Path) -> dict | list:
    return json.loads(path.read_text(encoding="utf-8"))


# --------------------------------------------------------------------------- #
#  Calcul des métriques (pur : testable hors run)
# --------------------------------------------------------------------------- #
def _prf(tp: int, fp: int, fn: int) -> dict:
    precision = tp / (tp + fp) if (tp + fp) else 0.0
    recall = tp / (tp + fn) if (tp + fn) else 0.0
    f1 = 2 * precision * recall / (precision + recall) if (precision + recall) else 0.0
    return {"precision": round(precision, 3), "recall": round(recall, 3),
            "f1": round(f1, 3), "tp": tp, "fp": fp, "fn": fn}


def _detector_metrics(rows: list[dict], *, flag_key: str, cat_key: str) -> dict:
    tp = fp = fn = tn = 0
    cat_ok = cat_total = 0
    by_diff = {d: {"flagged": 0, "total": 0} for d in ("explicite", "implicite", "piege", "aucune")}

    for r in rows:
        flagged = r[flag_key]
        suspect = r["gt_suspect"]
        if flagged and suspect:
            tp += 1
            cat_total += 1
            if r[cat_key] == r["gt_category"]:
                cat_ok += 1
        elif flagged and not suspect:
            fp += 1
        elif not flagged and suspect:
            fn += 1
        else:
            tn += 1
        d = r["gt_difficulte"]
        if d in by_diff:
            by_diff[d]["total"] += 1
            if flagged:
                by_diff[d]["flagged"] += 1

    out = _prf(tp, fp, fn)
    out["tn"] = tn
    out["category_accuracy"] = round(cat_ok / cat_total, 3) if cat_total else 0.0
    # Lecture par niveau :
    #  - explicite / implicite : rappel (signalées / total)
    #  - piege   : taux d'évitement (NON signalées / total)
    #  - aucune  : spécificité (NON signalées / total)
    per_level = {}
    for d, c in by_diff.items():
        if c["total"] == 0:
            continue
        if d in ("explicite", "implicite"):
            per_level[d] = {"rappel": round(c["flagged"] / c["total"], 3),
                            "detectees": c["flagged"], "total": c["total"]}
        else:  # piege, aucune : on veut NE PAS signaler
            avoided = c["total"] - c["flagged"]
            per_level[d] = {"evitement": round(avoided / c["total"], 3),
                            "faux_positifs": c["flagged"], "total": c["total"]}
    out["par_niveau"] = per_level
    return out


def compute_metrics(listings: list, labels: dict, results: dict) -> dict:
    rows = []
    for listing in listings:
        lid = str(listing["id"])
        if lid not in results or lid not in labels:
            continue
        gt = labels[lid]
        res = results[lid]
        rows.append({
            "gt_suspect": bool(gt["suspect"]),
            "gt_category": gt["categorie"],
            "gt_difficulte": gt["difficulte"],
            "llm_flag": res["llm_score"] >= THRESHOLD,
            "llm_category": res["llm_category"],
            "kw_flag": res["kw_flag"],
            "kw_category": res["kw_category"],
        })
    return {
        "n_evaluees": len(rows),
        "seuil": THRESHOLD,
        "llm_rag": _detector_metrics(rows, flag_key="llm_flag", cat_key="llm_category"),
        "baseline_motscles": _detector_metrics(rows, flag_key="kw_flag", cat_key="kw_category"),
    }


def print_report(m: dict) -> None:
    print("\n" + "=" * 64)
    print(f"ÉVALUATION — {m['n_evaluees']} annonces, seuil={m['seuil']}")
    print("=" * 64)
    for nom, d in (("LLM + RAG", m["llm_rag"]), ("Baseline mots-clés", m["baseline_motscles"])):
        print(f"\n### {nom}")
        print(f"  Précision={d['precision']}  Rappel={d['recall']}  F1={d['f1']}  "
              f"(TP={d['tp']} FP={d['fp']} FN={d['fn']} TN={d['tn']})")
        print(f"  Exactitude catégorie (sur vrais positifs) : {d['category_accuracy']}")
        for niv, v in d["par_niveau"].items():
            if "rappel" in v:
                print(f"  - {niv:10} rappel={v['rappel']:.2f} ({v['detectees']}/{v['total']})")
            else:
                print(f"  - {niv:10} évitement={v['evitement']:.2f} "
                      f"(faux positifs : {v['faux_positifs']}/{v['total']})")
    print("=" * 64)


def main() -> None:
    cfg = get_config()
    cfg.assert_lpd_compliance(consentement_cloud=True)
    retriever = QdrantRuleRetriever.from_config(cfg)

    listings = _load(LISTINGS)
    labels = _load(MANIFEST)["labels"]

    results: dict = {}
    if RESULTS.exists():
        results = _load(RESULTS)
        print(f"Reprise : {len(results)} annonces déjà évaluées sur {len(listings)}.")

    total = len(listings)
    for i, listing in enumerate(listings, 1):
        lid = str(listing["id"])
        if lid in results:
            continue
        text = f"{listing.get('title', '')}. {listing.get('description', '')}"
        kw_flag, kw_cat = keyword_predict(text)
        try:
            rules = retriever.retrieve(text)
            llm = score_listing(cfg, _annonce(listing), rules=rules)
        except Exception as e:  # noqa: BLE001 — robustesse du run long
            print(f"  [{i}/{total}] id={lid} ERREUR : {e} — pause 30 s, on continue")
            time.sleep(30)
            continue
        results[lid] = {
            "llm_score": llm["suspicion_score"],
            "llm_category": llm["category"],
            "kw_flag": kw_flag,
            "kw_category": kw_cat,
            "rag_used": llm["rag_used"],
            "rag_refs": llm["rag_refs"],
        }
        RESULTS.write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")
        if i % 10 == 0 or i == total:
            print(f"  [{i}/{total}] évaluées")
        time.sleep(SLEEP_SECONDS)

    report = compute_metrics(listings, labels, results)
    METRICS.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print_report(report)
    print(f"\nDétail par annonce : {RESULTS}\nMétriques : {METRICS}")


if __name__ == "__main__":
    main()