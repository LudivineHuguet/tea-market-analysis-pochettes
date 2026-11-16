# 🍃 D2C Tea Data Engineering Pipeline (Bulk & Refill Pouches)

Local LLM used in the project: `Qwen3-4B-Instruct-2507-Q6_K.gguf` from Hugging Face

An automated web scraping, data wrangling, data modeling, and pricing analysis pipeline focusing on loose-leaf tea, refill pouches, and doypacks across **7 major French tea brands**.

---

## 📌 Project Overview
This project automates the extraction, cleaning, archiving, and analysis of loose-leaf and refill tea catalogs in France (excluding tins, gift boxes, and individual tea bags). It establishes a structured data pipeline to monitor market pricing, analyze origins, and prepare clean dataset inputs for predictive modeling.

---

## 🛠️ Targeted Brands & Tech Stack

### Targeted Brands (7 French E-Commerce Stores)
- **Palais des Thés** (`palais_raw_results.json`)
- **Compagnie & Co** (`compagnie_raw_results.json`)
- **Les Jardins de Gaïa** (`jardins_gaia_raw_results.json`)
- **Kusmi Tea** (`kusmi_raw_results.json`)
- **Le Comptoir Français du Thé** (`comptoir_francais_the_raw_results.json`)
- **George Cannon** (`george_cannon_raw_results.json`)
- **Thés de la Pagode** (`thes_de_la_pagode_raw_results.json`)

### Technical Stack
- **Language**: Python 3.10+
- **HTTP Request / Anti-Bot**: `curl_cffi` (Chrome impersonation)
- **HTML Parsing**: `BeautifulSoup4`
- **Data Processing**: Native Python / `pandas` / `re`

---

## 📂 Repository Structure

```text
📁 Webscraper_Datawrangling/
├── 📁 .venv/                               # Python Virtual Environment
├── 📁 scrapers/                            # Brand-specific scraper scripts
│   ├── scrape_pages_palais_fr1.py
│   ├── scrape_pages_compagnie_co_fr2.py
│   ├── scrape_pages_jardins_gaia_fr3.py
│   ├── scrape_pages_kusmi_fr4.py
│   ├── scrape_pages_comptoir_francais_the_fr5.py
│   ├── scrape_pages_george_cannon_fr6.py
│   └── scrape_pages_thes_pagode_fr7.py
├── 📁 database/                            # Date-stamped database exports
│   └── tea_price_list_DDMMYYYY.csv
├── combine_catalogs.py                     # Merges raw brand JSON files
├── normalize_catalog.py                    # Cleans data, formats weight (gr), calculates EUR/kg
├── master_tea_catalog.json                 # Unfiltered master catalog (545 raw items)
├── master_tea_catalog_clean.json           # Final cleaned & standardized dataset
└── README.md
### Execution Pipeline Stages

1. Automatic process for webscraping
Each brand scraper inside scrapers/ extracts loose-leaf/pouch tea listings and writes its results into a corresponding *_raw_results.json file. A scraper execution is considered successful only if it exits with code 0 and generates a non-empty, freshly written output.

2. Human verification and combine data from different dates (Data wrangling)
- Consolidation: combine_catalogs.py scans the raw JSON outputs and merges them into master_tea_catalog.json (545 raw items).
- Data Cleaning & Normalization: normalize_catalog.py executes the wrangling step:
  - Standardizes tea type categories (Thé vert, Thé noir, Thé blanc, Thé oolong, Matcha, Rooibos, Infusion, Thé sombre).
  - Formats all weights into strict gram values with the gr suffix (e.g., 100gr, 500gr, 1000gr).
  - Computes the normalized price per kilogram (price_per_kg_eur) across all bag sizes for equitable comparison.
- Database Archiving: Output files are moved to the database/ folder using date suffixes (tea_price_list_DDMMYYYY.csv). This temporal tracking allows continuous price fluctuation monitoring and historical trend analysis.

3. Data_modeling
To predict intrinsic tea valuation without packaging shortcuts (e.g., small premium tins skewing price per kg):
- Feature Selection: Excludes raw weight parameters (weight_in_g) to prevent the model from learning package-size shortcuts.
- Evaluation Process: Splits dataset into 80% training / 20% testing with 5-fold cross-validation.
- Model Benchmark: A standalone Gradient Boosting Regressor predicting price_per_kg_eur achieves optimal performance ($R^2 \approx 0.85$), outperforming complex two-stage SVM/Ensemble architectures.

4. Data Visualization
The cleaned dataset facilitates e-commerce market benchmarking across key dimensions:
- Overall Market Overview: Evaluates average EUR/kg across tea types (Matcha and White Tea commanding top-tier pricing vs. Black/Green tea market saturation).
- Country-of-Origin Analysis: Analyzes origin pricing differentials (e.g., Japanese Green Tea vs. Chinese Green Tea pricing spread).
- Detailed Price Distributions: Boxplot distributions for key segments (Jasmine, Earl Grey, Chinese Black, Japanese Matcha).
- LLM Strategy Report: Automated market entry report generated via Qwen3-4B-Instruct based on competitive benchmark metrics.