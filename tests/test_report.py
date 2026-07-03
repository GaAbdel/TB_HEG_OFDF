"""Tests du générateur de rapport (couche restitution)."""

from __future__ import annotations

from osint.visualisation.report import build_report_data, render_report_html, write_report

_RUN = {"run_id": 9, "mode": "B", "model": "qwen3:8b"}
_LISTINGS = [
    {"id": 1, "title": "Ivoire sculpté — défense d'éléphant", "category": "cites",
     "suspicion_score": "0.950", "price_amount": "484.00", "price_currency": "CHF",
     "platform": "ANIBIS.CH", "location": "Vaud", "url": "http://x/9004",
     "rationale": "Vente d'ivoire d'éléphant, soumise à la réglementation CITES.",
     "content_hash": "b0e4881fd064a92b805b3b5aaaa"},
    {"id": 2, "title": "Puffs nicotine en lot", "category": "tabac",
     "suspicion_score": 0.65, "price_amount": 450, "price_currency": "CHF",
     "platform": "ANIBIS.CH", "location": "Vaud", "url": None,
     "rationale": "Vente en gros de produits nicotinés soumis à l'impôt sur le tabac."},
    {"id": 3, "title": "Canapé gris", "category": "aucune",
     "suspicion_score": 0.25, "price_amount": 300, "price_currency": "CHF",
     "platform": "ANIBIS.CH", "location": "Non mentionné", "url": None},
]


def test_synthese_trois_seuils():
    syn = build_report_data(_RUN, _LISTINGS)["synthese"]
    assert syn["analysees"] == 3
    assert syn["revision"] == 1        # 0.95 >= 0.70
    assert syn["surveillance"] == 1    # 0.65 dans [0.40, 0.70[
    assert syn["normal"] == 1          # 0.25 < 0.40


def test_toutes_annonces_triees_par_score():
    data = build_report_data(_RUN, _LISTINGS)
    scores = [a["score"] for a in data["annonces"]]
    assert scores == sorted(scores, reverse=True)
    assert len(data["annonces"]) == 3          # toutes incluses, pas seulement suspectes


def test_score_chaine_normalise():
    data = build_report_data(_RUN, _LISTINGS)
    assert data["annonces"][0]["score"] == 0.95


def test_html_justification_et_bandeau():
    html = render_report_html(build_report_data(_RUN, _LISTINGS))
    assert "Justification" in html                       # la justification est rendue
    assert "Révision humaine requise" in html            # bandeau pour le score >= 0.70
    assert "réglementation CITES" in html


def test_html_sobre_sans_jargon_interdit():
    html = render_report_html(build_report_data(_RUN, _LISTINGS)).lower()
    assert "chain of custody" not in html                # banni
    assert "généré automatiquement par le pipeline" not in html
    assert "empreinte de traçabilité" in html            # terme français retenu


def test_ecriture_json_et_html(tmp_path):
    paths = write_report(_RUN, _LISTINGS, tmp_path)
    assert paths["json"].exists() and paths["html"].exists()


def test_tri_deux_niveaux_categorie_demandee_en_tete():
    run = {"run_id": 19, "params": {"target_categories": ["arme"]}}
    listings = [
        {"id": 1, "title": "Alcool fort", "category": "alcool", "suspicion_score": 0.90},
        {"id": 2, "title": "Pistolet factice", "category": "arme", "suspicion_score": 0.75},
        {"id": 3, "title": "Couteau interdit", "category": "arme", "suspicion_score": 0.85},
    ]
    data = build_report_data(run, listings)
    cats = [a["categorie"] for a in data["annonces"]]
    # les armes d'abord (triées par score), l'alcool après malgré son score plus élevé
    assert cats == ["arme", "arme", "alcool"]
    assert data["annonces"][0]["score"] == 0.85      # arme la mieux notée en tête
    assert data["autres_detectees"] == ["alcool"]


def test_message_autres_detectees_dans_html():
    run = {"run_id": 19, "params": {"target_categories": ["arme"]}}
    listings = [
        {"id": 1, "title": "Alcool fort", "category": "alcool", "suspicion_score": 0.90},
        {"id": 2, "title": "Pistolet", "category": "arme", "suspicion_score": 0.75},
    ]
    html = render_report_html(build_report_data(run, listings))
    assert "aussi détecté" in html and "Alcool" in html


def test_deroule_lisible():
    run = {"run_id": 19, "params": {"target_categories": ["arme"]},
           "stats": {"etapes": {"expand": {"categories": ["arme"], "termes": 14},
                                "collecte": {"annonces": 41},
                                "scoring": {"scorees": 41, "alertes": 5,
                                            "par_categorie": {"arme": 3, "alcool": 1, "tabac": 1}}}}}
    data = build_report_data(run, [])
    d = data["deroule"]
    assert "catégorie Arme" in d and "14 termes" in d and "41 annonces" in d
    assert "5 signal" in d and "3 Arme" in d
    assert "Déroulé de la recherche" in render_report_html(data)