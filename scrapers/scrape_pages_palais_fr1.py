import os
import json
import re
import time
import random
from urllib.parse import urljoin
from bs4 import BeautifulSoup
from curl_cffi import requests as cr

TARGET_DIR = "."
OUTPUT_FILE = os.path.join(TARGET_DIR, "thes_de_la_pagode_raw_results.json")
CATALOG_URL = "https://www.thesdelapagode.com/fr/51-thes-en-vrac"
MARKET = "FR"

MAX_PRODUCTS = 5  # Mettre à None pour extraire tout le catalogue
MAX_CATALOG_PAGES = 10
DELAY_MIN, DELAY_MAX = 2.0, 4.0
IMPERSONATE = "chrome"

EXCLUDE_WORDS = ("tube", "métal", "metal", "boîte", "boite", "coffret", "sachet", "sachets", "infusette", "infusettes")
INCLUDE_WORDS = ("vrac", "thés en vrac", "pochette", "recharge", "doypack", "100g", "200g", "500g", "1kg")

COUNTRIES = {
    "Chine": "Chine", "Japon": "Japon", "Inde": "Inde", "Sri Lanka": "Sri Lanka",
    "Ceylan": "Sri Lanka", "Ceylon": "Sri Lanka", "Taïwan": "Taïwan", "Taiwan": "Taïwan",
    "Népal": "Népal", "Nepal": "Népal", "Kenya": "Kenya", "Corée du Sud": "Corée du Sud",
    "Vietnam": "Vietnam", "Thaïlande": "Thaïlande", "Afrique du Sud": "Afrique du Sud", "France": "France"
}


def parse_weight(text):
    m = re.search(r'(\d+(?:[.,]\d+)?)\s*(g|kg)\b', text or '', re.I)
    if not m:
        return None
    val, unit = m.group(1), m.group(2).lower()
    return f"{int(float(val.replace(',', '.')) * 1000)}g" if unit == "kg" else f"{val}g"


def find_country(text):
    low = (text or "").lower()
    for name, canon in COUNTRIES.items():
        if re.search(r"(?<!\w)" + re.escape(name.lower()) + r"(?!\w)", low):
            return canon
    return "Non précisé"


def detect_tea_type(url, page_text):
    url_lower = url.lower()
    if "the-vert" in url_lower: return "Thé vert"
    if "the-noir" in url_lower: return "Thé noir"
    if "the-blanc" in url_lower: return "Thé blanc"
    if "the-oolong" in url_lower or "the-wulong" in url_lower: return "Thé oolong"
    if "matcha" in url_lower: return "Matcha"
    if "rooibos" in url_lower: return "Rooibos"
    if "infusion" in url_lower or "tisane" in url_lower: return "Infusion"
    m = re.search(r'\b(th[ée]\s+(?:noir|vert|blanc|oolong|sombre)|rooibos|infusion|tisane|matcha)\b', page_text, re.I)
    return m.group(1).capitalize() if m else "Thé"


def extract_ingredients(soup):
    """Recherche spécifiquement les éléments décrivant les ingrédients."""
    ing_el = soup.select_one('.product-ingredients, .ingredients, [itemprop="description"], .product-description')
    if ing_el:
        txt = ing_el.get_text(" ", strip=True)
        if "ingrédient" in txt.lower():
            return txt
    # Recherche textuelle dans le corps de page si pas de classe spécifique
    for el in soup.select('p, div, td'):
        t = el.get_text(" ", strip=True)
        if t.lower().startswith("ingrédients") or "ingrédients :" in t.lower():
            return t
    return ""


def extract_product_variants(soup, url, market):
    h1 = soup.select_one("h1.h1, h1.page-title, h1[itemprop='name'], h1")
    name = h1.get_text(" ", strip=True) if h1 else "Inconnu"
    
    summary_el = soup.select_one('.product-description, #description, .product-information, .product-features')
    summary_text = summary_el.get_text(" ", strip=True) if summary_el else ""
    page_text = " ".join(soup.stripped_strings)
    
    # Extraire spécifiquement le bloc ingrédients
    ingredients_text = extract_ingredients(soup)

    tea_type = detect_tea_type(url, page_text)

    origin = None
    for el in soup.select('.data-sheet tr, .product-features tr, .product-information, dl.data-sheet'):
        txt = el.get_text(" ", strip=True)
        if any(w in txt.lower() for w in ("origine", "pays", "provenance")):
            origin = find_country(txt)
            if origin != "Non précisé": break
            
    if not origin or origin == "Non précisé":
        # Recherche dans les ingrédients puis dans la description
        origin = find_country(ingredients_text or summary_text or page_text)

    variants = []
    option_elements = soup.select(".product-variants select option, .attribute-color, .attribute-name, .input-container label, .product-variants label")
    for el in option_elements:
        txt = el.get_text(" ", strip=True)
        if any(w in txt.lower() for w in EXCLUDE_WORDS): continue
        weight = parse_weight(txt)
        if weight or any(w in txt.lower() for w in INCLUDE_WORDS):
            variants.append({"label": txt, "weight": weight})

    if not variants:
        variants.append({"label": "Poche vrac", "weight": parse_weight(summary_text) or "100g"})

    base_price = None
    price_el = soup.select_one('meta[property="product:price:amount"], meta[property="og:price:amount"], [itemprop="price"]')
    if price_el:
        try:
            base_price = float((price_el.get("content") or price_el.get("value") or "0").replace('\xa0', '').replace(' ', '').replace(',', '.'))
        except (ValueError, TypeError): pass

    if base_price is None:
        for p_sel in soup.select('.current-price-value, .current-price span, span.price, .product-prices .price'):
            m = re.search(r'(\d+[.,]\d{2})', p_sel.get_text(strip=True).replace('\xa0', '').replace(' ', ''))
            if m:
                try:
                    base_price = float(m.group(1).replace(',', '.'))
                    break
                except ValueError: pass

    return [{
        "brand": "Thés de la Pagode", 
        "market": market, 
        "url": url, 
        "name": name,
        "tea_type": tea_type, 
        "origin_country": origin, 
        "ingredients": ingredients_text,  # Champ ingrédients sauvegardé dans le JSON
        "format_valid": True,
        "pochette_label": v["label"], 
        "weight": v["weight"], 
        "price_eur": base_price
    } for v in variants]


def collect_product_links():
    session = cr.Session(impersonate=IMPERSONATE)
    links, seen = [], set()
    for page in range(1, MAX_CATALOG_PAGES + 1):
        page_url = f"{CATALOG_URL}?page={page}" if page > 1 else CATALOG_URL
        resp = session.get(page_url, headers={"Accept-Language": "fr-FR,fr;q=0.9"})
        if not resp or resp.status_code != 200: break

        soup = BeautifulSoup(resp.text, "html.parser")
        new_on_page = 0
        for a in soup.select('article.product-miniature a, .product-title a, a.product-thumbnail, a[href*=".html"]'):
            href = a.get("href")
            if not href: continue
            abs_url = urljoin(page_url, href).split('#')[0].split('?')[0]
            if not re.search(r'/\d+-[^/]+\.html$', abs_url) or any(b in abs_url for b in ("/panier", "/commande", "/mon-compte")):
                continue
            if abs_url not in seen:
                seen.add(abs_url)
                links.append(abs_url)
                new_on_page += 1
        if new_on_page == 0 or (MAX_PRODUCTS and len(links) >= MAX_PRODUCTS): break
        time.sleep(random.uniform(DELAY_MIN, DELAY_MAX))
    return links[:MAX_PRODUCTS] if MAX_PRODUCTS else links


def run_scraper():
    os.makedirs(TARGET_DIR, exist_ok=True)
    product_links = collect_product_links()
    session = cr.Session(impersonate=IMPERSONATE)
    results = []

    for url in product_links:
        time.sleep(random.uniform(DELAY_MIN, DELAY_MAX))
        resp = session.get(url, headers={"Accept-Language": "fr-FR,fr;q=0.9"})
        if not resp or resp.status_code != 200: continue
        soup = BeautifulSoup