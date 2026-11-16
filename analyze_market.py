import os
import glob
import pandas as pd
import matplotlib.pyplot as plt
import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
DEFAULT_CSV_GLOB = os.path.join(HERE, "database", "tea_price_list_*.csv")

def analyze_and_plot(csv_path):
    print(f"Chargement des données depuis : {csv_path}")
    df = pd.read_csv(csv_path)
    
    # Utiliser 'price_per_kg_eur' comme colonne de prix au kilo
    if "price_per_kg_eur" in df.columns:
        df["price_per_kilo"] = df["price_per_kg_eur"]
    elif "price_per_kilo" in df.columns:
        pass
    else:
        # Solution de secours si besoin
        price_col = next((c for c in ["price_eur", "price"] if c in df.columns), None)
        weight_col = next((c for c in ["weight"] if c in df.columns), None)
        if price_col and weight_col:
            df["price_clean"] = df[price_col].astype(str).str.replace(r"[^\d,\.]", "", regex=True).str.replace(",", ".").astype(float)
            df["weight_in_g"] = df[weight_col].astype(str).str.lower().str.replace(",", ".").str.extract(r"(\d+(?:\.\d+)?)")[0].astype(float)
            mask_kg = df[weight_col].astype(str).str.contains("kg", case=False, na=False)
            df.loc[mask_kg, "weight_in_g"] *= 1000
            df["price_per_kilo"] = df["price_clean"] / (df["weight_in_g"] / 1000)
        else:
            raise KeyError(f"Colonne de prix introuvable parmi : {df.columns.tolist()}")

    # 1. Calculer le prix moyen au kilo par type de thé
    market_df = df.groupby("tea_type")["price_per_kilo"].mean().reset_index()
    
    # Filtrer les 'Non précisé' pour l'analyse visuelle
    market_df = market_df[market_df["tea_type"] != "Non précisé"]

    # 2. RANGER DU PLUS CHER AU MOINS CHER (ascending=True place la plus grande valeur tout en haut sur barh)
    market_df = market_df.sort_values(by="price_per_kilo", ascending=True)

    # 3. CRÉER LA VISUALISATION
    fig, ax = plt.subplots(figsize=(10, 7))

    # Générer un dégradé de couleurs fluide (palette magma)
    colors = plt.cm.magma(np.linspace(0.15, 0.85, len(market_df)))

    bars = ax.barh(market_df["tea_type"], market_df["price_per_kilo"], color=colors, height=0.6)

    # 4. MISE EN FORME DU GRAPHIQUE
    ax.set_title("Average Price per Kilogram by Tea Type (€/kg)", fontsize=14, fontweight='bold', pad=15)
    ax.set_xlabel("Average Price (€/kg)", fontsize=12)
    ax.set_ylabel("")

    # Épure graphique
    ax.spines['top'].set_visible(False)
    ax.spines['right'].set_visible(False)
    ax.spines['left'].set_color('#cccccc')
    ax.spines['bottom'].set_color('#cccccc')

    ax.xaxis.grid(True, linestyle='--', alpha=0.5, color='#cccccc')
    ax.set_axisbelow(True)

    plt.tight_layout()
    
    output_path = os.path.join(HERE, "average_price_by_tea_type.png")
    plt.savefig(output_path, dpi=300)
    plt.close()
    
    print(f"[✔] Graphique de marché généré et sauvegardé sous : {output_path}")

if __name__ == "__main__":
    found = sorted(glob.glob(DEFAULT_CSV_GLOB), key=os.path.getmtime)
    if not found:
        raise SystemExit(f"Aucun fichier CSV trouvé pour {DEFAULT_CSV_GLOB}")
    latest_csv = found[-1]
    analyze_and_plot(latest_csv)