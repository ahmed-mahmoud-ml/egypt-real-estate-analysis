import requests
from bs4 import BeautifulSoup
import csv
import re
import time
from urllib.parse import urljoin

# ============================================================
# SETTINGS
# ============================================================

BASE_DOMAIN = "https://www.propertyfinder.eg"

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/154.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "en-US,en;q=0.9",
}

MAX_PAGES_PER_AREA = 10

REQUEST_TIMEOUT = 20

SLEEP_BETWEEN_REQUESTS = 1.0

OUTPUT_FILE = "data/raw/propertyfinder_raw.csv"


# ============================================================
# AREAS
# ============================================================

AREA_URLS = {
    "New Cairo": (
        "https://www.propertyfinder.eg/en/buy/cairo/"
        "apartments-for-sale-new-cairo-city.html"
    ),
    "Sheikh Zayed": (
        "https://www.propertyfinder.eg/en/buy/giza/"
        "apartments-for-sale-sheikh-zayed-city.html"
    ),
    "6th of October": (
        "https://www.propertyfinder.eg/en/buy/giza/"
        "apartments-for-sale-6th-of-october-city.html"
    ),
    "New Administrative Capital": (
        "https://www.propertyfinder.eg/en/buy/cairo/"
        "apartments-for-sale-new-administrative-capital.html"
    ),
    "Nasr City": (
        "https://www.propertyfinder.eg/en/buy/cairo/"
        "apartments-for-sale-nasr-city.html"
    ),
    "Heliopolis": (
        "https://www.propertyfinder.eg/en/buy/cairo/"
        "apartments-for-sale-heliopolis.html"
    ),
    "Maadi": (
        "https://www.propertyfinder.eg/en/buy/cairo/" "apartments-for-sale-maadi.html"
    ),
}


# ============================================================
# SESSION
# ============================================================

session = requests.Session()
session.headers.update(HEADERS)


# ============================================================
# HELPER FUNCTIONS
# ============================================================


def clean_text(text):
    """
    Clean unnecessary spaces/newlines.
    """
    if not text:
        return None

    text = re.sub(r"\s+", " ", text)
    return text.strip()


def extract_number(text):
    """
    Extract first number from text.

    Examples:
        '3 Beds' -> 3
        '220 sqm' -> 220
        'EGP 5,800,000' -> 5800000
    """
    if not text:
        return None

    match = re.search(r"[\d,]+(?:\.\d+)?", text)

    if not match:
        return None

    value = match.group(0).replace(",", "")

    try:
        if "." in value:
            return float(value)
        return int(value)
    except ValueError:
        return None


def extract_money(text):
    """
    Extract EGP amount from text.
    """
    if not text:
        return None

    match = re.search(r"(?:EGP|Egp|egp)\s*([\d,]+(?:\.\d+)?)", text)

    if not match:
        return None

    value = match.group(1).replace(",", "")

    try:
        return float(value)
    except ValueError:
        return None


def get_element_text(soup, selector):
    """
    Return cleaned text for a CSS selector.
    """
    element = soup.select_one(selector)

    if not element:
        return None

    return clean_text(element.get_text(" ", strip=True))


# ============================================================
# GET SEARCH PAGE
# ============================================================


def get_search_page(url):
    """
    Download a Property Finder search page.
    """

    try:
        response = session.get(url, timeout=REQUEST_TIMEOUT)

        print("Status:", response.status_code)

        if response.status_code != 200:
            print("Failed:", url)
            return None

        return response.text

    except requests.RequestException as e:
        print("Request error:", e)
        return None


# ============================================================
# EXTRACT PROPERTY URLS
# ============================================================


def extract_property_urls(html):
    """
    Extract unique Property Finder property URLs
    from a search page.
    """

    soup = BeautifulSoup(html, "html.parser")

    property_urls = set()

    links = soup.find_all("a", href=True)

    for link in links:

        href = link.get("href")

        if not href:
            continue

        # Property Finder property pages
        if "/en/plp/" in href:

            full_url = urljoin(BASE_DOMAIN, href)

            property_urls.add(full_url)

    return property_urls


# ============================================================
# EXTRACT BASIC PROPERTY DETAILS
# ============================================================


def extract_basic_details(soup):

    data = {
        "title": None,
        "price": None,
        "bedrooms": None,
        "bathrooms": None,
        "area_sqm": None,
        "price_per_sqm": None,
    }

    # --------------------------------------------------------
    # TITLE
    # --------------------------------------------------------

    title_element = soup.find("h1")

    if title_element:
        data["title"] = clean_text(title_element.get_text(" ", strip=True))

    # --------------------------------------------------------
    # PRICE
    # --------------------------------------------------------

    price_element = soup.find("div", class_="styles_attributes__price-container__jlc6e")

    if price_element:

        price_text = clean_text(price_element.get_text(" ", strip=True))

        data["price"] = extract_money(price_text)

    # --------------------------------------------------------
    # PROPERTY DETAILS
    # --------------------------------------------------------

    detail_elements = soup.find_all("div", class_="styles_desktop_list__item__lF_Fh")

    for element in detail_elements:

        text = clean_text(element.get_text(" ", strip=True))

        if not text:
            continue

        # Bedrooms
        if text.startswith("Bedrooms"):

            data["bedrooms"] = extract_number(text)

        # Bathrooms
        elif text.startswith("Bathrooms"):

            data["bathrooms"] = extract_number(text)

        # Area
        elif text.startswith("Area"):

            data["area_sqm"] = extract_number(text)

        # Price per area
        elif text.startswith("Price per area"):

            data["price_per_sqm"] = extract_number(text)

    # --------------------------------------------------------
    # CALCULATE PRICE PER SQM IF NOT FOUND
    # --------------------------------------------------------

    if (
        data["price_per_sqm"] is None
        and data["price"] is not None
        and data["area_sqm"] is not None
        and data["area_sqm"] > 0
    ):

        data["price_per_sqm"] = round(data["price"] / data["area_sqm"], 2)

    return data


# ============================================================
# EXTRACT GENERAL TEXT INFORMATION
# ============================================================


def extract_text_information(soup):

    full_text = clean_text(soup.get_text(" ", strip=True))

    data = {
        "location": None,
        "payment_method": None,
        "down_payment": None,
        "delivery_status": None,
        "availability": None,
        "property_type": None,
        "listing_type": None,
    }

    if not full_text:
        return data

    # --------------------------------------------------------
    # PAYMENT METHOD
    # --------------------------------------------------------

    if re.search(r"\bInstallments\b", full_text, re.IGNORECASE):
        data["payment_method"] = "Installments"

    elif re.search(r"\bCash\b", full_text, re.IGNORECASE):
        data["payment_method"] = "Cash"

    # --------------------------------------------------------
    # DOWN PAYMENT
    # --------------------------------------------------------

    down_match = re.search(r"Down payment\s*([\d,.]+)\s*EGP", full_text, re.IGNORECASE)

    if down_match:

        value = down_match.group(1).replace(",", "")

        try:
            data["down_payment"] = float(value)
        except ValueError:
            pass

    # --------------------------------------------------------
    # DELIVERY / AVAILABILITY
    # --------------------------------------------------------

    delivery_patterns = [
        r"\bReady to move\b",
        r"\bReady\b",
        r"\bOffplan\b",
        r"\bOff-plan\b",
        r"\bUnder construction\b",
        r"\bDelivered\b",
    ]

    for pattern in delivery_patterns:

        match = re.search(pattern, full_text, re.IGNORECASE)

        if match:

            data["delivery_status"] = clean_text(match.group(0))

            break

    # --------------------------------------------------------
    # AVAILABLE FROM
    # --------------------------------------------------------

    available_match = re.search(
        r"Available from\s+(.{1,30}?)\s+(?:Listed|Price|Location)",
        full_text,
        re.IGNORECASE,
    )

    if available_match:

        data["availability"] = clean_text(available_match.group(1))

    # --------------------------------------------------------
    # PROPERTY TYPE
    # --------------------------------------------------------

    property_types = [
        "Apartment",
        "Villa",
        "Townhouse",
        "Twin House",
        "Duplex",
        "Studio",
        "Penthouse",
        "Chalet",
    ]

    for property_type in property_types:

        if re.search(rf"\b{re.escape(property_type)}\b", full_text, re.IGNORECASE):

            data["property_type"] = property_type
            break

    # --------------------------------------------------------
    # LISTING TYPE
    # --------------------------------------------------------

    if re.search(r"\bResale\b", full_text, re.IGNORECASE):
        data["listing_type"] = "Resale"

    elif re.search(r"\bFirst Sale\b", full_text, re.IGNORECASE):
        data["listing_type"] = "First Sale"

    return data


# ============================================================
# EXTRACT LOCATION
# ============================================================


def extract_location(soup):

    # Look for breadcrumb/navigation links
    breadcrumbs = []

    for link in soup.find_all("a", href=True):

        text = clean_text(link.get_text(" ", strip=True))

        if not text:
            continue

        if len(text) > 100:
            continue

        breadcrumbs.append(text)

    # Remove duplicates while preserving order
    unique_breadcrumbs = []

    for item in breadcrumbs:

        if item not in unique_breadcrumbs:
            unique_breadcrumbs.append(item)

    # Keep meaningful location-like values
    location_keywords = [
        "Cairo",
        "Giza",
        "New Cairo",
        "5th Settlement",
        "New Capital",
        "Administrative Capital",
        "Sheikh Zayed",
        "October",
        "Maadi",
        "Nasr City",
        "Heliopolis",
        "Madinaty",
        "Zed",
        "Compound",
    ]

    possible_locations = []

    for item in unique_breadcrumbs:

        if any(keyword.lower() in item.lower() for keyword in location_keywords):
            possible_locations.append(item)

    if possible_locations:

        return " | ".join(possible_locations[-5:])

    return None


# ============================================================
# SCRAPE ONE PROPERTY
# ============================================================


def scrape_property(url, area_name):

    print("\n----------------------------------------")
    print("URL:", url)

    try:

        response = session.get(url, timeout=REQUEST_TIMEOUT)

        print("Status:", response.status_code)

        if response.status_code != 200:

            print("FAILED")

            return None

        soup = BeautifulSoup(response.text, "html.parser")

        basic_data = extract_basic_details(soup)

        text_data = extract_text_information(soup)

        location = extract_location(soup)

        property_data = {
            "source": "Property Finder",
            "source_area": area_name,
            "url": url,
            "title": basic_data["title"],
            "property_type": text_data["property_type"],
            "listing_type": text_data["listing_type"],
            "location": location,
            "price": basic_data["price"],
            "price_per_sqm": basic_data["price_per_sqm"],
            "area_sqm": basic_data["area_sqm"],
            "bedrooms": basic_data["bedrooms"],
            "bathrooms": basic_data["bathrooms"],
            "payment_method": text_data["payment_method"],
            "down_payment": text_data["down_payment"],
            "delivery_status": text_data["delivery_status"],
            "availability": text_data["availability"],
        }

        print("Price:", property_data["price"])

        print("Bedrooms:", property_data["bedrooms"])

        print("Bathrooms:", property_data["bathrooms"])

        print("Area:", property_data["area_sqm"])

        print("Price/sqm:", property_data["price_per_sqm"])

        return property_data

    except requests.RequestException as e:

        print("Request error:", e)

        return None

    except Exception as e:

        print("Unexpected error:", e)

        return None


# ============================================================
# MAIN SCRAPING PROCESS
# ============================================================


def main():

    print("\n========================================")
    print("PROPERTY FINDER REAL ESTATE SCRAPER")
    print("========================================\n")

    all_property_urls = set()

    # ========================================================
    # STEP 1 — COLLECT PROPERTY URLS
    # ========================================================

    print("STEP 1: Collecting property URLs...\n")

    for area_name, base_url in AREA_URLS.items():

        print("\n========================================")
        print("AREA:", area_name)
        print("========================================")

        for page in range(1, MAX_PAGES_PER_AREA + 1):

            if page == 1:

                page_url = base_url

            else:

                page_url = f"{base_url}?page={page}"

            print(f"\nPage {page}/{MAX_PAGES_PER_AREA}")

            html = get_search_page(page_url)

            if html is None:

                continue

            urls = extract_property_urls(html)

            print("Property URLs found:", len(urls))

            before = len(all_property_urls)

            all_property_urls.update(urls)

            after = len(all_property_urls)

            print("New unique URLs:", after - before)

            time.sleep(SLEEP_BETWEEN_REQUESTS)

    print("\n========================================")
    print("URL COLLECTION FINISHED")
    print("========================================")

    print("Total unique property URLs:", len(all_property_urls))

    # ========================================================
    # STEP 2 — SCRAPE PROPERTIES
    # ========================================================

    print("\nSTEP 2: Scraping property pages...\n")

    properties = []

    total = len(all_property_urls)

    for index, url in enumerate(sorted(all_property_urls), start=1):

        print("\n========================================")

        print(f"Scraping property {index}/{total}")

        # Find source area
        source_area = "Unknown"

        for area_name, base_url in AREA_URLS.items():

            if area_name.lower() in url.lower():

                source_area = area_name
                break

        property_data = scrape_property(url, source_area)

        if property_data is not None:

            properties.append(property_data)

        time.sleep(SLEEP_BETWEEN_REQUESTS)

    # ========================================================
    # STEP 3 — SAVE CSV
    # ========================================================

    print("\n========================================")
    print("STEP 3: Saving dataset")
    print("========================================")

    if not properties:

        print("No properties were successfully scraped.")

        return

    fieldnames = [
        "source",
        "source_area",
        "url",
        "title",
        "property_type",
        "listing_type",
        "location",
        "price",
        "price_per_sqm",
        "area_sqm",
        "bedrooms",
        "bathrooms",
        "payment_method",
        "down_payment",
        "delivery_status",
        "availability",
    ]

    with open(OUTPUT_FILE, "w", newline="", encoding="utf-8-sig") as file:

        writer = csv.DictWriter(file, fieldnames=fieldnames)

        writer.writeheader()

        writer.writerows(properties)

    # ========================================================
    # FINAL SUMMARY
    # ========================================================

    print("\n========================================")
    print("SCRAPING FINISHED")
    print("========================================")

    print("Unique property URLs:", len(all_property_urls))

    print("Successfully collected:", len(properties))

    print("Failed / skipped:", len(all_property_urls) - len(properties))

    print("CSV saved to:", OUTPUT_FILE)

    print("\nColumns:")

    for column in fieldnames:

        print(f"- {column}")

    print("\n========================================")
    print("DONE")
    print("========================================")


# ============================================================
# RUN
# ============================================================

if __name__ == "__main__":
    main()
