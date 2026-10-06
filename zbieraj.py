"""Zbieranie odpowiedzi AI.

Przykłady uruchomienia:
    python zbieraj.py --test                      # bez kluczy API, dane udawane
    python zbieraj.py --limit 2 --powtorzenia 1   # mały test na prawdziwych API
    python zbieraj.py --zapytania R02 M02 --powtorzenia 1 --silniki openai  # wybrane zapytania
    python zbieraj.py                             # pełne zbieranie wg config.py

Wyniki dopisywane są do pliku dane/odpowiedzi.jsonl (jedna odpowiedź = jedna linia).
Jeśli przerwiesz skrypt, po ponownym uruchomieniu pominie to, co już zebrał.
"""

import argparse
import csv
import json
import os
import random
import time
from datetime import datetime

from dotenv import load_dotenv

import config


def wczytaj_zapytania(sciezka):
    with open(sciezka, encoding="utf-8") as f:
        return list(csv.DictReader(f))


def juz_zebrane(sciezka, tryb_testowy):
    """Zbiór kluczy 'id|silnik|próba' dla odpowiedzi zapisanych bez błędu.

    Odpowiedzi testowe i prawdziwe liczymy osobno, żeby test nie blokował
    późniejszego prawdziwego zbierania.
    """
    gotowe = set()
    if os.path.exists(sciezka):
        with open(sciezka, encoding="utf-8") as f:
            for linia in f:
                r = json.loads(linia)
                if not r.get("blad") and r.get("tryb_testowy", False) == tryb_testowy:
                    gotowe.add(f'{r["id_zapytania"]}|{r["silnik"]}|{r["proba"]}')
    return gotowe


def udawana_odpowiedz(zapytanie, silnik):
    """Tryb testowy: losowa odpowiedź z markami i źródłami z plików danych."""
    with open(config.PLIK_MAREK, encoding="utf-8") as f:
        marki = list(csv.DictReader(f))
    with open(config.PLIK_TYPOW_ZRODEL, encoding="utf-8") as f:
        domeny = [w["domena"] for w in csv.DictReader(f)]
    wybrane = random.sample(marki, k=random.randint(0, min(4, len(marki))))
    tekst = "Odpowiedź testowa. " + " ".join(
        f"Warto rozważyć {m['marka']}." for m in wybrane)
    zrodla_dom = random.sample(domeny + [m["domena"] for m in marki], k=3)
    zrodla = [{"url": f"https://{d}/artykul", "tytul": d, "domena": d} for d in zrodla_dom]
    return {"tekst": tekst, "zrodla": zrodla, "model": f"test-{silnik}",
            "wyszukiwanie": random.random() < 0.8}


def zapytaj_z_ponawianiem(funkcja, zapytanie):
    for proba in range(1, config.MAKS_PROB_PRZY_BLEDZIE + 1):
        try:
            return funkcja(zapytanie), ""
        except Exception as e:  # błąd sieci, limit zapytań, zła nazwa modelu itd.
            blad = f"{type(e).__name__}: {e}"
            if any(s in blad for s in ("WPISZ", "Uzupełnij", "Brak zmiennej", "404", "401")):
                raise  # błąd konfiguracji - nie ma sensu ponawiać
            czekaj = 2 ** proba
            print(f"    błąd (próba {proba}): {blad[:120]} - czekam {czekaj} s")
            time.sleep(czekaj)
    return None, blad


def main():
    parser = argparse.ArgumentParser(description="Zbieranie odpowiedzi AI")
    parser.add_argument("--test", action="store_true", help="tryb bez kluczy API")
    parser.add_argument("--limit", type=int, default=None, help="tylko N pierwszych zapytań")
    parser.add_argument("--powtorzenia", type=int, default=config.POWTORZENIA)
    parser.add_argument("--silniki", nargs="+", default=config.SILNIKI)
    parser.add_argument("--zapytania", nargs="+", default=None,
                        help="tylko wybrane id zapytań, np. --zapytania R02 M02")
    args = parser.parse_args()

    load_dotenv()  # wczytuje klucze API z pliku .env
    zapytania = wczytaj_zapytania(config.PLIK_ZAPYTAN)
    if args.zapytania:
        zapytania = [z for z in zapytania if z["id"] in args.zapytania]
    zapytania = zapytania[: args.limit]
    gotowe = juz_zebrane(config.PLIK_ODPOWIEDZI, args.test)
    plan = [(z, s, p) for z in zapytania for s in args.silniki
            for p in range(1, args.powtorzenia + 1)
            if f'{z["id"]}|{s}|{p}' not in gotowe]
    print(f"Do zebrania: {len(plan)} odpowiedzi (pominięto już zebrane: {len(gotowe)})")

    if not args.test:
        from silniki import FUNKCJE

    os.makedirs(os.path.dirname(config.PLIK_ODPOWIEDZI), exist_ok=True)
    with open(config.PLIK_ODPOWIEDZI, "a", encoding="utf-8") as plik:
        for i, (z, silnik, proba) in enumerate(plan, start=1):
            print(f"[{i}/{len(plan)}] {silnik} | {z['id']} | próba {proba}")
            if args.test:
                wynik, blad = udawana_odpowiedz(z["zapytanie"], silnik), ""
            else:
                try:
                    wynik, blad = zapytaj_z_ponawianiem(FUNKCJE[silnik], z["zapytanie"])
                except RuntimeError as e:  # błąd konfiguracji: brak klucza lub modelu
                    print(f"\nZATRZYMANO: {e}")
                    return
            rekord = {
                "czas": datetime.now().isoformat(timespec="seconds"),
                "silnik": silnik,
                "model": (wynik or {}).get("model", config.MODELE.get(silnik)),
                "id_zapytania": z["id"],
                "grupa": z["grupa"],
                "zapytanie": z["zapytanie"],
                "proba": proba,
                "tekst": (wynik or {}).get("tekst", ""),
                "zrodla": (wynik or {}).get("zrodla", []),
                "wyszukiwanie": (wynik or {}).get("wyszukiwanie"),
                "liczba_wynikow_wyszukiwania": (wynik or {}).get("liczba_wynikow_wyszukiwania"),
                "cytowania_w_tekscie": (wynik or {}).get("cytowania_w_tekscie"),
                "blad": blad,
                "tryb_testowy": args.test,
            }
            plik.write(json.dumps(rekord, ensure_ascii=False) + "\n")
            plik.flush()  # zapis od razu, żeby nic nie zginęło przy przerwaniu
            if not args.test:
                time.sleep(config.PRZERWA_MIEDZY_ZAPYTANIAMI_S)
    print("Gotowe. Teraz uruchom: python analizuj.py")


if __name__ == "__main__":
    main()
