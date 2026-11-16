import os
import json
import pandas as pd
from datetime import datetime

# Chemins
INPUT_CLEAN_JSON = "master_tea_catalog_clean.json"
DATABASE_DIR = "database"

def archive_to_database():
    # 1. Vérifier que le fichier JSON propre existe
    if not os.path.exists(INPUT_CLEAN_JSON):
        print(f"[Erreur] Le fichier {INPUT_CLEAN_JSON} est introuvable. Exécutez d'abord normalize_catalog.py.")
        return

    # 2. Créer le dossier database s'il n'existe pas
    os.makedirs(DATABASE_DIR, exist_ok=True)

    # 3. Charger les données du catalogue propre
    with open(INPUT_CLEAN_JSON, "r", encoding="utf-8") as f:
        data = json.load(f)

    # 4. Convertir en DataFrame pandas et ajouter la date d'extraction
    df = pd.DataFrame(data)
    today_str = datetime.now().strftime("%d%m%Y")  # Format JJMMAAAA (ex: 25102026)
    today_date_formatted = datetime.now().strftime("%Y-%m-%d")
    
    df["extraction_date"] = today_date_formatted

    # 5. Définir le chemin de sortie du CSV horodaté
    output_filename = f"tea_price_list_{today_str}.csv"
    output_path = os.path.join(DATABASE_DIR, output_filename)
    
    # 6. Exporter au format CSV (encodage utf-8-sig pour les accents compatibles Excel)
    df.to_csv(output_path, index=False, encoding="utf-8-sig")
    print(f"[Succès] Fichier archivé avec succès dans '{output_path}' ({len(df)} produits enregistrés).")

if __name__ == "__main__":
    archive_to_database()