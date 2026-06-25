import sys, pathlib
sys.path.insert(0, str(pathlib.Path(__file__).parent))
from pypdf import PdfReader
from pos_parser import parse_pos_fields

cache = pathlib.Path(__file__).parent / "pos_study_cache"
TARGETS = ["264577","264579","262064","262314","262574","262577","262618","263035","264584"]

for name in TARGETS:
    matches = list(cache.glob(name + "_*.pdf"))
    if not matches:
        print(name + ": not found")
        continue
    reader = PdfReader(str(matches[0]))
    txt = "\n".join(p.extract_text() or "" for p in reader.pages)
    f = parse_pos_fields(txt)
    borrower = f.get("borrower")
    missing = f.get("_missing_essential", [])
    print(name + ": borrower=" + repr(borrower) + "  missing=" + repr(missing))
