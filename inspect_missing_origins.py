import json

with open("master_tea_catalog_clean.json", "r", encoding="utf-8") as f:
    products = json.load(f)

print("--- Liste des produits 'Non précisé' restants ---")
count = 0
for item in products:
    if item.get("origin_country") == "Non précisé":
        count += 1
        print(f"[{count}] Nom: {item.get('name')} | Marque: {item.get('brand')}")

print(f"\nTotal affiché : {count}")