"""Session de navigation Playwright sous garde-fous.

`BrowserSession` ouvre Chromium, crée un contexte SANS téléchargement, et y
branche l'interception réseau des garde-fous. Elle expose `fetch(url)` qui
consomme une action (budget) puis renvoie le HTML de la page.

Playwright n'est importé QUE dans `__aenter__` : ce module reste donc
importable (et l'orchestration de collecte testable) sans navigateur installé.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from osint.collecte.guardrails import Guardrails


class BrowserSession:
    def __init__(
        self,
        *,
        guardrails: "Guardrails",
        concurrency: int = 4,
        timeout_s: int = 30,
        headless: bool = True,
    ) -> None:
        self.guardrails = guardrails
        self.concurrency = concurrency
        self.timeout_ms = int(timeout_s * 1000)
        self.headless = headless
        self._pw = None
        self._browser = None
        self._context = None

    async def __aenter__(self) -> "BrowserSession":
        from playwright.async_api import async_playwright  # import paresseux

        self._pw = await async_playwright().start()
        self._browser = await self._pw.chromium.launch(headless=self.headless)
        # accept_downloads=False : filet anti-téléchargement au niveau navigateur
        self._context = await self._browser.new_context(accept_downloads=False)
        # Interception réseau : chaque requête passe par les garde-fous
        await self.guardrails.attach(self._context)
        return self

    async def __aexit__(self, *exc) -> None:
        if self._context:
            await self._context.close()
        if self._browser:
            await self._browser.close()
        if self._pw:
            await self._pw.stop()

    async def fetch(self, url: str) -> str:
        """Consomme une action, navigue, renvoie le HTML.

        Lève BudgetExhausted si le plafond d'actions est atteint. La navigation
        vers une URL hors périmètre échoue (requête abandonnée par les garde-fous).
        """
        self.guardrails.consume_action()
        page = await self._context.new_page()
        try:
            await page.goto(url, timeout=self.timeout_ms, wait_until="domcontentloaded")
            return await page.content()
        finally:
            await page.close()