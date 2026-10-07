#!/usr/bin/env python3
"""
Scraper stron z sitemap.xml
Szuka zadanych słów kluczowych i zapisuje wyniki do CSV
"""

import argparse
import csv
import os
import re
import sys
from datetime import datetime
from xml.etree import ElementTree

import requests
from bs4 import BeautifulSoup

# Litery polskie i łacińskie - słowo nie może być otoczone tymi znakami
LETTERS = r'a-zA-ZąćęłńóśźżĄĆĘŁŃÓŚŹŻ'


def load_keywords(filepath: str) -> list[str]:
    """Wczytuje słowa kluczowe z pliku (jedno na linię)."""
    if not os.path.exists(filepath):
        print(f"Błąd: Plik {filepath} nie istnieje")
        sys.exit(1)

    with open(filepath, 'r', encoding='utf-8') as f:
        keywords = [line.strip().lower() for line in f if line.strip()]

    if not keywords:
        print("Błąd: Brak słów kluczowych w pliku")
        sys.exit(1)

    return keywords


def load_visited(filepath: str) -> set[str]:
    """Wczytuje listę już odwiedzonych URL-ów."""
    if not os.path.exists(filepath):
        return set()

    with open(filepath, 'r', encoding='utf-8') as f:
        return {line.strip() for line in f if line.strip()}


def save_visited(filepath: str, url: str) -> None:
    """Dopisuje URL do listy odwiedzonych."""
    with open(filepath, 'a', encoding='utf-8') as f:
        f.write(url + '\n')


def parse_sitemap(url: str) -> list[str]:
    """Pobiera sitemap.xml i zwraca listę URL-ów."""
    try:
        response = requests.get(url, timeout=30)
        response.raise_for_status()
    except requests.RequestException as e:
        print(f"Błąd pobierania sitemap: {e}")
        sys.exit(1)

    try:
        root = ElementTree.fromstring(response.content)
    except ElementTree.ParseError as e:
        print(f"Błąd parsowania XML: {e}")
        sys.exit(1)

    # Namespace sitemap
    ns = {'sm': 'http://www.sitemaps.org/schemas/sitemap/0.9'}

    urls = []
    for loc in root.findall('.//sm:loc', ns):
        if loc.text:
            urls.append(loc.text.strip())

    return urls


def search_keywords(html: str, keywords: list[str]) -> list[str]:
    """Szuka słów kluczowych w treści HTML. Zwraca znalezione słowa.

    Szuka całych słów - słowo może być otoczone spacjami, znakami
    interpunkcyjnymi, ale nie innymi literami.
    Przykład: "eko" znajdzie "eko," i "produkt eko" ale nie "ekologiczny"
    """
    soup = BeautifulSoup(html, 'html.parser')

    # Usuń skrypty i style
    for tag in soup(['script', 'style', 'noscript']):
        tag.decompose()

    # Pobierz tekst strony
    text = soup.get_text(separator=' ').lower()

    found = []
    for keyword in keywords:
        # Regex: słowo nie poprzedzone i nie zakończone literą
        # (?<![litery]) - nie poprzedzone literą
        # (?![litery]) - nie zakończone literą
        pattern = rf'(?<![{LETTERS}]){re.escape(keyword)}(?![{LETTERS}])'
        if re.search(pattern, text, re.IGNORECASE):
            found.append(keyword)

    return found


def init_csv(filepath: str) -> None:
    """Tworzy plik CSV z nagłówkami jeśli nie istnieje."""
    if not os.path.exists(filepath):
        with open(filepath, 'w', encoding='utf-8', newline='') as f:
            writer = csv.writer(f)
            writer.writerow(['url', 'keyword', 'date'])


def save_result(filepath: str, url: str, keyword: str, date: str) -> None:
    """Dopisuje wynik do pliku CSV."""
    with open(filepath, 'a', encoding='utf-8', newline='') as f:
        writer = csv.writer(f)
        writer.writerow([url, keyword, date])


def main():
    parser = argparse.ArgumentParser(
        description='Scraper stron z sitemap.xml - szuka słów kluczowych'
    )
    parser.add_argument('sitemap_url', help='URL do sitemap.xml')
    parser.add_argument(
        '-k', '--keywords',
        default='keywords.txt',
        help='Plik ze słowami kluczowymi (domyślnie: keywords.txt)'
    )
    parser.add_argument(
        '-o', '--output',
        default='results.csv',
        help='Plik wynikowy CSV (domyślnie: results.csv)'
    )
    parser.add_argument(
        '-v', '--visited',
        default='visited.txt',
        help='Plik z odwiedzonymi URL (domyślnie: visited.txt)'
    )

    args = parser.parse_args()

    # Wczytaj słowa kluczowe
    keywords = load_keywords(args.keywords)
    print(f"Wczytano {len(keywords)} słów kluczowych: {', '.join(keywords)}")

    # Wczytaj odwiedzone strony
    visited = load_visited(args.visited)
    print(f"Już odwiedzonych stron: {len(visited)}")

    # Pobierz URL-e z sitemap
    print(f"\nPobieram sitemap: {args.sitemap_url}")
    urls = parse_sitemap(args.sitemap_url)
    print(f"Znaleziono {len(urls)} URL-ów w sitemap")

    # Filtruj już odwiedzone
    urls_to_visit = [u for u in urls if u not in visited]
    print(f"Do odwiedzenia: {len(urls_to_visit)} stron\n")

    if not urls_to_visit:
        print("Wszystkie strony już odwiedzone!")
        return

    # Inicjalizuj CSV
    init_csv(args.output)

    # Scrapuj strony
    today = datetime.now().strftime('%Y-%m-%d')
    total_found = 0

    for i, url in enumerate(urls_to_visit, 1):
        print(f"[{i}/{len(urls_to_visit)}] {url}")

        try:
            response = requests.get(url, timeout=30)
            response.raise_for_status()
        except requests.RequestException as e:
            print(f"  Błąd: {e}")
            save_visited(args.visited, url)
            continue

        # Szukaj słów kluczowych
        found_keywords = search_keywords(response.text, keywords)

        if found_keywords:
            print(f"  Znaleziono: {', '.join(found_keywords)}")
            for keyword in found_keywords:
                save_result(args.output, url, keyword, today)
                total_found += 1

        # Zapisz jako odwiedzoną
        save_visited(args.visited, url)

    print(f"\nZakończono! Znaleziono {total_found} dopasowań.")
    print(f"Wyniki zapisane w: {args.output}")


if __name__ == '__main__':
    main()
