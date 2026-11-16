import json
import requests

INPUT_FILE = "master_tea_catalog_clean.json"
OUTPUT_FILE = "master_tea_catalog_clean.json"

OLLAMA_MODEL = "qwen2.5:1.5b"
OLLAMA_URL = "http://localhost:11434/api/generate"

PROMPT_TEMPLATE = """Tu es un expert du thé. 
Analyse ce produit et fournis deux informations au format JSON strict :
1. "origin": Le PAYS D'ORIGINE principal de la feuille de thé (ex: Chine, Japon, Inde, Sri Lanka, Afrique du Sud, etc.). Si c'est un mélange parfumé, indique la base du thé.
2. "tea_type": Le TYPE DE THÉ exact parmi cette liste : ["Thé vert", "Thé noir", "Thé blanc", "Thé oolong", "Matcha", "Rooibos", "Infusion", "Thé sombre"].

Produit : {name}
Type actuel : {tea_type}
Marque : {brand}

Réponds STRICTEMENT sous ce format JSON exact sans aucun autre texte :
{{"origin": "NomDuPays", "tea_type": "TypeDeThé"}}
"""

def clean_country_name(country):
    if not country:
        return "Non précisé"
    c = str(country).strip()
    if c in ["中国", "Chine (Yunnan)", "Chine (Fujian)"]:
        return "Chine"
    if "taiwan" in c.lower() or "formose" in c.lower():
        return "Taïwan"
    if "thé chinois" in c.lower():
        return "Chine"
    return c

def get_llm_data(name, tea_type, brand):
    prompt = PROMPT_TEMPLATE.format(name=name, tea_type=tea_type, brand=brand)
    payload = {
        "model": OLLAMA_MODEL,
        "prompt": prompt,
        "stream": False,
        "format": "json"
    }
    try:
        res = requests.post(OLLAMA_URL, json=payload, timeout=10)
        if res.status_code == 200:
            data = json.loads(res.json()["response"])
            return data.get("origin"), data.get("tea_type")
    except Exception:
        pass
    return None, None

def main():
    try:
        with open(INPUT_FILE, "r", encoding="utf-8") as f:
            products = json.load(f)
    except FileNotFoundError:
        print(f"Erreur : Le fichier {INPUT_FILE} est introuvable.")
        return

    updated_count = 0
    print(f"Lancement de l'enrichissement (Origine + Type de thé) avec {OLLAMA_MODEL}...")

    for item in products:
        current_origin = item.get("origin_country", "Non précisé")
        current_type = item.get("tea_type", "Non précisé")
        
        # On interroge le LLM si l'origine OU le type de thé est manquant/générique
        needs_origin = current_origin in ["Non précisé", "Mélange", "Autre", None, ""]
        needs_type = current_type in ["Non précisé", None, ""]
        
        if needs_origin or needs_type:
            name = item.get("name", "")
            brand = item.get("brand", "")
            
            new_orig, new_type = get_llm_data(name, current_type, brand)
            
            changed = False
            if needs_origin and new_orig and new_orig != "Non précisé":
                item["origin_country"] = clean_country_name(new_orig)
                changed = True
                
            if needs_type and new_type and new_type != "Non précisé":
                item["tea_type"] = new_type
                changed = True
                
            if changed:
                updated_count += 1
                print(f"✔ {name} -> Origine: {item.get('origin_country')} | Type: {item.get('tea_type')}")

    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        json.dump(products, f, indent=2, ensure_ascii=False)

    print(f"\n[Terminé] {updated_count} produits mis à jour dans '{OUTPUT_FILE}' !")

if __name__ == "__main__":
    main()