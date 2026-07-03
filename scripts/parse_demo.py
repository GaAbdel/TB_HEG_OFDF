#!/usr/bin/env python3
"""Démo LLM-PARSE : extraction structurée de pages de sites inconnus.

Deux extraits HTML de structures différentes (sites « inconnus ») sont passés à
LLM-PARSE, qui en isole les champs par le sens — sans extracteur déterministe.

Usage :
    docker compose exec app python scripts/parse_demo.py
"""

from __future__ import annotations

from osint.analyse.parser_llm import parse_listing_llm
from osint.config import get_config

# Deux structures volontairement différentes (deux « sites » inconnus).
SAMPLES = [
    """
    <div class="ad">
      <h3>Vélo de course carbone — taille M</h3>
      <p class="cost">CHF 950.–</p>
      <p>Cadre carbone, groupe 105, parfait état.</p>
      <small>Vendeur : cycle_passion — Fribourg</small>
    </div>
    """,
    """
    <section>
      <header><span class="ttl">Cartouches de cigarettes (x10)</span></header>
      <table><tr><td>Prix</td><td>380 CHF</td></tr>
             <tr><td>Lieu</td><td>Chiasso</td></tr></table>
      <article>Lot de 10 cartouches, jamais déclarées, envoi discret.</article>
    </section>
    """,
]


def main() -> None:
    cfg = get_config()
    cfg.assert_lpd_compliance(consentement_cloud=True)
    print(f"Modèle : {cfg.resolve_model('LLM-PARSE').model}\n")
    for i, html in enumerate(SAMPLES, 1):
        rec = parse_listing_llm(cfg, html)
        flag = "OK" if rec["parse_ok"] else f"PROBLÈMES {rec['parse_problems']}"
        print(f"--- Extrait {i} [{flag}] ---")
        print(f"  title       : {rec['title']}")
        print(f"  price       : {rec['price_amount']} {rec['price_currency']}")
        print(f"  location    : {rec['location']}")
        print(f"  seller      : {rec['seller']}")
        print(f"  description : {rec['description']}\n")


if __name__ == "__main__":
    main()