"""Console d'analyse — page web unique (HTML/CSS/JS, sans dépendance).

Servie par l'API, elle consomme les endpoints existants :
- POST /search (consigne d'enquêteur en langage naturel) + suivi du job ;
- GET /listings (file d'investigation, filtrable par score) ;
- GET /listings/{id} (détail + justification) ;
- GET /reports/{run_id} (rapport généré).

Les fonctions non encore réalisées (validation enquêteur, planification,
export) sont présentes mais GRISÉES : l'interface matérialise la feuille de
route sans faire passer le futur pour de l'existant.
"""

from __future__ import annotations

INDEX_HTML = r"""<!doctype html>
<html lang="fr"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>OFDF OSINT — Console d'analyse</title>
<style>
  :root {
    --ink:#0f172a; --muted:#64748b; --line:#e5e9f0; --bg:#eef1f5; --card:#fff;
    --accent:#1d4ed8; --eleve:#dc2626; --moyen:#ea580c; --normal:#0d9488;
  }
  * { box-sizing:border-box; }
  body { font-family:system-ui,-apple-system,"Segoe UI",Roboto,sans-serif;
    color:var(--ink); background:var(--bg); margin:0; line-height:1.5; }
  .top { background:#0f172a; color:#fff; padding:16px 28px;
    display:flex; align-items:center; justify-content:space-between; }
  .top h1 { font-size:18px; margin:0; font-weight:650; }
  .top .s { color:#94a3b8; font-size:12px; }
  .wrap { max-width:1080px; margin:0 auto; padding:24px 28px 56px; }
  .panel { background:var(--card); border:1px solid var(--line); border-radius:14px;
    padding:20px; margin-bottom:20px; }
  .panel h2 { font-size:14px; margin:0 0 12px; color:var(--muted); font-weight:600;
    text-transform:uppercase; letter-spacing:.04em; }
  .search { display:flex; gap:10px; }
  .search input { flex:1; padding:11px 14px; border:1px solid var(--line); border-radius:10px;
    font-size:15px; font-family:inherit; }
  .search input:focus { outline:2px solid var(--accent); border-color:var(--accent); }
  button { font-family:inherit; font-size:14px; font-weight:600; border:0; border-radius:10px;
    padding:11px 18px; background:var(--accent); color:#fff; cursor:pointer; }
  button:hover { background:#1e40af; }
  button:disabled { background:#cbd5e1; cursor:not-allowed; }
  .hint { color:var(--muted); font-size:13px; margin-top:8px; }
  .status { margin-top:14px; font-size:14px; display:none; }
  .status.show { display:block; }
  .dot { display:inline-block; width:9px; height:9px; border-radius:50%; margin-right:6px; }
  .dot.pending { background:#cbd5e1; } .dot.running { background:var(--moyen); }
  .dot.done { background:var(--normal); } .dot.error { background:var(--eleve); }
  .report-link { display:inline-block; margin-top:10px; color:var(--accent);
    font-weight:600; text-decoration:none; }
  .report-link:hover { text-decoration:underline; }
  .filters { display:flex; align-items:center; gap:12px; margin-bottom:14px; }
  select { padding:8px 12px; border:1px solid var(--line); border-radius:8px; font-family:inherit; }
  table { width:100%; border-collapse:collapse; }
  th { text-align:left; font-size:11px; text-transform:uppercase; letter-spacing:.04em;
    color:var(--muted); padding:8px 10px; border-bottom:1px solid var(--line); }
  td { padding:10px; border-bottom:1px solid var(--line); font-size:14px; }
  tr.row { cursor:pointer; } tr.row:hover { background:var(--bg); }
  .score { font-weight:700; font-variant-numeric:tabular-nums; }
  .score.eleve { color:var(--eleve); } .score.moyen { color:var(--moyen); } .score.normal { color:var(--normal); }
  .cat { font-size:12px; padding:2px 9px; border-radius:999px; border:1px solid var(--line);
    background:var(--bg); white-space:nowrap; }
  .empty { color:var(--muted); text-align:center; padding:22px; }
  .count { font-size:13px; color:var(--muted); font-weight:400; }
  .id-cell { color:var(--muted); font-size:12px; font-variant-numeric:tabular-nums; }
  .pagination-nav { display:flex; align-items:center; justify-content:center; gap:16px; margin-top:14px; }
  .pagination-nav button { background:#fff; color:var(--ink); border:1px solid var(--line); }
  .pagination-nav button:hover:not(:disabled) { background:var(--bg); }
  .pagination-nav button:disabled { color:#cbd5e1; background:#fff; cursor:not-allowed; }
  .page-info { font-size:13px; color:var(--muted); }
  .rapport-btns { margin-left:auto; display:inline-flex; gap:14px; align-items:center; }
  .rapport-btns a { cursor:pointer; }
  #scrollBtn { position:fixed; right:22px; bottom:22px; width:42px; height:42px; border-radius:50%;
    background:#0f172a; color:#fff; font-size:18px; display:flex; align-items:center;
    justify-content:center; cursor:pointer; box-shadow:0 2px 8px rgba(0,0,0,.2); z-index:50; }
  #scrollBtn:hover { background:#1e293b; }
  .review { margin-top:14px; padding-top:12px; border-top:1px solid var(--line); }
  .review-row { display:flex; align-items:center; gap:14px; flex-wrap:wrap; margin-top:4px; }
  .review-status { font-size:13px; font-weight:600; padding:3px 10px; border-radius:999px; }
  .review-none { background:#f1f5f9; color:var(--muted); }
  .review-confirme { background:#fef2f2; color:var(--eleve); }
  .review-rejete { background:#f0fdf4; color:var(--normal); }
  .review-incertain { background:#fff7ed; color:var(--moyen); }
  .review-btns { display:inline-flex; gap:8px; }
  .rv { font-size:13px; padding:6px 12px; border-radius:8px; border:1px solid var(--line); background:#fff; color:var(--ink); }
  .rv-ok:hover { background:#fef2f2; border-color:#fecaca; color:var(--eleve); }
  .rv-no:hover { background:#f0fdf4; border-color:#bbf7d0; color:var(--normal); }
  .rv-maybe:hover { background:#fff7ed; border-color:#fed7aa; color:var(--moyen); }
  .btn-rapport { background:var(--accent); color:#fff; font-size:13px; font-weight:600;
    padding:8px 14px; border-radius:8px; text-decoration:none; white-space:nowrap; }
  .btn-rapport:hover { background:#1e40af; }
  .btn-rapport--alt { background:#fff; color:var(--accent); border:1px solid var(--accent); }
  .btn-rapport--alt:hover { background:#eff6ff; }
  .etat-cell { text-align:center; width:44px; }
  .pastille-etat { display:inline-block; width:12px; height:12px; border-radius:50%; cursor:help;
    border:1px solid transparent; vertical-align:middle; }
  .etat-confirme { background:var(--eleve); }
  .etat-rejete { background:var(--normal); }
  .etat-incertain { background:var(--moyen); }
  .etat-none { background:transparent; border-color:#cbd5e1; }
  .titre-main { font-weight:500; }
  .sub-row { color:var(--muted); font-size:12px; margin-top:2px; }
  .prix { white-space:nowrap; color:var(--muted); font-size:13px; }
  .detail-row td { background:var(--bg); padding:0; }
  .detail-inline { padding:14px 16px; border-left:3px solid var(--accent);
    margin:0 10px 10px; border-radius:0 8px 8px 0; }
  .detail-inline .lbl { font-size:11px; text-transform:uppercase; color:var(--muted); margin-bottom:4px; }
  .detail-inline p { margin:0 0 8px; font-size:14px; }
  .ex { display:block; margin-top:6px; color:#94a3b8; font-size:12px; }
  .future { display:flex; gap:10px; flex-wrap:wrap; }
  .future button { background:#e2e8f0; color:#94a3b8; }
  .sites-list { display:flex; flex-wrap:wrap; gap:10px 18px; margin-bottom:14px; }
  .site-check { display:inline-flex; align-items:center; gap:7px; font-size:14px;
    padding:7px 12px; border:1px solid var(--line); border-radius:8px; cursor:pointer; background:#fff; }
  .site-check:hover { background:var(--bg); }
  .site-check input { cursor:pointer; }
  .modeb-controls { display:flex; align-items:center; gap:14px; }
  .muted { color:var(--muted); font-size:13px; }
  .future .tag { font-size:10px; background:#f1f5f9; color:#94a3b8; border-radius:6px;
    padding:1px 6px; margin-left:6px; }
  /* Chips de mode dans les titres de panneaux */
  .mode-chip { font-size:11px; font-weight:700; padding:2px 8px; border-radius:999px;
    vertical-align:middle; margin-left:6px; letter-spacing:.02em; }
  .mode-a { background:#e0f2fe; color:#075985; border:1px solid #bae6fd; }
  .mode-b { background:#fef3c7; color:#92400e; border:1px solid #fde68a; }
  /* Badge d'origine dans la file d'investigation */
  .origin { font-size:11px; font-weight:600; padding:2px 7px; border-radius:6px; white-space:nowrap; }
  .origin-a { background:#e0f2fe; color:#075985; }
  .origin-b { background:#fef3c7; color:#92400e; }
  .origin-none { color:var(--muted); }
  /* Champ de filtre des sites Mode B */
  .filtre-sites { width:100%; padding:8px 12px; border:1px solid var(--line); border-radius:9px;
    font-size:13px; margin-bottom:10px; box-sizing:border-box; }
  .filtre-sites:focus { outline:2px solid var(--accent); border-color:var(--accent); }
  /* Maquette Mode B-2 (verrouillée, non fonctionnelle) */
  .b2-mock { margin-top:16px; border-top:1px dashed var(--line); padding-top:14px; }
  .b2-head { display:flex; align-items:center; gap:8px; }
  .b2-toggle { padding:9px 14px; border:1px solid var(--line); border-radius:9px; background:#f8fafc;
    color:var(--muted); font-weight:600; cursor:not-allowed; }
  .b2-options { margin-top:12px; padding:14px; border:1px dashed var(--line); border-radius:11px;
    background:#fafbfc; opacity:.7; }
  .b2-hint { font-size:12.5px; color:var(--muted); margin-bottom:12px; line-height:1.5; }
  .b2-field { display:block; font-size:12px; color:var(--muted); margin-bottom:10px; }
  .b2-field input, .b2-field select { display:block; width:100%; margin-top:4px; padding:8px 10px;
    border:1px solid var(--line); border-radius:8px; background:#fff; box-sizing:border-box;
    color:#94a3b8; cursor:not-allowed; }
  .b2-row { display:flex; gap:12px; }
  .b2-row .b2-field { flex:1; }
  .b2-launch { padding:9px 14px; border:none; border-radius:9px; background:#cbd5e1; color:#fff;
    font-weight:600; cursor:not-allowed; }
  /* Bouton et bulle n8n (outil externe) */
  .btn-n8n { padding:9px 14px; border:1px solid var(--accent); border-radius:9px;
    background:#fff; color:var(--accent); font-weight:600; cursor:pointer; }
  .btn-n8n:hover { background:var(--accent); color:#fff; }
  .n8n-bulle { margin-top:12px; padding:12px 14px; border:1px solid var(--line); border-left:3px solid var(--accent);
    border-radius:9px; background:#f8fafc; font-size:12.5px; color:#334155; line-height:1.55; }
  .n8n-bulle code { background:#eef2f7; padding:1px 5px; border-radius:4px; font-size:12px; }
  /* Bannière d'avertissement LPD (transfert cloud) */
  .lpd-warn { margin:10px 0 0; padding:10px 12px; border:1px solid #fecaca;
    border-left:3px solid #dc2626; border-radius:9px; background:#fef2f2;
    color:#991b1b; font-size:12.5px; line-height:1.5; }
  .lpd-config { display:block; margin-top:5px; color:#7f1d1d; opacity:.85; }
  /* Pop-up de consentement LPD */
  .lpd-modal { position:fixed; inset:0; background:rgba(15,23,42,.45);
    display:flex; align-items:center; justify-content:center; z-index:50; }
  .lpd-modal-card { background:#fff; border-radius:14px; max-width:440px; width:90%;
    padding:22px 24px; box-shadow:0 20px 50px rgba(0,0,0,.25); }
  .lpd-modal-title { font-size:16px; font-weight:700; color:#991b1b; margin-bottom:10px; }
  .lpd-modal-card p { font-size:13.5px; color:#334155; line-height:1.55; margin:0 0 10px; }
  .lpd-modal-note { font-size:12px; color:var(--muted); }
  .lpd-modal-note code { background:#eef2f7; padding:1px 5px; border-radius:4px; }
  .lpd-modal-actions { display:flex; justify-content:flex-end; gap:10px; margin-top:16px; }
  .lpd-btn-no { padding:9px 16px; border:1px solid var(--line); border-radius:9px;
    background:#fff; color:var(--muted); font-weight:600; cursor:pointer; }
  .lpd-btn-ok { padding:9px 18px; border:none; border-radius:9px;
    background:var(--accent); color:#fff; font-weight:600; cursor:pointer; }
  .lpd-btn-ok:hover { background:#1e40af; }
</style></head>
<body>
  <div class="top">
    <h1>OFDF OSINT — Console d'analyse</h1>
    <div class="s">v__VERSION__</div>
  </div>
  <div class="wrap">

    <div class="panel">
      <h2>Nouvelle recherche — Surveillance <span class="mode-chip mode-a">Mode A</span></h2>
      <div class="search">
        <select id="platform" title="Plateforme à surveiller"></select>
        <input id="q" type="text" placeholder="Décrivez ce que vous cherchez… ex. « cartouches de cigarettes non taxées »"
               onkeydown="if(event.key==='Enter')lancer()">
        <button id="go" onclick="lancer()">Lancer la recherche</button>
      </div>
      <div class="hint">
        Formulez votre recherche en langage naturel : le système identifie le bien visé,
        écarte le contexte, et génère automatiquement les variantes utiles (synonymes, argot, désignations détournées).
        <span class="ex">Exemples : « ivoire ou défenses d'éléphant » · « pistolets factices type airsoft » · « alcool fort revendu sans licence »</span>
      </div>
      <div class="status" id="status"></div>
    </div>

    <!-- BLOC 2 : Exploration au mieux (Mode B) — remonté avant la file -->
    <div class="panel">
      <h2>Exploration de sites <span class="mode-chip mode-b">Mode B</span></h2>
      <div class="hint">
        Exploration <b>au mieux</b> d'un ou plusieurs sites autorisés : l'agent navigue
        et relève les annonces au mieux. Moins exhaustive et moins fiable que la surveillance
        déterministe (Mode A) — à utiliser ponctuellement, pour des sites sans extracteur dédié.
      </div>
      <div class="modeb">
        <input id="filtreSites" class="filtre-sites" type="text"
               placeholder="Filtrer les sites autorisés…" oninput="filtrerSites()">
        <div id="sitesModeB" class="sites-list">Chargement des sites autorisés…</div>
        <input id="focusB" class="filtre-sites" type="text" style="margin-top:8px"
               placeholder="Focus optionnel — ex. « ivoire, cigarettes » (remonte ces catégories en tête du rapport)">
        <div class="modeb-controls">
          <label>Profondeur :
            <select id="depth">
              <option value="rapide">Rapide</option>
              <option value="standard" selected>Standard</option>
              <option value="approfondie">Approfondie</option>
            </select>
          </label>
          <button id="goExplore" onclick="explorer()">Explorer</button>
        </div>
        <div class="status" id="statusExplore"></div>
      </div>

      <!-- Mode B-2 (recherche autonome de sites) : MAQUETTE, verrouillée -->
      <div class="b2-mock">
        <div class="b2-head">
          <button class="b2-toggle" disabled>🔎 Recherche autonome de sites</button>
          <span class="tag">à activer par l'administrateur</span>
        </div>
        <div class="b2-options" aria-disabled="true">
          <div class="b2-hint">
            Aperçu de l'interface prévue. La recherche autonome de sites via moteur (Mode B-2)
            reste <b>désactivée</b> : son activation relève d'une décision de l'administrateur
            OFDF (responsabilité légale). Le backend refuse toute requête tant qu'elle n'est
            pas autorisée — ce panneau est une maquette non fonctionnelle.
          </div>
          <label class="b2-field">Requête de recherche
            <input type="text" placeholder="ex. « sites vendant de l'ivoire en Suisse romande »" disabled>
          </label>
          <div class="b2-row">
            <label class="b2-field">Sites max
              <input type="number" value="5" min="1" max="20" disabled>
            </label>
            <label class="b2-field">Profondeur par site
              <select disabled>
                <option>Rapide</option><option>Standard</option><option>Approfondie</option>
              </select>
            </label>
          </div>
          <button class="b2-launch" disabled>Lancer la recherche autonome (verrouillé)</button>
        </div>
      </div>
    </div>

    <!-- BLOC 3 : File d'investigation (résultats des deux modes) -->
    <div class="panel">
      <h2>File d'investigation <span id="count" class="count"></span></h2>
      <div class="filters">
        <label>Run :
          <select id="run" onchange="charger()">
            <option value="">Tous (historique)</option>
          </select>
        </label>
        <label>Seuil :
          <select id="seuil" onchange="charger()">
            <option value="0">Tous</option>
            <option value="0.4">≥ 40</option>
            <option value="0.5" selected>≥ 50</option>
            <option value="0.7">≥ 70 (alerte)</option>
          </select>
        </label>
        <label>Catégorie :
          <select id="cat" onchange="charger()">
            <option value="">Toutes</option>
            <option value="tabac">Tabac</option>
            <option value="alcool">Alcool</option>
            <option value="cites">CITES</option>
            <option value="viande">Viande</option>
            <option value="contrefacon">Contrefaçon</option>
            <option value="arme">Arme</option>
            <option value="autre">Autre</option>
          </select>
        </label>
        <label>Trier par :
          <select id="tri" onchange="rendre()">
            <option value="score_desc" selected>Score décroissant</option>
            <option value="score_asc">Score croissant</option>
            <option value="recent">Plus récentes</option>
            <option value="prix_desc">Prix décroissant</option>
          </select>
        </label>
        <button onclick="charger()">Rafraîchir</button>
        <span class="rapport-btns" id="rapportBtns" style="display:none">
          <a id="rapportHtml" class="btn-rapport" target="_blank">📄 Rapport HTML</a>
          <a id="rapportJson" class="btn-rapport btn-rapport--alt" target="_blank">JSON</a>
        </span>
      </div>
      <table>
        <thead><tr><th>#</th><th>Score</th><th>Catégorie</th><th>Annonce</th><th>Prix</th><th>Plateforme</th><th>Origine</th><th>État</th></tr></thead>
        <tbody id="rows"><tr><td colspan="8" class="empty">Chargement…</td></tr></tbody>
      </table>
      <div class="pagination-nav">
        <button id="prevBtn" onclick="precedent()" disabled>← Précédent</button>
        <span id="pageInfo" class="page-info"></span>
        <button id="nextBtn" onclick="suivant()" disabled>Suivant →</button>
      </div>
    </div>

    <!-- BLOC 4 : Actions -->
    <div class="panel">
      <h2>Actions</h2>
      <div class="future">
        <button class="btn-n8n" onclick="ouvrirN8n()">🗓 Planifier la surveillance (n8n)</button>
        <button disabled>↗ Exporter vers Maltego<span class="tag">à venir</span></button>
      </div>
      <div id="n8nBulle" class="n8n-bulle" style="display:none">
        <b>n8n</b> est un outil d'automatisation <b>externe</b>, qui tourne dans son propre
        service (port 5678). Ce bouton l'ouvre dans un nouvel onglet : vous y importez le
        workflow <code>surveillance_mode_a.json</code> (dossier <code>n8n/workflows/</code>),
        qui appelle périodiquement <code>POST /search</code>. L'application reste le cerveau ;
        n8n n'est que le planificateur.
      </div>
    </div>

  </div>
  <div id="scrollBtn" onclick="basculerScroll()" title="Haut / bas de page">↕</div>

  <!-- Pop-up de consentement LPD (s'affiche au lancement si un modèle cloud est utilisé) -->
  <div id="lpdModal" class="lpd-modal" style="display:none">
    <div class="lpd-modal-card">
      <div class="lpd-modal-title">⚠️ Traitement dans le cloud</div>
      <p>Cette opération s'appuie sur un modèle <b>cloud</b>
         (<span id="lpdModalProvider">tiers</span>). Les données traitées sont
         transmises à un fournisseur tiers.</p>
      <p class="lpd-modal-note">Le modèle est configurable par agent (local/cloud)
         dans <code>config.yaml</code>.</p>
      <div class="lpd-modal-actions">
        <button id="lpdModalNo" class="lpd-btn-no">Annuler</button>
        <button id="lpdModalOk" class="lpd-btn-ok">Continuer</button>
      </div>
    </div>
  </div>
<script>
const CATS = {tabac:"Tabac", alcool:"Alcool", cites:"CITES", viande:"Viande",
  contrefacon:"Contrefaçon", arme:"Arme", autre:"Autre", aucune:"Aucune"};
function niveau(s){ return s>=0.7?"eleve":(s>=0.4?"moyen":"normal"); }

async function lancer(){
  const q = document.getElementById('q').value.trim();
  if(!q) return;
  if(!(await gateLpd('a'))) return;   // consentement LPD si Mode A en cloud
  const go = document.getElementById('go'); go.disabled = true;
  const st = document.getElementById('status'); st.className = 'status show';
  st.innerHTML = '<span class="dot pending"></span> Recherche envoyée…';
  try {
    const sel = document.getElementById('platform');
    const opt = sel.options[sel.selectedIndex] || {};
    const payload = {seeds:[q]};
    if(sel.value){ payload.platform = sel.value; payload.base_url = opt.dataset ? opt.dataset.url : undefined; }
    const r = await fetch('/search', {method:'POST', headers:{'Content-Type':'application/json'},
      body: JSON.stringify(payload)});
    const j = await r.json();
    suivre(j.job_id);
  } catch(e){
    st.innerHTML = '<span class="dot error"></span> Erreur d\'envoi.'; go.disabled = false;
  }
}

async function suivre(jobId){
  const st = document.getElementById('status'); const go = document.getElementById('go');
  try {
    const r = await fetch('/search/'+jobId); const j = await r.json();
    if(j.status === 'done'){
      const res = j.result || {};
      if(res.extractor_stale){
        st.innerHTML = '<span class="dot error"></span> Extracteur obsolète — le site a changé. '
          + (res.candidate_id
              ? 'LLM-CODE a proposé un correctif (candidat #'+res.candidate_id+'). '
                + '<a class="report-link" href="/admin" target="_blank">Valider dans l\'admin →</a>'
              : 'Aucun correctif automatique proposé.');
        go.disabled = false; chargerRuns();
        return;
      }
      st.innerHTML = '<span class="dot done"></span> Terminé — '
        + (res.collected||0)+' annonces, '+(res.scored||0)+' scorées (run #'+res.run_id+'). '
        + '<a class="report-link" href="/reports/'+res.run_id+'" target="_blank">Ouvrir le rapport →</a>'
        + ' <a class="report-link" href="/reports/'+res.run_id+'?format=json" target="_blank">JSON</a>';
      go.disabled = false; chargerRuns(); charger();
    } else if(j.status === 'error'){
      st.innerHTML = '<span class="dot error"></span> Échec : '+(j.error||'inconnu'); go.disabled = false;
    } else {
      st.innerHTML = '<span class="dot running"></span> '
        + (j.status==='running'?'Analyse en cours…':'En file…');
      setTimeout(()=>suivre(jobId), 1500);
    }
  } catch(e){ st.innerHTML = '<span class="dot error"></span> Suivi interrompu.'; go.disabled = false; }
}

let currentItems = [];
let page = 0;
const PAGE_SIZE = 50;

async function chargerRuns(){
  try {
    const r = await fetch('/runs'); const j = await r.json();
    const sel = document.getElementById('run');
    const garde = sel.value;
    sel.innerHTML = '<option value="">Tous (historique)</option>' + (j.items||[]).map(function(rn){
      const n = (rn.stats&&rn.stats.scored!=null) ? (' · '+rn.stats.scored+' scorées') : '';
      return '<option value="'+rn.run_id+'">Run #'+rn.run_id+n+'</option>';
    }).join('');
    sel.value = garde;
    majBoutonsRapport();
  } catch(e){ /* le menu reste sur « Tous » */ }
}

function majBoutonsRapport(){
  const run = document.getElementById('run').value;
  const box = document.getElementById('rapportBtns');
  if(run){
    document.getElementById('rapportHtml').href = '/reports/'+run;
    document.getElementById('rapportJson').href = '/reports/'+run+'?format=json';
    box.style.display = 'inline-flex';
  } else { box.style.display = 'none'; }
}

async function charger(resetPage){
  if(resetPage !== false) page = 0;
  majBoutonsRapport();
  const seuil = document.getElementById('seuil').value;
  const run = document.getElementById('run').value;
  const cat = document.getElementById('cat').value;
  const tb = document.getElementById('rows');
  tb.innerHTML = '<tr><td colspan="6" class="empty">Chargement…</td></tr>';
  try {
    const params = ['limit='+PAGE_SIZE, 'offset='+(page*PAGE_SIZE)];
    if(parseFloat(seuil)>0) params.push('min_score='+seuil);
    if(run) params.push('run_id='+run);
    if(cat) params.push('category='+cat);
    const r = await fetch('/listings?'+params.join('&')); const j = await r.json();
    currentItems = j.items || [];
    rendre();
    majPagination();
  } catch(e){ tb.innerHTML = '<tr><td colspan="6" class="empty">Erreur de chargement.</td></tr>'; }
}

function majPagination(){
  document.getElementById('prevBtn').disabled = (page === 0);
  document.getElementById('nextBtn').disabled = (currentItems.length < PAGE_SIZE);
  document.getElementById('pageInfo').textContent = 'Page ' + (page + 1);
}
function precedent(){ if(page>0){ page--; charger(false); } }
function suivant(){ if(currentItems.length === PAGE_SIZE){ page++; charger(false); } }

function rendre(){
  const tb = document.getElementById('rows');
  const cnt = document.getElementById('count');
  const tri = document.getElementById('tri').value;
  const items = currentItems.slice();          // tri local à la page affichée
  const sc = it => parseFloat(it.suspicion_score)||0;
  const px = it => parseFloat(it.price_amount)||0;
  if(tri==='score_desc') items.sort((a,b)=>sc(b)-sc(a));
  else if(tri==='score_asc') items.sort((a,b)=>sc(a)-sc(b));
  else if(tri==='prix_desc') items.sort((a,b)=>px(b)-px(a));
  else if(tri==='recent') items.sort((a,b)=>(b.last_seen_at||'').localeCompare(a.last_seen_at||''));

  cnt.textContent = items.length ? ('— '+items.length+' sur cette page') : '';
  if(!items.length){ tb.innerHTML = '<tr><td colspan="8" class="empty">Aucune annonce.</td></tr>'; return; }
  tb.innerHTML = items.map(function(it){
    const s = sc(it); const pts = Math.round(s*100);
    const prix = it.price_amount!=null ? (escapeHtml(String(it.price_amount))+' '+escapeHtml(it.price_currency||'')) : '—';
    const meta = [it.location, it.seller_label].filter(Boolean).map(escapeHtml).join(' · ');
    const sub = meta ? '<div class="sub-row">'+meta+'</div>' : '';
    return '<tr class="row" onclick="basculerDetail(this,'+it.id+')">'
      + '<td class="id-cell">#'+it.id+'</td>'
      + '<td class="score '+niveau(s)+'">'+pts+'</td>'
      + '<td><span class="cat">'+(CATS[it.category]||it.category||'—')+'</span></td>'
      + '<td><div class="titre-main">'+(it.title?escapeHtml(it.title):'(sans titre)')+'</div>'+sub+'</td>'
      + '<td class="prix">'+prix+'</td>'
      + '<td>'+(it.platform||'')+'</td>'
      + '<td>'+origine(it.run_mode)+'</td>'
      + '<td class="etat-cell">'+pastilleEtat(it.review_decision)+'</td></tr>';
  }).join('');
}

async function basculerDetail(tr, id){
  const next = tr.nextElementSibling;
  if(next && next.classList.contains('detail-row')){ next.remove(); return; }
  document.querySelectorAll('.detail-row').forEach(e=>e.remove());
  const dr = document.createElement('tr'); dr.className = 'detail-row';
  dr.innerHTML = '<td colspan="8"><div class="detail-inline">Chargement…</div></td>';
  tr.after(dr);
  try {
    const r = await fetch('/listings/'+id); const j = await r.json();
    const l = j.listing||{}; const s = j.score||{}; const fb = j.feedback||null;
    const meta = [l.seller_label, (l.structured&&l.structured.location)].filter(Boolean).map(escapeHtml).join(' · ');
    dr.querySelector('.detail-inline').innerHTML =
        '<div class="lbl">Annonce #'+id+' — justification du score</div>'
      + (s.rationale ? '<p>'+escapeHtml(s.rationale)+'</p>' : '<p>Pas de justification enregistrée.</p>')
      + (meta ? '<div class="sub-row">'+meta+'</div>' : '')
      + (l.url ? '<a class="report-link" href="'+l.url+'" target="_blank">Voir l\'annonce →</a>' : '')
      + blocValidation(id, fb);
  } catch(e){ dr.querySelector('.detail-inline').innerHTML = 'Erreur de chargement du détail.'; }
}

const DECISIONS = {confirme:'Confirmé', rejete:'Écarté', incertain:'À vérifier'};

function pastilleEtat(decision){
  const d = decision || 'none';
  const titre = DECISIONS[decision] || 'Non examiné';
  return '<span class="pastille-etat etat-'+d+'" title="'+titre+'"></span>';
}

function origine(mode){
  // Mode A = surveillance déterministe ; Mode B = exploration au mieux.
  if(mode === 'A') return '<span class="origin origin-a" title="Surveillance déterministe (Mode A)">A · Surveillance</span>';
  if(mode === 'B') return '<span class="origin origin-b" title="Exploration au mieux (Mode B)">B · Exploration</span>';
  return '<span class="origin origin-none" title="Origine inconnue">—</span>';
}

function blocValidation(id, fb){
  const statut = fb
    ? '<span class="review-status review-'+fb.decision+'">'+DECISIONS[fb.decision]
        + (fb.investigator_ref ? ' · '+escapeHtml(fb.investigator_ref) : '')+'</span>'
    : '<span class="review-status review-none">Non examiné</span>';
  return '<div class="review">'
    + '<div class="lbl">Validation enquêteur</div>'
    + '<div class="review-row">' + statut
    + '<span class="review-btns">'
    + '<button class="rv rv-ok" onclick="valider('+id+',\'confirme\')">✓ Confirmer</button>'
    + '<button class="rv rv-no" onclick="valider('+id+',\'rejete\')">✕ Écarter</button>'
    + '<button class="rv rv-maybe" onclick="valider('+id+',\'incertain\')">? À vérifier</button>'
    + '</span></div></div>';
}

async function valider(id, decision){
  try {
    const r = await fetch('/listings/'+id+'/review', {method:'POST',
      headers:{'Content-Type':'application/json'}, body: JSON.stringify({decision:decision})});
    if(!r.ok) throw 0;
    const badge = document.querySelector('.detail-row .review-status');
    if(badge){ badge.className = 'review-status review-'+decision; badge.textContent = DECISIONS[decision]+' · à l\'instant'; }
    // met aussi à jour la pastille de la ligne parente (visible sans ouvrir le détail)
    const dr = document.querySelector('.detail-row');
    if(dr && dr.previousElementSibling){
      const cell = dr.previousElementSibling.querySelector('.etat-cell');
      if(cell) cell.innerHTML = pastilleEtat(decision);
    }
  } catch(e){ alert('Échec de l\'enregistrement de la décision.'); }
}

function basculerScroll(){
  const enBas = (window.innerHeight + window.scrollY) >= (document.body.scrollHeight - 40);
  window.scrollTo({top: enBas ? 0 : document.body.scrollHeight, behavior: 'smooth'});
}

function escapeHtml(t){ const e=document.createElement('div'); e.textContent=t; return e.innerHTML; }

// --- Mode B : exploration ---------------------------------------------------
async function chargerSitesModeB(){
  const box = document.getElementById('sitesModeB');
  try {
    const r = await fetch('/mode-b/sites'); const j = await r.json();
    const sites = j.sites || [];
    if(!sites.length){ box.innerHTML = '<span class="muted">Aucun site autorisé configuré.</span>'; return; }
    box.innerHTML = sites.map(function(s){
      const lbl = escapeHtml(s.label);
      return '<label class="site-check"><input type="checkbox" value="'+lbl+'"> '+lbl+'</label>';
    }).join('');
  } catch(e){ box.innerHTML = '<span class="muted">Impossible de charger les sites autorisés.</span>'; }
}

async function explorer(){
  const coches = Array.from(document.querySelectorAll('#sitesModeB input:checked')).map(c=>c.value);
  const st = document.getElementById('statusExplore');
  if(!coches.length){ st.className='status show'; st.innerHTML='<span class="dot error"></span> Sélectionnez au moins un site.'; return; }
  if(!(await gateLpd('b'))) return;   // consentement LPD si Mode B en cloud
  const depth = document.getElementById('depth').value;
  const focus = (document.getElementById('focusB').value||'').trim();
  const go = document.getElementById('goExplore'); go.disabled = true;
  st.className = 'status show';
  st.innerHTML = '<span class="dot pending"></span> Exploration envoyée…';
  try {
    const r = await fetch('/explore', {method:'POST', headers:{'Content-Type':'application/json'},
      body: JSON.stringify({sites:coches, depth:depth, focus:focus})});
    if(!r.ok){ const e = await r.json(); throw new Error(e.detail||'refus'); }
    const j = await r.json();
    suivreExplore(j.job_id);
  } catch(e){
    st.innerHTML = '<span class="dot error"></span> '+escapeHtml(e.message||'Erreur d\'envoi.'); go.disabled = false;
  }
}

async function suivreExplore(jobId){
  const st = document.getElementById('statusExplore'); const go = document.getElementById('goExplore');
  try {
    const r = await fetch('/search/'+jobId); const j = await r.json();
    if(j.status === 'done'){
      const res = j.result || {};
      st.innerHTML = '<span class="dot done"></span> Exploration terminée — '
        + (res.collected||0)+' annonces, '+(res.scored||0)+' scorées (run #'+res.run_id+'). '
        + '<a class="report-link" href="/reports/'+res.run_id+'" target="_blank">Ouvrir le rapport →</a>';
      go.disabled = false; chargerRuns(); charger();
    } else if(j.status === 'error'){
      st.innerHTML = '<span class="dot error"></span> Échec : '+(j.error||'inconnu'); go.disabled = false;
    } else {
      st.innerHTML = '<span class="dot running"></span> '
        + (j.status==='running'?'Exploration en cours…':'En file…');
      setTimeout(()=>suivreExplore(jobId), 1500);
    }
  } catch(e){ st.innerHTML = '<span class="dot error"></span> Erreur de suivi.'; go.disabled = false; }
}

function filtrerSites(){
  // Filtre les cases à cocher des sites Mode B (scale si beaucoup de sites).
  const q = (document.getElementById('filtreSites').value||'').toLowerCase();
  document.querySelectorAll('#sitesModeB .site-check').forEach(function(el){
    el.style.display = el.textContent.toLowerCase().includes(q) ? '' : 'none';
  });
}

let LPD_STATUS = { mode_a:{cloud:false}, mode_b:{cloud:false} };
async function chargerLpdStatus(){
  try { const r = await fetch('/lpd/status'); LPD_STATUS = await r.json(); } catch(e){}
}

async function chargerPlatforms(){
  // Peuple le sélecteur Mode A. Les plateformes sans extracteur déterministe
  // sont grisées (à construire par l'OFDF) ; fake_market est sélectionné par défaut.
  const sel = document.getElementById('platform');
  if(!sel) return;
  try {
    const r = await fetch('/platforms'); const j = await r.json();
    sel.innerHTML = (j.items||[]).map(function(p){
      const dis = p.extractor_available ? '' : ' disabled';
      const tag = p.extractor_available ? '' : ' (extracteur à construire)';
      const selAttr = p.name === 'fake_market' ? ' selected' : '';
      return '<option value="'+escapeHtml(p.name)+'" data-url="'+escapeHtml(p.base_url)+'"'
        + dis + selAttr + '>'+escapeHtml(p.name)+tag+'</option>';
    }).join('');
  } catch(e){}
}

function gateLpd(kind){
  // kind : 'a' (surveillance) | 'b' (exploration). Renvoie une promesse booléenne.
  // Si le mode concerné est LOCAL -> pas de pop-up, on continue directement.
  const info = kind === 'b' ? LPD_STATUS.mode_b : LPD_STATUS.mode_a;
  if(!info || !info.cloud) return Promise.resolve(true);
  return new Promise(function(resolve){
    const ov = document.getElementById('lpdModal');
    document.getElementById('lpdModalProvider').textContent = info.provider || 'tiers';
    ov.style.display = 'flex';
    const ok = document.getElementById('lpdModalOk');
    const no = document.getElementById('lpdModalNo');
    function fermer(val){ ov.style.display='none'; ok.onclick=null; no.onclick=null; resolve(val); }
    ok.onclick = function(){ fermer(true); };
    no.onclick = function(){ fermer(false); };
  });
}

function ouvrirN8n(){
  // n8n est un outil EXTERNE (service séparé, port 5678). On l'ouvre dans un
  // nouvel onglet ; l'utilisateur y importe le workflow surveillance_mode_a.json.
  document.getElementById('n8nBulle').style.display = 'block';
  const url = window.location.protocol + '//' + window.location.hostname + ':5678';
  window.open(url, '_blank');
}

chargerLpdStatus(); chargerPlatforms(); chargerRuns(); charger(); chargerSitesModeB();
</script>
</body></html>"""


def render_index() -> str:
    """Renvoie la page HTML de la console (autonome)."""
    from osint import __version__
    return INDEX_HTML.replace("__VERSION__", __version__)