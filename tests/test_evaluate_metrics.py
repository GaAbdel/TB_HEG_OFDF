"""Tests unitaires des métriques utilisées par scripts/evaluate.py.

Ces tests n'effectuent aucun appel réseau, aucun appel LLM et n'accèdent pas à
Qdrant. Ils valident uniquement les calculs purs de précision, rappel, F1,
exactitude de catégorie et métriques par niveau de difficulté.
"""

from scripts.evaluate import THRESHOLD, _detector_metrics, _prf, compute_metrics


def test_prf_calcul_standard():
    """Vérifie précision, rappel et F1 sur un cas non trivial."""
    metrics = _prf(tp=8, fp=2, fn=4)

    assert metrics == {
        "precision": 0.8,
        "recall": 0.667,
        "f1": 0.727,
        "tp": 8,
        "fp": 2,
        "fn": 4,
    }


def test_prf_division_par_zero():
    """Vérifie que l'absence de positifs ne provoque aucune division par zéro."""
    metrics = _prf(tp=0, fp=0, fn=0)

    assert metrics == {
        "precision": 0.0,
        "recall": 0.0,
        "f1": 0.0,
        "tp": 0,
        "fp": 0,
        "fn": 0,
    }


def test_detector_metrics_confusion_categories_et_niveaux():
    """Vérifie matrice de confusion, catégories et lecture par difficulté."""
    rows = [
        {
            "gt_suspect": True,
            "gt_category": "tabac",
            "gt_difficulte": "explicite",
            "pred_flag": True,
            "pred_category": "tabac",
        },
        {
            "gt_suspect": True,
            "gt_category": "alcool",
            "gt_difficulte": "implicite",
            "pred_flag": True,
            "pred_category": "tabac",  # vrai positif, catégorie incorrecte
        },
        {
            "gt_suspect": True,
            "gt_category": "arme",
            "gt_difficulte": "implicite",
            "pred_flag": False,
            "pred_category": "aucune",
        },
        {
            "gt_suspect": False,
            "gt_category": "aucune",
            "gt_difficulte": "piege",
            "pred_flag": True,
            "pred_category": "arme",
        },
        {
            "gt_suspect": False,
            "gt_category": "aucune",
            "gt_difficulte": "aucune",
            "pred_flag": False,
            "pred_category": "aucune",
        },
    ]

    metrics = _detector_metrics(
        rows,
        flag_key="pred_flag",
        cat_key="pred_category",
    )

    assert metrics["tp"] == 2
    assert metrics["fp"] == 1
    assert metrics["fn"] == 1
    assert metrics["tn"] == 1

    assert metrics["precision"] == 0.667
    assert metrics["recall"] == 0.667
    assert metrics["f1"] == 0.667
    assert metrics["category_accuracy"] == 0.5

    assert metrics["par_niveau"]["explicite"] == {
        "rappel": 1.0,
        "detectees": 1,
        "total": 1,
    }
    assert metrics["par_niveau"]["implicite"] == {
        "rappel": 0.5,
        "detectees": 1,
        "total": 2,
    }
    assert metrics["par_niveau"]["piege"] == {
        "evitement": 0.0,
        "faux_positifs": 1,
        "total": 1,
    }
    assert metrics["par_niveau"]["aucune"] == {
        "evitement": 1.0,
        "faux_positifs": 0,
        "total": 1,
    }


def test_compute_metrics_filtre_les_donnees_incompletes_et_applique_le_seuil():
    """Vérifie l'assemblage des métriques LLM/RAG et de la baseline."""
    listings = [
        {"id": 1},
        {"id": 2},
        {"id": 3},  # ignorée : aucune vérité terrain
    ]

    labels = {
        "1": {
            "suspect": True,
            "categorie": "tabac",
            "difficulte": "explicite",
        },
        "2": {
            "suspect": False,
            "categorie": "aucune",
            "difficulte": "aucune",
        },
    }

    results = {
        "1": {
            # La valeur exacte du seuil doit être considérée comme signalée.
            "llm_score": THRESHOLD,
            "llm_category": "tabac",
            "kw_flag": False,
            "kw_category": "aucune",
        },
        "2": {
            "llm_score": 0.2,
            "llm_category": "aucune",
            "kw_flag": True,
            "kw_category": "tabac",
        },
        "3": {
            "llm_score": 0.9,
            "llm_category": "arme",
            "kw_flag": True,
            "kw_category": "arme",
        },
    }

    metrics = compute_metrics(listings, labels, results)

    assert metrics["n_evaluees"] == 2
    assert metrics["seuil"] == THRESHOLD

    assert metrics["llm_rag"]["tp"] == 1
    assert metrics["llm_rag"]["fp"] == 0
    assert metrics["llm_rag"]["fn"] == 0
    assert metrics["llm_rag"]["tn"] == 1
    assert metrics["llm_rag"]["precision"] == 1.0
    assert metrics["llm_rag"]["recall"] == 1.0
    assert metrics["llm_rag"]["f1"] == 1.0
    assert metrics["llm_rag"]["category_accuracy"] == 1.0

    assert metrics["baseline_motscles"]["tp"] == 0
    assert metrics["baseline_motscles"]["fp"] == 1
    assert metrics["baseline_motscles"]["fn"] == 1
    assert metrics["baseline_motscles"]["tn"] == 0
    assert metrics["baseline_motscles"]["precision"] == 0.0
    assert metrics["baseline_motscles"]["recall"] == 0.0
    assert metrics["baseline_motscles"]["f1"] == 0.0
