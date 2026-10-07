#!/usr/bin/env python3
"""
Web Crawler - odkrywa URL-e zaczynając od strony głównej
Zbiera linki rekurencyjnie i szuka słów kluczowych
"""

import argparse
import csv
import os
import re
import signal
import sqlite3
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup

# Litery polskie i łacińskie - słowo nie może być otoczone tymi znakami
LETTERS = r'a-zA-ZąćęłńóśźżĄĆĘŁŃÓŚŹŻ'

# Rozszerzenia plików do pominięcia (nie są stronami HTML)
SKIP_EXTENSIONS = {
    '.pdf', '.jpg', '.jpeg', '.png', '.gif', '.webp', '.svg', '.ico',
    '.css', '.js', '.xml', '.json', '.zip', '.rar', '.tar', '.gz',
    '.mp3', '.mp4', '.avi', '.mov', '.wmv', '.doc', '.docx', '.xls',
    '.xlsx', '.ppt', '.pptx', '.exe', '.dmg', '.apk'
}


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


def count_errors(filepath: str) -> int:
    """Liczy błędy w pliku CSV."""
    if not os.path.exists(filepath):
        return 0

    with open(filepath, 'r', encoding='utf-8') as f:
        reader = csv.reader(f)
        next(reader, None)  # pomiń nagłówek
        return sum(1 for _ in reader)


def init_errors_csv(filepath: str) -> None:
    """Tworzy plik CSV błędów z nagłówkami jeśli nie istnieje."""
    if not os.path.exists(filepath):
        with open(filepath, 'w', encoding='utf-8', newline='') as f:
            writer = csv.writer(f)
            writer.writerow(['url', 'status_code', 'parent_url', 'link_rel', 'datetime'])


def save_error(filepath: str, url: str, status_code: int, parent_url: str, link_rel: str) -> None:
    """Dopisuje URL z błędem do pliku CSV."""
    timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    with open(filepath, 'a', encoding='utf-8', newline='') as f:
        writer = csv.writer(f)
        writer.writerow([url, status_code, parent_url, link_rel, timestamp])


class CrawlerDB:
    """Baza danych crawlera - kolejka i visited w SQLite."""

    def __init__(self, db_path: str, old_queue_csv: str = None, old_visited_txt: str = None):
        self.db_path = db_path
        self.conn = sqlite3.connect(db_path)
        self._init_tables()

        # Migracja ze starych plików
        if old_queue_csv and os.path.exists(old_queue_csv):
            self._migrate_queue_from_csv(old_queue_csv)
        if old_visited_txt and os.path.exists(old_visited_txt):
            self._migrate_visited_from_txt(old_visited_txt)

    def _init_tables(self):
        self.conn.execute('''
            CREATE TABLE IF NOT EXISTS queue (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                url TEXT UNIQUE,
                parent_url TEXT,
                link_rel TEXT
            )
        ''')
        self.conn.execute('''
            CREATE TABLE IF NOT EXISTS visited (
                url TEXT PRIMARY KEY
            )
        ''')
        self.conn.execute('CREATE INDEX IF NOT EXISTS idx_queue_url ON queue(url)')
        self.conn.commit()

    def _migrate_queue_from_csv(self, csv_path: str):
        """Migruje kolejkę ze starego pliku CSV."""
        count = 0
        with open(csv_path, 'r', encoding='utf-8') as f:
            reader = csv.reader(f)
            for row in reader:
                if row:
                    url = row[0]
                    parent = row[1] if len(row) > 1 else ''
                    rel = row[2] if len(row) > 2 else ''
                    try:
                        self.conn.execute(
                            'INSERT OR IGNORE INTO queue (url, parent_url, link_rel) VALUES (?, ?, ?)',
                            (url, parent, rel)
                        )
                        count += 1
                    except sqlite3.IntegrityError:
                        pass
        self.conn.commit()
        if count > 0:
            print(f"Zmigrowano {count} URL-ów kolejki z {csv_path}")
            os.remove(csv_path)

    def _migrate_visited_from_txt(self, txt_path: str):
        """Migruje visited ze starego pliku TXT."""
        count = 0
        with open(txt_path, 'r', encoding='utf-8') as f:
            for line in f:
                url = line.strip()
                if url:
                    try:
                        self.conn.execute('INSERT OR IGNORE INTO visited (url) VALUES (?)', (url,))
                        count += 1
                    except sqlite3.IntegrityError:
                        pass
        self.conn.commit()
        if count > 0:
            print(f"Zmigrowano {count} URL-ów visited z {txt_path}")
            os.remove(txt_path)

    # --- Kolejka ---

    def queue_add(self, url: str, parent_url: str, link_rel: str) -> bool:
        """Dodaje URL do kolejki. Zwraca True jeśli dodano."""
        try:
            self.conn.execute(
                'INSERT INTO queue (url, parent_url, link_rel) VALUES (?, ?, ?)',
                (url, parent_url, link_rel)
            )
            self.conn.commit()
            return True
        except sqlite3.IntegrityError:
            return False

    def queue_pop_batch(self, limit: int) -> list[tuple]:
        """Pobiera i usuwa kilka elementów z kolejki."""
        cursor = self.conn.execute(
            'SELECT id, url, parent_url, link_rel FROM queue ORDER BY id LIMIT ?',
            (limit,)
        )
        rows = cursor.fetchall()
        if rows:
            ids = [row[0] for row in rows]
            placeholders = ','.join('?' * len(ids))
            self.conn.execute(f'DELETE FROM queue WHERE id IN ({placeholders})', ids)
            self.conn.commit()
            return [(row[1], row[2], row[3]) for row in rows]
        return []

    def queue_count(self) -> int:
        """Zwraca liczbę elementów w kolejce."""
        cursor = self.conn.execute('SELECT COUNT(*) FROM queue')
        return cursor.fetchone()[0]

    def queue_cleanup(self):
        """Usuwa z kolejki URL-e które są już w visited."""
        self.conn.execute('''
            DELETE FROM queue WHERE url IN (SELECT url FROM visited)
        ''')
        self.conn.commit()

    # --- Visited ---

    def visited_add(self, url: str) -> bool:
        """Dodaje URL do visited. Zwraca True jeśli dodano."""
        try:
            self.conn.execute('INSERT INTO visited (url) VALUES (?)', (url,))
            self.conn.commit()
            return True
        except sqlite3.IntegrityError:
            return False

    def visited_add_batch(self, urls: list[str]):
        """Dodaje wiele URL-ów do visited."""
        for url in urls:
            try:
                self.conn.execute('INSERT OR IGNORE INTO visited (url) VALUES (?)', (url,))
            except sqlite3.IntegrityError:
                pass
        self.conn.commit()

    def is_visited(self, url: str) -> bool:
        """Sprawdza czy URL był odwiedzony."""
        cursor = self.conn.execute('SELECT 1 FROM visited WHERE url = ?', (url,))
        return cursor.fetchone() is not None

    def visited_count(self) -> int:
        """Zwraca liczbę odwiedzonych URL-ów."""
        cursor = self.conn.execute('SELECT COUNT(*) FROM visited')
        return cursor.fetchone()[0]

    def close(self):
        """Zamyka połączenie z bazą."""
        self.conn.close()


def normalize_url(url: str) -> str:
    """Normalizuje URL - usuwa fragment (#) i trailing slash."""
    parsed = urlparse(url)
    # Usuń fragment (#section)
    normalized = parsed._replace(fragment='')
    result = normalized.geturl()
    # Usuń trailing slash (ale zostaw dla samej domeny)
    if result.endswith('/') and result.count('/') > 3:
        result = result.rstrip('/')
    return result


def is_same_domain(url: str, base_domain: str) -> bool:
    """Sprawdza czy URL należy do tej samej domeny."""
    parsed = urlparse(url)
    return parsed.netloc == base_domain or parsed.netloc == ''


def should_skip_url(url: str) -> bool:
    """Sprawdza czy URL powinien być pominięty (nie-HTML)."""
    parsed = urlparse(url)
    path_lower = parsed.path.lower()

    for ext in SKIP_EXTENSIONS:
        if path_lower.endswith(ext):
            return True

    return False


def extract_links(html: str, base_url: str, base_domain: str) -> dict[str, str]:
    """Wyciąga wszystkie linki z HTML należące do tej samej domeny.
    Zwraca dict: {url: rel_attribute}"""
    soup = BeautifulSoup(html, 'html.parser')
    links = {}

    for a_tag in soup.find_all('a', href=True):
        href = a_tag['href'].strip()

        # Pomiń puste, javascript:, mailto:, tel:
        if not href or href.startswith(('javascript:', 'mailto:', 'tel:', '#')):
            continue

        # Zbuduj pełny URL
        full_url = urljoin(base_url, href)

        # Normalizuj
        full_url = normalize_url(full_url)

        # Sprawdź domenę
        if not is_same_domain(full_url, base_domain):
            continue

        # Pomiń pliki nie-HTML
        if should_skip_url(full_url):
            continue

        # Upewnij się że to HTTP/HTTPS
        if full_url.startswith(('http://', 'https://')):
            # Pobierz atrybut rel (może być lista lub string)
            rel = a_tag.get('rel', [])
            if isinstance(rel, list):
                rel = ' '.join(rel)
            links[full_url] = rel

    return links


def fetch_url(url: str, timeout: int = 30) -> dict:
    """Pobiera URL i zwraca wynik. Thread-safe."""
    try:
        response = requests.get(url, timeout=timeout)
        response.raise_for_status()
        return {'url': url, 'html': response.text, 'error': None, 'status_code': response.status_code}
    except requests.HTTPError as e:
        status_code = e.response.status_code if e.response else 0
        return {'url': url, 'html': None, 'error': f'HTTP {status_code}', 'status_code': status_code}
    except requests.RequestException as e:
        return {'url': url, 'html': None, 'error': str(e), 'status_code': 0}


def search_keywords(html: str, keywords: list[str]) -> list[str]:
    """Szuka słów kluczowych w treści HTML. Zwraca znalezione słowa."""
    soup = BeautifulSoup(html, 'html.parser')

    # Usuń skrypty i style
    for tag in soup(['script', 'style', 'noscript']):
        tag.decompose()

    # Pobierz tekst strony
    text = soup.get_text(separator=' ').lower()

    found = []
    for keyword in keywords:
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


# Globalne zmienne dla obsługi przerwania
_state = {
    'db': None,
    'visited_buffer': None,
}


def handle_interrupt(signum, frame):
    """Zapisuje stan przed zakończeniem programu."""
    print("\n\nPrzerwano! Zapisuję stan...")
    if _state['db']:
        if _state['visited_buffer']:
            _state['db'].visited_add_batch(_state['visited_buffer'])
        queue_count = _state['db'].queue_count()
        visited_count = _state['db'].visited_count()
        _state['db'].close()
        print(f"Zapisano: {queue_count} w kolejce, {visited_count} odwiedzonych")
    print("Możesz wznowić crawling uruchamiając ponownie.")
    sys.exit(0)


def main():
    # Rejestruj obsługę Ctrl+C
    signal.signal(signal.SIGINT, handle_interrupt)
    signal.signal(signal.SIGTERM, handle_interrupt)

    parser = argparse.ArgumentParser(
        description='Web Crawler - odkrywa URL-e i szuka słów kluczowych'
    )
    parser.add_argument('start_url', help='URL startowy (np. https://example.com)')
    parser.add_argument(
        '-k', '--keywords',
        default='keywords.txt',
        help='Plik ze słowami kluczowymi (domyślnie: keywords.txt)'
    )
    parser.add_argument(
        '-o', '--output',
        default='crawler_results.csv',
        help='Plik wynikowy CSV (domyślnie: crawler_results.csv)'
    )
    parser.add_argument(
        '-m', '--max-pages',
        type=int,
        default=1000,
        help='Maksymalna liczba stron do odwiedzenia (domyślnie: 1000)'
    )
    parser.add_argument(
        '-q', '--queue',
        default='crawler_queue.db',
        help='Baza SQLite z kolejką URL (domyślnie: crawler_queue.db)'
    )
    parser.add_argument(
        '-e', '--errors',
        default='crawler_errors.csv',
        help='Plik CSV z URL-ami które zwróciły błąd (domyślnie: crawler_errors.csv)'
    )
    parser.add_argument(
        '-t', '--threads',
        type=int,
        default=10,
        help='Liczba równoległych wątków (domyślnie: 10)'
    )

    args = parser.parse_args()

    # Normalizuj URL startowy
    start_url = normalize_url(args.start_url)
    base_domain = urlparse(start_url).netloc

    if not base_domain:
        print("Błąd: Nieprawidłowy URL startowy")
        sys.exit(1)

    print(f"Domena: {base_domain}")
    print(f"Limit stron: {args.max_pages}")

    # Wczytaj słowa kluczowe
    keywords = load_keywords(args.keywords)
    print(f"Wczytano {len(keywords)} słów kluczowych")

    # Policz dotychczasowe błędy
    error_count = count_errors(args.errors)
    if error_count:
        print(f"Dotychczasowych błędów: {error_count}")

    # Inicjalizuj pliki CSV
    init_csv(args.output)
    init_errors_csv(args.errors)

    # Inicjalizuj bazę SQLite (z migracją starych plików)
    old_queue_csv = args.queue.replace('.db', '.txt')
    old_visited_txt = 'crawler_visited.txt'
    db = CrawlerDB(args.queue, old_queue_csv, old_visited_txt)

    # Wyświetl stan
    visited_count = db.visited_count()
    print(f"Już odwiedzonych stron: {visited_count}")

    # Usuń z kolejki URL-e które są w visited
    db.queue_cleanup()

    # Zapisz referencje do globalnego stanu (dla obsługi przerwania)
    _state['db'] = db

    queue_count = db.queue_count()
    if queue_count:
        print(f"W kolejce: {queue_count} URL-ów do odwiedzenia")
    else:
        # Dodaj URL startowy jeśli nie był odwiedzony
        if not db.is_visited(start_url):
            db.queue_add(start_url, '', '')
            queue_count = 1

    today = datetime.now().strftime('%Y-%m-%d')
    total_found = 0
    pages_visited = 0
    consecutive_errors = 0
    max_consecutive_errors = 10
    visited_buffer = []  # bufor do zapisu visited
    _state['visited_buffer'] = visited_buffer

    print(f"\nRozpoczynam crawling ({args.threads} wątków)...\n")

    with ThreadPoolExecutor(max_workers=args.threads) as executor:
        while pages_visited < args.max_pages:
            # Pobierz batch URL-ów z kolejki
            batch_size = min(args.threads, args.max_pages - pages_visited)
            batch = db.queue_pop_batch(batch_size)

            if not batch:
                break

            # Filtruj już odwiedzone
            batch = [(url, parent, rel) for url, parent, rel in batch if not db.is_visited(url)]
            if not batch:
                continue

            # Równoległe pobieranie
            url_to_meta = {item[0]: (item[1], item[2]) for item in batch}
            futures = {executor.submit(fetch_url, url): url for url, _, _ in batch}

            batch_errors = 0
            for future in as_completed(futures):
                url = futures[future]
                parent_url, link_rel = url_to_meta[url]
                result = future.result()

                pages_visited += 1

                if result['error']:
                    print(f"[{pages_visited}/{args.max_pages}] {url} - {result['error']}")
                    save_error(args.errors, url, result['status_code'], parent_url, link_rel)
                    error_count += 1
                    batch_errors += 1
                    continue

                # Sukces
                html = result['html']
                found_keywords = search_keywords(html, keywords)

                if found_keywords:
                    print(f"[{pages_visited}/{args.max_pages}] {url} - znaleziono: {', '.join(found_keywords)}")
                    for keyword in found_keywords:
                        save_result(args.output, url, keyword, today)
                        total_found += 1
                else:
                    print(f"[{pages_visited}/{args.max_pages}] {url}")

                # Wyciągnij nowe linki
                new_links = extract_links(html, url, base_domain)
                new_count = 0
                for link, rel in new_links.items():
                    if not db.is_visited(link) and db.queue_add(link, url, rel):
                        new_count += 1

                if new_count > 0:
                    print(f"  +{new_count} linków")

                # Dodaj do visited
                visited_buffer.append(url)

            # Zapisz visited z bufora
            db.visited_add_batch(visited_buffer)
            visited_buffer.clear()

            # Pokaż stan kolejki po batchu
            print(f"  --- Kolejka: {db.queue_count()} | Odwiedzonych: {db.visited_count()} ---")

            # Sprawdź consecutive errors (uproszczone - per batch)
            if batch_errors == len(batch):
                consecutive_errors += 1
                if consecutive_errors >= 3:  # 3 batche z samymi błędami
                    print(f"\n{consecutive_errors} batchy z błędami pod rząd - przerywam!")
                    break
            else:
                consecutive_errors = 0

    # Zapisz pozostały bufor i zamknij bazę
    if visited_buffer:
        db.visited_add_batch(visited_buffer)
    remaining = db.queue_count()
    db.close()

    print(f"\n{'='*50}")
    print(f"Zakończono!")
    print(f"Odwiedzono stron: {pages_visited}")
    print(f"Znaleziono dopasowań: {total_found}")
    print(f"Błędów (łącznie): {error_count}")
    print(f"Pozostało w kolejce: {remaining}")
    print(f"Wyniki zapisane w: {args.output}")
    if error_count:
        print(f"Błędy zapisane w: {args.errors}")

    if remaining > 0:
        print(f"\nUwaga: Osiągnięto limit {args.max_pages} stron.")
        print(f"Uruchom ponownie aby kontynuować.")


if __name__ == '__main__':
    main()
