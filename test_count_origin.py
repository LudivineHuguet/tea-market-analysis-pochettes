import json

# Charger le catalogue nettoyé
with open("master_tea_catalog_clean.json", "r", encoding="utf-8") as f:
    products = json.load(f)

# Compter combien de produits ont l'origine "Non précisé"
count = sum(1 for p in products if p.get("origin_country") == "Non précisé")

print(f"--- Résultat du test ---")
print(f"Nombre total de produits dans le catalogue : {len(products)}")
print(f"Produits avec une origine 'Non précisé' : {count}")