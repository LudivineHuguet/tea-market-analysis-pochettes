import os
import json
import re
import time
import random
import unicodedata
from urllib.parse import urljoin
from bs4 import BeautifulSoup, Comment
from curl_cffi import requests as cr

# ----------------------------------------------------------------------
# Settings
# ----------------------------------------------------------------------
TARGET_DIR = "."
OUTPUT_FILE = os.path.join(TARGET_DIR, "thes_de_la_pagode_raw_results.json")
CATALOG_URL = "https://www.thesdelapagode.com/fr/51-thes-en-vrac"
MARKET = "FR"

MAX_PRODUCTS = None     # None = tout le catalogue vrac ; mettre 5 pour tester
MAX_CATALOG_PAGES = 10
DELAY_MIN, DELAY_MAX = 2.0, 4.0
IMPERSONATE = "chrome"

# Mots d'URL qui ne sont pas des thés en vrac (sachets, boîtes, infusettes, packs santé "...30")
URL_EXCLUDE = ("sachet", "infusette", "boite", "fld30", "/panier", "/commande", "/mon-compte")

# 1) Pays écrits explicitement (nom ou adjectif) -> origine sûre. Clés sans accents, en minuscules.
COUNTRY_MAP = {
    "chine": "Chine", "chinois": "Chine", "chinoise": "Chine",
    "inde": "Inde", "sri lanka": "Sri Lanka", "ceylan": "Sri Lanka",
    "japon": "Japon", "japonais": "Japon", "japonaise": "Japon", "japan": "Japon",
    "taiwan": "Taïwan", "nepal": "Népal", "kenya": "Kenya",
    "coree": "Corée du Sud", "coree du sud": "Corée du Sud", "vietnam": "Vietnam",
    "thailande": "Thaïlande", "indonesie": "Indonésie", "afrique du sud": "Afrique du Sud",
    "argentine": "Argentine", "bresil": "Brésil", "paraguay": "Paraguay",
}
# 2) Terroirs / thés typiques d'un pays -> origine DÉDUITE (moins sûre : un "Sencha" peut venir de Chine).
TERROIR_MAP = {
    "yunnan": "Chine", "fujian": "Chine", "keemun": "Chine", "longjing": "Chine", "gunpowder": "Chine",
    "pu-erh": "Chine", "puerh": "Chine", "chun mee": "Chine", "pai mu tan": "Chine", "lapsang": "Chine",
    "assam": "Inde", "darjeeling": "Inde", "nilgiri": "Inde",
    "sencha": "Japon", "genmaicha": "Japon", "gyokuro": "Japon", "matcha": "Japon", "hojicha": "Japon",
    "formose": "Taïwan",
}

# Origines à compléter à la main pour les thés dont le site ne dit rien (nom en minuscules -> pays).
# Exemple : {"thé vert earl grey": "Chine"}. Elles priment sur la détection (origin_source = "manuel").
ORIGIN_OVERRIDES = {}

# Lien de format d'une fiche : "Vrac 100g", "Boite 100g", "20 sachets"
FORMAT_LINK_RE = re.compile(r"^(vrac|bo[iî]te|\d+\s*(?:sachets?|infusettes?))", re.I)
# "Vrac 100g", "Vrac 500 g", "Vrac 1kg" : le format affiché sur la fiche (jamais deviné)
VRAC_RE = re.compile(r"\bvrac\s*\d+(?:[.,]\d+)?\s*(?:kg|g)\b", re.I)
STOP_RE = r"(?:Description|Composition|Les secrets de production|Le brevet|Nos engagements|Nos certifications|Avis clients)"
TYPE_RE = re.compile(r"\b(th[ée]\s+(?:noir|vert|blanc|oolong|sombre)|rooibos|infusion|tisane|matcha|maté)\b", re.I)


def fold(text):
    t = unicodedata.normalize("NFKD", text or "")
    return "".join(c for c in t if not unicodedata.combining(c)).lower()


def _rx(mapping):
    keys = sorted(mapping, key=len, reverse=True)
    return re.compile(r"(?<![a-z0-9])(" + "|".join(re.escape(k) for k in keys) + r")(?![a-z0-9])")


COUNTRY_RE, TERROIR_RE = _rx(COUNTRY_MAP), _rx(TERROIR_MAP)


def parse_weight(text):
    m = re.search(r'(\d+(?:[.,]\d+)?)\s*(g|kg)\b', text or '', re.I)
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


def tea_sentences(desc):
    """Phrases de la description qui parlent du thé (pas d'un ingrédient : « le yuzu, agrume japonais »)."""
    sentences = re.split(r"(?<=[.!?])\s+", desc or "")
    return " ".join(s for s in sentences if re.search(r"\bthes?\b|jardin|plantation", fold(s)))


def detect_origin(name, desc, comp):
    """Pays d'où vient le thé -> (pays, source). Un pays écrit prime sur un terroir ;
    dans chaque cas : composition, puis description, puis nom. Aucun pays par défaut."""
    for rx, mapping, kind in ((COUNTRY_RE, COUNTRY_MAP, "pays"), (TERROIR_RE, TERROIR_MAP, "terroir")):
        for where, text in (("composition", comp), ("description", tea_sentences(desc)), ("nom", name)):
            hits = detect(text, rx, mapping)
            if hits:
                return ", ".join(hits), f"{kind}:{where}"
    return "Non précisé", None


def detect_tea_type(url, text):
    url_lower = url.lower()
    for key, label in (("the-vert", "Thé vert"), ("the-noir", "Thé noir"), ("the-blanc", "Thé blanc"),
                       ("the-oolong", "Thé oolong"), ("the-wulong", "Thé oolong"), ("matcha", "Matcha"),
                       ("rooibos", "Rooibos"), ("infusion", "Infusion"), ("tisane", "Infusion")):
        if key in url_lower:
            return label
    m = TYPE_RE.search(text)
    return m.group(1).capitalize() if m else "Thé"


def product_text(soup, h1=None):
    """Texte de la fiche : de son titre (h1) jusqu'à « Vous aimerez aussi ».
    Le menu, le pied de page et les produits suggérés (avec leurs « 30 sachets ») sont ainsi ignorés."""
    h1 = h1 or soup.select_one("h1")
    parts = []
    for s in (h1.find_all_next(string=True) if h1 else soup.stripped_strings):
        if isinstance(s, Comment) or (getattr(s, "parent", None) is not None and s.parent.name in ("script", "style", "noscript")):
            continue
        s = " ".join(str(s).split())
        if not s:
            continue
        if "aimerez aussi" in s.lower():
            break
        parts.append(s)
    return " ".join(parts)


def current_format(soup, url):
    """Format du produit affiché : le lien de format (« Vrac 100g », « Boite 100g »…) qui pointe vers cette fiche."""
    for a in soup.select("a[href]"):
        label = " ".join(a.get_text(" ").split())
        if FORMAT_LINK_RE.match(label) and urljoin(url, a["href"]).split("#")[0].split("?")[0] == url:
            return label
    return None


def section(text, title):
    """Contenu d'une rubrique de la fiche (« Description », « Composition »)."""
    m = re.search(rf"\b{title}\s+(.{{3,3000}}?)(?=\s+{STOP_RE}\b|$)", text)
    return m.group(1) if m else ""


def page_price(soup):
    price_el = soup.select_one('meta[property="product:price:amount"], meta[property="og:price:amount"], [itemprop="price"]')
    if price_el:
        try:
            return float((price_el.get("content") or price_el.get("value") or "").replace('\xa0', '').replace(' ', '').replace(',', '.'))
        except (ValueError, TypeError):
            pass
    for p_sel in soup.select('.current-price-value, .current-price span, span.price, .product-prices .price'):
        m = re.search(r'(\d+[.,]\d{2})', p_sel.get_text(strip=True).replace('\xa0', '').replace(' ', ''))
        if m:
            return float(m.group(1).replace(',', '.'))
    return None


def extract_product_variants(soup, url, market):
    if any(w in url.lower() for w in URL_EXCLUDE):
        return []

    h1 = soup.select_one("h1.h1, h1.page-title, h1[itemprop='name'], h1")
    name = h1.get_text(" ", strip=True) if h1 else "Inconnu"
    text = product_text(soup, h1)

    # Thés en vrac uniquement : si la fiche affiche une boîte ou des sachets, on l'écarte
    shown = current_format(soup, url)
    if shown and not VRAC_RE.match(shown):
        return []

    # Formats vrac réellement affichés sur la fiche ("Vrac 100g") ; sans eux, ce n'est pas un thé en vrac (ex. lot de 3)
    vrac, seen = [], set()
    for m in VRAC_RE.finditer(text):
        w = parse_weight(m.group(0))
        if w and w not in seen:
            seen.add(w)
            vrac.append({"label": " ".join(m.group(0).split()), "weight": w})
    if not vrac:
        return []

    meta = soup.select_one('meta[name="description"], meta[property="og:description"]')
    desc = section(text, "Description") or (meta.get("content", "") if meta else "")
    comp = section(text, "Composition")
    origin, origin_source = detect_origin(name, desc, comp)
    if name.lower() in ORIGIN_OVERRIDES:
        origin, origin_source = ORIGIN_OVERRIDES[name.lower()], "manuel"
    price = page_price(soup)

    return [{
        "brand": "Thés de la Pagode", "market": market, "url": url, "name": name,
        "tea_type": detect_tea_type(url, text), "origin_country": origin, "origin_source": origin_source,
        "format_valid": True, "pochette_label": v["label"], "weight": v["weight"],
        # le prix affiché est celui du format de la page ; s'il y a plusieurs tailles on ne l'attribue qu'à la première
        "price_eur": price if i == 0 else None,
    } for i, v in enumerate(vrac)]


def fetch(session, url, tries=3):
    """GET avec nouvelles tentatives : un échec n'est plus ignoré en silence."""
    for i in range(tries):
        try:
            resp = session.get(url, headers={"Accept-Language": "fr-FR,fr;q=0.9"}, timeout=30)
            if resp.status_code == 200:
                return resp
            print(f"[HTTP {resp.status_code}] {url} (essai {i + 1}/{tries})")
        except Exception as e:
            print(f"[ERREUR] {url} : {e} (essai {i + 1}/{tries})")
        time.sleep(random.uniform(DELAY_MIN, DELAY_MAX) * (i + 1))
    return None


def collect_product_links(max_limit=None):
    session = cr.Session(impersonate=IMPERSONATE)
    links, seen = [], set()

    for page in range(1, MAX_CATALOG_PAGES + 1):
        page_url = f"{CATALOG_URL}?page={page}" if page > 1 else CATALOG_URL
        resp = fetch(session, page_url)
        if not resp:
            break

        soup = BeautifulSoup(resp.text, "html.parser")
        candidates = soup.select('.product-miniature a[href*=".html"], .product-title a[href*=".html"], a.product-thumbnail[href*=".html"], #js-product-list a[href*=".html"]')

        new_on_page = 0
        for a in candidates:
            href = a.get("href")
            if not href:
                continue
            abs_url = urljoin(page_url, href).split('#')[0].split('?')[0]

            if any(b in abs_url for b in URL_EXCLUDE):
                continue

            if re.search(r'/\d+-[^/]+\.html$', abs_url) and abs_url not in seen:
                seen.add(abs_url)
                links.append(abs_url)
                new_on_page += 1

                if max_limit and len(links) >= max_limit:
                    return links

        # Si aucune page suivante ne rapporte de nouveaux produits, on arrête la pagination
        if new_on_page == 0:
            break
        time.sleep(random.uniform(DELAY_MIN, DELAY_MAX))

    return links[:max_limit] if max_limit else links


def run_scraper():
    os.makedirs(TARGET_DIR, exist_ok=True)
    product_links = collect_product_links(MAX_PRODUCTS)
    print(f"[Info] {len(product_links)} produits uniques trouvés au total.")

    session = cr.Session(impersonate=IMPERSONATE)
    results, ignored = [], []

    for url in product_links:
        time.sleep(random.uniform(DELAY_MIN, DELAY_MAX))
        resp = fetch(session, url)
        if not resp:
            ignored.append((url, "page inaccessible"))
            continue
        rows = extract_product_variants(BeautifulSoup(resp.text, "html.parser"), url, MARKET)
        if not rows:
            ignored.append((url, "pas de format « Vrac » sur la fiche"))
            print(f"[IGNORÉ] {url}")
            continue
        for data in rows:
            results.append(data)
            print(f"OK : {data['name']} | {data['tea_type']} | Origine: {data['origin_country']} ({data['origin_source']}) | Poids: {data['weight']} | {data['price_eur']}€")

    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        json.dump(results, f, indent=2, ensure_ascii=False)
    print(f"\n[Terminé] {len(results)} lignes enregistrées dans {OUTPUT_FILE} ({len(ignored)} produits ignorés)")
    for url, why in ignored:
        print(f"   - {why} : {url}")

    print("\n[ORIGINES]")
    for name in dict.fromkeys(r["name"] for r in results):
        r = next(x for x in results if x["name"] == name)
        print(f"   {name:38s} -> {r['origin_country']}  ({r['origin_source'] or 'non publiée par le site'})")
    missing = [n for n in dict.fromkeys(r["name"] for r in results) if next(x for x in results if x["name"] == n)["origin_country"] == "Non précisé"]
    if missing:
        print(f"\n{len(missing)} thé(s) sans origine sur le site : complétez ORIGIN_OVERRIDES si vous la connaissez.")


if __name__ == "__main__":
    run_scraper()