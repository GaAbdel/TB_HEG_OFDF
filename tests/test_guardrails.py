"""Tests des garde-fous de collecte"""

from __future__ import annotations

import pytest

from osint.collecte.guardrails import BudgetExhausted, Guardrails

ALLOW = ["ricardo.ch", "anibis.ch", "tutti.ch"]
BLOCK = ["login", "checkout", "payment"]


def make(budget: int = 5, **kw) -> Guardrails:
    return Guardrails(allowlist=ALLOW, action_budget=budget, blocklist=BLOCK, **kw)


# --- Périmètre : domaines ----------------------------------------------------
def test_domaine_exact_autorise():
    assert make().domain_allowed("https://ricardo.ch/annonce/1") is True


def test_sous_domaine_autorise():
    assert make().domain_allowed("https://www.ricardo.ch/x") is True


def test_domaine_hors_liste_bloque():
    assert make().domain_allowed("https://google.com/track") is False


def test_faux_sous_domaine_bloque():
    # ricardo.ch.evil.com ne doit PAS passer
    assert make().domain_allowed("https://ricardo.ch.evil.com/x") is False


def test_prefixe_trompeur_bloque():
    assert make().domain_allowed("https://evil-ricardo.ch/x") is False


# --- Périmètre : chemins interdits -------------------------------------------
def test_chemin_login_bloque():
    assert make().path_blocked("https://ricardo.ch/login") is True


def test_chemin_normal_ok():
    assert make().path_blocked("https://ricardo.ch/annonce/42") is False


# --- Périmètre : téléchargements ---------------------------------------------
def test_telechargement_bloque():
    assert make().is_download("https://ricardo.ch/fichier.pdf") is True


def test_page_html_non_telechargement():
    assert make().is_download("https://ricardo.ch/annonce/1") is False


def test_telechargement_autorise_si_option():
    assert make(allow_downloads=True).is_download("https://ricardo.ch/x.zip") is False


# --- Décision combinée -------------------------------------------------------
def test_requete_legitime_autorisee():
    d = make().evaluate_request("https://ricardo.ch/annonce/1", "document")
    assert d.allowed is True


def test_hors_allowlist_refuse():
    d = make().evaluate_request("https://tracker.ads.com/pixel", "image")
    assert d.allowed is False and "allowlist" in d.reason


def test_telechargement_refuse_meme_sur_allowlist():
    d = make().evaluate_request("https://ricardo.ch/export.xlsx", "document")
    assert d.allowed is False and "téléchargement" in d.reason


def test_login_refuse_meme_sur_allowlist():
    d = make().evaluate_request("https://ricardo.ch/login?next=/x", "document")
    assert d.allowed is False and "blocklist" in d.reason


# --- Budget d'actions --------------------------------------------------------
def test_budget_decompte():
    g = make(budget=3)
    assert g.budget_remaining == 3
    g.consume_action()
    g.consume_action()
    assert g.actions_used == 2 and g.budget_remaining == 1


def test_budget_epuise_leve():
    g = make(budget=2)
    g.consume_action()
    g.consume_action()
    assert g.can_act() is False
    with pytest.raises(BudgetExhausted):
        g.consume_action()