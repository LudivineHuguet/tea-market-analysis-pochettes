import os
import glob
import json

# Configuration
PATTERN = "*_raw_results.json"
OUTPUT_MASTER_FILE = "master_tea_catalog.json"

def combine_json_files():
    all_products = []
    files = glob.glob(PATTERN)
    
    if not files:
        print(f"[Attention] Aucun fichier correspondant au motif '{PATTERN}' n'a été trouvé.")
        return

    print(f"[Info] {len(files)} fichiers de résultats bruts trouvés : {files}")

    for file_path in files:
        print(f"--> Chargement de {file_path}...")
        try:
            with open(file_path, "r", encoding="utf-8") as f:
                data = json.load(f)
                if isinstance(data, list):
                    all_products.extend(data)
                    print(f"    {len(data)} produits ajoutés.")
                else:
                    print(f"    [Avertissement] Le fichier {file_path} ne contient pas une liste JSON valide.")
        except Exception as e:
            print(f"    [Erreur] Impossible de lire {file_path}: {e}")

    # Écriture du fichier maître consolidé
    with open(OUTPUT_MASTER_FILE, "w", encoding="utf-8") as f:
        json.dump(all_products, f, indent=2, ensure_ascii=False)
        
    print(f"\n[Terminé] Fusion réussie ! Un total de {len(all_products)} produits a été enregistré dans '{OUTPUT_MASTER_FILE}'.")

if __name__ == "__main__":
    combine_json_files()