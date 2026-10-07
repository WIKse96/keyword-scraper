# Web Scraper & Crawler

Narzędzia do przeszukiwania stron internetowych pod kątem słów kluczowych.

**Dwa tryby pracy:**
- **scraper.py** - pobiera URL-e z sitemap.xml
- **crawler.py** - sam odkrywa URL-e zaczynając od strony głównej

## Instalacja

```bash
pip install -r requirements.txt
```

---

## Scraper (sitemap.xml)

Pobiera listę stron z pliku sitemap.xml i przeszukuje każdą.

### Użycie

```bash
python scraper.py <URL_SITEMAP>
```

### Przykład

```bash
python scraper.py https://www.seart.pl/sitemap.xml
```

### Opcje

| Opcja | Domyślnie | Opis |
|-------|-----------|------|
| `-k`, `--keywords` | `keywords.txt` | Plik ze słowami kluczowymi |
| `-o`, `--output` | `results.csv` | Plik wynikowy CSV |
| `-v`, `--visited` | `visited.txt` | Plik z odwiedzonymi URL |

---

## Crawler (odkrywanie URL-ów)

Zaczyna od strony głównej, zbiera wszystkie linki i rekurencyjnie odwiedza każdy. Pozostaje w obrębie tej samej domeny.

### Użycie

```bash
python crawler.py <URL_STARTOWY>
```

### Przykład

```bash
python crawler.py https://www.seart.pl --max-pages 5000 --threads 10
```

### Opcje

| Opcja | Domyślnie | Opis |
|-------|-----------|------|
| `-m`, `--max-pages` | `1000` | Maksymalna liczba stron do odwiedzenia |
| `-t`, `--threads` | `10` | Liczba równoległych wątków |
| `-k`, `--keywords` | `keywords.txt` | Plik ze słowami kluczowymi |
| `-o`, `--output` | `crawler_results.csv` | Plik wynikowy CSV |
| `-q`, `--queue` | `crawler_queue.db` | Baza SQLite (kolejka + visited) |
| `-e`, `--errors` | `crawler_errors.csv` | Plik CSV z błędami |

### Jak działa crawler

1. Zaczyna od podanego URL-a
2. Pobiera strony równolegle (domyślnie 10 wątków)
3. Wyciąga wszystkie linki (`<a href="...">`)
4. Filtruje linki - tylko ta sama domena
5. Pomija pliki (PDF, obrazy, JS, CSS itp.)
6. Dodaje nowe linki do kolejki SQLite
7. Powtarza aż do osiągnięcia limitu lub wyczerpania linków

### Baza danych SQLite

Wszystko jest w jednym pliku `crawler_queue.db`:
- **Tabela `queue`** - URL-e do odwiedzenia (z parent_url i link_rel)
- **Tabela `visited`** - URL-e już odwiedzone

Zalety:
- Brak limitu pamięci RAM (nawet 3+ miliony URL-ów)
- Szybki start (nie wczytuje wszystkiego do pamięci)
- Atomowy zapis (brak utraty danych przy przerwaniu)

### Wznawianie crawlera

Po osiągnięciu limitu lub przerwaniu (Ctrl+C) uruchom ponownie:

```bash
# Pierwsze uruchomienie - odwiedzi 1000 stron
python crawler.py https://example.com --max-pages 1000

# Kolejne uruchomienie - kontynuuje od miejsca gdzie skończył
python crawler.py https://example.com --max-pages 1000
```

### Przerwanie (Ctrl+C)

Crawler bezpiecznie zapisuje stan po Ctrl+C - baza SQLite jest zawsze aktualna.

### Plik błędów (crawler_errors.csv)

Strony które zwróciły błąd (404, 500, timeout) są zapisywane z metadanymi:

| Kolumna | Opis |
|---------|------|
| `url` | URL który zwrócił błąd |
| `status_code` | Kod HTTP (404, 500, 0=timeout) |
| `parent_url` | Strona z której prowadził link |
| `link_rel` | Atrybut `rel` linku (np. `nofollow`) |
| `datetime` | Data i godzina błędu |

Strony z błędami **nie blokują** kolejnych prób - przy następnym uruchomieniu będą sprawdzane ponownie.

### Migracja ze starych plików

Przy pierwszym uruchomieniu crawler automatycznie migruje:
- `crawler_queue.txt` → tabela `queue` w SQLite
- `crawler_visited.txt` → tabela `visited` w SQLite

Stare pliki są usuwane po migracji.

### Reset crawlera

Aby zacząć od nowa, usuń pliki:

```bash
rm crawler_queue.db crawler_errors.csv crawler_results.csv
```

---

## Narzędzia pomocnicze

### dedupe.py

Usuwa duplikaty z pliku CSV na podstawie pierwszej kolumny (URL):

```bash
python dedupe.py                    # domyślnie crawler_results.csv
python dedupe.py results.csv        # lub podaj inny plik
```

---

## Wspólne pliki

### keywords.txt

Lista słów kluczowych do wyszukiwania (jedno słowo/fraza na linię):

```
eko
ekologiczny
przyjazny środowisku
```

**Zasady wyszukiwania:**
- **Case-insensitive** - nie rozróżnia wielkości liter ("Eko" = "eko" = "EKO")
- **Całe słowa** - szuka tylko kompletnych słów, nie fragmentów
  - `eko` znajdzie: "eko", "Eko,", "(eko)", "produkt eko."
  - `eko` **nie** znajdzie: "ekologiczny", "jakiekolwiek"
- Słowo może być otoczone spacjami, znakami interpunkcyjnymi, nawiasami itp.

### results.csv / crawler_results.csv

Wyniki w formacie CSV:

| url | keyword | date |
|-----|---------|------|
| https://example.com/strona1.html | eko | 2026-07-29 |
| https://example.com/strona2.html | ekologiczny | 2026-07-29 |

---

## Wydajność

Crawler jest zoptymalizowany do dużej skali:

| Funkcja | Opis |
|---------|------|
| SQLite (kolejka + visited) | Brak limitu pamięci, obsługa milionów URL-ów |
| Równoległe pobieranie | 10 wątków domyślnie, konfigurowalne (`--threads`) |
| Batch processing | Pobiera 10 stron naraz, potem przetwarza |
| Atomowy zapis | SQLite zapisuje natychmiast, brak utraty danych |

### Szacowane zużycie przy dużej skali

| URL-ów | RAM | Plik .db |
|--------|-----|----------|
| 100 000 | ~50 MB | ~15 MB |
| 500 000 | ~50 MB | ~75 MB |
| 3 000 000 | ~50 MB | ~450 MB |

RAM jest stały - wszystko jest na dysku w SQLite.

---

## Wymagania

- Python 3.10+
- requests
- beautifulsoup4
