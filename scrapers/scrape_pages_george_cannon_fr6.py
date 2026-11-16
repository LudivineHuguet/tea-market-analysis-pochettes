import os
import json
import re
import time
import random
from urllib.parse import urljoin, urlparse

from bs4 import BeautifulSoup
from curl_cffi import requests as cr

# ----------------------------------------------------------------------
# Settings
# ----------------------------------------------------------------------
TARGET_DIR = "."
CATALOG_URL = "https://www.georgecannon.fr/collections/tous-nos-thes"
MARKET = "FR"

MAX_PRODUCTS = None     # Extraction complète de tout le catalogue
MAX_CATALOG_PAGES = 50  
DELAY_MIN, DELAY_MAX = 2.0, 4.0
MAX_RETRIES = 5
IMPERSONATE = "chrome"

COUNTRIES = {
    "Chine": "Chine", "Japon": "Japon", "Inde": "Inde", "Sri Lanka": "Sri Lanka",
    "Taïwan": "Taïwan", "Taiwan": "Taïwan", "Népal": "Népal", "Nepal": "Népal",
    "Kenya": "Kenya", "Corée du Sud": "Corée du Sud", "Vietnam": "Vietnam",
    "Thaïlande": "Thaïlande", "Afrique du Sud": "Afrique du Sud", "Italie": "Italie",
    "France": "France", "Colombie": "Colombie", "Pérou": "Pérou", "Brésil": "Brésil"
}

EXCLUDE_WORDS = ("boîte", "boite", "sachet", "sachets", "coffret", "tasse", "mousseline")
INCLUDE_WORDS = ("vrac", "100g", "300g", "500g", "1kg", "recharge")


def parse_weight(text):
    m = re.search(r'(\d+(?:[.,]\d+)?)\s*(kg|g)\b', text or '', re.I)
    if not m:
        return None
    val, unit = m.group(1), m.group(2).lower()
    return f"{int(float(val.replace(',', '.')) * 1000)}g" if unit == "kg" else f"{val}g"


def countries_in(text):
    low = (text or "").lower()
    hits = []
    for name in sorted(COUNTRIES, key=len, reverse=True):
        if re.search(r"(?<!\w)" + re.escape(name.lower()) + r"(?!\w)", low):
            canon = COUNTRIES[name]
            if canon not in hits:
                hits.append(canon)
    return hits


def find_name(soup):
    h1 = soup.select_one("h1.product-title, h1.product__title, h1.h2, h1")
    if h1 and h1.get_text(strip=True):
        return h1.get_text(" ", strip=True)
    og = soup.select_one('meta[property="og:title"]')
    return og["content"].strip() if og and og.get("content") else None


def extract_product_variants(soup, url, market):
    name = find_name(soup)
    page_text = " ".join(soup.stripped_strings)

    # Type de thé
    tea_type = "Thé"
    category_match = re.search(r'\b(th[ée]\s+(?:noir|vert|blanc|oolong|sombre)|rooibos|infusion|tisane|matcha)\b', page_text, re.I)
    if category_match:
        tea_type = category_match.group(1).capitalize()

    # Origine
    origin_country = None
    for el in soup.select('.product-description, .product__description, .tab-content, #description, .description'):
        txt = el.get_text(" ", strip=True)
        found = countries_in(txt)
        if found:
            origin_country = ", ".join(found)
            break
    if not origin_country:
        found_countries = countries_in(page_text)
        if found_countries:
            origin_country = ", ".join(found_countries)
    if not origin_country:
        origin_country = "Non précisé"

    variants = []

    # 1. Extraction des variantes Shopify (JSON)
    for script in soup.find_all("script", type="application/json"):
        txt = script.string or script.get_text() or ""
        if "variants" in txt and "price" in txt:
            try:
                data = json.loads(txt)
                raw_variants = []
                if isinstance(data, dict):
                    raw_variants = data.get("variants", []) or data.get("product", {}).get("variants", [])
                elif isinstance(data, list):
                    for item in data:
                        if isinstance(item, dict) and "variants" in item:
                            raw_variants = item["variants"]

                for v in raw_variants:
                    v_title = str(v.get("title", "") or v.get("name", ""))
                    v_title_lower = v_title.lower()

                    # Exclusion stricte des boîtes et sachets
                    if any(w in v_title_lower for w in EXCLUDE_WORDS):
                        continue
                    # Validation vrac / recharge / poids
                    if not any(w in v_title_lower for w in INCLUDE_WORDS) and not parse_weight(v_title):
                        continue

                    raw_price = v.get("price")
                    price = float(raw_price) / 100.0 if raw_price and float(raw_price) > 500 else (float(raw_price) if raw_price else None)
                    weight = parse_weight(v_title)

                    variants.append({
                        "pochette_label": v_title,
                        "weight": weight,
                        "price_eur": price,
                        "format_valid": True
                    })
            except Exception:
                pass

    # 2. Repli DOM si aucune variante JSON n'a été trouvée
    if not variants:
        global_weight = parse_weight(page_text) or "100g"
        price = None
        price_el = soup.select_one('.price-item--regular, .product__price span, .price, meta[property="product:price:amount"]')
        if price_el:
            p_text = price_el.get("content") or price_el.get_text(strip=True)
            m = re.search(r'(\d+[.,]\d{2})', p_text.replace('\xa0', '').replace(',', '.'))
            if m:
                try:
                    price = float(m.group(1))
                except ValueError:
                    pass

        variants.append({
            "pochette_label": "Vrac Standard",
            "weight": global_weight,
            "price_eur": price,
            "format_valid": True
        })

    results = []
    for v in variants:
        results.append({
            "brand": "George Cannon",
            "market": market,
            "url": url,
            "name": name,
            "tea_type": tea_type,
            "origin_country": origin_country,
            "format_valid": v["format_valid"],
            "pochette_label": v["pochette_label"],
            "weight": v["weight"],
            "price_eur": v["price_eur"]
        })
    return results


# ----------------------------------------------------------------------
# Downloading & Session
# ----------------------------------------------------------------------
session = cr.Session(impersonate=IMPERSONATE)
HEADERS = {"Accept-Language": "fr-FR,fr;q=0.9,en-US;q=0.8,en;q=0.7"}


def polite_sleep():
    time.sleep(random.uniform(DELAY_MIN, DELAY_MAX))


def fetch(url):
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            resp = session.get(url, headers=HEADERS, timeout=30)
            if resp.status_code == 200:
                return resp
            if resp.status_code in (429, 503):
                time.sleep(10 * attempt)
                continue
        except Exception:
            time.sleep(5 * attempt)
            continue
    return None


def clean_product_url(base, href):
    abs_url = urljoin(base, href).split('#')[0].split('?')[0]
    path = urlparse(abs_url).path
    return abs_url if '/products/' in path else None


def collect_product_links():
    links = []
    seen = set()
    for page in range(1, MAX_CATALOG_PAGES + 1):
        page_url = CATALOG_URL if page == 1 else f"{CATALOG_URL}?page={page}"
        resp = fetch(page_url)
        if resp is None or resp.status_code != 200:
            break

        soup = BeautifulSoup(resp.text, "html.parser")
        new_on_page = 0
        for a in soup.select('a[href*="/products/"]'):
            url = clean_product_url(page_url, a.get("href", ""))
            if url and url not in seen:
                seen.add(url)
                links.append(url)
                new_on_page += 1

        if new_on_page == 0:
            break
        polite_sleep()
    return links


# ----------------------------------------------------------------------
# Main
# ----------------------------------------------------------------------
def run_phase_one():
    os.makedirs(TARGET_DIR, exist_ok=True)
    product_links = collect_product_links()

    results = []
    for url in product_links:
        polite_sleep()
        resp = fetch(url)
        if resp is None or resp.status_code != 200:
            continue

        soup = BeautifulSoup(resp.text, "html.parser")
        rows = extract_product_variants(soup, url, MARKET)
        for data in rows:
            results.append(data)
            print(f"OK : {data['name']} | {data['pochette_label']} | {data['weight']} | {data['price_eur']}€")

    output_file = os.path.join(TARGET_DIR, "george_cannon_raw_results.json")
    with open(output_file, "w", encoding="utf-8") as f:
        json.dump(results, f, indent=2, ensure_ascii=False)
    print(f"\n[Terminé] {len(results)} lignes enregistrées dans {output_file}")


if __name__ == "__main__":
    run_phase_one()