import json

INPUT_FILE = "master_tea_catalog_clean.json"

def clean_country_name(country):
    if not country:
        return "Non précisé"
    c = str(country).strip()
    
    # Correction des caractères chinois ou formats libres
    if c in ["中国", "Chine (Yunnan)", "Chine (Fujian)"]:
        return "Chine"
    if "taiwan" in c.lower() or "formose" in c.lower():
        return "Taïwan"
    if "thé chinois" in c.lower():
        return "Chine"
    if "thé du hammam" in c.lower():
        return "Chine" # Base classique du thé du hammam
        
    return c

def main():
    with open(INPUT_FILE, "r", encoding="utf-8") as f:
        products = json.load(f)

    for item in products:
        if "origin_country" in item:
            item["origin_country"] = clean_country_name(item["origin_country"])

    with open(INPUT_FILE, "w", encoding="utf-8") as f:
        json.dump(products, f, indent=2, ensure_ascii=False)
        
    print("[✔] Normalisation des pays terminée !")

if __name__ == "__main__":
    main()