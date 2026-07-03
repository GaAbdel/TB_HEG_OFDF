"""Garde-fous de collecte — périmètre d'action de l'agent.

Deux protections complémentaires :

  1. Périmètre RÉSEAU (par requête) : domaine hors allowlist, chemin interdit
     (login/checkout...) ou téléchargement -> requête bloquée à la source via
     l'interception réseau Playwright. C'est une GARANTIE (« l'agent ne peut
     techniquement pas sortir »), pas une simple politique.
  2. Budget d'ACTIONS (par navigation) : plafond du nombre de pages ouvertes
     par session -> coupe-circuit. Périmètre d'action fini et garanti.

La logique de DÉCISION est testable sans navigateur. Seule `attach()`
touche Playwright. L'allowlist est reçue en paramètre : la même classe sert le
Mode A (liste statique), le Mode B routine (liste vérifiée) et le Mode B
ponctuel (domaines autorisés par un humain).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING
from urllib.parse import urlparse

if TYPE_CHECKING:
    from osint.config import Config

# Extensions considérées comme des téléchargements (interdits par défaut).
DOWNLOAD_EXTENSIONS = (
    ".zip", ".rar", ".7z", ".tar", ".gz", ".exe", ".msi", ".dmg", ".apk",
    ".bin", ".iso", ".pdf", ".doc", ".docx", ".xls", ".xlsx", ".ppt", ".pptx",
)


@dataclass(frozen=True)
class Decision:
    """Résultat de l'évaluation d'une requête."""

    allowed: bool
    reason: str


class BudgetExhausted(RuntimeError):
    """Levée quand le budget d'actions de la session est épuisé."""


class Guardrails:
    def __init__(
        self,
        *,
        allowlist,
        action_budget: int,
        blocklist=(),
        allow_downloads: bool = False,
    ) -> None:
        # Normalisation : minuscules, sans point de tête.
        self.allowlist = {d.lower().lstrip(".") for d in allowlist if d}
        self.action_budget = int(action_budget)
        self.blocklist = tuple(b.lower() for b in blocklist)
        self.allow_downloads = allow_downloads
        self._actions_used = 0
    
    @classmethod
    def from_config(cls, cfg: "Config", *, allowlist=None, action_budget=None) -> "Guardrails":
        """Construit les garde-fous depuis config.yaml.

        `allowlist` surcharge la liste statique (Mode B : périmètre fourni
        à l'exécution).
        """
        coll = cfg.get("collecte", default={}) or {}
        return cls(
            allowlist=allowlist if allowlist is not None else coll.get("allowlist", []),
            action_budget=action_budget if action_budget is not None else coll.get("budget_actions", 40),
            blocklist=coll.get("blocklist", []),
        )

    # --- Périmètre réseau (décision par requête) -----------------------------
    def domain_allowed(self, url: str) -> bool:
        """Vrai si l'hôte de l'URL est dans l'allowlist (sous-domaines inclus)."""
        host = (urlparse(url).hostname or "").lower()
        if not host:
            return False
        return any(host == d or host.endswith("." + d) for d in self.allowlist)

    def path_blocked(self, url: str) -> bool:
        """Vrai si l'URL contient un mot-clé de la blocklist (login, checkout...)."""
        u = url.lower()
        return any(kw in u for kw in self.blocklist)

    def is_download(self, url: str, resource_type: str | None = None) -> bool:
        """Vrai si l'URL ressemble à un téléchargement de fichier."""
        if self.allow_downloads:
            return False
        return urlparse(url).path.lower().endswith(DOWNLOAD_EXTENSIONS)

    def evaluate_request(self, url: str, resource_type: str | None = None) -> Decision:
        """Décision complète pour une requête réseau."""
        if not self.domain_allowed(url):
            return Decision(False, f"hors allowlist: {urlparse(url).hostname}")
        if self.path_blocked(url):
            return Decision(False, "chemin interdit (blocklist)")
        if self.is_download(url, resource_type):
            return Decision(False, "téléchargement interdit")
        return Decision(True, "ok")

    # --- Budget d'actions (par navigation) -----------------------------------
    @property
    def actions_used(self) -> int:
        return self._actions_used

    @property
    def budget_remaining(self) -> int:
        return max(0, self.action_budget - self._actions_used)

    def can_act(self) -> bool:
        return self._actions_used < self.action_budget

    def consume_action(self) -> int:
        """Décompte une navigation. Lève BudgetExhausted si le plafond est atteint."""
        if self._actions_used >= self.action_budget:
            raise BudgetExhausted(
                f"budget d'actions épuisé ({self.action_budget})"
            )
        self._actions_used += 1
        return self._actions_used

    # --- Attachement Playwright (non testé sans navigateur) ------------------
    async def attach(self, context) -> None:
        """Branche l'interception réseau sur un BrowserContext Playwright.

        Chaque requête émise par le navigateur (page ET ressources annexes :
        images, scripts, trackers...) passe par `evaluate_request`. Le contexte
        doit par ailleurs être créé avec `accept_downloads=False` (filet
        anti-téléchargement au niveau navigateur).
        """
        async def _handle(route) -> None:
            req = route.request
            decision = self.evaluate_request(req.url, req.resource_type)
            if decision.allowed:
                await route.continue_()
            else:
                await route.abort()

        await context.route("**/*", _handle)