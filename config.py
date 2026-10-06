"""Ustawienia projektu. To jedyny plik, który zwykle trzeba zmieniać."""

# --- Modele -----------------------------------------------------------------
# Nazwy modeli zmieniają się co kilka miesięcy. Przed pierwszym uruchomieniem
# sprawdź aktualną listę u każdego dostawcy i wpisz nazwę modelu, który
# obsługuje wyszukiwanie w sieci:
#   OpenAI:     https://platform.openai.com/docs/models
#   Gemini:     https://ai.google.dev/gemini-api/docs/models
#   Perplexity: https://docs.perplexity.ai (Agent API, model "perplexity/sonar")
MODELE = {
    "openai": "gpt-5.4-mini",
    "gemini": "gemini-3.8-flash",
    "perplexity": "perplexity/sonar",
}

# Silniki używane domyślnie (można zmienić flagą --silniki przy uruchomieniu).
SILNIKI = ["openai", "gemini", "perplexity"]

# Ile razy zadać każde zapytanie w każdym silniku.
POWTORZENIA = 5

# --- Lokalizacja wyszukiwania --------------------------------------------------
# Bez tego OpenAI domyślnie szuka jak użytkownik z USA.
LOKALIZACJA_OPENAI = {"type": "approximate", "country": "PL", "city": "Warszawa",
                      "timezone": "Europe/Warsaw"}

# --- Tempo i ponawianie --------------------------------------------------------
PRZERWA_MIEDZY_ZAPYTANIAMI_S = 7   # przerwa po każdym wywołaniu API
MAKS_PROB_PRZY_BLEDZIE = 4           # ile razy ponowić wywołanie po błędzie
LIMIT_CZASU_S = 120                  # maksymalny czas oczekiwania na odpowiedź

# --- Pliki -----------------------------------------------------------------------
PLIK_ZAPYTAN = "dane/zapytania.csv"
PLIK_MAREK = "dane/marki.csv"
PLIK_TYPOW_ZRODEL = "dane/typy_zrodel.csv"
PLIK_WALIDACJI = "dane/walidacja_reczna.csv"
PLIK_ODPOWIEDZI = "dane/odpowiedzi.jsonl"
FOLDER_WYNIKOW = "wyniki"
