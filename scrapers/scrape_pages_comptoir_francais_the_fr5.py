import os
import json
import re
import unicodedata
from bs4 import BeautifulSoup
from curl_cffi import requests

TARGET_DIR = "."
OUTPUT_FILE = os.path.join(TARGET_DIR, "comptoir_francais_the_raw_results.json")
RAW_PAGES = []

MAX_PRODUCTS = None  # None = tout le catalogue ; mettre 5 pour tester
BASE_URL = "https://comptoir-francais-du-the.fr"

# Les mots "France", "Français", "Alsace" ne sont JAMAIS lus comme une origine :
# ils viennent du nom de la marque et du pied de page, pas du thé.

# 1) Pays écrits explicitement (nom ou adjectif) -> origine sûre. Clés sans accents, en minuscules.
#    ("indien" est volontairement absent : "océan Indien" donnerait de fausses origines.)
COUNTRY_MAP = {
    "chine": "Chine", "chinois": "Chine", "chinoise": "Chine",
    "inde": "Inde",
    "sri lanka": "Sri Lanka", "ceylan": "Sri Lanka", "ceylanais": "Sri Lanka",
    "japon": "Japon", "japan": "Japon", "japonais": "Japon", "japonaise": "Japon",
    "taiwan": "Taïwan", "taiwanais": "Taïwan",
    "nepal": "Népal", "nepalais": "Népal",
    "kenya": "Kenya",
    "coree": "Corée du Sud", "coree du sud": "Corée du Sud",
    "vietnam": "Vietnam", "vietnamien": "Vietnam",
    "thailande": "Thaïlande", "indonesie": "Indonésie", "malawi": "Malawi",
    "tanzanie": "Tanzanie", "rwanda": "Rwanda", "birmanie": "Birmanie",
    "georgie": "Géorgie", "turquie": "Turquie",
    "afrique du sud": "Afrique du Sud", "argentine": "Argentine",
    "bresil": "Brésil", "paraguay": "Paraguay", "colombie": "Colombie", "perou": "Pérou",
}
# 2) Terroirs et thés typiques d'un pays -> origine DÉDUITE du nom (moins sûre : un "Sencha" peut venir de Chine).
TERROIR_MAP = {
    "yunnan": "Chine", "fujian": "Chine", "keemun": "Chine", "longjing": "Chine", "lung ching": "Chine",
    "pu-erh": "Chine", "pu erh": "Chine", "pu ehr": "Chine", "puerh": "Chine", "gunpowder": "Chine",
    "chun mee": "Chine", "pai mu tan": "Chine", "bai mu dan": "Chine", "lapsang": "Chine",
    "assam": "Inde", "darjeeling": "Inde", "nilgiri": "Inde",
    "sencha": "Japon", "genmaicha": "Japon", "kukicha": "Japon", "gyokuro": "Japon",
    "matcha": "Japon", "hojicha": "Japon", "bancha": "Japon", "uji": "Japon",
    "formose": "Taïwan",
}

EXCLUDE_WORDS = ("boîte", "boite", "sachet", "sachets", "coffret", "tasse", "mousseline")
INCLUDE_WORDS = ("poche vrac", "poche", "vrac", "100g", "250g", "500g", "1kg")

TYPE_RE = re.compile(r"\b(th[ée]\s+(?:noir|vert|blanc|oolong|sombre|jaune)|rooibos|infusion|tisane|matcha|maté)\b", re.I)
# "Poche vrac – Code article 901151 – Code EAN 3700476801862 – Poids net 1kg"
PACK_RE = re.compile(r"((?:poche|boite|boîte|sachet|doypack)[^–]{0,40}?)\s*–\s*Code article.{0,80}?Poids net\s*(\d+(?:[.,]\d+)?\s*(?:kg|g))\b", re.I)


def fold(text):
    t = unicodedata.normalize("NFKD", text or "")
    return "".join(c for c in t if not unicodedata.combining(c)).lower()


def _rx(mapping):
    keys = sorted(mapping, key=len, reverse=True)
    return re.compile(r"(?<![a-z0-9])(" + "|".join(re.escape(k) for k in keys) + r")(?![a-z0-9])")


COUNTRY_RE, TERROIR_RE = _rx(COUNTRY_MAP), _rx(TERROIR_MAP)


def parse_weight(text):
    m = re.search(r'(\d+(?:[.,]\d+)?)\s*(kg|g)\b', text or '', re.I)
    if not m:
        return None
    val, unit = m.group(1), m.group(2).lower()
    return f"{int(float(val.replace(',', '.')) * 1000)}g" if unit == "kg" else f"{val}g"


def detect(text, rx, mapping):
    """Pays trouvés dans le texte, dans l'ordre d'apparition, sans doublon."""
    hits = []
    for m in rx.finditer(fold(text)):
        if mapping[m.group(1)] not in hits:
            hits.append(mapping[m.group(1)])
    return hits


def detect_origin(name, desc, page):
    """Origine du thé -> (pays, source). On cherche d'abord un pays écrit, puis seulement un terroir.
    Dans chaque cas : nom du produit, puis description courte, puis texte de la fiche."""
    for rx, mapping, kind in ((COUNTRY_RE, COUNTRY_MAP, "pays"), (TERROIR_RE, TERROIR_MAP, "terroir")):
        for where, text in (("nom", name), ("description", desc), ("fiche", page)):
            hits = detect(text, rx, mapping)
            if hits:
                return ", ".join(hits), f"{kind}:{where}"
    return "Non précisé", None


def find_name(soup):
    h1 = soup.select_one("h1.product_title, h1.entry-title, h1")
    if h1 and h1.get_text(strip=True):
        return h1.get_text(" ", strip=True)
    og = soup.select_one('meta[property="og:title"]')
    return og["content"].strip() if og and og.get("content") else "Inconnu"


def get_variations(soup):
    """Variations WooCommerce (prix par conditionnement), vide si le site ne les fournit pas."""
    form = soup.select_one("form.variations_form[data-product_variations]")
    try:
        data = json.loads(form["data-product_variations"]) if form else []
    except ValueError:
        data = []
    return data if isinstance(data, list) else []


def page_price(soup):
    el = soup.select_one('meta[property="product:price:amount"]')
    if el and el.get("content"):
        try:
            return float(el["content"])
        except ValueError:
            pass
    el = soup.select_one(".price ins .woocommerce-Price-amount, .price .woocommerce-Price-amount, span.price")
    m = re.search(r'(\d+[.,]\d{2})', el.get_text().replace('\xa0', '')) if el else None
    return float(m.group(1).replace(',', '.')) if m else None


def clean_page(soup):
    """Retire menu, pied de page et 'Vous aimerez aussi' pour ne garder que le texte du produit."""
    for h in soup.find_all(["h2", "h3"]):
        if "aimerez aussi" in h.get_text().lower():
            ul = h.find_next_sibling("ul")
            if ul:
                ul.decompose()
            h.decompose()
    for el in soup.select("header, footer, nav, script, style, .related, .upsells"):
        if not getattr(el, "decomposed", False):
            el.decompose()
    main = soup.select_one("main, #primary, #content") or soup
    return " ".join(main.get_text(" ", strip=True).split())


def pack_weight(packs, label):
    """Poids net du conditionnement dont le nom correspond au libellé ('Vrac' <-> 'Poche vrac')."""
    key = fold(label)
    return next((w for l, w in packs if key in fold(l) or fold(l) in key), None)


def extract_product_variants(soup, url, market):
    name = find_name(soup)
    meta = soup.select_one('meta[name="description"], meta[property="og:description"]')
    desc = meta["content"].strip() if meta and meta.get("content") else ""
    variations = get_variations(soup)      # à lire AVANT le nettoyage de la page
    price = page_price(soup)
    options = soup.select("select[name^='attribute_'] option")
    text = clean_page(soup)

    # Type de thé
    m = TYPE_RE.search(name + " " + desc) or TYPE_RE.search(text)
    tea_type = m.group(1).capitalize() if m else "Thé"

    # Origine : le pays où pousse le thé (jamais un défaut "France")
    origin_country, origin_source = detect_origin(name, desc, text)

    # Conditionnements de la fiche : [("Poche vrac", "1000g"), ("Boite métal", "100g"), ...]
    packs = [(" ".join(l.split()), parse_weight(w)) for l, w in PACK_RE.findall(text)]
    vrac_weight = next((w for l, w in packs if "vrac" in fold(l)), None)

    variants = []
    for opt in options:
        label = opt.get_text(strip=True)
        low = label.lower()
        if not opt.get("value") or any(w in low for w in EXCLUDE_WORDS):
            continue
        if any(w in low for w in INCLUDE_WORDS) or parse_weight(label):
            # Prix de CE conditionnement (la fiche affiche sinon la fourchette 12€ – 47€)
            v_price = next((v.get("display_price") for v in variations
                            if opt["value"] in (v.get("attributes") or {}).values()), None)
            variants.append({"label": label, "price": v_price, "valid": True,
                             "weight": parse_weight(label) or pack_weight(packs, label)})

    if not variants:
        if packs and vrac_weight is None:   # produit sans poche vrac (ex. boîte métal seule)
            variants.append({"label": packs[0][0], "price": price, "weight": packs[0][1], "valid": False})
        else:
            variants.append({"label": "Poche vrac", "price": price, "valid": True,
                             "weight": vrac_weight or parse_weight(desc)})

    return [{
        "brand": "Le Comptoir Français du Thé",
        "market": market,
        "url": url,
        "name": name,
        "tea_type": tea_type,
        "origin_country": origin_country,
        "origin_source": origin_source,
        "format_valid": v["valid"],
        "pochette_label": v["label"],
        "weight": v["weight"],
        "price_eur": v["price"],
    } for v in variants]


def run_scraper():
    os.makedirs(TARGET_DIR, exist_ok=True)

    categories = [
        BASE_URL + "/categorie-produit/thes-natures/",
        BASE_URL + "/categorie-produit/thes-aromatises/"
    ]

    session = requests.Session(impersonate="chrome")
    seen_products = set()
    done = False

    for cat_url in categories:
        current_url = cat_url
        while current_url and not done:
            print(f"[CATALOGUE] Page en cours : {current_url}")
            resp = session.get(current_url)
            if resp.status_code != 200:
                print(f"[ERREUR] Impossible d'accéder à {current_url} (Code: {resp.status_code})")
                break

            soup = BeautifulSoup(resp.text, "html.parser")

            product_links = soup.select('ul.products li.product a.woocommerce-LoopProduct-link, ul.products li a[href*="/catalogue-produit/"], ul.products li a[href*="/produit/"]')
            for a in product_links:
                href = a.get("href")
                if not href:
                    continue

                url = href.split('#')[0].split('?')[0]
                if url in seen_products:
                    continue
                if '/categorie-produit/' in url or '/panier' in url or '/mon-compte' in url:
                    continue
                if MAX_PRODUCTS and len(seen_products) >= MAX_PRODUCTS:
                    done = True
                    break

                seen_products.add(url)

                print(f"[PRODUIT] Téléchargement : {url}")
                prod_resp = session.get(url)
                if prod_resp.status_code == 200:
                    prod_soup = BeautifulSoup(prod_resp.text, "html.parser")
                    rows = extract_product_variants(prod_soup, url, "FR")
                    for data in rows:
                        RAW_PAGES.append(data)
                        print(f"   -> OK : {data['name']} | Origine: {data['origin_country']} ({data['origin_source']}) | {data['weight']} | {data['price_eur']}€")
                else:
                    print(f"   -> Erreur HTTP {prod_resp.status_code}")

            next_page_el = soup.select_one('a.next.page-numbers, .woocommerce-pagination a.next')
            if next_page_el and next_page_el.get('href') and not done:
                next_href = next_page_el.get('href')
                current_url = next_href if next_href.startswith("http") else BASE_URL + next_href
            else:
                break

    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        json.dump(RAW_PAGES, f, indent=2, ensure_ascii=False)
    print(f"\n[Terminé] {len(RAW_PAGES)} lignes enregistrées dans {OUTPUT_FILE}")


if __name__ == "__main__":
    run_scraper()