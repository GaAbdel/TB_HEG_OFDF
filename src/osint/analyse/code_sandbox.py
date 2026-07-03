"""Dispositif d'exécution isolée pour un extracteur candidat (verrou OFDF).

⚠️ CE N'EST PAS UNE ISOLATION DE SÉCURITÉ. C'est un dispositif d’exécution isolée : le
code candidat est chargé dans un SOUS-PROCESSUS Python séparé, avec un délai
maximal (timeout). Cela :
  - isole les plantages et les blocages du processus principal ;
  - vérifie que le code se CHARGE (pas d'erreur de syntaxe/import) et respecte
    l'INTERFACE attendue (une classe avec `async def run()` et un constructeur
    acceptant base_url + guardrails).
Cela NE protège PAS contre un code malveillant (accès disque/réseau possible au
sein du sous-processus). Une véritable isolation de sécurité (conteneur dédié,
gVisor/nsjail) relève de l'évolution par l'OFDF. Le risque est ici borné par des
VM jetables et par le verrou d'activation.

Ce dispositif ne vérifie PAS la correction de l'extraction (extraire les bons
champs) : cela suppose un jeu de test par site, incrément ultérieur.
"""

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
from pathlib import Path

# Runner exécuté dans le sous-processus. Reçoit le chemin du candidat en argv[1].
# Ne fait AUCUNE interpolation (pas de .format) : robuste aux accolades.
_RUNNER = r'''
import importlib.util, inspect, sys, json
path = sys.argv[1]
spec = importlib.util.spec_from_file_location("candidate_extractor", path)
mod = importlib.util.module_from_spec(spec)
try:
    spec.loader.exec_module(mod)
except Exception as e:
    print(json.dumps({"ok": False, "stage": "import", "error": repr(e)[:400]})); sys.exit(0)
cls = None
for _name, obj in vars(mod).items():
    if inspect.isclass(obj) and inspect.iscoroutinefunction(getattr(obj, "run", None)):
        cls = obj; break
if cls is None:
    print(json.dumps({"ok": False, "stage": "interface", "error": "aucune classe avec 'async def run()'"})); sys.exit(0)
try:
    params = list(inspect.signature(cls.__init__).parameters)
except Exception as e:
    print(json.dumps({"ok": False, "stage": "interface", "error": repr(e)[:400]})); sys.exit(0)
if "base_url" not in params or "guardrails" not in params:
    print(json.dumps({"ok": False, "stage": "interface", "error": "constructeur sans base_url/guardrails"})); sys.exit(0)
print(json.dumps({"ok": True, "cls": cls.__name__}))
'''


def check_candidate(code: str, *, timeout: float = 15.0) -> dict:
    """Charge le code candidat dans un sous-processus isolé et vérifie l'interface.

    Renvoie {ok: bool, stage?: str, error?: str, cls?: str}. `stage` vaut
    'import' (ne se charge pas), 'interface' (mauvais contrat), 'timeout', ou
    'run' (échec inattendu du dispositif).
    """
    with tempfile.TemporaryDirectory() as d:
        cand = Path(d) / "candidate_extractor.py"
        cand.write_text(code, encoding="utf-8")
        runner = Path(d) / "_runner.py"
        runner.write_text(_RUNNER, encoding="utf-8")
        try:
            proc = subprocess.run(
                [sys.executable, str(runner), str(cand)],
                capture_output=True, text=True, timeout=timeout,
            )
        except subprocess.TimeoutExpired:
            return {"ok": False, "stage": "timeout", "error": f"dépassement de {timeout}s"}
        lines = (proc.stdout or "").strip().splitlines()
        if not lines:
            return {"ok": False, "stage": "run", "error": (proc.stderr or "sortie vide")[:400]}
        try:
            return json.loads(lines[-1])
        except Exception:
            return {"ok": False, "stage": "run", "error": (proc.stderr or proc.stdout)[:400]}