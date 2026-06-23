"""
bidnow_filter_enums.py — BidNow filter parameter enums (valid dropdown values).

Extracted from: https://www.bidnow.my/properties/auction (Select2 dropdowns)
Ported from goal_6_prop/orchestrator/utilities/bidnow_filter_enums.py
"""

# Malaysian States (15 total — Labuan omitted, not on BidNow)
BIDNOW_STATES = [
    "Johor",
    "Kedah",
    "Kelantan",
    "Kuala Lumpur",
    "Melaka",
    "Negeri Sembilan",
    "Pahang",
    "Penang",
    "Perak",
    "Perlis",
    "Putrajaya",
    "Sabah",
    "Sarawak",
    "Selangor",
    "Terengganu",
]

# Property Types (14 complete types as they appear in BidNow dropdown)
BIDNOW_PROPERTY_TYPES = [
    "Bungalow / Villa House / Semi-D House",
    "Chalet",
    "Condominium / SOHO House / Apartment",
    "Executive Suite",
    "Flat House",
    "Land",
    "Link House / Townhouse / Terrace House",
    "Office Unit / Shop Lot / Retail Space",
    "Penthhouse",
    "Petrol Station",
    "Resorts / Hotel & Accommodation / Clubhouse",
    "Service Suite",
    "Vegetable Stall",
    "Warehouse / Factory Unit",
    "Water Villa",
]

# Auction Types
BIDNOW_AUCTION_TYPES = [
    "JomBid",
    "LACA",
    "Non-LACA",
    "TENDER CASE",
]

# Listing Status
BIDNOW_LISTING_STATUS = [
    "active",
    "closed",
    "upcoming",
]

# Sorting Options {sort_value: display_text}
BIDNOW_SORT_OPTIONS = {
    "new": "Newest Listing",
    "asc_auction_date": "Auction Date (Ascending)",
    "desc_auction_date": "Auction Date (Descending)",
    "asc_auction_price": "Lowest Price",
    "desc_auction_price": "Highest Price",
    "asc_bmv_percent": "Lowest BMV",
    "desc_bmv_percent": "Highest BMV",
}

# Property Type Mapping (short names → BidNow dropdown value)
PROPERTY_TYPE_TO_BIDNOW_MAPPING = {
    "terrace": "Link House / Townhouse / Terrace House",
    "townhouse": "Link House / Townhouse / Terrace House",
    "link_house": "Link House / Townhouse / Terrace House",
    "semi_detached": "Bungalow / Villa House / Semi-D House",
    "bungalow": "Bungalow / Villa House / Semi-D House",
    "apartment": "Condominium / SOHO House / Apartment",
    "condo": "Condominium / SOHO House / Apartment",
    "condominium": "Condominium / SOHO House / Apartment",
    "flat": "Flat House",
    "shop": "Office Unit / Shop Lot / Retail Space",
    "office": "Office Unit / Shop Lot / Retail Space",
    "warehouse": "Warehouse / Factory Unit",
    "land": "Land",
}

# District → State mapping for address parsing
DISTRICT_TO_STATE = {
    # Kuala Lumpur
    "cheras": "Kuala Lumpur",
    "bangsar": "Kuala Lumpur",
    "kepong": "Kuala Lumpur",
    "kl": "Kuala Lumpur",
    "kuala lumpur": "Kuala Lumpur",
    "wangsa maju": "Kuala Lumpur",
    "setapak": "Kuala Lumpur",
    "mont kiara": "Kuala Lumpur",
    "bukit jalil": "Kuala Lumpur",
    "sri petaling": "Kuala Lumpur",
    "titiwangsa": "Kuala Lumpur",
    "klcc": "Kuala Lumpur",
    # Selangor
    "subang": "Selangor",
    "shah alam": "Selangor",
    "petaling jaya": "Selangor",
    "pj": "Selangor",
    "damansara": "Selangor",
    "selangor": "Selangor",
    "klang": "Selangor",
    "sunway": "Selangor",
    "puchong": "Selangor",
    "kajang": "Selangor",
    "semenyih": "Selangor",
    "bangi": "Selangor",
    "rawang": "Selangor",
    "serdang": "Selangor",
    "ampang": "Selangor",
    "cyberjaya": "Selangor",
    "sepang": "Selangor",
    "gombak": "Selangor",
    "setia alam": "Selangor",
    "usj": "Selangor",
    "seri kembangan": "Selangor",
    # Putrajaya
    "putrajaya": "Putrajaya",
    # Penang
    "penang": "Penang",
    "georgetown": "Penang",
    "bayan lepas": "Penang",
    "butterworth": "Penang",
    "seberang perai": "Penang",
    "bukit mertajam": "Penang",
    # Johor
    "johor": "Johor",
    "johor bahru": "Johor",
    "jb": "Johor",
    "skudai": "Johor",
    "kulai": "Johor",
    "batu pahat": "Johor",
    # Others
    "melaka": "Melaka",
    "negeri sembilan": "Negeri Sembilan",
    "seremban": "Negeri Sembilan",
    "ipoh": "Perak",
    "perak": "Perak",
    "alor setar": "Kedah",
    "kedah": "Kedah",
    "kota bharu": "Kelantan",
    "kelantan": "Kelantan",
    "kuantan": "Pahang",
    "pahang": "Pahang",
    "kota kinabalu": "Sabah",
    "sabah": "Sabah",
    "kuching": "Sarawak",
    "sarawak": "Sarawak",
    "perlis": "Perlis",
    "terengganu": "Terengganu",
}


# ── Validation helpers ──────────────────────────────────────────────────────

def validate_state(state: str) -> bool:
    return state in BIDNOW_STATES

def validate_property_type(prop_type: str) -> bool:
    return prop_type in BIDNOW_PROPERTY_TYPES

def validate_auction_type(auction_type: str) -> bool:
    return auction_type in BIDNOW_AUCTION_TYPES

def validate_listing_status(status: str) -> bool:
    return status in BIDNOW_LISTING_STATUS

def validate_sort_option(sort: str) -> bool:
    return sort in BIDNOW_SORT_OPTIONS

def get_sort_display_text(sort_value: str) -> str:
    return BIDNOW_SORT_OPTIONS.get(sort_value, "")
