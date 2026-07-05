"""Génération de rapports d'analyse — JSON et HTML (couche restitution).

Prend le bilan d'un run (annonces + scores + justifications) et produit :
- un rapport JSON structuré (exploitable par d'autres outils) ;
- un rapport HTML autonome, lisible, imprimable (pour l'enquêteur).

Fonctions pures : données en entrée -> chaînes en sortie. Aucune dépendance à
la base ou au réseau, donc entièrement testable.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from html import escape
from pathlib import Path

# Seuils d'orientation (sur une échelle 0..1).
SEUIL_REVISION = 0.70       # >= : révision humaine requise (alerte)
SEUIL_SURVEILLANCE = 0.40   # >= : à surveiller ; en dessous : normal

CATEGORIES = {
    "tabac": "Tabac", "alcool": "Alcool", "cites": "CITES (espèces protégées)",
    "viande": "Viande", "contrefacon": "Contrefaçon", "arme": "Arme",
    "autre": "Autre (hors taxonomie)", "aucune": "Aucune",
}


def _score(listing: dict) -> float:
    try:
        return float(listing.get("suspicion_score") or 0.0)
    except (TypeError, ValueError):
        return 0.0


def _niveau(score: float) -> str:
    if score >= SEUIL_REVISION:
        return "eleve"
    if score >= SEUIL_SURVEILLANCE:
        return "moyen"
    return "normal"


# Les sites de démo tournent dans Docker : leurs URL internes (fake_market:8000)
# ne sont pas résolubles depuis le navigateur de l'hôte. Pour que les liens du
# rapport soient cliquables en démo, on les réécrit vers l'adresse publiée sur
# l'hôte. Les URL des vraies plateformes (ricardo.ch…) ne sont pas touchées.
_HOTES_DEMO = {"fake_market:8000": "localhost:8001", "mock_shop:8000": "localhost:8002"}


def _lien_public(url: str) -> str:
    for interne, public in _HOTES_DEMO.items():
        if interne in url:
            return url.replace(interne, public)
    return url


def _bloc_scoring(sco: dict) -> str:
    """Phrase de synthèse du scoring, commune aux deux modes."""
    alertes = sco.get("alertes", 0)
    detail = sco.get("par_categorie") or {}
    if detail:
        rep = ", ".join(f"{n} {CATEGORIES.get(c, c)}" for c, n in
                        sorted(detail.items(), key=lambda kv: -kv[1]))
        return (f"L'analyse a produit {alertes} signal(aux) prioritaire(s) sur "
                f"{sco.get('scorees', 0)} annonces analysées ({rep}).")
    return (f"L'analyse a examiné {sco.get('scorees', 0)} annonces, "
            f"sans signal prioritaire.")


def _phrase_deroule(run: dict) -> str:
    """Formule le déroulé de la recherche en langage d'enquêteur (non technique).

    Deux régimes distincts, décrits fidèlement :
      - Mode A (surveillance) : LLM-EXPAND génère des termes qui PILOTENT la
        collecte -> on rend compte des termes et catégories ciblés.
      - Mode B (exploration) : sans requête, l'agent explore LIBREMENT les sites
        désignés ; avec une requête, LLM-EXPAND l'enrichit et ces éléments
        ORIENTENT prioritairement la navigation ET le tri, sans filtrage strict.
        (L'étape "expand" n'était pas décrite en Mode B -> l'ancienne formulation
        affichait à tort « 0 termes / aucune catégorie ».)
    """
    stats = run.get("stats") or {}
    etapes = stats.get("etapes")
    if not etapes:
        return ""
    col = etapes.get("collecte", {})
    sco = etapes.get("scoring", {})

    # --- Mode B : exploration libre -----------------------------------------
    params = run.get("params") or {}
    mode = str(params.get("mode") or "").upper()
    is_mode_b = (
        mode in {"B", "B1", "B2"}
        or stats.get("mode_b") is True
        or "exploration" in etapes
    )
    if is_mode_b:
        sites = (etapes.get("exploration", {}).get("sites")) or {}
        nb_sites = len(sites)
        seeds = params.get("seeds") or []
        focus = str(seeds[0]).strip() if seeds else ""
        cats = params.get("target_categories") or []
        if nb_sites == 1:
            p1 = "En exploration (Mode B), l'agent a parcouru librement le site désigné."
        else:
            p1 = (f"En exploration (Mode B), l'agent a parcouru librement "
                  f"les {nb_sites} sites désignés.")
        if focus:
            terms = params.get("generated_terms") or []
            if cats:
                libelles = ", ".join(CATEGORIES.get(c, c) for c in cats)
                p1 += (f" La requête « {focus} » (rattachée à : {libelles}) a orienté "
                       f"l'exploration et la priorisation des résultats.")
            else:
                p1 += (f" La requête « {focus} » a orienté l'exploration et la "
                       f"priorisation des résultats.")
            if terms:
                p1 += (f" LLM-EXPAND en a dérivé {len(terms)} formulation(s) "
                       f"associée(s) pour guider l'agent.")
        p2 = f"La collecte a relevé {col.get('annonces', 0)} annonces."
        return f"{p1} {p2} {_bloc_scoring(sco)}"

    # --- Mode A : surveillance (collecte pilotée par LLM-EXPAND) -------------
    exp = etapes.get("expand", {})
    cats = exp.get("categories") or []
    if cats:
        libelles = ", ".join(CATEGORIES.get(c, c) for c in cats)
        cible = f"a ciblé la catégorie {libelles}"
    else:
        cible = "n'a ciblé aucune catégorie précise"
    p1 = f"La recherche {cible} et a généré {exp.get('termes', 0)} termes de recherche."
    p2 = f"La collecte a relevé {col.get('annonces', 0)} annonces."
    return f"{p1} {p2} {_bloc_scoring(sco)}"


def build_report_data(run: dict, listings: list[dict]) -> dict:
    """Construit la structure de rapport (le rapport JSON).

    Si le run cible une (des) catégorie(s), les annonces de cette catégorie sont
    placées en tête (puis triées par score) et les autres signaux détectés sont
    signalés à part. Sinon, simple tri par score décroissant.
    """
    target = run.get("params", {}).get("target_categories") or []

    def cle_tri(l: dict) -> tuple:
        prioritaire = 0 if (target and (l.get("category") in target)) else 1
        return (prioritaire, -_score(l))

    annonces = sorted(listings, key=cle_tri)

    revision = sum(1 for l in annonces if _score(l) >= SEUIL_REVISION)
    surveillance = sum(1 for l in annonces if SEUIL_SURVEILLANCE <= _score(l) < SEUIL_REVISION)
    normal = len(annonces) - revision - surveillance

    par_categorie: dict[str, int] = {}
    for l in annonces:
        if _score(l) >= SEUIL_SURVEILLANCE:
            cat = l.get("category") or "aucune"
            par_categorie[cat] = par_categorie.get(cat, 0) + 1

    # Catégories détectées EN PLUS de celle(s) recherchée(s) (effet de bord utile).
    autres_detectees = []
    if target:
        for cat, _n in sorted(par_categorie.items(), key=lambda kv: -kv[1]):
            if cat not in target and cat != "aucune" and cat not in autres_detectees:
                autres_detectees.append(cat)

    prompt = "; ".join(str(s) for s in (run.get("params", {}).get("seeds") or []))
    duree_s = (run.get("stats") or {}).get("duree_s")

    # Fallback lien (surtout Mode B, où BROWSE ne capture pas toujours l'URL
    # d'annonce) : URL du SITE source, reconstruite depuis le config_snapshot du
    # run. L'enquêteur atterrit sur le site et retrouve l'annonce par son titre.
    snap = run.get("config_snapshot") or {}
    site_urls: dict[str, str] = {}
    if isinstance(snap.get("sites"), list):
        for s in snap["sites"]:
            if s.get("platform") and s.get("base_url"):
                site_urls[s["platform"]] = s["base_url"]
    elif snap.get("platform") and snap.get("base_url"):
        site_urls[snap["platform"]] = snap["base_url"]

    return {
        "run": run,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "prompt": prompt,
        "duree_s": duree_s,
        "seuils": {"revision": SEUIL_REVISION, "surveillance": SEUIL_SURVEILLANCE},
        "deroule": _phrase_deroule(run),
        "categorie_demandee": target,
        "autres_detectees": autres_detectees,
        "synthese": {
            "analysees": len(annonces),
            "revision": revision,
            "surveillance": surveillance,
            "normal": normal,
            "par_categorie": par_categorie,
        },
        "annonces": [
            {
                "id": l.get("id"),
                "titre": l.get("title"),
                "categorie": l.get("category") or "aucune",
                "score": round(_score(l), 3),
                "prix": l.get("price_amount"),
                "devise": l.get("price_currency"),
                "localisation": l.get("location"),
                "plateforme": l.get("platform"),
                "url": l.get("url"),
                "lien_site": None if l.get("url") else site_urls.get(l.get("platform")),
                "justification": l.get("rationale"),
                "empreinte": l.get("content_hash"),
            }
            for l in annonces
        ],
    }


def _carte(a: dict) -> str:
    score = a["score"]
    niveau = _niveau(score)
    pts = int(round(score * 100))
    titre = escape(a.get("titre") or "(sans titre)")
    cat = escape(CATEGORIES.get(a["categorie"], a["categorie"]))
    plateforme = escape(a.get("plateforme") or "—")
    loc = escape(a.get("localisation") or "Non mentionné")
    prix = f"{a['prix']} {escape(a['devise'] or '')}" if a.get("prix") is not None else "—"
    if a.get("url"):
        lien = (f"<a href='{escape(_lien_public(a['url']))}' target='_blank' rel='noopener'>"
                f"Voir l'annonce →</a>")
    elif a.get("lien_site"):
        lien = (f"<a href='{escape(_lien_public(a['lien_site']))}' target='_blank' rel='noopener' "
                f"title='URL exacte non capturée — retrouvez via le titre'>"
                f"Voir le site source →</a>")
    else:
        lien = ""
    sous_titre = f"{plateforme} · {loc} · {prix}"

    bloc_just = ""
    if a.get("justification"):
        bloc_just = (f"<div class='just'><div class='lbl'>Justification</div>"
                     f"<p>{escape(a['justification'])}</p></div>")

    bloc_empreinte = ""
    if a.get("empreinte"):
        emp = escape(str(a["empreinte"]))[:24]
        bloc_empreinte = (f"<div class='meta'><div class='lbl'>Empreinte de traçabilité</div>"
                          f"<code>sha256:{emp}…</code></div>")

    bandeau = ""
    if score >= SEUIL_REVISION:
        bandeau = (f"<div class='alerte'>⚠ <b>Révision humaine requise</b> — "
                   f"score {pts}/100 au-dessus du seuil. Vérification prioritaire.</div>")

    return f"""
    <article class="carte">
      <div class="tete">
        <div class="pastille pastille--{niveau}">{pts}</div>
        <div class="ident">
          <h3>{titre}</h3>
          <div class="sous">{sous_titre} · {lien}</div>
        </div>
        <span class="cat cat--{niveau}">{cat}</span>
      </div>
      <div class="corps">
        <div class="meta"><div class="lbl">Prix</div><div>{prix}</div></div>
        <div class="meta"><div class="lbl">Localisation</div><div>{loc}</div></div>
        {bloc_empreinte}
      </div>
      {bloc_just}
      {bandeau}
    </article>"""


def render_report_html(data: dict) -> str:
    """Rend le rapport en HTML autonome (CSS inline), imprimable."""
    run = data.get("run", {})
    syn = data.get("synthese", {})
    run_id = run.get("run_id", "—")
    modele = run.get("model")
    gen = data.get("generated_at", "")[:19].replace("T", " ")
    sous_entete = f"Généré le {escape(gen)} UTC · Run #{run_id}"
    if modele:
        sous_entete += f" · Modèle {escape(str(modele))}"
    duree = data.get("duree_s")
    if duree is not None:
        sous_entete += f" · Analyse en {escape(str(duree))} s"

    alerte_badge = (f"<span class='badge'>{syn.get('revision', 0)} alerte(s)</span>"
                    if syn.get("revision") else "")

    # Message à l'enquêteur : catégories repérées en plus de celle recherchée.
    prompt = data.get("prompt") or ""
    deroule = data.get("deroule") or ""
    bloc_prompt = (f"<div class='prompt-box'><span class='lbl'>Requête de l'enquêteur</span>"
                   f"<p>« {escape(prompt)} »</p></div>") if prompt else ""
    bloc_deroule = (f"<div class='deroule'>{bloc_prompt}"
                    f"<div class='lbl'>Déroulé de la recherche</div>"
                    f"<p>{escape(deroule)}</p></div>") if (deroule or prompt) else ""

    autres = data.get("autres_detectees") or []
    info_autres = ""
    if autres:
        libelles = ", ".join(CATEGORIES.get(c, c) for c in autres)
        info_autres = (
            f"<div class='info'>Durant cette recherche, le système a aussi détecté "
            f"des signaux dans d'autres catégories : <b>{escape(libelles)}</b>. "
            f"Ces annonces figurent en fin de liste.</div>"
        )

    cartes = "".join(_carte(a) for a in data.get("annonces", [])) or \
        "<p class='vide'>Aucune annonce analysée.</p>"

    return f"""<!doctype html>
<html lang="fr"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>OFDF OSINT — Rapport d'analyse · Run #{run_id}</title>
<style>
  :root {{
    --ink:#0f172a; --muted:#64748b; --line:#e5e9f0; --bg:#eef1f5; --card:#fff;
    --accent:#1d4ed8; --eleve:#dc2626; --moyen:#ea580c; --normal:#0d9488;
  }}
  * {{ box-sizing:border-box; }}
  body {{ font-family:system-ui,-apple-system,"Segoe UI",Roboto,sans-serif;
    color:var(--ink); background:var(--bg); margin:0; line-height:1.5; }}
  .top {{ background:#0f172a; color:#fff; padding:18px 28px;
    display:flex; align-items:center; justify-content:space-between; }}
  .top h1 {{ font-size:18px; margin:0; font-weight:650; }}
  .top .s {{ color:#94a3b8; font-size:12px; margin-top:2px; }}
  .badge {{ background:var(--eleve); color:#fff; font-size:12px; font-weight:600;
    padding:4px 10px; border-radius:999px; }}
  .wrap {{ max-width:1080px; margin:0 auto; padding:24px 28px 56px; }}
  .cards {{ display:grid; grid-template-columns:repeat(4,1fr); gap:16px; margin-bottom:28px; }}
  .kpi {{ background:var(--card); border:1px solid var(--line); border-radius:12px; padding:18px; }}
  .kpi .n {{ font-size:30px; font-weight:700; line-height:1; }}
  .kpi .l {{ color:var(--muted); font-size:12px; margin-top:8px; }}
  .kpi.r .n {{ color:var(--eleve); }} .kpi.s .n {{ color:var(--moyen); }} .kpi.o .n {{ color:var(--normal); }}
  h2.section {{ font-size:14px; color:var(--muted); margin:0 0 14px; font-weight:600; }}
  .carte {{ background:var(--card); border:1px solid var(--line); border-radius:14px;
    padding:18px 20px; margin-bottom:16px; }}
  .tete {{ display:flex; align-items:center; gap:14px; }}
  .pastille {{ width:46px; height:46px; border-radius:50%; color:#fff; flex:0 0 auto;
    display:flex; align-items:center; justify-content:center; font-weight:700; font-size:17px; }}
  .pastille--eleve {{ background:var(--eleve); }}
  .pastille--moyen {{ background:var(--moyen); }}
  .pastille--normal {{ background:var(--normal); }}
  .ident {{ flex:1 1 auto; min-width:0; }}
  .ident h3 {{ margin:0; font-size:16px; }}
  .sous {{ color:var(--muted); font-size:13px; margin-top:2px; }}
  .sous a {{ color:var(--accent); text-decoration:none; }}
  .cat {{ font-size:12px; padding:3px 10px; border-radius:999px; white-space:nowrap;
    border:1px solid var(--line); background:var(--bg); }}
  .cat--eleve {{ color:var(--eleve); border-color:#fecaca; background:#fef2f2; }}
  .cat--moyen {{ color:var(--moyen); border-color:#fed7aa; background:#fff7ed; }}
  .corps {{ display:flex; gap:40px; flex-wrap:wrap; margin:16px 0 4px;
    padding-top:14px; border-top:1px solid var(--line); }}
  .lbl {{ font-size:11px; text-transform:uppercase; letter-spacing:.04em; color:var(--muted); margin-bottom:3px; }}
  code {{ font-size:12px; color:var(--muted); }}
  .just {{ background:var(--bg); border-left:3px solid var(--accent); border-radius:0 8px 8px 0;
    padding:12px 16px; margin-top:14px; }}
  .just p {{ margin:0; font-size:14px; }}
  .alerte {{ background:#fffbeb; border:1px solid #fde68a; color:#92400e; border-radius:8px;
    padding:10px 14px; margin-top:14px; font-size:13px; }}
  .info {{ background:#eff6ff; border:1px solid #bfdbfe; color:#1e40af; border-radius:8px;
    padding:11px 15px; margin-bottom:16px; font-size:13px; }}
  .deroule {{ background:var(--card); border:1px solid var(--line); border-left:3px solid var(--accent);
    border-radius:0 10px 10px 0; padding:14px 18px; margin-bottom:24px; }}
  .deroule .lbl {{ font-size:11px; text-transform:uppercase; letter-spacing:.04em; color:var(--muted); margin-bottom:5px; }}
  .prompt-box {{ background:#f8fafc; border:1px solid var(--line); border-radius:8px;
    padding:8px 11px; margin-bottom:11px; }}
  .prompt-box p {{ margin:2px 0 0; font-style:italic; color:var(--ink); }}
  .deroule p {{ margin:0; font-size:14px; }}
  .vide {{ color:var(--muted); }}
  footer {{ color:var(--muted); font-size:12px; margin-top:24px;
    border-top:1px solid var(--line); padding-top:14px; }}
  @media (max-width:760px) {{ .cards {{ grid-template-columns:repeat(2,1fr); }} }}
  @media print {{ body {{ background:#fff; }} .carte,.kpi {{ break-inside:avoid; }} }}
</style></head>
<body>
  <div class="top">
    <div><h1>OFDF OSINT — Rapport d'analyse</h1><div class="s">{sous_entete}</div></div>
    {alerte_badge}
  </div>
  <div class="wrap">
    <div class="cards">
      <div class="kpi"><div class="n">{syn.get('analysees', 0)}</div><div class="l">Annonces analysées</div></div>
      <div class="kpi r"><div class="n">{syn.get('revision', 0)}</div><div class="l">Score ≥ 70 — Révision requise</div></div>
      <div class="kpi s"><div class="n">{syn.get('surveillance', 0)}</div><div class="l">Score 40–69 — Surveillance</div></div>
      <div class="kpi o"><div class="n">{syn.get('normal', 0)}</div><div class="l">Score &lt; 40 — Normal</div></div>
    </div>
    {bloc_deroule}
    <h2 class="section">Annonces analysées (triées par score de suspicion)</h2>
    {info_autres}
    {cartes}
    <footer>
      Run #{run_id} · {syn.get('revision', 0)} annonce(s) à réviser en priorité.
      Chaque score est accompagné de sa justification ; la piste d'audit conserve la trace de chaque action.
    </footer>
  </div>
</body></html>"""


def write_report(run: dict, listings: list[dict], out_dir: str | Path) -> dict[str, Path]:
    """Écrit le rapport JSON et HTML dans `out_dir`. Renvoie les deux chemins."""
    data = build_report_data(run, listings)
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    rid = run.get("run_id", "x")
    json_path = out / f"rapport_run_{rid}.json"
    html_path = out / f"rapport_run_{rid}.html"
    json_path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    html_path.write_text(render_report_html(data), encoding="utf-8")
    return {"json": json_path, "html": html_path}