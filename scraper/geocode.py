"""
geocode.py — Address → lat/lng using Nominatim (OpenStreetMap, free, no API key).

Strategy:
1. Check geocache.json first (keyed by normalised address string)
2. Query Nominatim with full_address
3. If exact match fails, retry with postcode only (returns centroid of postcode area)
4. Write successful results to cache

Nominatim usage policy:
- Max 1 request per second (enforced via time.sleep)
- Must include a descriptive User-Agent
- Do not scrape bulk without identifying yourself

Cache key: normalised address string (lowercase, stripped)
Cache value: {"lat": float, "lng": float, "source": "exact"|"postcode_centroid"}
"""

import json
import re
import time
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import requests

NOMINATIM_URL = "https://nominatim.openstreetmap.org/search"
NOMINATIM_HEADERS = {
    "User-Agent": "AuctionVaultScraper/1.0 (property research tool; contact via GitHub)"
}
REQUEST_DELAY = 1.1  # seconds between Nominatim calls (policy: max 1/s)
REQUEST_TIMEOUT = 10

# Approximate centroids for Malaysian postcodes (fallback lookup)
# Keyed by first 2 digits of postcode → (lat, lng, area_name)
POSTCODE_PREFIX_CENTROIDS: Dict[str, Tuple[float, float, str]] = {
    "01": (6.1248, 100.3673, "Kangar, Perlis"),
    "02": (6.1248, 100.3673, "Perlis"),
    "03": (6.1248, 100.3673, "Perlis"),
    "04": (5.8490, 100.7100, "Alor Setar, Kedah"),
    "05": (5.8490, 100.7100, "Kedah"),
    "06": (5.8490, 100.7100, "Kedah"),
    "07": (5.8490, 100.7100, "Kedah"),
    "08": (5.8490, 100.7100, "Kedah"),
    "09": (5.8490, 100.7100, "Kedah"),
    "10": (5.4141, 100.3288, "Georgetown, Penang"),
    "11": (5.4141, 100.3288, "Penang"),
    "12": (5.3768, 100.4071, "Seberang Perai, Penang"),
    "13": (5.3768, 100.4071, "Seberang Perai, Penang"),
    "14": (5.3768, 100.4071, "Penang"),
    "15": (6.1254, 102.2381, "Kota Bharu, Kelantan"),
    "16": (6.1254, 102.2381, "Kelantan"),
    "17": (6.1254, 102.2381, "Kelantan"),
    "18": (6.1254, 102.2381, "Kelantan"),
    "19": (6.1254, 102.2381, "Kelantan"),
    "20": (5.3317, 103.1408, "Kuala Terengganu"),
    "21": (5.3317, 103.1408, "Terengganu"),
    "22": (5.3317, 103.1408, "Terengganu"),
    "23": (5.3317, 103.1408, "Terengganu"),
    "24": (5.3317, 103.1408, "Terengganu"),
    "25": (3.8126, 103.3256, "Kuantan, Pahang"),
    "26": (3.8126, 103.3256, "Pahang"),
    "27": (3.8126, 103.3256, "Pahang"),
    "28": (3.8126, 103.3256, "Pahang"),
    "39": (4.5921, 101.0901, "Ipoh, Perak"),
    "30": (4.5921, 101.0901, "Ipoh, Perak"),
    "31": (4.5921, 101.0901, "Perak"),
    "32": (4.5921, 101.0901, "Perak"),
    "33": (4.5921, 101.0901, "Perak"),
    "34": (4.5921, 101.0901, "Perak"),
    "35": (4.5921, 101.0901, "Perak"),
    "36": (4.5921, 101.0901, "Perak"),
    "40": (3.0738, 101.5183, "Shah Alam, Selangor"),
    "41": (3.0449, 101.4455, "Klang, Selangor"),
    "42": (3.0449, 101.4455, "Klang, Selangor"),
    "43": (2.9930, 101.7842, "Kajang, Selangor"),
    "44": (3.3333, 101.1333, "Kuala Selangor"),
    "45": (3.3000, 101.2167, "Selangor"),
    "46": (3.1045, 101.6373, "Petaling Jaya, Selangor"),
    "47": (3.0469, 101.6839, "Puchong / Subang, Selangor"),
    "48": (3.3186, 101.5741, "Rawang, Selangor"),
    "50": (3.1478, 101.6953, "Kuala Lumpur"),
    "51": (3.1478, 101.6953, "Kuala Lumpur"),
    "52": (3.1878, 101.6953, "Kepong, Kuala Lumpur"),
    "53": (3.1878, 101.6953, "Setapak, Kuala Lumpur"),
    "54": (3.1478, 101.6953, "Kuala Lumpur"),
    "55": (3.1478, 101.6953, "Kuala Lumpur"),
    "56": (3.0978, 101.7353, "Cheras, Kuala Lumpur"),
    "57": (3.0678, 101.6953, "Sri Petaling, Kuala Lumpur"),
    "58": (3.0678, 101.6553, "Kuala Lumpur"),
    "59": (3.1478, 101.6653, "Bangsar, Kuala Lumpur"),
    "60": (3.1878, 101.6053, "Kuala Lumpur"),
    "62": (2.9264, 101.6964, "Putrajaya"),
    "63": (2.9264, 101.7964, "Cyberjaya, Selangor"),
    "68": (3.1478, 101.7853, "Ampang, Selangor"),
    "69": (3.0769, 101.9169, "Selangor"),
    "70": (2.7297, 101.9381, "Seremban, Negeri Sembilan"),
    "71": (2.7297, 101.9381, "Negeri Sembilan"),
    "72": (2.7297, 101.9381, "Negeri Sembilan"),
    "73": (2.7297, 101.9381, "Negeri Sembilan"),
    "75": (2.1896, 102.2501, "Melaka"),
    "76": (2.1896, 102.2501, "Melaka"),
    "77": (2.1896, 102.2501, "Melaka"),
    "78": (2.1896, 102.2501, "Melaka"),
    "79": (1.4655, 103.7578, "Johor Bahru"),
    "80": (1.4655, 103.7578, "Johor Bahru"),
    "81": (1.4655, 103.7578, "Johor"),
    "82": (1.4655, 103.7578, "Johor"),
    "83": (1.4655, 103.7578, "Johor"),
    "84": (1.4655, 103.7578, "Johor"),
    "85": (1.4655, 103.7578, "Johor"),
    "86": (1.4655, 103.7578, "Johor"),
    "87": (1.4655, 103.7578, "Johor"),
    "88": (5.9749, 116.0724, "Kota Kinabalu, Sabah"),
    "89": (5.9749, 116.0724, "Sabah"),
    "90": (5.9749, 116.0724, "Sabah"),
    "91": (5.9749, 116.0724, "Sabah"),
    "93": (1.5497, 110.3626, "Kuching, Sarawak"),
    "94": (1.5497, 110.3626, "Sarawak"),
    "95": (1.5497, 110.3626, "Sarawak"),
    "96": (1.5497, 110.3626, "Sarawak"),
    "97": (1.5497, 110.3626, "Sarawak"),
    "98": (1.5497, 110.3626, "Sarawak"),
}


class Geocoder:

    def __init__(self, cache_path: str):
        self.cache_path = Path(cache_path)
        self.cache: Dict[str, Dict] = {}
        self._load_cache()
        self._last_request_time = 0.0

    # ── Public API ────────────────────────────────────────────────────────────

    def geocode(self, address: str) -> Optional[Dict]:
        """
        Return {"lat": float, "lng": float, "source": str} or None.

        Checks cache first; falls back through Nominatim → postcode centroid.
        """
        key = self._cache_key(address)
        if key in self.cache:
            return self.cache[key]

        # Try Nominatim exact address
        result = self._nominatim_query(address + ", Malaysia")
        if result:
            result["source"] = "exact"
            self._store(key, result)
            return result

        # Fallback: postcode centroid
        postcode = self._extract_postcode(address)
        if postcode:
            centroid = self._postcode_centroid(postcode)
            if centroid:
                centroid["source"] = "postcode_centroid"
                self._store(key, centroid)
                return centroid

        return None

    def save_cache(self):
        """Persist cache to disk."""
        self.cache_path.parent.mkdir(parents=True, exist_ok=True)
        with open(self.cache_path, "w", encoding="utf-8") as f:
            json.dump(self.cache, f, indent=2, ensure_ascii=False)

    # ── Internals ─────────────────────────────────────────────────────────────

    def _load_cache(self):
        if self.cache_path.exists():
            try:
                with open(self.cache_path, encoding="utf-8") as f:
                    self.cache = json.load(f)
                print(f"  [geocode] loaded {len(self.cache)} cached entries")
            except Exception as exc:
                print(f"  [geocode] cache load error: {exc}")
                self.cache = {}

    def _store(self, key: str, value: Dict):
        self.cache[key] = value

    @staticmethod
    def _cache_key(address: str) -> str:
        return re.sub(r"\s+", " ", address.lower().strip())

    @staticmethod
    def _extract_postcode(address: str) -> str:
        m = re.search(r"\b(\d{5})\b", address)
        return m.group(1) if m else ""

    def _nominatim_query(self, query: str) -> Optional[Dict]:
        """Call Nominatim and return {"lat": float, "lng": float} or None."""
        # Enforce rate limit
        elapsed = time.time() - self._last_request_time
        if elapsed < REQUEST_DELAY:
            time.sleep(REQUEST_DELAY - elapsed)

        try:
            resp = requests.get(
                NOMINATIM_URL,
                params={"q": query, "format": "json", "limit": 1},
                headers=NOMINATIM_HEADERS,
                timeout=REQUEST_TIMEOUT,
            )
            self._last_request_time = time.time()
            resp.raise_for_status()
            data = resp.json()
            if data:
                return {"lat": float(data[0]["lat"]), "lng": float(data[0]["lon"])}
        except Exception as exc:
            print(f"  [geocode] Nominatim error for '{query}': {exc}")

        return None

    @staticmethod
    def _postcode_centroid(postcode: str) -> Optional[Dict]:
        """Look up approximate centroid by first 2 digits of postcode."""
        prefix = postcode[:2]
        entry = POSTCODE_PREFIX_CENTROIDS.get(prefix)
        if entry:
            return {"lat": entry[0], "lng": entry[1]}
        return None

    # ── Batch helper ──────────────────────────────────────────────────────────

    def geocode_listings(self, listings: List[Dict]) -> List[Dict]:
        """
        Add lat/lng to each listing dict in place.
        Saves cache after processing.
        """
        geocoded = 0
        cached_hits = 0
        for listing in listings:
            address = listing.get("full_address", "")
            if not address:
                listing["lat"] = None
                listing["lng"] = None
                listing["geocode_source"] = "missing_address"
                continue

            key = self._cache_key(address)
            if key in self.cache:
                cached_hits += 1
                result = self.cache[key]
            else:
                result = self.geocode(address)
                geocoded += 1

            if result:
                listing["lat"] = result["lat"]
                listing["lng"] = result["lng"]
                listing["geocode_source"] = result.get("source", "unknown")
            else:
                listing["lat"] = None
                listing["lng"] = None
                listing["geocode_source"] = "failed"

        print(
            f"  [geocode] {geocoded} new lookups, {cached_hits} cache hits, "
            f"{sum(1 for l in listings if l.get('lat') is None)} failed"
        )
        self.save_cache()
        return listings


