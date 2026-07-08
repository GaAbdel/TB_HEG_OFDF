from __future__ import annotations

import asyncio
import json

from osint.analyse.browse import run_browse
from osint.config import get_config


async def main() -> None:
    cfg = get_config()

    output = await run_browse(
        cfg,
        "https://www.anibis.ch",
        max_steps=25,
        headless=False,
        focus="cigarettes",
        generated_terms=[
            "cigarette",
            "cartouche de cigarettes",
            "tabac",
        ],
    )

    print("\n===== RESULTAT BRUT BROWSER-USE =====")
    print(output.get("result"))

    print("\n===== TRACE =====")
    print(
        json.dumps(
            output.get("trace") or {},
            ensure_ascii=False,
            indent=2,
            default=str,
        )
    )


if __name__ == "__main__":
    asyncio.run(main())