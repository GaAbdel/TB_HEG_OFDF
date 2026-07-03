"""Site factice « Brocante Léman » (mock_shop) — deux versions structurelles.

  - /v1/...  structure A (classes `listing-*`)
  - /v2/...  structure B (classes `product__*`, prix éclaté en sous-balises)

Objectif : démontrer LLM-CODE. Un extracteur déterministe calé sur la v1 casse
sur la v2 ; LLM-CODE doit retrouver les bons sélecteurs. Le site sert aussi de
cible propre à LLM-BROWSE (Mode B) pour une démonstration maîtrisée en
soutenance : design crédible, JS (révélation de numéro), et un pop-up métier
(newsletter) que l'agent doit fermer — comme sur un vrai site.

Environnement de démonstration : données fictives.
"""

from __future__ import annotations

from html import escape

from fastapi import FastAPI
from fastapi.responses import HTMLResponse

app = FastAPI(title="mock_shop")

SITE_NAME = "Brocante Léman"

# Données fictives : 1 explicite (cartouches non taxées), 1 implicite (ivoire
# sans certificat), le reste légal pour la crédibilité. Une démo de bout en bout
# produit ainsi un rapport avec des signaux réalistes.
LISTINGS: list[dict] = [
    {"id": 1, "title": "Montre automatique suisse — acier",
     "price": 540, "currency": "CHF", "seller": "horloger_gva",
     "location": "Genève", "cat": "Montres",
     "description": "Mouvement automatique, révisée, boîte et papiers d'origine."},
    {"id": 2, "title": "Cartouches de cigarettes (x10) — non taxées",
     "price": 380, "currency": "CHF", "seller": "import_direct",
     "location": "Chiasso", "cat": "Divers",
     "description": "Lot de 10 cartouches, jamais déclarées, envoi discret possible."},
    {"id": 3, "title": "Ivoire sculpté ancien — pièce de famille",
     "price": 1200, "currency": "CHF", "seller": "brocante_vd",
     "location": "Lausanne", "cat": "Antiquités",
     "description": "Statuette ancienne en ivoire, héritage familial, vendue sans certificat."},
    {"id": 4, "title": "Canapé 3 places en tissu gris",
     "price": 300, "currency": "CHF", "seller": "marie_b",
     "location": "Berne", "cat": "Maison",
     "description": "Confortable, très bon état, à venir chercher sur place."},
    {"id": 5, "title": "Vélo de course carbone — taille M",
     "price": 950, "currency": "CHF", "seller": "cycle_passion",
     "location": "Fribourg", "cat": "Sport",
     "description": "Cadre carbone, groupe Shimano 105, parfait état, entretien suivi."},
]
BY_ID = {it["id"]: it for it in LISTINGS}

# Vignette : une pastille colorée avec l'initiale (pas d'image externe à charger).
_COLORS = ["#3266CC", "#0a7d33", "#b45309", "#9333ea", "#0891b2"]


def _thumb(it: dict) -> str:
    color = _COLORS[(it["id"] - 1) % len(_COLORS)]
    initial = escape(it["title"][:1].upper())
    return (f"<div class='thumb' style='background:{color}'>{initial}"
            f"<span class='thumb-cat'>{escape(it.get('cat', ''))}</span></div>")


_CSS = """
:root{--accent:#2563eb;--ink:#0f172a;--muted:#64748b;--line:#e2e8f0;--bg:#f8fafc}
*{box-sizing:border-box}
body{font-family:system-ui,-apple-system,Segoe UI,Arial,sans-serif;color:var(--ink);margin:0;background:var(--bg)}
a{color:var(--accent);text-decoration:none}
header.site{background:#fff;border-bottom:1px solid var(--line);position:sticky;top:0;z-index:10}
.site-bar{max-width:960px;margin:0 auto;display:flex;align-items:center;gap:18px;padding:12px 20px}
.brand{font-weight:800;font-size:20px;color:var(--ink);letter-spacing:-.02em}
.brand span{color:var(--accent)}
.nav{display:flex;gap:16px;font-size:14px;color:var(--muted)}
.searchbar{margin-left:auto;display:flex;gap:0}
.searchbar input{border:1px solid var(--line);border-radius:8px 0 0 8px;padding:8px 12px;width:200px;font-size:14px}
.searchbar button{border:0;background:var(--accent);color:#fff;border-radius:0 8px 8px 0;padding:8px 14px;cursor:pointer}
.container{max-width:960px;margin:0 auto;padding:22px 20px}
.hero{margin:4px 0 20px}
.hero h1{font-size:22px;margin:0 0 4px}
.hero p{color:var(--muted);margin:0;font-size:14px}
.grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(220px,1fr));gap:16px}
.card{background:#fff;border:1px solid var(--line);border-radius:12px;overflow:hidden;transition:box-shadow .15s}
.card:hover{box-shadow:0 4px 16px rgba(15,23,42,.08)}
.thumb{height:120px;color:#fff;font-size:42px;font-weight:800;display:flex;align-items:center;justify-content:center;position:relative}
.thumb-cat{position:absolute;bottom:8px;right:10px;font-size:11px;font-weight:600;background:rgba(0,0,0,.25);padding:2px 8px;border-radius:999px}
.card-body{padding:12px 14px}
.card-title{font-weight:600;font-size:15px;margin:0 0 6px;color:var(--ink)}
.card-price{color:#0a7d33;font-weight:700;font-size:17px}
.card-loc{color:var(--muted);font-size:13px;margin-top:4px}
/* --- pages de détail : structures v1 (listing-*) et v2 (product__*) --- */
.listing.card,.product.card{max-width:620px;padding:22px;border-radius:12px}
.listing.card h1,.product__name{font-size:22px;margin:0 0 10px}
.price,.product__price{color:#0a7d33;font-weight:700;font-size:22px}
.meta,.product__attrs{color:var(--muted);font-size:14px;list-style:none;padding:0;display:flex;gap:14px;margin:10px 0}
.listing.card .listing-description,.product__desc{margin:14px 0;line-height:1.5}
button.reveal{background:var(--accent);color:#fff;border:0;border-radius:8px;padding:9px 16px;cursor:pointer;font-size:14px}
.phone{margin-top:12px;font-weight:700;color:var(--ink)}
.crumb{font-size:13px;color:var(--muted);margin-bottom:14px}
.pager{margin-top:18px;display:flex;gap:12px;align-items:center;color:var(--muted);font-size:14px}
/* --- pop-up métier (newsletter) --- */
.modal-overlay{position:fixed;inset:0;background:rgba(15,23,42,.55);display:flex;align-items:center;justify-content:center;z-index:50}
.modal{background:#fff;border-radius:14px;padding:26px;max-width:380px;text-align:center;box-shadow:0 10px 40px rgba(0,0,0,.25)}
.modal h3{margin:0 0 8px}
.modal p{color:var(--muted);font-size:14px;margin:0 0 18px}
.modal button{background:var(--accent);color:#fff;border:0;border-radius:9px;padding:10px 18px;cursor:pointer;font-size:14px}
.modal .later{display:block;margin-top:10px;font-size:13px;color:var(--muted);background:none;padding:4px}
footer{max-width:960px;margin:20px auto;padding:0 20px 30px;color:var(--muted);font-size:12px}
"""

_JS = """
function showPhone(btn){
  var el=document.getElementById('phone');
  el.textContent='+41 79 000 00 00';
  btn.style.display='none';
}
function fermerPromo(){
  var m=document.getElementById('promo');
  if(m) m.parentNode.removeChild(m);
}
"""

_PROMO = f"""
<div id='promo' class='modal-overlay'>
  <div class='modal'>
    <h3>Bienvenue sur {SITE_NAME}</h3>
    <p>Inscrivez-vous à nos alertes bonnes affaires et soyez informé des nouvelles annonces près de chez vous.</p>
    <button onclick='fermerPromo()'>Continuer sur le site</button>
    <button class='later' onclick='fermerPromo()'>Plus tard</button>
  </div>
</div>
"""


def _header() -> str:
    return (
        "<header class='site'><div class='site-bar'>"
        f"<div class='brand'>Brocante<span>Léman</span></div>"
        "<nav class='nav'><a href='#'>Toutes les annonces</a><a href='#'>Catégories</a>"
        "<a href='#'>Déposer une annonce</a></nav>"
        "<div class='searchbar'><input placeholder='Rechercher une annonce…'>"
        "<button>Rechercher</button></div>"
        "</div></header>"
    )


def _page(title: str, body: str, *, promo: bool = False) -> str:
    return (
        "<!doctype html><html lang='fr'><head><meta charset='utf-8'>"
        "<meta name='viewport' content='width=device-width, initial-scale=1'>"
        f"<title>{escape(title)} — {SITE_NAME}</title><style>{_CSS}</style></head>"
        f"<body>{_header()}<div class='container'>{body}</div>"
        f"<footer>{SITE_NAME} — petites annonces entre particuliers.</footer>"
        f"{_PROMO if promo else ''}"
        f"<script>{_JS}</script></body></html>"
    )


def _card(version: str, it: dict) -> str:
    return (
        f"<a class='card' href='/{version}/listing/{it['id']}'>"
        f"{_thumb(it)}"
        "<div class='card-body'>"
        f"<div class='card-title'>{escape(it['title'])}</div>"
        f"<div class='card-price'>{it['price']} {escape(it['currency'])}</div>"
        f"<div class='card-loc'>{escape(it['location'])} · {escape(it['seller'])}</div>"
        "</div></a>"
    )


def _hero() -> str:
    return ("<div class='hero'><h1>Petites annonces de la région lémanique</h1>"
            "<p>Achetez et vendez près de chez vous — objets d'occasion, collection, mobilier.</p></div>")


def _index(version: str) -> str:
    cards = "".join(_card(version, it) for it in LISTINGS)
    body = _hero() + f"<div class='grid'>{cards}</div>"
    return _page("Annonces", body, promo=True)


PER_PAGE = 3


def _index_paginated(version: str, page: int) -> str:
    page = max(1, page)
    total_pages = (len(LISTINGS) + PER_PAGE - 1) // PER_PAGE
    start = (page - 1) * PER_PAGE
    subset = LISTINGS[start:start + PER_PAGE]
    cards = "".join(_card(version, it) for it in subset)
    nav = []
    if page > 1:
        nav.append(f"<a class='page-prev' href='/{version}?page={page - 1}'>← Précédent</a>")
    nav.append(f"<span class='page-info'>Page {page} / {total_pages}</span>")
    if page < total_pages:
        nav.append(f"<a class='page-next' href='/{version}?page={page + 1}'>Suivant →</a>")
    nav_html = f"<div class='pager'>{' '.join(nav)}</div>" if nav else ""
    body = _hero() + f"<div class='grid'>{cards}</div>{nav_html}"
    return _page("Annonces", body, promo=True)


# --- Version 1 : structure A (classes listing-*) ----------------------------
def _listing_v1(it: dict) -> str:
    body = (
        f"<div class='crumb'><a href='/v1'>Annonces</a> › {escape(it['title'])}</div>"
        "<article class='listing card'>"
        f"<h1 class='listing-title'>{escape(it['title'])}</h1>"
        f"<div class='listing-price price'>{it['price']} {escape(it['currency'])}</div>"
        "<div class='listing-meta meta'>"
        f"<span class='seller'>{escape(it['seller'])}</span>"
        f"<span class='location'>{escape(it['location'])}</span></div>"
        f"<div class='listing-description'>{escape(it['description'])}</div>"
        "<button class='reveal' onclick='showPhone(this)'>Afficher le numéro</button>"
        "<div id='phone' class='phone'></div>"
        "</article>"
    )
    return _page(it["title"], body)


# --- Version 2 : structure B (classes et imbrication différentes) -----------
def _listing_v2(it: dict) -> str:
    body = (
        f"<div class='crumb'><a href='/v2'>Annonces</a> › {escape(it['title'])}</div>"
        "<section class='product card'>"
        f"<h2 class='product__name'>{escape(it['title'])}</h2>"
        "<p class='product__price'>"
        f"<span class='amount'>{it['price']}</span> "
        f"<span class='currency'>{escape(it['currency'])}</span></p>"
        "<ul class='product__attrs'>"
        f"<li class='attr attr--seller'>{escape(it['seller'])}</li>"
        f"<li class='attr attr--location'>{escape(it['location'])}</li></ul>"
        f"<div class='product__desc'>{escape(it['description'])}</div>"
        "<button class='reveal' onclick='showPhone(this)'>Afficher le numéro</button>"
        "<div id='phone' class='phone'></div>"
        "</section>"
    )
    return _page(it["title"], body)


@app.get("/healthz")
def healthz() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/v1", response_class=HTMLResponse)
def index_v1() -> str:
    return _index("v1")


@app.get("/v2", response_class=HTMLResponse)
def index_v2(page: int = 1) -> str:
    return _index_paginated("v2", page)


@app.get("/v1/listing/{listing_id}", response_class=HTMLResponse)
def listing_v1(listing_id: int) -> str:
    it = BY_ID.get(listing_id)
    return _listing_v1(it) if it else _page("Introuvable", "<p>Annonce introuvable.</p>")


@app.get("/v2/listing/{listing_id}", response_class=HTMLResponse)
def listing_v2(listing_id: int) -> str:
    it = BY_ID.get(listing_id)
    return _listing_v2(it) if it else _page("Introuvable", "<p>Annonce introuvable.</p>")


# --- Version « courante » flippable : terrain de démo LLM-CODE ----------------
#  /shop sert TOUJOURS la même URL, mais son HTML de détail bascule de v1 à v2
#  quand on flippe la version. C'est la simulation fidèle d'une refonte de site :
#  l'extracteur Mode A vise /shop, marche sur v1, casse sur v2 -> réparation.
_CURRENT = {"v": "v1"}


@app.get("/shop", response_class=HTMLResponse)
def shop_index() -> str:
    return _index("shop")            # cartes -> /shop/listing/{id}


@app.get("/shop/listing/{listing_id}", response_class=HTMLResponse)
def shop_listing(listing_id: int) -> str:
    it = BY_ID.get(listing_id)
    if not it:
        return _page("Introuvable", "<p>Annonce introuvable.</p>")
    return _listing_v2(it) if _CURRENT["v"] == "v2" else _listing_v1(it)


@app.post("/shop/version/{version}")
def shop_set_version(version: str) -> dict:
    """Bascule la version servie par /shop (v1 <-> v2). Pour la démo."""
    if version not in ("v1", "v2"):
        return {"error": "version inconnue", "current": _CURRENT["v"]}
    _CURRENT["v"] = version
    return {"current": _CURRENT["v"]}


@app.get("/shop/version")
def shop_get_version() -> dict:
    return {"current": _CURRENT["v"]}