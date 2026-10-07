#!/usr/bin/env python3
"""Usuwa duplikaty z CSV na podstawie pierwszej kolumny."""

import csv
import sys

def main():
    input_file = sys.argv[1] if len(sys.argv) > 1 else 'crawler_results.csv'

    seen = set()
    rows = []

    with open(input_file, 'r', encoding='utf-8') as f:
        reader = csv.reader(f)
        header = next(reader)
        rows.append(header)

        for row in reader:
            if row and row[0] not in seen:
                seen.add(row[0])
                rows.append(row)

    with open(input_file, 'w', encoding='utf-8', newline='') as f:
        writer = csv.writer(f)
        writer.writerows(rows)

    print(f"Gotowe. Unikalne wiersze: {len(rows) - 1}")

if __name__ == '__main__':
    main()
