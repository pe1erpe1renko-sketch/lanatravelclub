#!/usr/bin/env python3
"""Download landing-page photos from Wikimedia Commons, normalise them and write CREDITS.md.

Procedure (per spec):
  1. Try https://en.wikipedia.org/api/rest_v1/page/summary/<Title> -> originalimage.source
  2. If there is no originalimage, or the picture is unusable (logo / map / diagram /
     portrait orientation), fall back to the Commons search API and pick the first
     horizontal photo carrying a CC BY / CC BY-SA / CC0 / Public domain licence.
  3. Resize every file to 1600px wide (proportional), JPEG quality 82.
  4. Anything whose original is narrower than 1200px is rejected and the next
     candidate is used instead.

Usage:  python3 tools/fetch_photos.py
Needs:  Pillow  (pip install Pillow)  and outbound access to *.wikimedia.org
"""

import io
import json
import os
import re
import sys
import urllib.parse
import urllib.request

from PIL import Image

UA = "LanaTravelClub-landing/1.0 (https://github.com/pe1erpe1renko-sketch/lanatravelclub)"
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
IMG_DIR = os.path.join(ROOT, "img")

TARGET_WIDTH = 1600
MIN_ORIGINAL_WIDTH = 1200
JPEG_QUALITY = 82

OK_LICENCES = ("cc by", "cc by-sa", "cc0", "public domain", "cc-by", "pd-")
BAD_WORDS = ("logo", "map", "carte", "plan", "diagram", "schema", "coat of arms",
             "flag", "seal", "portrait", "icon", "chart")

# filename -> (wikipedia title or None, commons fallback search query)
TARGETS = [
    ("hero.jpg",            "Hassan_II_Mosque", "Hassan II Mosque ocean"),
    ("about-fes.jpg",       "Fes_el_Bali",      "Fez medina street"),
    ("d1-casablanca.jpg",   None,               "Hassan II Mosque minaret"),
    ("d2-volubilis.jpg",    "Volubilis",        "Volubilis arch of Caracalla"),
    ("d3-fes.jpg",          "Chouara_Tannery",  "Fez tannery"),
    ("d4-atlas.jpg",        "Ifrane",           "Middle Atlas cedar forest"),
    ("d5-marrakech.jpg",    "Jemaa_el-Fnaa",    "Jemaa el-Fnaa sunset"),
    ("d6-essaouira.jpg",    "Essaouira",        "Essaouira port boats"),
    ("d7-departure.jpg",    "Koutoubia_Mosque", "Koutoubia mosque Marrakech"),
    ("h-casablanca.jpg",    "Casablanca",       "Casablanca skyline"),
    ("h-fes.jpg",           "Fez,_Morocco",     "Fez medina rooftops"),
    ("h-marrakech.jpg",     "Majorelle_Garden", "Majorelle Garden blue"),
    ("price-marrakech.jpg", "Marrakesh",        "Marrakesh sunset"),
]


def get_json(url):
    req = urllib.request.Request(url, headers={"User-Agent": UA,
                                               "Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=40) as r:
        return json.loads(r.read().decode("utf-8"))


def get_bytes(url):
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=90) as r:
        return r.read()


def plain(html):
    return re.sub(r"<[^>]+>", "", html or "").strip()


def looks_bad(name):
    low = name.lower()
    return any(w in low for w in BAD_WORDS)


def commons_file_page(title):
    return "https://commons.wikimedia.org/wiki/" + urllib.parse.quote(title.replace(" ", "_"))


def from_summary(title):
    """Candidate from the Wikipedia page summary, or None."""
    url = "https://en.wikipedia.org/api/rest_v1/page/summary/" + urllib.parse.quote(title)
    try:
        data = get_json(url)
    except Exception as exc:                                  # noqa: BLE001
        print("    summary failed: %s" % exc)
        return None
    oi = data.get("originalimage")
    if not oi:
        print("    no originalimage on %s" % title)
        return None
    w, h = oi.get("width", 0), oi.get("height", 0)
    src = oi["source"]
    name = urllib.parse.unquote(src.rsplit("/", 1)[-1])
    if w < MIN_ORIGINAL_WIDTH:
        print("    rejected (width %s < %s): %s" % (w, MIN_ORIGINAL_WIDTH, name))
        return None
    if h and w <= h:
        print("    rejected (not horizontal %sx%s): %s" % (w, h, name))
        return None
    if looks_bad(name):
        print("    rejected (logo/map/diagram): %s" % name)
        return None
    # summary gives no structured licence data -> look the file up on Commons
    meta = commons_file_meta("File:" + name)
    if meta is None:
        print("    rejected (no usable Commons licence): %s" % name)
        return None
    return meta


def commons_file_meta(file_title):
    """imageinfo + licence check for one Commons file; None if not acceptable."""
    url = ("https://commons.wikimedia.org/w/api.php?action=query&titles=%s"
           "&prop=imageinfo&iiprop=url|size|extmetadata&iiurlwidth=%d&format=json"
           % (urllib.parse.quote(file_title), TARGET_WIDTH))
    try:
        data = get_json(url)
    except Exception as exc:                                  # noqa: BLE001
        print("    imageinfo failed: %s" % exc)
        return None
    pages = data.get("query", {}).get("pages", {})
    for page in pages.values():
        info = (page.get("imageinfo") or [None])[0]
        if not info:
            continue
        return accept(page.get("title", file_title), info)
    return None


def accept(title, info):
    """Turn one imageinfo record into a candidate dict, or None."""
    ex = info.get("extmetadata", {})
    licence = plain(ex.get("LicenseShortName", {}).get("value", ""))
    author = plain(ex.get("Artist", {}).get("value", "")) or "Unknown"
    width = info.get("width", 0)
    height = info.get("height", 0)

    if width < MIN_ORIGINAL_WIDTH:
        print("    rejected (width %s): %s" % (width, title))
        return None
    if height and width <= height:
        print("    rejected (not horizontal %sx%s): %s" % (width, height, title))
        return None
    if looks_bad(title):
        print("    rejected (logo/map/diagram): %s" % title)
        return None
    if not any(tok in licence.lower() for tok in OK_LICENCES):
        print("    rejected (licence %r): %s" % (licence, title))
        return None

    return {
        "title": title,
        "download": info.get("thumburl") or info["url"],
        "page": info.get("descriptionurl") or commons_file_page(title),
        "author": " ".join(author.split())[:160],
        "licence": licence,
        "width": width,
    }


def from_commons_search(query):
    url = ("https://commons.wikimedia.org/w/api.php?action=query&generator=search"
           "&gsrsearch=%s&gsrnamespace=6&gsrlimit=10&prop=imageinfo"
           "&iiprop=url|size|extmetadata&iiurlwidth=%d&format=json"
           % (urllib.parse.quote(query), TARGET_WIDTH))
    try:
        data = get_json(url)
    except Exception as exc:                                  # noqa: BLE001
        print("    commons search failed: %s" % exc)
        return None
    pages = data.get("query", {}).get("pages", {})
    ordered = sorted(pages.values(), key=lambda p: p.get("index", 999))
    for page in ordered:
        info = (page.get("imageinfo") or [None])[0]
        if not info:
            continue
        if not re.search(r"\.(jpe?g|png)$", page.get("title", ""), re.I):
            continue
        cand = accept(page.get("title", ""), info)
        if cand:
            return cand
    return None


def normalise(raw, dest):
    im = Image.open(io.BytesIO(raw))
    im = im.convert("RGB")
    if im.width > TARGET_WIDTH:
        height = round(im.height * TARGET_WIDTH / im.width)
        im = im.resize((TARGET_WIDTH, height), Image.LANCZOS)
    im.save(dest, "JPEG", quality=JPEG_QUALITY, optimize=True, progressive=True)
    return im.size


def main():
    os.makedirs(IMG_DIR, exist_ok=True)
    credits, failed = [], []

    for filename, wiki_title, query in TARGETS:
        print("== %s" % filename)
        cand = from_summary(wiki_title) if wiki_title else None
        if cand is None:
            print("    -> Commons search: %s" % query)
            cand = from_commons_search(query)
        if cand is None:
            print("    !! no usable candidate")
            failed.append(filename)
            continue

        dest = os.path.join(IMG_DIR, filename)
        try:
            size = normalise(get_bytes(cand["download"]), dest)
        except Exception as exc:                              # noqa: BLE001
            print("    !! download/convert failed: %s" % exc)
            failed.append(filename)
            continue

        print("    ok %s  %sx%s  (%s)" % (cand["title"], size[0], size[1], cand["licence"]))
        credits.append((filename, cand))

    write_credits(credits)
    if failed:
        print("\nFAILED: %s" % ", ".join(failed))
        return 1
    print("\nAll %d photos fetched." % len(credits))
    return 0


def write_credits(credits):
    out = [
        "# Источники фотографий",
        "",
        "Все фотографии загружены с Wikimedia Commons и распространяются по свободным",
        "лицензиям (CC BY, CC BY-SA, CC0 или Public domain).",
        "Файлы приведены к ширине 1600 px, JPEG, качество 82.",
        "",
        "| Файл | Автор | Лицензия | Страница файла на Commons |",
        "| --- | --- | --- | --- |",
    ]
    for filename, c in credits:
        out.append("| `img/%s` | %s | %s | [%s](%s) |"
                   % (filename, c["author"] or "—", c["licence"],
                      c["title"].replace("File:", ""), c["page"]))
    out.append("")
    out.append("Сгенерировано `tools/fetch_photos.py`.")
    with io.open(os.path.join(ROOT, "CREDITS.md"), "w", encoding="utf-8") as fh:
        fh.write("\n".join(out) + "\n")


if __name__ == "__main__":
    sys.exit(main())
