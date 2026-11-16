import os
import glob
import pandas as pd
import matplotlib.pyplot as plt
import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
DEFAULT_CSV_GLOB = os.path.join(HERE, "database", "tea_price_list_*.csv")
VIZ_DIR = os.path.join(HERE, "Visualization")

# S'assurer que le dossier Visualization existe
os.makedirs(VIZ_DIR, exist_ok=True)

def load_and_filter_data():
    """Charge le dernier CSV et filtre uniquement les thés en vrac / pochettes."""
    found = sorted(glob.glob(DEFAULT_CSV_GLOB), key=os.path.getmtime)
    if not found:
        raise SystemExit(f"Aucun fichier CSV trouvé pour {DEFAULT_CSV_GLOB}")
    
    csv_path = found[-1]
    print(f"Chargement des données depuis : {csv_path}")
    df = pd.read_csv(csv_path)
    
    # Filtrer pour ne garder que le vrac / pochettes valides
    if "format_valid" in df.columns:
        df = df[df["format_valid"] == True]
    
    # Sécurité supplémentaire : exclure explicitement les mentions de boîtes/coffrets dans le nom si nécessaire
    df = df[~df["name"].str.contains("boîte|coffret|tin|box", case=False, na=False)]
    
    print(f"Nombre de produits en vrac/pochettes retenus : {len(df)}")
    return df

def plot_market_overview(df):
    """1. Prix moyen au kilo par type de thé (Vrac uniquement)"""
    market_df = df.groupby("tea_type")["price_per_kg_eur"].mean().reset_index()
    market_df = market_df[market_df["tea_type"] != "Non précisé"].sort_values(by="price_per_kg_eur", ascending=True)
    
    fig, ax = plt.subplots(figsize=(10, 7))
    colors = plt.cm.magma(np.linspace(0.15, 0.85, len(market_df)))
    ax.barh(market_df["tea_type"], market_df["price_per_kg_eur"], color=colors, height=0.6)
    ax.set_title("Loose Tea: Average Price per Kilogram by Tea Type (€/kg)", fontsize=14, fontweight='bold', pad=15)
    ax.set_xlabel("Average Price (€/kg)", fontsize=12)
    ax.spines['top'].set_visible(False)
    ax.spines['right'].set_visible(False)
    plt.tight_layout()
    plt.savefig(os.path.join(VIZ_DIR, "loose_tea_average_price_by_type.png"), dpi=300)
    plt.close()

def plot_black_tea_comparison(df):
    """2. Thé noir en vrac : Chine vs Inde / Sri Lanka (Min, Moyen, Max)"""
    df_black = df[df["tea_type"].str.contains("noir|black", case=False, na=False)].copy()
    
    def map_origin(orig):
        o = str(orig).lower()
        if any(c in o for c in ["chine", "china"]): return "Chine"
        if any(c in o for c in ["inde", "india", "sri lanka", "ceylan", "ceylon"]): return "Inde / Sri Lanka"
        return "Autre"
    
    df_black["origin_group"] = df_black["origin_country"].apply(map_origin)
    stats = df_black[df_black["origin_group"].isin(["Chine", "Inde / Sri Lanka"])].groupby("origin_group")["price_per_kg_eur"].agg(['mean', 'min', 'max']).reset_index()
    
    if stats.empty:
        print("Attention : Pas assez de données pour le comparatif thé noir Chine vs Inde/Sri Lanka.")
        return

    fig, ax = plt.subplots(figsize=(10, 6))
    x = np.arange(len(stats))
    width = 0.25
    ax.bar(x - width, stats['min'], width, label='Minimum', color='#8ecae6')
    ax.bar(x, stats['mean'], width, label='Moyen', color='#ffb703')
    ax.bar(x + width, stats['max'], width, label='Maximum', color='#fb8500')
    ax.set_title("Loose Black Tea Price per Kg: China vs India / Sri Lanka", fontsize=14, fontweight='bold', pad=15)
    ax.set_ylabel("Price (€/kg)", fontsize=12)
    ax.set_xticks(x)
    ax.set_xticklabels(stats['origin_group'], fontsize=12, fontweight='bold')
    ax.legend(frameon=False)
    ax.spines['top'].set_visible(False)
    ax.spines['right'].set_visible(False)
    plt.tight_layout()
    plt.savefig(os.path.join(VIZ_DIR, "loose_black_tea_china_india_price.png"), dpi=300)
    plt.close()

def plot_green_tea_comparison(df):
    """3. Thé vert en vrac hors matcha : Chine vs Japon (Min, Moyen, Max)"""
    df_green = df[df["tea_type"].str.contains("vert|green", case=False, na=False)].copy()
    df_green = df_green[~df_green["name"].str.contains("matcha", case=False, na=False)]
    
    def map_origin_green(orig):
        o = str(orig).lower()
        if any(c in o for c in ["chine", "china"]): return "Chine"
        if any(c in o for c in ["japon", "japan"]): return "Japon"
        return "Autre"
    
    df_green["origin_group"] = df_green["origin_country"].apply(map_origin_green)
    stats = df_green[df_green["origin_group"].isin(["Chine", "Japon"])].groupby("origin_group")["price_per_kg_eur"].agg(['mean', 'min', 'max']).reset_index()
    
    if stats.empty:
        print("Attention : Pas assez de données pour le comparatif thé vert Chine vs Japon.")
        return

    fig, ax = plt.subplots(figsize=(10, 6))
    x = np.arange(len(stats))
    width = 0.25
    ax.bar(x - width, stats['min'], width, label='Minimum', color='#a7c957')
    ax.bar(x, stats['mean'], width, label='Moyen', color='#386641')
    ax.bar(x + width, stats['max'], width, label='Maximum', color='#6a994e')
    ax.set_title("Loose Green Tea (Excl. Matcha) Price per Kg: China vs Japan", fontsize=14, fontweight='bold', pad=15)
    ax.set_ylabel("Price (€/kg)", fontsize=12)
    ax.set_xticks(x)
    ax.set_xticklabels(stats['origin_group'], fontsize=12, fontweight='bold')
    ax.legend(frameon=False)
    ax.spines['top'].set_visible(False)
    ax.spines['right'].set_visible(False)
    plt.tight_layout()
    plt.savefig(os.path.join(VIZ_DIR, "loose_green_tea_china_japan_price.png"), dpi=300)
    plt.close()

def plot_origin_pie_chart(df):
    """4. Camembert des origines pour les thés en vrac"""
    origins = df["origin_country"].fillna("Inconnu").astype(str)
    counts = origins.value_counts()
    top_origins = counts.head(5)
    other_count = counts.iloc[5:].sum()
    if other_count > 0:
        top_origins["Autres"] = other_count
        
    fig, ax = plt.subplots(figsize=(8, 8))
    wedges, texts, autotexts = ax.pie(
        top_origins, 
        labels=top_origins.index, 
        autopct='%1.1f%%', 
        startangle=140, 
        colors=plt.cm.Paired(np.linspace(0, 1, len(top_origins)))
    )
    plt.setp(autotexts, size=10, weight="bold")
    ax.set_title("Répartition des Origines (Thés en Vrac / Pochettes)", fontsize=14, fontweight='bold', pad=15)
    plt.tight_layout()
    plt.savefig(os.path.join(VIZ_DIR, "loose_tea_origin_pie_chart.png"), dpi=300)
    plt.close()

if __name__ == "__main__":
    df = load_and_filter_data()
    print("Génération des graphiques spécifiques au vrac...")
    plot_market_overview(df)
    plot_black_tea_comparison(df)
    plot_green_tea_comparison(df)
    plot_origin_pie_chart(df)
    print(f"[✔] Toutes les visualisations vrac ont été générées et enregistrées dans : {VIZ_DIR}")