"""Console d'administration (page web unique, vanilla), organisée en blocs.

Blocs actuels :
  1. Validation des extracteurs (candidats LLM-CODE + historique des décisions)
  2. Plateformes & extracteurs (état de couverture)
  3. Journal d'audit (chaîne de traçabilité, centralisé)
  4. Export des cas validés (téléchargement JSON ; pas de transmission externe)
  5. Maintenance (réinitialisation des données de démonstration)

Structure pensée pour accueillir d'autres blocs (allowlist Mode B, verrou B-2,
vérification du journal scellé, ré-ingestion des règles) sans refonte.
"""

from __future__ import annotations

_ADMIN_HTML = r"""<!doctype html>
<html lang="fr"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>OFDF OSINT — Administration</title>
<style>
  :root { --ink:#0f172a; --muted:#64748b; --line:#e2e8f0; --card:#fff;
    --accent:#1d4ed8; --ok:#15803d; --bad:#b91c1c; --bg:#f1f5f9; }
  * { box-sizing:border-box; }
  body { margin:0; font:14px/1.5 -apple-system,Segoe UI,Roboto,sans-serif;
    color:var(--ink); background:var(--bg); }
  .top { background:#0f172a; color:#fff; padding:16px 24px;
    display:flex; align-items:center; justify-content:space-between; }
  .top h1 { margin:0; font-size:18px; }
  .top .ver { color:#94a3b8; font-size:13px; font-variant-numeric:tabular-nums; }
  .wrap { max-width:960px; margin:22px auto; padding:0 18px; }
  .card { background:var(--card); border:1px solid var(--line); border-radius:12px;
    padding:18px 20px; margin-bottom:16px; }
  .bloc { margin-bottom:30px; }
  .bloc-titre { font-size:13px; text-transform:uppercase; letter-spacing:.05em;
    color:var(--muted); margin:0 0 12px; font-weight:700; }
  .login { display:flex; gap:10px; align-items:center; flex-wrap:wrap; }
  input[type=password] { padding:9px 12px; border:1px solid var(--line);
    border-radius:9px; font-size:14px; min-width:220px; }
  button { padding:9px 16px; border:none; border-radius:9px; font-weight:600;
    cursor:pointer; font-size:14px; }
  .btn-primary { background:var(--accent); color:#fff; }
  .btn-primary:hover { background:#1e40af; }
  .btn-ok { background:var(--ok); color:#fff; }
  .btn-bad { background:#fff; color:var(--bad); border:1px solid #fecaca; }
  .btn-danger { background:var(--bad); color:#fff; }
  .muted { color:var(--muted); }
  .cand-head { display:flex; justify-content:space-between; align-items:baseline; }
  .cand-head b { font-size:15px; }
  .pill { font-size:11px; text-transform:uppercase; letter-spacing:.04em;
    background:#eff6ff; color:#1e40af; border:1px solid #bfdbfe;
    border-radius:999px; padding:2px 9px; }
  .sel-grid { display:grid; grid-template-columns:1fr 1fr; gap:12px; margin:12px 0; }
  .sel-box { border:1px solid var(--line); border-radius:9px; padding:10px 12px;
    background:#f8fafc; font-family:ui-monospace,Menlo,monospace; font-size:12.5px; }
  .sel-box h4 { margin:0 0 6px; font-family:inherit; font-size:11px;
    text-transform:uppercase; letter-spacing:.04em; color:var(--muted); }
  .sel-row { display:flex; justify-content:space-between; gap:8px; padding:2px 0; }
  .sel-row .k { color:var(--muted); }
  .changed { background:#fef9c3; border-radius:4px; padding:0 3px; }
  .actions { display:flex; gap:10px; margin-top:12px; }
  details { margin-top:10px; }
  details summary { cursor:pointer; color:var(--muted); font-size:13px; }
  pre { background:#0f172a; color:#e2e8f0; padding:12px; border-radius:8px;
    overflow:auto; font-size:12px; }
  .status { margin-top:10px; font-size:13px; }
  .empty { color:var(--muted); text-align:center; padding:22px; }
  .valid-ok { color:var(--ok); } .valid-bad { color:var(--bad); }
  table { width:100%; border-collapse:collapse; font-size:13px; }
  th,td { text-align:left; padding:8px 10px; border-bottom:1px solid var(--line);
    vertical-align:top; }
  th { color:var(--muted); font-size:11px; text-transform:uppercase; letter-spacing:.04em; }
  td code { font-size:12px; color:var(--muted); }
  .tag-ok { color:var(--ok); font-weight:600; } .tag-no { color:var(--muted); }
  .note { color:var(--muted); font-size:12.5px; margin-top:10px; }
  .subhead { font-size:12px; color:var(--muted); margin:18px 0 8px; font-weight:600; }
</style></head>
<body>
  <div class="top">
    <h1>OFDF OSINT — Administration</h1>
    <div class="ver">v__VERSION__</div>
  </div>
  <div class="wrap">
    <div class="card">
      <div class="login" id="loginRow">
        <input id="pwd" type="password" placeholder="Mot de passe administrateur"
               onkeydown="if(event.key==='Enter')charger()">
        <button class="btn-primary" onclick="charger()">Se connecter</button>
        <span id="loginStatus" class="muted"></span>
      </div>
      <div class="login" id="connectedRow" style="display:none">
        <span class="muted" style="font-weight:600">Connecté ✓</span>
        <span id="loginStatus2" class="muted" style="flex:1"></span>
        <button class="btn-primary" onclick="charger()">Rafraîchir</button>
        <button class="btn-bad" onclick="quitter()">Quitter la console d'admin</button>
      </div>
    </div>

    <div id="blocs" style="display:none">

      <section class="bloc">
        <h2 class="bloc-titre">1 · Validation des extracteurs (LLM-CODE)</h2>
        <div id="liste"></div>
        <div class="subhead" id="histoTitre" style="display:none">Historique des décisions</div>
        <div id="histoire"></div>
      </section>

      <section class="bloc">
        <h2 class="bloc-titre">2 · Plateformes &amp; extracteurs</h2>
        <div class="card" id="extracteurs"></div>
      </section>

      <section class="bloc">
        <h2 class="bloc-titre">3 · Journal d'audit (chaîne de traçabilité)</h2>
        <div class="card" id="audit"></div>
      </section>

      <section class="bloc">
        <h2 class="bloc-titre">4 · Export des cas validés</h2>
        <div class="card">
          <button class="btn-primary" onclick="exporter()">Télécharger les cas confirmés (JSON)</button>
          <span id="exportStatus" class="muted" style="margin-left:10px"></span>
          <div class="note">Produit un fichier local des annonces confirmées en format JSON
            (informations de l'annonce, score, empreinte, feedback).</div>
        </div>
      </section>

      <section class="bloc">
        <h2 class="bloc-titre">5 · Réinitialisation</h2>
        <div class="card">
          <button class="btn-danger" onclick="reinitialiser()">Réinitialiser les données</button>
          <label style="margin-left:12px;font-size:13px;cursor:pointer">
            <input type="checkbox" id="resetExtractors"> remettre aussi les extracteurs à la configuration initiale
          </label>
          <span id="resetStatus" class="muted" style="margin-left:10px"></span>
          <div class="note">Efface les <b>données</b> (runs, annonces, scores, feedback, journal
            d'audit) pour revenir à une base vierge. La <b>configuration</b> (plateformes,
            extracteurs) est conservée — sauf si la case ci-dessus est cochée, qui remet alors les
            extracteurs à leur état d'origine (retour usine). Irréversible : confirmation demandée.</div>
        </div>
      </section>

      <section class="bloc">
        <h2 class="bloc-titre">6 · Intégrité des journaux scellés</h2>
        <div class="card">
          <button class="btn-primary" onclick="verifier()">Vérifier l'intégrité</button>
          <span id="verifStatus" class="muted" style="margin-left:10px"></span>
          <div id="verifResult" style="margin-top:12px"></div>
          <div class="note">Rejoue le chaînage de hachage de la chaîne d'audit (base) et des
            journaux d'exploration Mode B (fichiers). Toute altération rompt la chaîne et est
            localisée à l'entrée fautive.</div>
        </div>
      </section>

      <section class="bloc">
        <h2 class="bloc-titre">7 · Réparation de code (expérimental — verrou OFDF)</h2>
        <div class="card">
          <div id="crStatus" class="muted">Chargement…</div>
          <div id="crGenerate" style="display:none;margin-top:12px">
            <div style="display:flex;gap:8px;flex-wrap:wrap;align-items:center">
              <input id="crPlatform" type="text" placeholder="plateforme (ex. fake_market)"
                style="padding:9px 12px;border:1px solid var(--line);border-radius:9px;min-width:220px">
              <button class="btn-primary" onclick="crGenerer()">Générer une proposition</button>
              <span id="crGenStatus" class="muted"></span>
            </div>
            <textarea id="crHtml" placeholder="Coller le nouveau HTML de la page qui casse l'extraction…"
              style="width:100%;margin-top:8px;min-height:90px;padding:10px;border:1px solid var(--line);border-radius:9px;font-family:ui-monospace,monospace;font-size:12px"></textarea>
          </div>
          <div id="crProposals" style="margin-top:14px"></div>
          <div class="note">Verrou par défaut (décision OFDF). Le code proposé n'est <b>jamais exécuté</b>
            par l'application : il est déposé dans un dossier, relu, puis installé <b>manuellement</b> par un
            développeur. Les instances tournant sur VM jetables, le risque d'une proposition erronée reste borné.</div>
        </div>
      </section>

    </div>
  </div>
<script>
function pwd(){ return document.getElementById('pwd').value; }
function H(){ return { 'X-Admin-Password': pwd() }; }
function esc(s){ const d=document.createElement('div'); d.textContent=(s==null?'':String(s)); return d.innerHTML; }
function dt(s){ return (s||'').substring(0,19).replace('T',' '); }

async function charger(){
  const st = document.getElementById('loginStatus');
  st.textContent = 'Connexion…';
  try {
    const r = await fetch('/admin/candidates', { headers: H() });
    if(r.status === 401){ st.textContent = 'Mot de passe invalide.'; return; }
    if(r.status === 503){ st.textContent = 'Espace admin non configuré (ADMIN_PASSWORD).'; return; }
    const j = await r.json();
    document.getElementById('loginRow').style.display = 'none';
    document.getElementById('connectedRow').style.display = 'flex';
    document.getElementById('blocs').style.display = 'block';
    document.getElementById('loginStatus2').textContent = j.count + ' candidat(s) en attente.';
    rendre(j.items || []);
    chargerHistorique(); chargerExtracteurs(); chargerAudit(); chargerCodeRepair();
  } catch(e){ st.textContent = 'Erreur de connexion.'; }
}

function quitter(){
  document.getElementById('pwd').value = '';
  document.getElementById('connectedRow').style.display = 'none';
  document.getElementById('loginRow').style.display = 'flex';
  document.getElementById('blocs').style.display = 'none';
  document.getElementById('loginStatus').textContent = '';
  document.getElementById('liste').innerHTML = '';
  document.getElementById('histoire').innerHTML = '';
}

/* --- Bloc 1 : candidats + historique -------------------------------------- */
function selBox(titre, sel, ref){
  sel = sel || {}; ref = ref || {};
  const keys = Array.from(new Set(Object.keys(sel).concat(Object.keys(ref))));
  const rows = keys.map(function(k){
    const v = sel[k]; const changed = ref[k] !== undefined && ref[k] !== v;
    return "<div class='sel-row'><span class='k'>"+esc(k)+"</span><span class='"
      + (changed?'changed':'') + "'>"+esc(v)+"</span></div>";
  }).join('');
  return "<div class='sel-box'><h4>"+esc(titre)+"</h4>"+rows+"</div>";
}
function carte(c){
  const valid = c.validation || {};
  const validOk = valid.title && valid.price && valid.description;
  const validHtml = "<div class='status'>Validation du candidat : "
    + (validOk ? "<span class='valid-ok'>✓ ré-extraction des champs requis réussie</span>"
               : "<span class='valid-bad'>⚠ champs requis toujours manquants</span>") + "</div>";
  return "<div class='card' id='cand-"+c.id+"'>"
    + "<div class='cand-head'><b>Candidat #"+c.id+" — "+esc(c.platform)+"</b>"
    +   "<span class='pill'>"+esc(c.source)+"</span></div>"
    + "<div class='muted' style='font-size:12px'>proposé le "+esc(dt(c.created_at))+"</div>"
    + "<div class='sel-grid'>"
    +   selBox('Sélecteurs actifs (cassés)', c.active_selectors, c.selectors)
    +   selBox('Sélecteurs proposés', c.selectors, c.active_selectors)
    + "</div>" + validHtml
    + "<details><summary>Historique de réparation</summary><pre>"
    +   esc(JSON.stringify(c.repair_history, null, 2)) + "</pre></details>"
    + "<div class='actions'>"
    +   "<button class='btn-ok' onclick=\"decider("+c.id+",'approve')\">Approuver</button>"
    +   "<button class='btn-bad' onclick=\"decider("+c.id+",'reject')\">Rejeter</button>"
    + "</div></div>";
}
function rendre(items){
  const box = document.getElementById('liste');
  if(!items.length){ box.innerHTML = "<div class='card empty'>Aucun candidat en attente.</div>"; return; }
  box.innerHTML = items.map(carte).join('');
}
async function decider(id, action){
  try {
    const r = await fetch('/admin/candidates/'+id+'/'+action, { method:'POST', headers: H() });
    if(!r.ok){ alert('Échec : '+(await r.json()).detail); return; }
    const el = document.getElementById('cand-'+id);
    if(el){ el.style.opacity=.5; el.querySelector('.actions').innerHTML =
      "<span class='muted'>"+(action==='approve'?'Approuvé — extracteur actif mis à jour.':'Rejeté.')+"</span>"; }
    chargerHistorique(); chargerExtracteurs();
  } catch(e){ alert('Erreur réseau.'); }
}
const _STATUTS = {
  active:{txt:'Approuvé — actif',cls:'valid-ok'},
  superseded:{txt:'Remplacé',cls:'muted'},
  rejected:{txt:'Rejeté',cls:'valid-bad'}
};
async function chargerHistorique(){
  try {
    const r = await fetch('/admin/history', { headers: H() }); if(!r.ok) return;
    const j = await r.json(); rendreHistorique(j.items || []);
  } catch(e){}
}
function rendreHistorique(items){
  const titre = document.getElementById('histoTitre'); const box = document.getElementById('histoire');
  if(!items.length){ titre.style.display='none'; box.innerHTML=''; return; }
  titre.style.display='block';
  box.innerHTML = items.map(function(h){
    const s = _STATUTS[h.status] || {txt:h.status,cls:'muted'};
    return "<div class='card' style='padding:11px 16px;display:flex;justify-content:space-between;align-items:center;gap:12px'>"
      + "<div><b>#"+h.id+" — "+esc(h.platform)+"</b> <span class='pill'>"+esc(h.source)+"</span><br>"
      + "<span class='muted' style='font-size:12px'>"+esc(dt(h.decided_at))
      + (h.decided_by?" · par "+esc(h.decided_by):"")+"</span></div>"
      + "<span class='"+s.cls+"' style='font-weight:600'>"+s.txt+"</span></div>";
  }).join('');
}

/* --- Bloc 2 : plateformes & extracteurs ----------------------------------- */
async function chargerExtracteurs(){
  try {
    const r = await fetch('/admin/extractors', { headers: H() }); if(!r.ok) return;
    const j = await r.json(); const box = document.getElementById('extracteurs');
    if(!j.items.length){ box.innerHTML = "<div class='empty'>Aucune plateforme.</div>"; return; }
    let h = "<table><tr><th>Plateforme</th><th>URL</th><th>Mode A (extracteur)</th><th>Mode B</th><th>Sélecteurs actifs</th></tr>";
    h += j.items.map(function(p){
      const modeA = p.extractor_available
        ? "<span class='tag-ok'>"+esc(p.kind)+"</span>" : "<span class='tag-no'>—</span>";
      const modeB = p.mode_b ? "<span class='tag-ok'>✓ autorisé</span>" : "<span class='tag-no'>—</span>";
      let sel = "—";
      if(p.active_selectors_present === true) sel = "<span class='tag-ok'>présents</span>";
      else if(p.active_selectors_present === false) sel = "<span class='valid-bad'>absents</span>";
      return "<tr><td><b>"+esc(p.platform)+"</b></td><td><code>"+esc(p.base_url)+"</code></td>"
        + "<td>"+modeA+"</td><td>"+modeB+"</td><td>"+sel+"</td></tr>";
    }).join('');
    box.innerHTML = h + "</table>";
  } catch(e){}
}

/* --- Bloc 3 : journal d'audit --------------------------------------------- */
async function chargerAudit(){
  try {
    const r = await fetch('/admin/audit?limit=100', { headers: H() }); if(!r.ok) return;
    const j = await r.json(); const box = document.getElementById('audit');
    if(!j.items.length){ box.innerHTML = "<div class='empty'>Journal vide.</div>"; return; }
    let h = "<table><tr><th>Date (UTC)</th><th>Acteur</th><th>Action</th><th>Run</th><th>Annonce</th><th>Détail</th></tr>";
    h += j.items.map(function(a){
      let det = a.detail ? JSON.stringify(a.detail) : "";
      if(det.length > 90) det = det.substring(0,90) + "…";
      return "<tr><td><code>"+esc(dt(a.created_at))+"</code></td><td>"+esc(a.actor)+"</td>"
        + "<td>"+esc(a.action)+"</td><td>"+esc(a.run_id!=null?a.run_id:"—")+"</td>"
        + "<td>"+esc(a.listing_id!=null?a.listing_id:"—")+"</td><td><code>"+esc(det)+"</code></td></tr>";
    }).join('');
    box.innerHTML = h + "</table>";
  } catch(e){}
}

/* --- Bloc 4 : export ------------------------------------------------------ */
async function exporter(){
  const st = document.getElementById('exportStatus'); st.textContent = 'Génération…';
  try {
    const r = await fetch('/admin/export', { headers: H() });
    if(!r.ok){ st.textContent = 'Échec.'; return; }
    const blob = await r.blob();
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a'); a.href = url; a.download = 'cas_confirmes.json';
    document.body.appendChild(a); a.click(); a.remove(); URL.revokeObjectURL(url);
    st.textContent = 'Téléchargé.';
  } catch(e){ st.textContent = 'Erreur.'; }
}

/* --- Bloc 5 : réinitialisation ------------------------------------------- */
async function reinitialiser(){
  const aussiExtr = document.getElementById('resetExtractors').checked;
  const msg = "Cette action efface les données (runs, annonces, scores, feedback, audit)"
    + (aussiExtr ? " ET remet les extracteurs à leur configuration initiale." : ".")
    + "\n\nTapez RESET pour confirmer :";
  const saisie = prompt(msg);
  if(saisie !== 'RESET'){ return; }
  const st = document.getElementById('resetStatus'); st.textContent = 'Réinitialisation…';
  try {
    const r = await fetch('/admin/reset', { method:'POST',
      headers: Object.assign({'Content-Type':'application/json'}, H()),
      body: JSON.stringify({confirm:'RESET', reset_extractors: aussiExtr}) });
    if(!r.ok){ st.textContent = 'Échec : '+(await r.json()).detail; return; }
    st.textContent = 'Données réinitialisées.';
    chargerAudit(); chargerHistorique(); chargerExtracteurs(); charger();
  } catch(e){ st.textContent = 'Erreur réseau.'; }
}
/* --- Bloc 6 : intégrité des journaux scellés ------------------------------ */
async function verifier(){
  const st = document.getElementById('verifStatus');
  const box = document.getElementById('verifResult');
  st.textContent = 'Vérification…'; box.innerHTML = '';
  try {
    const r = await fetch('/admin/verify', { headers: H() });
    if(!r.ok){ st.textContent = 'Échec.'; return; }
    const j = await r.json();
    st.textContent = '';
    function ligne(nom, ok, bad, extra){
      const v = ok ? "<span class='valid-ok'>✓ chaîne intacte</span>"
                   : "<span class='valid-bad'>⚠ rupture à l'entrée "+(bad!=null?bad:'?')+"</span>";
      return "<div class='sel-row' style='padding:5px 0'><span class='k'>"+esc(nom)
        + (extra?" <span class='muted'>("+esc(extra)+")</span>":"")+"</span>"+v+"</div>";
    }
    let h = ligne("Chaîne d'audit (base)", j.audit.ok, j.audit.first_bad);
    if(!j.browse || !j.browse.length){
      h += "<div class='sel-row' style='padding:5px 0'><span class='k'>Journaux Mode B</span><span class='muted'>aucun fichier</span></div>";
    } else {
      j.browse.forEach(function(b){
        h += b.error
          ? "<div class='sel-row' style='padding:5px 0'><span class='k'>"+esc(b.file)+"</span><span class='valid-bad'>illisible</span></div>"
          : ligne(b.file, b.ok, b.first_bad, b.count+" entrées");
      });
    }
    box.innerHTML = "<div class='card' style='background:#f8fafc;margin:0'>"+h+"</div>";
  } catch(e){ st.textContent = 'Erreur réseau.'; }
}
/* --- Bloc 7 : réparation de code (verrou OFDF) ---------------------------- */
async function chargerCodeRepair(){
  try {
    const r = await fetch('/admin/code-repair/status', { headers: H() }); if(!r.ok) return;
    const s = await r.json();
    const st = document.getElementById('crStatus');
    const gen = document.getElementById('crGenerate');
    if(s.enabled){
      st.innerHTML = "<span class='valid-ok'>✓ Activé</span> — dépôt : <code>"+esc(s.proposals_dir)+"</code>";
      gen.style.display = 'block';
    } else {
      st.innerHTML = "<span class='valid-bad'>Verrouillé</span> — activer via "
        + "<code>code_repair.enabled: true</code> dans config.yaml (décision OFDF).";
      gen.style.display = 'none';
    }
    crChargerPropositions();
  } catch(e){}
}
async function crChargerPropositions(){
  try {
    const r = await fetch('/admin/code-repair/proposals', { headers: H() }); if(!r.ok) return;
    const j = await r.json(); const box = document.getElementById('crProposals');
    if(!j.items.length){ box.innerHTML = "<div class='muted' style='font-size:13px'>Aucune proposition déposée.</div>"; return; }
    box.innerHTML = j.items.map(function(p){
      return "<div class='card' style='margin:8px 0'>"
        + "<div style='display:flex;justify-content:space-between;align-items:center'>"
        +   "<b>"+esc(p.filename)+"</b>"
        +   "<button class='btn-bad' onclick=\"crJeter('"+esc(p.filename)+"')\">Jeter</button></div>"
        + "<details style='margin-top:6px'><summary>Voir le code proposé</summary><pre>"
        +   esc(p.content)+"</pre></details>"
        + "<div class='note'>Installation manuelle : relire, copier dans <code>src/osint/collecte/</code>, "
        +   "enregistrer dans <code>EXTRACTORS</code> (pipeline.py), redémarrer.</div></div>";
    }).join('');
  } catch(e){}
}
async function crGenerer(){
  const platform = document.getElementById('crPlatform').value.trim();
  const html = document.getElementById('crHtml').value;
  const st = document.getElementById('crGenStatus');
  if(!platform){ st.textContent = 'Indiquer une plateforme.'; return; }
  st.textContent = 'Génération…';
  try {
    const r = await fetch('/admin/code-repair/generate', { method:'POST',
      headers: Object.assign({'Content-Type':'application/json'}, H()),
      body: JSON.stringify({platform: platform, sample_html: html}) });
    if(!r.ok){ st.textContent = 'Échec : '+(await r.json()).detail; return; }
    const res = await r.json();
    if(res.validated === false){
      st.textContent = 'Proposition générée (vérification désactivée).';
    } else if(res.ok){
      st.innerHTML = "<span class='valid-ok'>Proposition validée</span> (charge + interface) en "+res.iterations+" tentative(s).";
    } else {
      st.innerHTML = "<span class='valid-bad'>Proposition NON validée</span> après "+res.iterations+" tentative(s) — voir le code.";
    }
    crChargerPropositions();
  } catch(e){ st.textContent = 'Erreur réseau.'; }
}
async function crJeter(filename){
  try {
    const r = await fetch('/admin/code-repair/discard', { method:'POST',
      headers: Object.assign({'Content-Type':'application/json'}, H()),
      body: JSON.stringify({filename: filename}) });
    if(!r.ok){ alert('Échec.'); return; }
    crChargerPropositions();
  } catch(e){}
}
</script>
</body></html>"""


def render_admin() -> str:
    from osint import __version__
    return _ADMIN_HTML.replace("__VERSION__", __version__)