"""Analiza zebranych odpowiedzi.

Uruchomienie:
    python analizuj.py          # analiza prawdziwych odpowiedzi
    python analizuj.py --test   # analiza odpowiedzi z trybu testowego

Wyniki trafiają do folderu wyniki/ jako pliki CSV gotowe do Looker Studio.
"""

import argparse
import csv
import json
import math
import os
import re
from collections import Counter
from itertools import combinations

import pandas as pd

import config


# --- Wczytywanie ------------------------------------------------------------------
def wczytaj_marki():
    """Każda marka dostaje wyrażenie regularne zbudowane z jej wzorców.

    Wzorce w marki.csv oddzielasz znakiem '|', np. 'inpost(?:u|em|owi)?|inpoście'.
    (?<!\\w) i (?!\\w) pilnują, żeby dopasować całe słowo, a nie jego fragment.
    """
    marki = []
    with open(config.PLIK_MAREK, encoding="utf-8") as f:
        for w in csv.DictReader(f):
            wzorzec = r"(?<!\w)(?:" + w["wzorce"] + r")(?!\w)"
            marki.append({
                "marka": w["marka"],
                "domena": w["domena"].lower().strip(),
                "regex": re.compile(wzorzec, re.IGNORECASE),
                "klient": w["klient"].strip().lower() == "tak",
            })
    return marki


def wczytaj_typy_zrodel(marki):
    typy = {m["domena"]: "strona marki" for m in marki}
    if os.path.exists(config.PLIK_TYPOW_ZRODEL):
        with open(config.PLIK_TYPOW_ZRODEL, encoding="utf-8") as f:
            for w in csv.DictReader(f):
                typy.setdefault(w["domena"].lower().strip(), w["typ"])
    return typy


def typ_domeny(domena, typy):
    """Dopasowuje też subdomeny, np. 'blog.inpost.pl' -> typ domeny 'inpost.pl'."""
    for znana, typ in typy.items():
        if domena == znana or domena.endswith("." + znana):
            return typ
    return "inne"


# --- Statystyka --------------------------------------------------------------------
def wilson(k, n, z=1.96):
    """95-procentowy przedział ufności Wilsona dla odsetka k/n."""
    if n == 0:
        return (float("nan"), float("nan"))
    p = k / n
    mianownik = 1 + z**2 / n
    srodek = (p + z**2 / (2 * n)) / mianownik
    polowa = z * math.sqrt(p * (1 - p) / n + z**2 / (4 * n**2)) / mianownik
    return (max(0.0, srodek - polowa), min(1.0, srodek + polowa))


def jaccard(a, b):
    """Podobieństwo dwóch zbiorów marek: część wspólna / suma (1 = identyczne)."""
    a, b = set(a), set(b)
    if not a and not b:
        return 1.0  # w obu próbach brak marek: traktujemy jako zgodne
    return len(a & b) / len(a | b)


def wykryj_marki(tekst, marki):
    """Lista marek w kolejności pierwszego wystąpienia w tekście."""
    znalezione = []
    for m in marki:
        trafienie = m["regex"].search(tekst)
        if trafienie:
            znalezione.append((trafienie.start(), m["marka"]))
    return [marka for _, marka in sorted(znalezione)]


# --- Analiza ------------------------------------------------------------------------
def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--test", action="store_true", help="analizuj odpowiedzi testowe")
    args = parser.parse_args()

    marki = wczytaj_marki()
    klient = next((m for m in marki if m["klient"]), None)
    typy = wczytaj_typy_zrodel(marki)

    rekordy = []
    with open(config.PLIK_ODPOWIEDZI, encoding="utf-8") as f:
        for linia in f:
            r = json.loads(linia)
            if r.get("tryb_testowy", False) == args.test and not r.get("blad"):
                rekordy.append(r)
    if not rekordy:
        print("Brak odpowiedzi do analizy. Sprawdź, czy zbieranie się udało.")
        return
    print(f"Analizuję {len(rekordy)} odpowiedzi.")

    # 1. Jedna linia na odpowiedź + lista wzmianek + lista źródeł
    odpowiedzi, wzmianki, zrodla = [], [], []
    for i, r in enumerate(rekordy, start=1):
        kolejnosc = wykryj_marki(r["tekst"], marki)
        domeny = sorted({z["domena"] for z in r["zrodla"] if z.get("domena")})
        klient_cytowany = bool(klient) and any(
            d == klient["domena"] or d.endswith("." + klient["domena"]) for d in domeny)
        odpowiedzi.append({
            "id_odpowiedzi": i, "silnik": r["silnik"], "model": r["model"],
            "id_zapytania": r["id_zapytania"], "grupa": r["grupa"], "proba": r["proba"],
            "data": r["czas"][:10], "marki": "|".join(kolejnosc),
            "liczba_marek": len(kolejnosc),
            "klient_wymieniony": int(bool(klient) and klient["marka"] in kolejnosc),
            "pozycja_klienta": (kolejnosc.index(klient["marka"]) + 1
                                if klient and klient["marka"] in kolejnosc else ""),
            "klient_cytowany": int(klient_cytowany),
            "liczba_zrodel": len(domeny), "domeny": "|".join(domeny),
            "wyszukiwanie": ("" if r.get("wyszukiwanie") is None else int(r["wyszukiwanie"])),
        })
        for poz, marka in enumerate(kolejnosc, start=1):
            wzmianki.append({"silnik": r["silnik"], "grupa": r["grupa"],
                             "id_zapytania": r["id_zapytania"], "proba": r["proba"],
                             "marka": marka, "pozycja": poz})
        for d in domeny:
            zrodla.append({"silnik": r["silnik"], "grupa": r["grupa"],
                           "domena": d, "typ": typ_domeny(d, typy)})

    df_odp = pd.DataFrame(odpowiedzi)
    df_wzm = pd.DataFrame(wzmianki, columns=["silnik", "grupa", "id_zapytania",
                                             "proba", "marka", "pozycja"])
    df_zr = pd.DataFrame(zrodla, columns=["silnik", "grupa", "domena", "typ"])

    # 2. Podsumowanie marek: osobno dla każdej grupy zapytań i łącznie
    wiersze = []
    for (silnik, grupa), czesc in list(df_odp.groupby(["silnik", "grupa"])) + \
            [((s, "wszystkie"), c) for s, c in df_odp.groupby("silnik")]:
        n = len(czesc)
        wszystkie_wzm = sum(len(m.split("|")) for m in czesc["marki"] if m)
        for m in marki:
            z_marka = czesc["marki"].apply(lambda x: m["marka"] in x.split("|") if x else False)
            k = int(z_marka.sum())
            dol, gora = wilson(k, n)
            pozycje = df_wzm[(df_wzm.silnik == silnik) & (df_wzm.marka == m["marka"]) &
                             ((df_wzm.grupa == grupa) if grupa != "wszystkie" else True)]["pozycja"]
            wiersze.append({
                "silnik": silnik, "grupa": grupa, "marka": m["marka"],
                "klient": int(m["klient"]), "liczba_odpowiedzi": n, "liczba_wzmianek": k,
                "wskaznik_wzmianek": round(k / n, 4),
                "wilson_dol": round(dol, 4), "wilson_gora": round(gora, 4),
                "udzial_glosu": round(k / wszystkie_wzm, 4) if wszystkie_wzm else 0,
                "srednia_pozycja": round(pozycje.mean(), 2) if len(pozycje) else "",
            })
    df_marki = pd.DataFrame(wiersze)

    # 3. Źródła: które domeny i typy są cytowane najczęściej
    if len(df_zr):
        df_zrodla = (df_zr.groupby(["silnik", "domena", "typ"]).size()
                     .reset_index(name="liczba_cytowan")
                     .sort_values(["silnik", "liczba_cytowan"], ascending=[True, False]))
        df_zrodla["udzial_w_silniku"] = (df_zrodla["liczba_cytowan"] /
            df_zrodla.groupby("silnik")["liczba_cytowan"].transform("sum")).round(4)
    else:
        df_zrodla = pd.DataFrame()

    # 4. Stabilność: jak bardzo różnią się marki między powtórzeniami tego samego zapytania
    stab = []
    for (silnik, idz), czesc in df_odp.groupby(["silnik", "id_zapytania"]):
        zbiory = [set(m.split("|")) if m else set() for m in czesc["marki"]]
        pary = list(combinations(zbiory, 2))
        stab.append({"silnik": silnik, "id_zapytania": idz, "liczba_prob": len(zbiory),
                     "sredni_jaccard": round(sum(jaccard(a, b) for a, b in pary) / len(pary), 4)
                     if pary else ""})
    df_stab = pd.DataFrame(stab)

    # 5. Zgodność silników: najczęściej polecana jako pierwsza marka w każdym silniku
    zgodnosc = []
    for idz, czesc in df_odp.groupby("id_zapytania"):
        wiersz = {"id_zapytania": idz}
        pierwsze = {}
        for silnik, cz in czesc.groupby("silnik"):
            pierwsze_marki = [m.split("|")[0] for m in cz["marki"] if m]
            pierwsze[silnik] = Counter(pierwsze_marki).most_common(1)[0][0] if pierwsze_marki else ""
            wiersz[f"pierwsza_marka_{silnik}"] = pierwsze[silnik]
        wartosci = [v for v in pierwsze.values() if v]
        wiersz["zgodne_wszystkie"] = int(len(wartosci) == len(pierwsze) and len(set(wartosci)) == 1)
        zgodnosc.append(wiersz)
    df_zgod = pd.DataFrame(zgodnosc)

    # 6. Walidacja: porównanie z odpowiedziami sprawdzonymi ręcznie w aplikacjach
    df_wal = pd.DataFrame()
    if os.path.exists(config.PLIK_WALIDACJI):
        recznie = pd.read_csv(config.PLIK_WALIDACJI, dtype=str).fillna("")
        wal = []
        for _, w in recznie.iterrows():
            api = df_odp[(df_odp.id_zapytania == w["id_zapytania"]) &
                         (df_odp.silnik == w["silnik"])]
            if not len(api) or not w["marki_recznie"]:
                continue
            marki_api = set().union(*[set(m.split("|")) if m else set() for m in api["marki"]])
            marki_r = set(w["marki_recznie"].split("|"))
            wal.append({"id_zapytania": w["id_zapytania"], "silnik": w["silnik"],
                        "marki_api": "|".join(sorted(marki_api)),
                        "marki_recznie": "|".join(sorted(marki_r)),
                        "jaccard": round(jaccard(marki_api, marki_r), 4)})
        df_wal = pd.DataFrame(wal)

    # 6b. Jak często silnik w ogóle sięgał do wyszukiwarki
    df_szuk = pd.DataFrame()
    znane = df_odp[df_odp["wyszukiwanie"] != ""].copy()
    if len(znane):
        znane["wyszukiwanie"] = znane["wyszukiwanie"].astype(int)
        df_szuk = (znane.groupby(["silnik", "grupa"])["wyszukiwanie"]
                   .agg(liczba_odpowiedzi="count", z_wyszukiwaniem="sum").reset_index())
        df_szuk["odsetek_z_wyszukiwaniem"] = (df_szuk["z_wyszukiwaniem"] /
                                             df_szuk["liczba_odpowiedzi"]).round(4)

    # 7. Próbka do ręcznej kontroli: czy skrypt dobrze rozpoznaje marki?
    probka = pd.DataFrame([{"id_odpowiedzi": i, "silnik": r["silnik"],
                            "id_zapytania": r["id_zapytania"],
                            "marki_wykryte": odpowiedzi[i - 1]["marki"],
                            "marki_poprawne": "", "tekst": r["tekst"]}
                           for i, r in enumerate(rekordy, start=1)])
    probka = probka.sample(n=min(20, len(probka)), random_state=42)

    # 8. Zapis
    os.makedirs(config.FOLDER_WYNIKOW, exist_ok=True)
    pliki = {"odpowiedzi_kodowane.csv": df_odp, "wzmianki.csv": df_wzm,
             "marki_podsumowanie.csv": df_marki, "zrodla.csv": df_zrodla,
             "stabilnosc.csv": df_stab, "zgodnosc_silnikow.csv": df_zgod,
             "walidacja.csv": df_wal, "probka_do_kontroli.csv": probka,
             "wyszukiwanie.csv": df_szuk}
    for nazwa, df in pliki.items():
        if len(df):
            df.to_csv(os.path.join(config.FOLDER_WYNIKOW, nazwa), index=False, encoding="utf-8")

    # 9. Krótkie podsumowanie w konsoli
    if klient:
        print(f"\nWidoczność klienta: {klient['marka']} (wszystkie zapytania)")
        for _, w in df_marki[(df_marki.marka == klient["marka"]) &
                             (df_marki.grupa == "wszystkie")].iterrows():
            print(f"  {w.silnik:<11} wzmianki: {w.wskaznik_wzmianek:.0%} "
                  f"(95% przedział: {w.wilson_dol:.0%}–{w.wilson_gora:.0%}), "
                  f"udział głosu: {w.udzial_glosu:.0%}")
    if len(df_stab):
        print("\nŚrednia stabilność marek między powtórzeniami (1 = zawsze te same):")
        for silnik, cz in df_stab.groupby("silnik"):
            print(f"  {silnik:<11} {pd.to_numeric(cz.sredni_jaccard).mean():.2f}")
    if len(df_szuk):
        print("\nOdsetek odpowiedzi, w których silnik skorzystał z wyszukiwania:")
        for silnik, cz in df_szuk.groupby("silnik"):
            print(f"  {silnik:<11} {cz.z_wyszukiwaniem.sum() / cz.liczba_odpowiedzi.sum():.0%}")
    if len(df_wal):
        print(f"\nZgodność API z ręcznym sprawdzeniem (średni Jaccard): {df_wal.jaccard.mean():.2f}")
    print(f"\nPliki zapisane w folderze '{config.FOLDER_WYNIKOW}/'.")


if __name__ == "__main__":
    main()
