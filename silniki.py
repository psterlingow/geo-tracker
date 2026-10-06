"""Wywołania trzech silników AI z włączonym wyszukiwaniem w sieci.

Każda funkcja przyjmuje treść zapytania i zwraca słownik:
    {"tekst": str, "zrodla": [{"url": str, "tytul": str, "domena": str}], "model": str}
"""

import os
import re
from urllib.parse import urlparse

import requests

import config


def domena_z_adresu(url: str) -> str:
    """Zwraca samą domenę bez 'www.', np. 'https://www.inpost.pl/cennik' -> 'inpost.pl'."""
    if not url:
        return ""
    netloc = urlparse(url).netloc.lower()
    return netloc[4:] if netloc.startswith("www.") else netloc


def _sprawdz_model(silnik: str) -> str:
    model = config.MODELE.get(silnik, "")
    if not model or model.startswith("WPISZ"):
        raise RuntimeError(
            f"Uzupełnij nazwę modelu dla silnika '{silnik}' w pliku config.py "
            "(lista modeli jest w dokumentacji dostawcy)."
        )
    return model


# --- OpenAI --------------------------------------------------------------------
def zapytaj_openai(zapytanie: str) -> dict:
    from openai import OpenAI  # import tutaj, żeby tryb testowy działał bez biblioteki

    model = _sprawdz_model("openai")
    klient = OpenAI(timeout=config.LIMIT_CZASU_S)  # klucz z OPENAI_API_KEY
    odp = klient.responses.create(
        model=model,
        input=zapytanie,
        tools=[{"type": "web_search", "user_location": config.LOKALIZACJA_OPENAI}],
    )
    # Model sam decyduje, czy szukać w sieci. Jeśli szukał, w odpowiedzi jest
    # element typu "web_search_call".
    wyszukiwanie = any(getattr(e, "type", "") == "web_search_call" for e in odp.output)
    zrodla = []
    # Źródła są adnotacjami typu "url_citation" w treści odpowiedzi.
    for element in odp.output:
        if getattr(element, "type", "") != "message":
            continue
        for czesc in getattr(element, "content", []) or []:
            for adn in getattr(czesc, "annotations", []) or []:
                if getattr(adn, "type", "") == "url_citation":
                    zrodla.append({"url": adn.url, "tytul": adn.title,
                                   "domena": domena_z_adresu(adn.url)})
    return {"tekst": odp.output_text or "", "zrodla": zrodla, "model": odp.model,
            "wyszukiwanie": wyszukiwanie}


# --- Gemini --------------------------------------------------------------------
def zapytaj_gemini(zapytanie: str) -> dict:
    from google import genai
    from google.genai import types

    model = _sprawdz_model("gemini")
    # klucz z GEMINI_API_KEY; limit czasu podawany w milisekundach
    klient = genai.Client(http_options=types.HttpOptions(timeout=config.LIMIT_CZASU_S * 1000))
    odp = klient.models.generate_content(
        model=model,
        contents=zapytanie,
        config=types.GenerateContentConfig(
            tools=[types.Tool(google_search=types.GoogleSearch())],
            # wyłącza automatyczne wywoływanie funkcji (i ostrzeżenie AFC) - nie jest tu potrzebne
            automatic_function_calling=types.AutomaticFunctionCallingConfig(disable=True),
        ),
    )
    zrodla = []
    kandydaci = odp.candidates or []
    meta = kandydaci[0].grounding_metadata if kandydaci else None
    # Gemini też sam decyduje, czy użyć wyszukiwarki Google.
    wyszukiwanie = bool(meta and (meta.web_search_queries or meta.grounding_chunks))
    for fragment in (meta.grounding_chunks if meta and meta.grounding_chunks else []):
        web = fragment.web
        if not web:
            continue
        # Adres z Gemini to zwykle przekierowanie Google, więc domenę bierzemy
        # z pola 'domain', a gdy go brak - z tytułu (często jest nim domena).
        domena = (web.domain or web.title or domena_z_adresu(web.uri) or "").lower()
        domena = domena[4:] if domena.startswith("www.") else domena
        zrodla.append({"url": web.uri or "", "tytul": web.title or "", "domena": domena})
    return {"tekst": odp.text or "", "zrodla": zrodla, "model": model,
            "wyszukiwanie": wyszukiwanie}


# --- Perplexity (Agent API) -----------------------------------------------------
# Przy jawnie wybranym modelu Perplexity nie wstawia znaczników [1] w tekście,
# więc prosimy o nie wprost (tak zaleca dokumentacja Perplexity). To polecenie
# dotyczy tylko formy cytowania, nie treści odpowiedzi. Opisz je w metodzie badania.
INSTRUKCJA_PERPLEXITY = (
    "Po każdym zdaniu opartym na wynikach wyszukiwania podaj numer źródła "
    "w nawiasie kwadratowym, np. [1] albo [1][2]. Cytuj tylko źródła, z których "
    "faktycznie korzystasz. Nie dodawaj osobnej listy źródeł na końcu."
)


def zapytaj_perplexity(zapytanie: str) -> dict:
    model = _sprawdz_model("perplexity")
    klucz = os.environ.get("PERPLEXITY_API_KEY")
    if not klucz:
        raise RuntimeError("Brak zmiennej PERPLEXITY_API_KEY w pliku .env")
    odp = requests.post(
        "https://api.perplexity.ai/v1/agent",
        headers={"Authorization": f"Bearer {klucz}", "Content-Type": "application/json"},
        # Przy wyborze konkretnego modelu narzędzie web_search trzeba dodać jawnie.
        json={"model": model, "input": zapytanie, "instructions": INSTRUKCJA_PERPLEXITY,
              "tools": [{"type": "web_search"}]},
        timeout=config.LIMIT_CZASU_S,
    )
    odp.raise_for_status()
    dane = odp.json()
    tekst, wyniki = "", []
    for element in dane.get("output", []):
        if element.get("type") == "message":
            for czesc in element.get("content", []):
                if czesc.get("type") == "output_text":
                    tekst += czesc.get("text", "")
        elif element.get("type") == "search_results":
            wyniki.extend(element.get("results", []))
    # Perplexity zwraca WSZYSTKIE znalezione wyniki, a w tekście oznacza te,
    # z których faktycznie skorzystał, znacznikami [1] albo [web:1]. Żeby
    # porównanie z OpenAI i Gemini było uczciwe, jako źródła liczymy tylko
    # wyniki zacytowane w tekście. Gdy znaczników brak, bierzemy wszystkie
    # i zaznaczamy to w polu "cytowania_w_tekscie".
    cytowane_id = {int(n) for n in re.findall(r"\[(?:web:)?(\d+)\]", tekst)}
    wybrane = [w for w in wyniki if w.get("id") in cytowane_id] if cytowane_id else wyniki
    zrodla = [{"url": w.get("url", ""), "tytul": w.get("title", ""),
               "domena": domena_z_adresu(w.get("url", ""))} for w in wybrane]
    return {"tekst": tekst, "zrodla": zrodla, "model": dane.get("model", model),
            "wyszukiwanie": bool(wyniki), "liczba_wynikow_wyszukiwania": len(wyniki),
            "cytowania_w_tekscie": bool(cytowane_id)}


FUNKCJE = {
    "openai": zapytaj_openai,
    "gemini": zapytaj_gemini,
    "perplexity": zapytaj_perplexity,
}
