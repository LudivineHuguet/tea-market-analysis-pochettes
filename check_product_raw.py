import json

with open("master_tea_catalog.json", "r", encoding="utf-8") as f:
    products = json.load(f)

# Cherchons le "Thé des Sources" ou un autre produit de la liste
for item in products:
    if "Thé des Sources" in item.get("name", ""):
        print(f"Nom : {item.get('name')}")
        print(f"Origine brute : {item.get('origin_country')}")
        print(f"Ingrédients bruts : {item.get('ingredients')}")
        break