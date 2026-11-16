import json
import re

INPUT_FILE = "master_tea_catalog.json"
OUTPUT_FILE = "master_tea_catalog_clean.json"

# Dictionnaire de correspondance élargi pour les origines
ORIGIN_MAPPING = {
    "Japon": ["Japon", "Sencha", "Matcha", "Gyokuro", "Genmaicha", "Bancha", "Hojicha", "Kukicha", "Shizuoka", "Uji", "Kagoshima"],
    "Chine": ["Chine", "Long Jing", "Pu-erh", "Puerh", "Tie Guan Yin", "Pai Mu Tan", "Jasmin", "Keemun", "Lapsang Souchong", "Yunnan", "Fujian", "Anhui"],
    "Inde": ["Inde", "Darjeeling", "Assam", "Nilgiri"],
    "Sri Lanka": ["Sri Lanka", "Ceylan", "Ceylon"],
    "Brésil": ["Brésil", "Maté", "Mate"],
    "Afrique du Sud": ["Afrique du Sud", "Rooibos", "Roobos", "Honeybush"],
    "Taïwan": ["Taïwan", "Taiwan", "Formose"]
}

def normalize_tea_type(tea_type):
    if not tea_type:
        return "Non précisé"
    t = tea_type.strip().lower()
    if "vert" in t: return "Thé vert"
    if "noir" in t: return "Thé noir"
    if "blanc" in t: return "Thé blanc"
    if "oolong" in t or "wulong" in t: return "Thé oolong"
    if "matcha" in t: return "Matcha"
    if "rooibos" in t: return "Rooibos"
    if "infusion" in t or "tisane" in t: return "Infusion"
    if "sombre" in t or "pu-erh" in t or "puerh" in t: return "Thé sombre"
    return tea_type.capitalize()

def parse_weight_in_grams(weight_str):
    """Extrait la valeur numérique exacte en grammes d'une chaîne de poids."""
    if not weight_str:
        return 100.0
    w = str(weight_str).lower().replace(" ", "")
    m = re.search(r'(\d+(?:[.,]\d+)?)\s*(g|gr|kg)?\b', w)
    if not m:
        return 100.0
    val = float(m.group(1).replace(',', '.'))
    unit = m.group(2) or "g"
    if unit.startswith("kg"):
        return val * 1000.0
    return val

def clean_origin(item):
    """
    Détermine le pays d'origine en cherchant en priorité dans les ingrédients,
    puis dans le nom et l'origine brute.
    """
    raw_origin = str(item.get("origin_country", "") or "")
    name = str(item.get("name", "") or "")
    ingredients = str(item.get("ingredients", "") or "")
    
    # Priorité au texte des ingrédients et du nom combinés
    full_text = f"{ingredients} {name} {raw_origin}".strip()
    
    found_countries = []
    for country, keywords in ORIGIN_MAPPING.items():
        for kw in keywords:
            if re.search(r'\b' + re.escape(kw) + r'\b', full_text, re.IGNORECASE):
                if country not in found_countries:
                    found_countries.append(country)
                break

    if found_countries:
        return ", ".join(found_countries)
    
    if raw_origin and raw_origin.lower() not in ["non précisé", "none", ""]:
        return raw_origin.strip()
        
    return "Non précisé"

def clean_catalog():
    try:
        with open(INPUT_FILE, "r", encoding="utf-8") as f:
            products = json.load(f)
    except Exception as e:
        print(f"[Erreur] Impossible de lire {INPUT_FILE}: {e}")
        return

    print(f"[Info] {len(products)} produits chargés depuis {INPUT_FILE}.")
    cleaned_products = []
    seen_signatures = set()

    for item in products:
        name = item.get("name", "Inconnu").strip()
        brand = item.get("brand", "Inconnue").strip()
        url = item.get("url", "").strip()
        
        tea_type = normalize_tea_type(item.get("tea_type"))
        
        # Récupération du poids brut pour calcul et formatage en 'gr'
        raw_weight_str = item.get("weight")
        grams = parse_weight_in_grams(raw_weight_str)
        weight_formatted = f"{int(grams)}gr" if grams.is_integer() else f"{grams}gr"
        
        # Détection intelligente des origines
        origin = clean_origin(item)
        
        # Nettoyage et conversion du prix du format
        price = item.get("price_eur")
        try:
            price_eur = float(price) if price is not None else None
        except (ValueError, TypeError):
            price_eur = None

        # Calcul automatique du prix au kilo (EUR/kg)
        price_per_kg_eur = None
        if price_eur is not None and grams > 0:
            price_per_kg_eur = round((price_eur / grams) * 1000, 2)

        signature = (brand, name, weight_formatted, url)
        if signature in seen_signatures:
            continue
        seen_signatures.add(signature)

        cleaned_item = {
            "brand": brand,
            "market": item.get("market", "FR"),
            "url": url,
            "name": name,
            "tea_type": tea_type,
            "origin_country": origin,
            "format_valid": bool(item.get("format_valid", True)),
            "pochette_label": item.get("pochette_label", "Poche vrac"),
            "weight": weight_formatted,
            "price_eur": price_eur,                
            "price_per_kg_eur": price_per_kg_eur   
        }
        cleaned_products.append(cleaned_item)

    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        json.dump(cleaned_products, f, indent=2, ensure_ascii=False)

    print(f"[Terminé] Normalisation, prix au kilo et origines mis à jour dans '{OUTPUT_FILE}' !")

if __name__ == "__main__":
    clean_catalog()