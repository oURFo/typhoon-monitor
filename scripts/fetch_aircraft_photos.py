"""從 Wikimedia Commons 下載常用機型照片並產生授權對照表。"""

from __future__ import annotations

import json
import re
import time
import urllib.parse
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT_DIR = ROOT / "public" / "assets" / "aircraft" / "photos"
CREDITS_PATH = ROOT / "public" / "data" / "aircraft-credits.json"

USER_AGENT = "TyphoonMonitor/1.0 (educational; github.com/oURFo/typhoon-monitor)"

# 台灣機場常見機型；每筆為 (本機檔名, Wikimedia 檔名)
CURATED: list[tuple[str, str]] = [
    ("a320", "21-SEP-2022 - 3K684 KUL-SIN (A320 - 9V-JSJ) (04).jpg"),
    ("a321", "Airbus A321 - DSC0082.jpg"),
    ("a330", "2017-09-20 02 Air Greenland Airbus A330-200 (OY-GRN) at Kangerlussuaq Airport (SFJ), Greenlan.jpg"),
    ("a330neo", "Airbus A330neo F-WTTN 25.jpg"),
    ("a350", "Airbus A350-1000 F-WMIL 15.jpg"),
    ("b737", "Southwest Boeing 737-800 N8523W BWI MD1.jpg"),
    ("b777", "Qatar Boeing 777-300ER A7-BEP IAD VA1.jpg"),
    ("b787", "N1015X Air Tahiti Nui Boeing 787-9 Dreamliner 26.jpg"),
    ("atr72", "ATR 72 G-FBXB MG 8116.jpg"),
    ("a319", "2017-09-12 Atlantic Airways (Faroe Islands) Airbus A319 aircraft (OY-RCG) at Narsarsuaq, Greenland.jpg"),
    ("b747", "2018 MUNCYT Boeing 747 -7.jpg"),
    ("b739", "Southwest Boeing 737-800 N8523W BWI MD1.jpg"),  # 與 738 共用圖
]


def strip_html(text: str) -> str:
    text = re.sub(r"<[^>]+>", "", text)
    text = urllib.parse.unquote(text)
    return re.sub(r"\s+", " ", text).strip()


def fetch_meta(filename: str) -> dict:
    title = f"File:{filename}"
    url = "https://commons.wikimedia.org/w/api.php?" + urllib.parse.urlencode(
        {
            "action": "query",
            "titles": title,
            "prop": "imageinfo",
            "iiprop": "url|extmetadata|mime",
            "iiurlwidth": 800,
            "format": "json",
        }
    )
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    data = json.loads(urllib.request.urlopen(req, timeout=60).read())
    pages = data.get("query", {}).get("pages", {})
    page = next(iter(pages.values()))
    if "missing" in page:
        raise FileNotFoundError(filename)
    ii = page["imageinfo"][0]
    meta = ii.get("extmetadata") or {}
    license_short = strip_html((meta.get("LicenseShortName") or {}).get("value", ""))
    license_url = strip_html((meta.get("LicenseUrl") or {}).get("value", ""))
    artist = strip_html((meta.get("Artist") or {}).get("value", ""))
    usage = strip_html((meta.get("UsageTerms") or {}).get("value", ""))
    lic = license_short or usage
    low = lic.lower()
    if any(x in low for x in ("nc", "nd", "non-commercial", "no derivatives")):
        raise ValueError(f"License not allowed: {lic}")
    commons_url = "https://commons.wikimedia.org/wiki/" + urllib.parse.quote(title, safe="/:")
    return {
        "file": filename,
        "commonsUrl": commons_url,
        "author": artist or "Unknown",
        "license": lic,
        "licenseUrl": license_url,
        "downloadUrl": ii.get("thumburl") or ii.get("url"),
        "mime": ii.get("mime", "image/jpeg"),
    }


def download(url: str, dest: Path) -> None:
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    dest.write_bytes(urllib.request.urlopen(req, timeout=120).read())


def main() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    credits: dict[str, dict] = {}
    seen_files: dict[str, str] = {}

    for key, wiki_file in CURATED:
        if wiki_file in seen_files:
            src_key = seen_files[wiki_file]
            credits[key] = {**credits[src_key], "aliasOf": src_key}
            continue

        meta = fetch_meta(wiki_file)
        ext = ".jpg" if "jpeg" in meta["mime"] else ".png"
        local_name = f"{key}{ext}"
        dest = OUT_DIR / local_name
        print(f"Downloading {key} <- {wiki_file}")
        time.sleep(2)
        download(meta["downloadUrl"], dest)
        time.sleep(1)

        entry = {
            "label": key,
            "localPath": f"/static/assets/aircraft/photos/{local_name}",
            "wikimediaFile": wiki_file,
            "commonsUrl": meta["commonsUrl"],
            "author": meta["author"],
            "license": meta["license"],
            "licenseUrl": meta["licenseUrl"],
            "attribution": f'{meta["author"]} / {meta["license"]} / Wikimedia Commons',
        }
        credits[key] = entry
        seen_files[wiki_file] = key

    CREDITS_PATH.parent.mkdir(parents=True, exist_ok=True)
    CREDITS_PATH.write_text(json.dumps(credits, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Wrote {len(credits)} entries -> {CREDITS_PATH}")


if __name__ == "__main__":
    main()
