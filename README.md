# GEO tracker: pomiar widoczności marek w odpowiedziach AI

Skrypt zadaje ten sam zestaw zapytań modelom AI z włączonym wyszukiwaniem w sieci (OpenAI, Gemini, Perplexity), wielokrotnie, i mierzy, jak często i na którym miejscu pojawiają się w odpowiedziach wybrane marki oraz jakie źródła są cytowane.

## Co mierzy

- **Wskaźnik wzmianek** marki z 95-procentowym przedziałem ufności Wilsona
- **Udział głosu** marki na tle konkurencji
- **Średnią pozycję** marki na liście poleceń
- **Cytowane domeny i typy źródeł**
- **Stabilność** odpowiedzi między powtórzeniami (współczynnik Jaccarda)
- **Zgodność silników** co do marki polecanej jako pierwsza
- **Zgodność z ręcznym sprawdzeniem** w aplikacjach (walidacja)

## Uruchomienie

```bash
python -m venv .venv
# Windows: .venv\Scripts\activate    macOS/Linux: source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env        # wklej klucze API do pliku .env
python zbieraj.py --test    # test bez kluczy API, dane udawane
python analizuj.py --test
python zbieraj.py --limit 2 --powtorzenia 1   # mały test na prawdziwych API
python zbieraj.py           # pełne zbieranie
python analizuj.py          # wyniki w folderze wyniki/
```

Przed pierwszym prawdziwym uruchomieniem uzupełnij nazwy modeli w `config.py`.

## Dane wejściowe

- `dane/zapytania.csv`: zamrożona lista zapytań (id, grupa, zapytanie)
- `dane/marki.csv`: marki, ich domeny, wzorce nazw z odmianami (wyrażenia regularne) i oznaczenie marki-klienta
- `dane/typy_zrodel.csv`: przypisanie znanych domen do typów źródeł
- `dane/walidacja_reczna.csv`: marki zauważone przy ręcznym sprawdzeniu w aplikacjach

## Ograniczenia

- Odpowiedzi z API mogą różnić się od tego, co widzi użytkownik w aplikacjach; skala tej różnicy jest mierzona w walidacji.
- Wyniki zależą od daty, wersji modelu i ustawionej lokalizacji. Odpowiedzi AI zmieniają się w czasie.
- Rozpoznawanie marek opiera się na wzorcach nazw; jego trafność jest sprawdzana ręcznie na losowej próbce (`wyniki/probka_do_kontroli.csv`).
- „Przegląd od AI” w Google jest sprawdzany ręcznie, bo automatyczne pobieranie wyników Google narusza jego regulamin.

## Autor

Piotr Sterlingow
