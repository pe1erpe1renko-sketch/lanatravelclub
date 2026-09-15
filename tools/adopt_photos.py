#!/usr/bin/env python3
"""Принять фотографии заказчика: переименовать, привести к формату, обновить CREDITS.md.

Что делает:
  1. находит исходники по именам из MAPPING (в указанной папке);
  2. приводит каждый к ширине 1200 px с сохранением пропорций, JPEG q85,
     понижая качество, пока файл не уложится в 500 КБ;
  3. кладёт в img/ поверх прежних файлов;
  4. в CREDITS.md заменяет строки этих файлов на «предоставлено заказчиком»
     и снимает их из числа снимков с Wikimedia Commons.

Использование:
    python3 tools/adopt_photos.py ~/Downloads
    python3 tools/adopt_photos.py ~/Downloads --dry-run

Нужен Pillow:  pip install Pillow
"""

import argparse
import io
import os
import re
import sys

from PIL import Image, ImageOps

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
IMG_DIR = os.path.join(ROOT, "img")
CREDITS = os.path.join(ROOT, "CREDITS.md")

TARGET_WIDTH = 1200
START_QUALITY = 85
MAX_BYTES = 500 * 1024

# исходное имя -> (файл в img/, сюжет для CREDITS.md)
MAPPING = [
    ("IMG_6705.JPG", "about-fes.jpg",    "Рынок в медине: специи, ткани и ковры"),
    ("IMG_6720.JPG", "h-casablanca.jpg", "Касабланка с высоты: мечеть Хасана II и набережная"),
    ("IMG_6721.JPG", "h-fes.jpg",        "Красильни Феса с высоты"),
    ("IMG_6708.JPG", "h-marrakech.jpg",  "Сады Мажорель: вилла, кактусы и фонтан"),
]

OWNER_NOTE = "предоставлено заказчиком"


def find_source(folder, name):
    """Ищем без учёта регистра — телефоны отдают и .JPG, и .jpg."""
    target = name.lower()
    for entry in os.listdir(folder):
        if entry.lower() == target:
            return os.path.join(folder, entry)
    stem = os.path.splitext(target)[0]
    for entry in os.listdir(folder):
        if os.path.splitext(entry.lower())[0] == stem:
            return os.path.join(folder, entry)
    return None


def convert(src, dest, dry_run=False):
    im = Image.open(src)
    im = ImageOps.exif_transpose(im)          # учесть поворот из EXIF
    im = im.convert("RGB")
    if im.width > TARGET_WIDTH:
        height = round(im.height * TARGET_WIDTH / im.width)
        im = im.resize((TARGET_WIDTH, height), Image.LANCZOS)

    quality = START_QUALITY
    while True:
        buf = io.BytesIO()
        im.save(buf, "JPEG", quality=quality, optimize=True, progressive=True)
        data = buf.getvalue()
        if len(data) <= MAX_BYTES or quality <= 60:
            break
        quality -= 5

    if not dry_run:
        with open(dest, "wb") as fh:
            fh.write(data)
    return im.size, quality, len(data)


def update_credits(done, dry_run=False):
    """Строки принятых файлов переводим на «предоставлено заказчиком»."""
    if not os.path.exists(CREDITS):
        print("  CREDITS.md не найден — пропускаю")
        return
    with io.open(CREDITS, encoding="utf-8") as fh:
        text = fh.read()

    for _, filename, subject in done:
        row = re.compile(r"^\| `img/%s` \|.*$" % re.escape(filename), re.M)
        new_row = "| `img/%s` | %s | %s | — | — |" % (filename, subject, OWNER_NOTE)
        if row.search(text):
            text = row.sub(new_row, text)
        else:
            print("  строка для %s в CREDITS.md не найдена" % filename)

    note = ("\n## Фотографии заказчика\n\n"
            "Снимки, помеченные «%s», предоставлены Lana Travel Club и не связаны\n"
            "с Wikimedia Commons: права на них у заказчика, атрибуция Commons к ним\n"
            "не применяется. Приведены к ширине %d px, JPEG.\n" % (OWNER_NOTE, TARGET_WIDTH))
    if "## Фотографии заказчика" not in text:
        text = text.rstrip() + "\n" + note

    if not dry_run:
        with io.open(CREDITS, "w", encoding="utf-8") as fh:
            fh.write(text)
    print("  CREDITS.md обновлён (%d строк)" % len(done))


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("folder", help="папка с исходниками IMG_67xx")
    ap.add_argument("--dry-run", action="store_true", help="показать, но ничего не писать")
    args = ap.parse_args()

    if not os.path.isdir(args.folder):
        print("Папки нет: %s" % args.folder)
        return 1

    done, missing = [], []
    for source_name, filename, subject in MAPPING:
        src = find_source(args.folder, source_name)
        if not src:
            print("!! не найден %s" % source_name)
            missing.append(source_name)
            continue
        dest = os.path.join(IMG_DIR, filename)
        (w, h), q, size = convert(src, dest, args.dry_run)
        shape = "вертикальная" if h > w else "ГОРИЗОНТАЛЬНАЯ — проверьте соответствие!"
        print("ok %s -> img/%s  %dx%d  q%d  %.0f КБ  (%s)"
              % (source_name, filename, w, h, q, size / 1024.0, shape))
        done.append((source_name, filename, subject))

    if done:
        update_credits(done, args.dry_run)
    if missing:
        print("\nНе хватает: %s" % ", ".join(missing))
        return 1
    print("\nГотово: %d фотографий принято." % len(done))
    return 0


if __name__ == "__main__":
    sys.exit(main())
