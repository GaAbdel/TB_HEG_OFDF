#!/usr/bin/env python3
"""Génère le jeu de données du marché factice.

Dataset à DIFFICULTÉ GRADUÉE :

  - bénignes          annonces légales ordinaires (bruit de fond)
  - explicite         positif où l'illégalité est ÉCRITE ("non taxé", "sans
                      certificat CITES") -> un simple mot-clé suffit (plancher)
  - implicite         positif où l'illégalité est SOUS-ENTENDUE ("ivoire ancien
                      de famille") -> exige compréhension sémantique + RAG
  - piège             annonce LÉGALE qui contient un mot déclencheur ("ivoire
                      végétal", "réplique 1:18") -> teste la précision

Sortie (versionnée dans Git, graine fixe -> reproductible) :
    listings.json          toutes les annonces servies par le faux marché
    dataset_manifest.json  vérité terrain : id -> {suspect, catégorie,
                           difficulté, piège, leurre_catégorie}

Les positifs sont des TEXTES D'ANNONCE plausibles ; aucun ne fournit
d'instruction illicite — ce sont les signaux que le système doit détecter.

Usage :  python generate_dataset.py
"""

from __future__ import annotations

import json
import random
from pathlib import Path

SEED = 42
N_BENIGN = 250
PLATFORMS = ["ricardo", "anibis", "tutti"]
CITIES = ["Genève", "Lausanne", "Zurich", "Berne", "Bâle", "Sion", "Fribourg", "Lugano"]
HERE = Path(__file__).parent

# --- Gabarits d'annonces bénignes (catégorie "aucune") -----------------------
BENIGN = [
    ("Table en chêne massif", "Belle table de salle à manger, très bon état, à venir chercher.", (80, 450)),
    ("Canapé 3 places", "Canapé tissu gris, confortable, quelques traces d'usage.", (120, 600)),
    ("iPhone 12 64 Go", "Smartphone débloqué, batterie 87%, avec chargeur.", (250, 480)),
    ("Casque audio Sony", "Casque sans fil à réduction de bruit, comme neuf.", (90, 220)),
    ("Vélo de course", "Cadre alu, 18 vitesses, révisé récemment.", (200, 900)),
    ("VTT tout suspendu", "Bon état général, freins à disque, taille L.", (300, 1200)),
    ("Veste en cuir", "Veste homme taille M, cuir véritable, peu portée.", (60, 250)),
    ("Baskets de sport", "Pointure 42, portées quelques fois, propres.", (40, 130)),
    ("Tondeuse à gazon", "Tondeuse thermique, fonctionne parfaitement.", (100, 350)),
    ("Barbecue à gaz", "Barbecue 3 brûleurs avec housse, peu utilisé.", (120, 400)),
    ("Guitare acoustique", "Guitare folk avec housse et accordeur.", (80, 300)),
    ("Lot de livres", "Romans et BD, une cinquantaine de titres.", (20, 80)),
    ("Télévision 55 pouces", "TV LED 4K, télécommande et pied inclus.", (200, 650)),
    ("Réfrigérateur", "Frigo combiné, classe A++, encore sous garantie.", (150, 500)),
    ("Poussette bébé", "Poussette pliable avec nacelle, très propre.", (80, 280)),
    ("Bureau d'angle", "Bureau en bois clair, idéal télétravail.", (70, 260)),
    ("Console de jeux", "Console avec deux manettes et trois jeux.", (180, 420)),
    ("Machine à café", "Machine à expresso automatique, détartrée.", (90, 350)),
    ("Set de golf", "Sac avec clubs complets pour débutant.", (150, 500)),
    ("Aspirateur robot", "Robot aspirateur avec station de charge.", (120, 400)),
]
CONDITIONS = ["neuf", "comme neuf", "très bon état", "bon état", "occasion"]

# --- Positifs : explicite (l'illégalité est écrite) --------------------------
POSITIFS_EXPLICITE = {
    "tabac": [
        ("Cartouches de cigarettes (x10) — non taxées",
         "Lot de 10 cartouches, jamais déclarées à la douane, livraison discrète possible."),
        ("Tabac à rouler en gros — import direct",
         "Plusieurs kilos disponibles, prix hors taxes, idéal pour revente."),
    ],
    "alcool": [
        ("Spiritueux forts hors taxes — lot",
         "Bouteilles importées sans déclaration douanière, vente au carton uniquement."),
        ("Eau-de-vie maison très forte",
         "Distillation personnelle, teneur en alcool élevée, vente directe sans étiquette."),
    ],
    "cites": [
        ("Ivoire sculpté ancien — défense d'éléphant",
         "Authentique ivoire, pièce de collection, vendu sans certificat CITES."),
        ("Carapace de tortue marine",
         "Objet décoratif rare issu d'une espèce protégée, vendu en l'état."),
    ],
    "viande": [
        ("Viande de brousse importée",
         "Spécialité importée, viande non contrôlée par les services vétérinaires, congelée."),
        ("Charcuterie de ferme sans contrôle",
         "Production maison, abattage personnel, aucune inspection sanitaire."),
    ],
    "contrefacon": [
        ("Sac de marque — réplique haut de gamme",
         "Copie fidèle d'un grand maroquinier, logo conforme, qualité identique à l'original."),
        ("Montres de luxe répliques 1:1",
         "Clones de modèles connus, mouvement automatique, prix imbattable."),
    ],
    "arme": [
        ("Pistolet de collection — cession sans permis",
         "Arme de poing fonctionnelle, cession de la main à la main, sans paperasse."),
        ("Couteau papillon et matraque télescopique",
         "Objets prohibés vendus en lot, envoi discret."),
    ],
}

# --- Positifs : implicite (l'illégalité est sous-entendue) --------------------
POSITIFS_IMPLICITE = {
    "tabac": [
        ("Cartouches de clopes — lot, arrangement possible",
         "Plusieurs cartouches dispo, paiement cash, je me déplace dans la région."),
        ("Tabac ramené de vacances, trop pour moi",
         "Acheté en grande quantité à l'étranger, je revends mon stock, plusieurs kilos."),
    ],
    "alcool": [
        ("Gnôle maison du grand-père, au litre",
         "Distillée à la ferme, bien forte, bouteilles non étiquetées, je cède le stock."),
        ("Caisse de spiritueux ramenée de voyage",
         "Trop acheté au duty-free, je cède le tout, jamais ouvert, plusieurs litres."),
    ],
    "cites": [
        ("Ivoire ancien sculpté, pièce de famille",
         "Hérité, belle patine, objet de collection rare, à saisir."),
        ("Bracelet en écaille véritable, vintage",
         "Authentique écaille, fait main, pièce ancienne difficile à trouver."),
    ],
    "viande": [
        ("Spécialité ramenée du voyage, congelée",
         "Viande séchée artisanale rapportée d'un long voyage, sous vide, lot."),
        ("Gibier maison, au kilo",
         "Chevreuil et sanglier préparés à la maison, sans étiquette, à récupérer sur place."),
    ],
    "contrefacon": [
        ("Sac inspiré d'un grand créateur, qualité top",
         "Look identique au modèle iconique, finitions soignées, logo présent, prix mini."),
        ("Montre style chrono de luxe, automatique",
         "Ressemble trait pour trait au modèle suisse connu, mouvement auto, introuvable à ce prix."),
    ],
    "arme": [
        ("Objet de défense compact, envoi discret",
         "Petit dispositif dissuasif pratique à transporter, je préfère m'en séparer."),
        ("Couteau à ouverture rapide, lame auto",
         "Mécanisme à cran, la lame sort toute seule, pièce de collection."),
    ],
}

# --- Pièges : annonces LÉGALES contenant un mot déclencheur ------------------
#  (titre, description, catégorie leurrée)
PIEGES = [
    ("Ivoire végétal (tagua) — bijoux artisanaux",
     "Graines de tagua, alternative éthique et légale à l'ivoire animal.", "cites"),
    ("Défense de mammouth fossile",
     "Ivoire de mammouth fossile, espèce éteinte, commerce autorisé, pièce paléontologique.", "cites"),
    ("Réplique Ferrari échelle 1:18",
     "Maquette de collection en métal, à exposer en vitrine.", "contrefacon"),
    ("Épée décorative de film, réplique cosplay",
     "Reproduction non tranchante pour costume, purement décorative.", "arme"),
    ("Cigarette électronique + e-liquides",
     "Kit vape complet, plusieurs arômes, batterie neuve.", "tabac"),
    ("Vin sans alcool bio, festif",
     "Boisson désalcoolisée 0.0%, idéale pour les fêtes.", "alcool"),
    ("Couteau de cuisine japonais Santoku",
     "Lame inox, parfait pour la cuisine, neuf sous blister.", "arme"),
    ("Steak de soja végétal, lot surgelé",
     "Substitut de viande 100% végétal, riche en protéines.", "viande"),
    ("Pistolet à eau XL pour enfants",
     "Jouet d'été grande capacité, plastique, sans danger.", "arme"),
    ("Champagne sans alcool pour célébration",
     "Mousseux désalcoolisé, bulles festives, 0.0%.", "alcool"),
]


def _listing(rng: random.Random, lid: int, title: str, desc: str, lo: int, hi: int) -> dict:
    return {
        "id": lid,
        "platform": rng.choice(PLATFORMS),
        "title": title,
        "description": desc,
        "price": rng.randint(lo, hi),
        "currency": "CHF",
        "seller": f"vendeur{rng.randint(100, 999)}",
        "location": rng.choice(CITIES),
    }


def main() -> None:
    rng = random.Random(SEED)
    listings: list[dict] = []
    labels: dict[str, dict] = {}

    # Bénignes
    for i in range(N_BENIGN):
        base_title, base_desc, (lo, hi) = rng.choice(BENIGN)
        cond = rng.choice(CONDITIONS)
        lid = 1000 + i
        listings.append(_listing(rng, lid, f"{base_title} — {cond}", base_desc, lo, hi))
        labels[str(lid)] = {"suspect": False, "categorie": "aucune",
                            "difficulte": "aucune", "piege": False}

    # Positifs explicite + implicite
    lid = 9000
    for difficulte, source in (("explicite", POSITIFS_EXPLICITE), ("implicite", POSITIFS_IMPLICITE)):
        for categorie, items in source.items():
            for title, desc in items:
                listings.append(_listing(rng, lid, title, desc, 50, 800))
                labels[str(lid)] = {"suspect": True, "categorie": categorie,
                                    "difficulte": difficulte, "piege": False}
                lid += 1

    # Pièges (légaux)
    lid = 8000
    for title, desc, leurre in PIEGES:
        listings.append(_listing(rng, lid, title, desc, 20, 400))
        labels[str(lid)] = {"suspect": False, "categorie": "aucune",
                            "difficulte": "piege", "piege": True, "leurre_categorie": leurre}
        lid += 1

    rng.shuffle(listings)

    # Résumé
    par_diff: dict[str, int] = {}
    par_cat: dict[str, int] = {}
    for v in labels.values():
        par_diff[v["difficulte"]] = par_diff.get(v["difficulte"], 0) + 1
        if v["suspect"]:
            par_cat[v["categorie"]] = par_cat.get(v["categorie"], 0) + 1
    summary = {
        "total": len(listings),
        "benignes": par_diff.get("aucune", 0),
        "suspectes": sum(1 for v in labels.values() if v["suspect"]),
        "pieges": par_diff.get("piege", 0),
        "par_difficulte": par_diff,
        "positifs_par_categorie": par_cat,
    }

    (HERE / "listings.json").write_text(
        json.dumps(listings, ensure_ascii=False, indent=2), encoding="utf-8")
    (HERE / "dataset_manifest.json").write_text(
        json.dumps({"summary": summary, "labels": labels}, ensure_ascii=False, indent=2),
        encoding="utf-8")

    print(f"Généré : {summary['total']} annonces")
    print(f"  par difficulté : {par_diff}")
    print(f"  positifs par catégorie : {par_cat}")


if __name__ == "__main__":
    main()