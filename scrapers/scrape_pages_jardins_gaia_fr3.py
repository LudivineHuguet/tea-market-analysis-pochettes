import json
import os
import re
import scrapy
from bs4 import BeautifulSoup
from scrapy.crawler import CrawlerProcess

OUTPUT_FILE = "jardins_gaia_raw_results.json"
RAW_PAGES = []

EXCLUDE_WORDS = ("tube", "métal", "metal", "boîte", "boite", "coffret")
INCLUDE_WORDS = ("sachet", "vrac", "doypack")

COUNTRIES = [
    "Chine", "Japon", "Inde", "Sri Lanka", "Taïwan", "Taiwan", "Népal", "Nepal",
    "Kenya", "Corée du Sud", "Vietnam", "Thaïlande", "Afrique du Sud", "France"
]


def parse_weight(text):
    m = re.search(r'(\d+(?:[.,]\d+)?)\s*(g|kg)\b', text or '', re.I)
    if not m:
        return None
    val, unit = m.group(1), m.group(2).lower()
    return f"{int(float(val.replace(',', '.')) * 1000)}g" if unit == "kg" else f"{val}g"


def find_country(text):
    low = (text or "").lower()
    for c in COUNTRIES:
        if re.search(r"(?<!\w)" + re.escape(c.lower()) + r"(?!\w)", low):
            return c
    return None


def detect_tea_type(url, page_text):
    url_lower = url.lower()
    if "the-vert" in url_lower:
        return "Thé vert"
    if "the-noir" in url_lower:
        return "Thé noir"
    if "the-blanc" in url_lower:
        return "Thé blanc"
    if "the-oolong" in url_lower or "the-wulong" in url_lower:
        return "Thé oolong"
    if "the-sombre" in url_lower:
        return "Thé sombre"
    if "matcha" in url_lower:
        return "Matcha"
    
    for t_candidate in ["Thé vert", "Thé noir", "Thé blanc", "Thé oolong", "Matcha", "Thé sombre"]:
        if t_candidate.lower() in page_text.lower():
            return t_candidate
    return "Thé"


def extract_product_variants(soup, url, market):
    h1 = soup.select_one("h1")
    name = h1.get_text(" ", strip=True) if h1 else "Inconnu"
    page_text = " ".join(soup.stripped_strings)

    tea_type = detect_tea_type(url, page_text)

    # Recherche du pays d'origine dans les tableaux de spécifications PrestaShop
    origin = None
    for el in soup.select('.data-sheet tr, .product-features tr, .product-information, dl.data-sheet'):
        txt = el.get_text(" ", strip=True)
        if "origine" in txt.lower():
            origin = find_country(txt)
            if origin:
                break
    if not origin:
        origin = find_country(page_text)

    # Extraction des variantes (ex: 100g, 500g...)
    variants = []
    option_elements = soup.select(".product-variants select option, .attribute-color, .attribute-name, .input-container label, .product-variants label")
    
    for el in option_elements:
        txt = el.get_text(" ", strip=True)
        if any(w in txt.lower() for w in EXCLUDE_WORDS):
            continue
        weight = parse_weight(txt)
        if weight or any(w in txt.lower() for w in INCLUDE_WORDS):
            variants.append({
                "label": txt,
                "weight": weight
            })

    if not variants:
        global_weight = parse_weight(page_text)
        variants.append({
            "label": "Standard",
            "weight": global_weight
        })

    # --- EXTRACTION DE PRIX ROBUSTE (Multiples Fallbacks) ---
    base_price = None

    # 1. Via les métadonnées OpenGraph / Schema.org
    price_el = soup.select_one('meta[property="product:price:amount"], meta[property="og:price:amount"], [itemprop="price"]')
    if price_el:
        val = price_el.get("content") or price_el.get("value") or price_el.get_text(strip=True)
        try:
            base_price = float(val.replace('\xa0', '').replace(',', '.'))
        except (ValueError, TypeError):
            pass

    # 2. Via les classes spécifiques PrestaShop de prix courant
    if base_price is None:
        for p_sel in soup.select('.current-price-value, span.price, .product-prices .price'):
            p_txt = p_sel.get_text(strip=True)
            m = re.search(r'(\d+[.,]\d{2})', p_txt.replace('\xa0', '').replace(',', '.'))
            if m:
                try:
                    base_price = float(m.group(1))
                    break
                except ValueError:
                    pass

    # 3. Dernier recours : chercher le premier montant en euros directement dans le texte de la page
    if base_price is None:
        m = re.search(r'(\d+[.,]\d{2})\s*€', page_text)
        if m:
            try:
                base_price = float(m.group(1).replace(',', '.'))
            except ValueError:
                pass
    # --------------------------------------------------------

    results = []
    for v in variants:
        is_valid = any(w in v["label"].lower() for w in INCLUDE_WORDS) or v["weight"] is not None
        
        results.append({
            "brand": "Les Jardins de Gaïa",
            "market": market,
            "url": url,
            "name": name,
            "tea_type": tea_type,
            "origin_country": origin,
            "format_valid": is_valid,
            "pochette_label": v["label"],
            "weight": v["weight"],
            "price_eur": base_price,
        })

    return results


class JardinsGaiaSpider(scrapy.Spider):
    name = "jardins_gaia_spider"

    def __init__(self, shops_config=None, max_products=None, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.shops_config = shops_config or []
        self.max_products = int(max_products) if max_products else None
        self.seen_products = set()

    def start_requests(self):
        for shop in self.shops_config:
            yield scrapy.Request(shop["url"], callback=self.parse, cb_kwargs={"market": shop["market"]})

    async def start(self):
        for req in self.start_requests():
            yield req

    def parse(self, response, market):
        links = response.css("article.product-miniature a::attr(href), .product-description a::attr(href), a.thumbnail::attr(href)").getall()
        for link in links:
            url = response.urljoin(link).split("#")[0].split("?")[0]
            if any(b in url for b in ("/cart", "/checkout", "/account", "/tisanes", "/infusions", "/accessoires", "/coffrets", "/epices")):
                continue
            if not url.endswith(".html"):
                continue
            if url in self.seen_products:
                continue
            if self.max_products and len(self.seen_products) >= self.max_products:
                return
            self.seen_products.add(url)
            yield response.follow(url, callback=self.parse_product, cb_kwargs={"market": market})

        if not self.max_products or len(self.seen_products) < self.max_products:
            next_page = response.css("a.next::attr(href), .pagination a.js-search-link::attr(href)").get()
            if next_page:
                yield response.follow(next_page, callback=self.parse, cb_kwargs={"market": market})

    def parse_product(self, response, market):
        soup = BeautifulSoup(response.text, "html.parser")
        rows = extract_product_variants(soup, response.url, market)
        for data in rows:
            if data["format_valid"]:
                RAW_PAGES.append(data)
                self.logger.info(f"OK : {data['name']} | {data['tea_type']} | Origine: {data['origin_country']} | Poids: {data['weight']} | {data['price_eur']}€")


def run_scraper(max_products=None):
    shops = [{"url": "https://www.jardinsdegaia.com/fr/16-types-de-thes", "market": "FR"}]

    process = CrawlerProcess(settings={
        "USER_AGENT": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36",
        "ROBOTSTXT_OBEY": False,
        "DOWNLOAD_DELAY": 1.5,
        "LOG_LEVEL": "INFO",
    })

    process.crawl(JardinsGaiaSpider, shops_config=shops, max_products=max_products)
    process.start()

    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        json.dump(RAW_PAGES, f, indent=2, ensure_ascii=False)
    print(f"\n[Terminé] {len(RAW_PAGES)} lignes enregistrées dans {OUTPUT_FILE}")


if __name__ == "__main__":
    run_scraper(max_products=None)