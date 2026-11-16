import json
import os
import re
import unicodedata
from collections import Counter, defaultdict
from urllib.parse import urlencode, urlsplit

import scrapy
from bs4 import BeautifulSoup, Comment
from scrapy.crawler import CrawlerProcess

try:
    import lxml  # noqa: F401
    PARSER = "lxml"
except ImportError:
    PARSER = "html.parser"

OUTPUT_FILE = "compagnie_raw_results.json"
DEBUG_DIR = "debug_html_compagnie"
DEBUG_MAX_PAGES = 5

# Formats à exclure / à conserver pour Compagnie & Co (comparés en minuscules)
EXCLUDE_WORDS = ("boîte", "boite", "métal", "metal", "coffret", "tasse", "mousseline")
INCLUDE_WORDS = ("format sac vrac", "format doypack", "format sachet recharge vrac", "sac vrac", "doypack", "recharge", "sachet", "vrac")

# Dénominations de format suivies d'un poids : "Sac vrac 1 Kg", "Sachet recharge 100g", "Doypack 50g"
LABEL_RE = re.compile(
    r"((?:format\s+)?(?:sac\s+vrac|doypack|sachet\s+recharge\s+vrac|pochette|sachet|recharge)(?:\s+vrac)?\s*(?:de\s+)?"
    r"\d+(?:[.,]\d+)?\s*(?:kg|grammes?|gr|g))\b",
    re.I,
)
PRICE_RE = re.compile(r"(\d{1,4}(?:[.,]\d{1,2})?)\s*€")
GROUP_RE = re.compile(r"group\[(\d+)\]")

# Mots-clés de format (sans accents) pour relier un poids à la bonne déclinaison
FORMAT_KEYS = ("sac vrac", "doypack", "recharge")
OTHER_FORMAT_WORDS = FORMAT_KEYS + ("boite", "metal", "mousseline", "coffret", "sachet")

# Poids « standard » d'un format, utilisé UNIQUEMENT si le site n'en donne aucun (weight_source = "format_default").
# Constaté sur le site : "Sachet recharge 100g" (Hojicha, Darjeeling), "Doypack 50g" (Ubé Violet, Matcha Premium).
# Pas de valeur pour "sac vrac" : 500g pour le matcha, 1 Kg pour le Caravane... Mettre False pour désactiver.
USE_FORMAT_DEFAULTS = True
FORMAT_DEFAULT_WEIGHTS = {"recharge": "100g", "doypack": "50g"}

TEA_TYPES = {
    "Thé vert": 1,
    "Thé noir": 2,
    "Thé oolong": 3,
    "Thé blanc": 4,
    "Matcha": 5,
    "Rooibos": 6,
    "Infusion": 7,
}
SUBTITLE_TYPE_RE = re.compile(
    r"\b(thé\s+(?:vert|noir|blanc|jaune|oolong|sombre|bleu)|matcha|maté|mate|rooibos|infusion)\b", re.I
)

# Origines = catégories « Thés d'origines » du menu du site (une page liste par pays)
ORIGIN_PAGES = {
    "Japon": "https://www.compagnie-co.com/fr/180-the-japonais",
    "Sri Lanka": "https://www.compagnie-co.com/fr/184-the-ceylan",   # « Thé Ceylan » sur le site
    "Chine": "https://www.compagnie-co.com/fr/181-the-chine",
    "Inde": "https://www.compagnie-co.com/fr/182-the-inde",
    "Népal": "https://www.compagnie-co.com/fr/186-the-du-nepal",
    "Kenya": "https://www.compagnie-co.com/fr/185-the-kenya",
    "Taïwan": "https://www.compagnie-co.com/fr/183-the-taiwan",
}
ORIGIN_ALIASES = {
    "japon": "Japon", "japonais": "Japon", "japonaise": "Japon",
    "ceylan": "Sri Lanka", "sri lanka": "Sri Lanka",
    "chine": "Chine",
    "inde": "Inde",
    "nepal": "Népal",
    "kenya": "Kenya",
    "taiwan": "Taïwan",
}
ORIGIN_SUBTITLE_RE = re.compile(
    r"\b(" + "|".join(re.escape(k) for k in sorted(ORIGIN_ALIASES, key=len, reverse=True)) + r")\b"
)


# ----------------------------------------------------------------------
# Utilitaires
# ----------------------------------------------------------------------
def norm(text):
    return re.sub(r"\s+", " ", text or "").strip()


def fold(text):
    t = unicodedata.normalize("NFKD", text or "")
    return "".join(c for c in t if not unicodedata.combining(c)).strip().casefold()


def parse_weight(text):
    m = re.search(r"(\d+(?:[.,]\d+)?)\s*(kg|grammes?|gr|g)\b", text or "", re.I)
    if not m:
        return None
    unit = "kg" if m.group(2).lower() == "kg" else "g"
    return f"{m.group(1)}{unit}"


def parse_price(text):
    m = PRICE_RE.search(text or "")
    return float(m.group(1).replace(",", ".")) if m else None


def to_float(value):
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        try:
            return float(value.replace(",", ".").strip())
        except ValueError:
            return parse_price(value)
    return None


def is_pochette(label, attr_label=""):
    text = f"{attr_label or ''} {label or ''}".lower()
    if any(w in text for w in EXCLUDE_WORDS):
        return False
    if any(w in text for w in INCLUDE_WORDS):
        return True
    return bool(parse_weight(label))


def clean_url(url):
    return url.split("#")[0].split("?")[0]


def add_query(url, params):
    return url + ("&" if "?" in url else "?") + urlencode(params)


# ----------------------------------------------------------------------
# Lecture de la fiche produit (PrestaShop)
# ----------------------------------------------------------------------
def read_product_data(soup):
    """JSON data-product de la fiche : déclinaison actuellement affichée (prix, attributs...)."""
    el = soup.select_one("[data-product]")
    if el:
        try:
            return json.loads(el.get("data-product", "")) or {}
        except (ValueError, TypeError):
            pass
    return {}


def meta_price(soup):
    el = soup.select_one('meta[property="product:price:amount"]')
    try:
        return float(el["content"]) if el and el.get("content") else None
    except ValueError:
        return None


def page_price(soup, data):
    """Prix TTC de la déclinaison affichée -> (prix, source)."""
    for key in ("price_amount", "price"):
        p = to_float(data.get(key))
        if p is not None:
            return p, "data_product"
    p = meta_price(soup)
    if p is not None:
        return p, "meta_price"
    el = soup.select_one('[itemprop="price"]')
    if el:
        p = to_float(el.get("content")) or parse_price(el.get_text(" "))
        if p is not None:
            return p, "itemprop"
    return None, None


def clean_scope(soup):
    """Retire menu, pied de page et produits suggérés ('Vous aimerez aussi') avant toute recherche de texte."""
    for sel in ("header", "footer", "nav", "#header", "#footer",
                ".product-miniature", ".featured-products", ".product-accessories"):
        for el in soup.select(sel):
            if not getattr(el, "decomposed", False):
                el.decompose()


def option_label(el):
    for attr in ("title", "data-title", "aria-label"):
        v = norm(el.get(attr))
        if v:
            return v
    sib = el.find_next_sibling(["span", "label"])
    if sib and norm(sib.get_text(" ")):
        return norm(sib.get_text(" "))
    return norm(el.parent.get_text(" ")) if el.parent else ""


def format_options(soup):
    """Options du sélecteur 'Conditionnement' : [{group, value, label, selected}]."""
    options = []
    for inp in soup.select('input[name^="group["]'):
        m = GROUP_RE.match(inp.get("name", ""))
        if m and inp.get("value"):
            options.append({"group": m.group(1), "value": inp["value"],
                            "label": option_label(inp), "selected": inp.has_attr("checked")})
    for sel in soup.select('select[name^="group["]'):
        m = GROUP_RE.match(sel.get("name", ""))
        if not m:
            continue
        for opt in sel.find_all("option"):
            if opt.get("value"):
                options.append({"group": m.group(1), "value": opt["value"],
                                "label": norm(opt.get_text(" ")), "selected": opt.has_attr("selected")})
    return options


def selected_value(soup, group, data):
    inp = soup.select_one(f'input[name="group[{group}]"][checked]')
    if inp:
        return inp.get("value")
    opt = soup.select_one(f'select[name="group[{group}]"] option[selected]')
    if opt:
        return opt.get("value")
    attrs = data.get("attributes") or {}
    if isinstance(attrs, dict) and str(group) in attrs:
        return str((attrs[str(group)] or {}).get("id_attribute"))
    return None


def format_key(label):
    low = fold(label)
    return next((k for k in FORMAT_KEYS if k in low), None)


def data_weight_g(soup, data):
    """Poids indiqué dans les données de la page (peut inclure l'emballage) -> grammes, ou None."""
    value, unit = to_float(data.get("weight")), str(data.get("weight_unit") or "kg").lower()
    if not value:
        for script in soup.find_all("script", type="application/ld+json"):
            try:
                obj = json.loads(script.string or script.get_text() or "")
            except ValueError:
                continue
            for item in (obj if isinstance(obj, list) else [obj]):
                w = item.get("weight") if isinstance(item, dict) else None
                if isinstance(w, dict):
                    value, unit = to_float(w.get("value")), str(w.get("unitCode") or "kg").lower()
                    break
            if value:
                break
    if not value:
        return None
    grams = round(value * (1 if unit in ("g", "gr", "grm", "gram") else 1000), 1)
    return int(grams) if grams == int(grams) else grams


def image_texts(soup):
    """alt/title de toutes les images de la fiche (principale + galerie), ex. 'Matcha Premium Bio 50g'."""
    texts = []
    for img in soup.find_all("img"):
        for attr in ("alt", "title"):
            if img.get(attr):
                texts.append(img[attr])
    return texts


def image_weight(texts, key):
    """Poids lu dans les images. Une image qui cite un autre format ('Boite métal 100g') est ignorée."""
    keyed, plain = [], []
    for t in texts:
        w = parse_weight(t)
        if not w:
            continue
        low = fold(t)
        if any(k in low for k in OTHER_FORMAT_WORDS):
            if key and key in low:
                keyed.append(w)
        else:
            plain.append(w)
    for group in (keyed, plain):
        if group and len(set(group)) == 1:   # des poids contradictoires = on ne tranche pas
            return group[0]
    return None


def zone_texts(soup):
    yield soup.get_text(" ")
    for el in soup.find_all(True):
        for attr in ("alt", "title"):
            if el.get(attr):
                yield el[attr]


def find_weight(soup, label, image_ok):
    """Poids d'une déclinaison -> (poids, source). Jamais deviné ici : None si introuvable."""
    w = parse_weight(label)
    if w:
        return w, "label"
    key = format_key(label)
    if image_ok:   # les images de la page correspondent bien à ce format
        w = image_weight(image_texts(soup), key)
        if w:
            return w, "image_alt"
    if key:   # texte propre au produit citant ce format : "Sac vrac 1 Kg", "recharge 100g"
        for t in zone_texts(soup):
            for m in LABEL_RE.finditer(norm(t)):
                if key in fold(m.group(1)):
                    w = parse_weight(m.group(1))
                    if w:
                        return w, "page_text"
    return None, None


def labels_from_dom(scope):
    """Repli sans sélecteur de formats : libellés avec poids dans la zone produit."""
    found, seen = [], set()
    for t in zone_texts(scope):
        for m in LABEL_RE.finditer(norm(t)):
            label = norm(m.group(1))
            k = parse_weight(label) or label.lower()
            if k not in seen:
                seen.add(k)
                found.append(label)
    return found


def make_row(base, label, idx, price, price_source, weight, weight_source, shipping_g=None, own_page=False):
    row = dict(base)
    row.update({
        "_idx": idx,
        "_own_page": own_page,
        "pochette_found": True,
        "pochette_label": label,
        "weight_raw": weight,
        "weight_source": weight_source,
        "shipping_weight_g": shipping_g,
        "price_eur": price,
        "price_source": price_source,
    })
    return row


def not_found_row(base, options_seen):
    row = dict(base)
    row.update({
        "_idx": 0,
        "pochette_found": False,
        "pochette_label": None,
        "weight_raw": None,
        "weight_source": None,
        "shipping_weight_g": None,
        "price_eur": None,
        "price_source": None,
        "options_seen": options_seen,
    })
    return row


def listing_info_from_card(card_text, card_alts, name):
    label = None
    for txt in [card_text] + list(card_alts):
        m = LABEL_RE.search(norm(txt))
        if m:
            label = norm(m.group(1))
            break
    low = card_text.lower()
    unavailable = "bientôt disponible" in low or "indisponible" in low
    return {
        "name": name,
        "label": label,
        "price": None if unavailable else parse_price(card_text),
    }


# ----------------------------------------------------------------------
# Type de thé et origine
# ----------------------------------------------------------------------
def resolve_tea_types(selection):
    if not selection:
        return dict(TEA_TYPES)
    if isinstance(selection, str):
        selection = selection.split(",")
    by_fold = {fold(k): k for k in TEA_TYPES}
    chosen = {}
    for item in selection:
        key = fold(item)
        if not key:
            continue
        if key not in by_fold:
            raise ValueError(f"Type de thé inconnu : {item!r}.")
        chosen[by_fold[key]] = TEA_TYPES[by_fold[key]]
    return chosen


def tea_types_from_subtitle(soup):
    h1 = soup.select_one("h1")
    if not h1:
        return []
    texts = [s.strip() for s in h1.find_all_next(string=True, limit=12) if s.strip()][:4]
    by_fold = {fold(k): k for k in TEA_TYPES}
    found = []
    for m in SUBTITLE_TYPE_RE.finditer(" ".join(texts)):
        raw = norm(m.group(1))
        label = by_fold.get(fold(raw)) or (raw[0].upper() + raw[1:])
        if label not in found:
            found.append(label)
    return found


def subtitle_window(soup, limit=2):
    """Les premiers textes APRÈS le <h1> (le titre lui-même est ignoré)."""
    h1 = soup.select_one("h1")
    if not h1:
        return ""
    texts = []
    for s in h1.find_all_next(string=True, limit=60):
        if isinstance(s, Comment) or s.find_parent("h1") is h1:
            continue
        s = s.strip()
        if s:
            texts.append(s)
        if len(texts) >= limit:
            break
    return " ".join(texts)


def origins_from_subtitle(soup):
    text = fold(subtitle_window(soup))
    found = []
    for m in ORIGIN_SUBTITLE_RE.finditer(text):
        label = ORIGIN_ALIASES.get(m.group(1))
        if label and label not in found:
            found.append(label)
    return found


# ----------------------------------------------------------------------
# Spider Scrapy pour Compagnie & Co
# ----------------------------------------------------------------------
class CompagnieCoSpider(scrapy.Spider):
    name = "compagnie_co_spider"

    def __init__(self, shops_config=None, max_products=None, tea_types=None, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.shops_config = shops_config or []
        self.max_products = int(max_products) if max_products else None
        self.tea_types = resolve_tea_types(tea_types)
        self.seen_products = set()
        self.seq_by_key = {}
        self.types_by_url = defaultdict(set)
        self.origins_by_url = defaultdict(set)
        self.rows = []
        self.debug_saved = 0

    def _initial_requests(self):
        for shop in self.shops_config:
            yield scrapy.Request(
                shop["url"],
                callback=self.parse,
                errback=self.on_error,
                cb_kwargs={"market": shop["market"]},
            )
        market = self.shops_config[0]["market"] if self.shops_config else "FR"
        for label, url in ORIGIN_PAGES.items():
            yield scrapy.Request(
                url,
                callback=self.parse,
                errback=self.on_error,
                cb_kwargs={"market": market, "origin": label},
            )

    async def start(self):
        for request in self._initial_requests():
            yield request

    def start_requests(self):
        yield from self._initial_requests()

    def parse(self, response, market, origin=None):
        discover = origin is None
        found = 0
        for a in response.css(".product-title a, a.product-name, .thumbnail.product-thumbnail"):
            href = a.attrib.get("href") or a.attrib.get("content")
            if not href:
                continue
            url = clean_url(response.urljoin(href))
            path = urlsplit(url).path
            if any(b in path for b in ("/checkout", "/customer", "/cart", "/connexion")):
                continue
            found += 1

            if origin:
                self.origins_by_url[url].add(origin)
            if not discover:
                continue
            if url in self.seen_products:
                continue
            if self.max_products and len(self.seen_products) >= self.max_products:
                continue
            self.seen_products.add(url)
            self.seq_by_key[url] = len(self.seen_products)

            card = a.xpath("ancestor::article[1]")
            card_text = " ".join(card.xpath(".//text()").getall()) if card else ""
            card_alts = card.xpath(".//img/@alt").getall() if card else []
            name = norm(" ".join(a.xpath(".//text()").getall())) or "Inconnu"
            listing = listing_info_from_card(card_text, card_alts, name)

            yield response.follow(
                url,
                callback=self.parse_product,
                errback=self.on_error,
                cb_kwargs={"market": market, "key": url, "listing": listing},
            )

        if not found:
            self.logger.warning("Aucun lien produit trouvé sur %s", response.url)

        keep_going = (not discover) or (not self.max_products or len(self.seen_products) < self.max_products)
        if keep_going:
            next_page = response.css(
                "a.next::attr(href), a[rel='next']::attr(href), link[rel='next']::attr(href), "
                ".page-list .current + li a::attr(href)"
            ).get()
            if next_page:
                yield response.follow(
                    next_page,
                    callback=self.parse,
                    errback=self.on_error,
                    cb_kwargs={"market": market, "origin": origin},
                )

    # -- fiche produit : formats, prix et poids -------------------------
    def parse_product(self, response, market, key, listing=None):
        listing = listing or {}
        soup = BeautifulSoup(response.text, PARSER)

        h1 = soup.select_one("h1")
        name = (h1.get_text(" ", strip=True) if h1 else None) or listing.get("name") or "Inconnu"
        data = read_product_data(soup)
        avail_el = soup.select_one('meta[property="product:availability"]')
        availability = data.get("availability") or (avail_el.get("content") if avail_el else None)
        base = {
            "brand": "Compagnie & Co",
            "market": market,
            "url": key,
            "name": name,
            "availability": availability,
            "_key": key,
            "_seq": self.seq_by_key.get(key, 0),
            "_subtitle_types": tea_types_from_subtitle(soup),
            "_subtitle_origins": origins_from_subtitle(soup),
        }

        options = format_options(soup)
        price_here, price_src = page_price(soup, data)
        ship_here = data_weight_g(soup, data)
        clean_scope(soup)   # la suite ne regarde plus que le produit lui-même

        pochettes = [(i, o) for i, o in enumerate(options) if is_pochette(o["label"])]

        if pochettes:
            for idx, opt in pochettes:
                if opt["selected"]:
                    # Cette déclinaison est celle affichée : prix et image de la page courante
                    weight, wsrc = find_weight(soup, opt["label"], image_ok=True)
                    self.rows.append(make_row(base, opt["label"], idx, price_here,
                                              f"page+{price_src}" if price_src else None,
                                              weight, wsrc, ship_here, own_page=True))
                else:
                    # Autres déclinaisons : on recharge la fiche avec ce format sélectionné
                    yield response.follow(
                        add_query(key, {f"group[{opt['group']}]": opt["value"]}),
                        callback=self.parse_variant,
                        errback=self.on_variant_error,
                        dont_filter=True,
                        cb_kwargs={"base": base, "option": opt, "idx": idx},
                    )
            return

        # Aucun sélecteur de format reconnu : repli sur les libellés avec poids dans la zone produit
        labels = labels_from_dom(soup)
        if labels:
            for idx, label in enumerate(labels):
                price = price_here if len(labels) == 1 else None
                src = f"page+{price_src}" if (price is not None and price_src) else None
                self.rows.append(make_row(base, label, idx, price, src, parse_weight(label), "label"))
            return
        if listing.get("label"):
            self.rows.append(make_row(base, listing["label"], 0, listing.get("price"),
                                      "listing", parse_weight(listing["label"]), "label"))
            return

        self.logger.warning("Aucun format vrac/sac trouvé : %s (options : %s)",
                            response.url, [o["label"] for o in options])
        self._dump(response)
        self.rows.append(not_found_row(base, [o["label"] for o in options]))

    def parse_variant(self, response, base, option, idx):
        soup = BeautifulSoup(response.text, PARSER)
        data = read_product_data(soup)
        shown = selected_value(soup, option["group"], data)
        ok = shown == option["value"]
        if ok:
            price, psrc = page_price(soup, data)
            price_source = f"variant_page+{psrc}" if psrc else None
        else:
            # Le site n'a pas affiché ce format : on préfère un prix vide à un prix faux
            price, price_source = None, "variant_not_selected"
            self.logger.warning("Format %r non sélectionné sur %s (affiché : %s)",
                                option["label"], response.url, shown)
            self._dump(response)
        ship = data_weight_g(soup, data) if ok else None
        clean_scope(soup)
        weight, wsrc = find_weight(soup, option["label"], image_ok=ok)
        self.rows.append(make_row(base, option["label"], idx, price, price_source, weight, wsrc, ship))

    def on_variant_error(self, failure):
        kw = failure.request.cb_kwargs
        self.logger.warning("Échec requête format : %s (%s)", failure.request.url, failure.value)
        self.rows.append(make_row(kw["base"], kw["option"]["label"], kw["idx"],
                                  None, "request_failed", None, None))

    def _dump(self, response):
        if self.debug_saved < DEBUG_MAX_PAGES:
            os.makedirs(DEBUG_DIR, exist_ok=True)
            path = os.path.join(DEBUG_DIR, f"debug_cc_{self.debug_saved}.html")
            with open(path, "w", encoding="utf-8") as f:
                f.write(f"<!-- {response.url} -->\n" + response.text)
            self.debug_saved += 1

    def on_error(self, failure):
        self.logger.warning("Échec requête : %s (%s)", failure.request.url, failure.value)

    @staticmethod
    def _finalize_weights(rows):
        by_key = defaultdict(list)
        for r in rows:
            by_key[r["_key"]].append(r)
        # Même poids lu dans l'image pour plusieurs formats d'un produit (ex. "50g" sur toutes les photos) :
        # seule la page affichée par défaut est fiable, les autres sont ambiguës.
        for group in by_key.values():
            counts = Counter(r["weight_raw"] for r in group
                             if r.get("weight_source") == "image_alt" and r["weight_raw"])
            for r in group:
                if (r.get("weight_source") == "image_alt" and not r.get("_own_page")
                        and counts[r["weight_raw"]] > 1):
                    r["weight_raw"], r["weight_source"] = None, None
        if USE_FORMAT_DEFAULTS:
            for r in rows:
                if r.get("pochette_found") and not r["weight_raw"]:
                    w = FORMAT_DEFAULT_WEIGHTS.get(format_key(r["pochette_label"]))
                    if w:
                        r["weight_raw"], r["weight_source"] = w, "format_default"

    def closed(self, reason):
        origin_order = list(ORIGIN_PAGES)
        out = []
        rows = sorted(self.rows, key=lambda r: (r.get("_seq", 0), r.get("_idx", 0)))
        self._finalize_weights(rows)
        for row in rows:
            key = row.pop("_key")
            row.pop("_seq", None)
            row.pop("_idx", None)
            row.pop("_own_page", None)
            subtitle_types = row.pop("_subtitle_types")
            subtitle_origins = row.pop("_subtitle_origins")

            types = subtitle_types
            type_source = "subtitle" if types else None

            origins = sorted(self.origins_by_url.get(key, ()), key=origin_order.index)
            origin_source = "filter" if origins else None
            if not origins and subtitle_origins:
                origins, origin_source = subtitle_origins, "subtitle"

            ordered = {}
            for k, v in row.items():
                ordered[k] = v
                if k == "name":
                    ordered["tea_type"] = ", ".join(types) if types else None
                    ordered["tea_type_source"] = type_source
                    ordered["origin"] = ", ".join(origins) if origins else None
                    ordered["origin_source"] = origin_source
            out.append(ordered)

        with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
            json.dump(out, f, indent=2, ensure_ascii=False)
        stats = Counter((r.get("weight_source") or "aucun") for r in out if r.get("pochette_found"))
        self.logger.info("Poids par source : %s", dict(stats))
        self.logger.info("%d lignes écrites dans %s (%s)", len(out), OUTPUT_FILE, reason)


# ----------------------------------------------------------------------
# Lancement
# ----------------------------------------------------------------------
def run_scraper_compagnie(max_products=None):
    shops = [
        {"url": "https://www.compagnie-co.com/fr/179-thes-d-origines", "market": "FR"},
    ]

    process = CrawlerProcess(settings={
        "USER_AGENT": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "ROBOTSTXT_OBEY": False,
        "DOWNLOAD_DELAY": 1.5,
        "AUTOTHROTTLE_ENABLED": True,
        "CONCURRENT_REQUESTS_PER_DOMAIN": 1,
        "RETRY_TIMES": 2,
        "LOG_LEVEL": "INFO",
    })

    process.crawl(CompagnieCoSpider, shops_config=shops, max_products=max_products)
    process.start()
    print(f"\n[Terminé] Résultats sauvegardés dans {OUTPUT_FILE}")


if __name__ == "__main__":
    run_scraper_compagnie(max_products=None)