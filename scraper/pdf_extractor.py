"""
pdf_extractor.py — Extract text from a POS PDF (local file or HTTPS URL).

Ported from goal_6_prop/orchestrator/utilities/pdf_extractor.py.
Used by pos_analyzer.py (on-demand POS analysis, not the nightly scrape).
"""

import re
from io import BytesIO
from pathlib import Path
from typing import Dict, Optional


def extract_text(
    file_path: Optional[str] = None,
    url: Optional[str] = None,
    timeout: int = 30,
) -> Dict:
    """
    Extract text from a PDF file (local path) or a HTTPS URL.

    Returns:
        {
            "extracted_text": str,
            "encoding": str,
            "page_count": int,
            "error": str | None,
            "source": "local" | "url" | None,
            "confidence": "high" | "medium" | "low",
        }
    """
    if not file_path and not url:
        return _err("Either file_path or url must be provided", source=None)

    if file_path:
        return _extract_local(file_path)

    return _extract_url(url, timeout)


# ── Internal helpers ──────────────────────────────────────────────────────────

def _err(msg: str, source: Optional[str] = None) -> Dict:
    return {
        "extracted_text": "",
        "encoding": "utf-8",
        "page_count": 0,
        "error": msg,
        "source": source,
        "confidence": "high",
    }


def _pdf_reader():
    """Import pypdf or fall back to PyPDF2."""
    try:
        from pypdf import PdfReader
        return PdfReader
    except ImportError:
        pass
    try:
        from PyPDF2 import PdfReader  # type: ignore
        return PdfReader
    except ImportError:
        raise ImportError("Install pypdf: pip install pypdf")


def _read_pages(reader) -> str:
    text = ""
    for page in reader.pages:
        try:
            chunk = page.extract_text()
            if chunk:
                text += chunk + "\n"
        except Exception:
            continue
    return re.sub(r"\n\s*\n", "\n", text).strip()


def _extract_local(file_path: str) -> Dict:
    path = Path(file_path)
    if not path.exists():
        return _err(f"File not found: {file_path}", source="local")
    if path.suffix.lower() != ".pdf":
        return _err(f"Not a PDF file: {file_path}", source="local")

    try:
        PdfReader = _pdf_reader()
        reader = PdfReader(str(path))
        text = _read_pages(reader)
        return {
            "extracted_text": text,
            "encoding": "utf-8",
            "page_count": len(reader.pages),
            "error": None,
            "source": "local",
            "confidence": "high" if text else "low",
        }
    except ImportError as exc:
        return _err(str(exc), source="local")
    except Exception as exc:
        return _err(f"Extraction error: {exc}", source="local")


def _extract_url(url: str, timeout: int) -> Dict:
    if not url.startswith(("http://", "https://")):
        return _err(f"URL must start with http:// or https://: {url}", source="url")

    try:
        import requests
    except ImportError:
        return _err("requests not installed: pip install requests", source="url")

    try:
        resp = requests.get(url, timeout=timeout, verify=True)
        resp.raise_for_status()
    except Exception as exc:
        return _err(f"Download error: {exc}", source="url")

    content_type = resp.headers.get("content-type", "").lower()
    if "pdf" not in content_type and not url.lower().endswith(".pdf"):
        return _err(f"URL does not return PDF (content-type: {content_type})", source="url")

    try:
        PdfReader = _pdf_reader()
        reader = PdfReader(BytesIO(resp.content))
        text = _read_pages(reader)
        return {
            "extracted_text": text,
            "encoding": "utf-8",
            "page_count": len(reader.pages),
            "error": None,
            "source": "url",
            "confidence": "high" if text else "medium",
        }
    except ImportError as exc:
        return _err(str(exc), source="url")
    except Exception as exc:
        return _err(f"PDF parse error: {exc}", source="url")
