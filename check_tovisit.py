#!/usr/bin/env python3
"""
Sprawdza URLe z tovisit.txt pod kątem keywords z keywords.txt
"""

import csv
import re
import sys
from datetime import datetime

import requests
from bs4 import BeautifulSoup

LETTERS = r'a-zA-ZąćęłńóśźżĄĆĘŁŃÓŚŹŻ'


def load_keywords(filepath: str) -> list[str]:
    with open(filepath, 'r', encoding='utf-8') as f:
        return [line.strip().lower() for line in f if line.strip()]


def load_urls(filepath: str) -> list[str]:
    with open(filepath, 'r', encoding='utf-8') as f:
        return [line.strip() for line in f if line.strip() and line.strip().startswith('http')]


def search_keywords(html: str, keywords: list[str]) -> list[str]:
    soup = BeautifulSoup(html, 'html.parser')
    for tag in soup(['script', 'style', 'noscript']):
        tag.decompose()
    text = soup.get_text(separator=' ').lower()

    found = []
    for keyword in keywords:
        pattern = rf'(?<![{LETTERS}]){re.escape(keyword)}(?![{LETTERS}])'
        if re.search(pattern, text, re.IGNORECASE):
            found.append(keyword)
    return found


def main():
    keywords = load_keywords('keywords.txt')
    urls = load_urls('tovisit.txt')

    print(f"Keywords: {', '.join(keywords)}")
    print(f"URLs do sprawdzenia: {len(urls)}\n")

    today = datetime.now().strftime('%Y-%m-%d')
    results = []

    for i, url in enumerate(urls, 1):
        print(f"[{i}/{len(urls)}] {url}", end=" ")
        sys.stdout.flush()

        try:
            response = requests.get(url, timeout=30)
            response.raise_for_status()
            found = search_keywords(response.text, keywords)

            if found:
                print(f"-> ZNALEZIONO: {', '.join(found)}")
                for kw in found:
                    results.append({'url': url, 'keyword': kw, 'date': today})
            else:
                print("-> brak")

        except requests.RequestException as e:
            print(f"-> BŁĄD: {e}")

    # Zapisz wyniki
    if results:
        with open('tovisit_results.csv', 'w', encoding='utf-8', newline='') as f:
            writer = csv.DictWriter(f, fieldnames=['url', 'keyword', 'date'])
            writer.writeheader()
            writer.writerows(results)
        print(f"\nZnaleziono {len(results)} dopasowań, zapisano do tovisit_results.csv")
    else:
        print("\nNie znaleziono żadnych keywords na sprawdzonych stronach")


if __name__ == '__main__':
    main()
