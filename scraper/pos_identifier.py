"""
pos_identifier.py — Identify current vs historical POS documents for a property.

Ported from goal_6_prop/orchestrator/utilities/pos_identifier.py.

BidNow POS file path pattern:
    files/upload/ap/{LISTING_ID}/pos_file/{TIMESTAMP}_{HASH}.pdf

When listing_id in path == current property_id → Current Active POS ✓
When listing_id in path != property_id         → Historical/Expired POS ✗
"""

import re
from typing import Dict, List, Optional, Tuple


def extract_listing_id_from_filepath(file_path: str) -> Optional[int]:
    """
    Extract the listing_id embedded in a BidNow POS file path.

    Example path: "files/upload/ap/248650/pos_file/20260313_160846_676bc.pdf"
    Returns: 248650
    """
    match = re.search(r"/ap/(\d+)/pos_file/", file_path)
    if match:
        return int(match.group(1))
    return None


def identify_current_pos(property_data: Dict) -> Dict:
    """
    Classify POS PDFs for a property into current vs historical.

    Args:
        property_data: dict with keys:
            - property_id (int)
            - property_title (str)
            - pdfs (list of {"file_path": str, "timestamp": str, ...})

    Returns:
        {
            "property_id": int,
            "property_title": str,
            "has_current_pos": bool,
            "current_pos": dict | None,
            "historical_pos": list[dict],
            "auction_attempts": int,
            "previous_attempts": int,
        }
    """
    property_id = property_data.get("property_id")
    pdfs = property_data.get("pdfs", [])

    current_pos = None
    historical_pos: List[Dict] = []

    for pdf in pdfs:
        file_path = pdf.get("file_path", "")
        lid = extract_listing_id_from_filepath(file_path)
        enriched = {**pdf, "listing_id": lid, "is_current": lid == property_id}

        if lid == property_id:
            current_pos = enriched
        else:
            historical_pos.append(enriched)

    return {
        "property_id": property_id,
        "property_title": property_data.get("property_title"),
        "has_current_pos": current_pos is not None,
        "current_pos": current_pos,
        "historical_pos": historical_pos,
        "auction_attempts": len(pdfs),
        "previous_attempts": len(historical_pos),
    }


def extract_pdfs_with_status(
    property_data: Dict,
) -> Tuple[Optional[Dict], List[Dict]]:
    """Convenience wrapper — returns (current_pos, historical_pos_list)."""
    result = identify_current_pos(property_data)
    return result["current_pos"], result["historical_pos"]


def validate_property_pos_status(property_data: Dict) -> Dict:
    """
    Return a validation summary dict for a property's POS status.

    Returns status one of: "valid" | "expired" | "missing"
    """
    result = identify_current_pos(property_data)

    if result["has_current_pos"]:
        return {
            "status": "valid",
            "property_id": result["property_id"],
            "message": f"Current POS available (timestamp: {result['current_pos'].get('timestamp')})",
            "recommendation": "Ready for analysis",
            "auction_history": f"{result['previous_attempts']} previous attempts",
        }

    if result["auction_attempts"] > 0:
        latest = (
            sorted(result["historical_pos"], key=lambda x: x.get("timestamp", ""), reverse=True)[0]
            if result["historical_pos"]
            else None
        )
        return {
            "status": "expired",
            "property_id": result["property_id"],
            "message": (
                f"No current POS ({result['auction_attempts']} auction attempts found "
                "but none matches current listing ID)"
            ),
            "recommendation": "Request current POS from bank or verify on BidNow",
            "latest_attempt": latest.get("timestamp") if latest else None,
        }

    return {
        "status": "missing",
        "property_id": result["property_id"],
        "message": "No POS documents found for this property",
        "recommendation": "Property may not have a published POS yet",
    }
