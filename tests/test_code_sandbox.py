"""Tests du harnais d'exécution isolée (code_sandbox).

Vérifie qu'un candidat valide passe, qu'une erreur de syntaxe est détectée, et
qu'une mauvaise interface est rejetée. Pas de LLM : on fournit le code à la main.
"""

from __future__ import annotations

from osint.analyse.code_sandbox import check_candidate

_VALID = '''
class MonExtracteur:
    def __init__(self, base_url, guardrails, *, concurrency=4, terms=None):
        self.base_url = base_url
    async def run(self):
        return []
'''

_SYNTAXE = "class Cassé(:\n    pass\n"

_MAUVAISE_INTERFACE = '''
class SansRun:
    def __init__(self, base_url, guardrails):
        pass
'''

_RUN_PAS_ASYNC = '''
class RunSync:
    def __init__(self, base_url, guardrails):
        pass
    def run(self):
        return []
'''

_CONSTRUCTEUR_INCOMPLET = '''
class MauvaisCtor:
    def __init__(self, url):
        pass
    async def run(self):
        return []
'''


def test_candidat_valide_passe():
    res = check_candidate(_VALID)
    assert res["ok"] is True
    assert res["cls"] == "MonExtracteur"


def test_erreur_syntaxe_detectee():
    res = check_candidate(_SYNTAXE)
    assert res["ok"] is False
    assert res["stage"] == "import"


def test_sans_run_rejete():
    res = check_candidate(_MAUVAISE_INTERFACE)
    assert res["ok"] is False
    assert res["stage"] == "interface"


def test_run_non_async_rejete():
    res = check_candidate(_RUN_PAS_ASYNC)
    assert res["ok"] is False
    assert res["stage"] == "interface"


def test_constructeur_incomplet_rejete():
    res = check_candidate(_CONSTRUCTEUR_INCOMPLET)
    assert res["ok"] is False
    assert res["stage"] == "interface"