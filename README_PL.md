# Band Structure Plotter v2

Aplikacja Streamlit do tworzenia publikacyjnych wykresów struktur pasmowych.

## Nowości w v2

- dowolna kolejność paneli przez pole **Pozycja w siatce**,
- nakładanie **noSOC + SOC** na jednym panelu,
- osobne kolory, style, grubości, przezroczystości i energie odniesienia dla noSOC/SOC,
- legenda noSOC/SOC,
- indeksy dolne w tytułach i opisach: wpisz np. `WSe_2` lub `WSe_{17}Al`,
- zapis całego projektu (ustawienia + dane) do JSON,
- zapis/odczyt projektu z prywatnego **GitHub Gist**,
- eksport PNG/PDF/SVG.

## Ubuntu

```bash
sudo apt update
sudo apt install python3-venv python3-pip unzip
unzip bandplot_app_v2.zip
cd bandplot_app
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
streamlit run app.py
```

Albo po rozpakowaniu:

```bash
chmod +x run_linux_mac.sh
./run_linux_mac.sh
```

## Dane

Pliki `.gnu`, `.dat`, `.txt`: dwie kolumny `x E`, a puste linie oddzielają kolejne pasma.

Wczytaj pliki bazowe w sekcji **Pasma podstawowe / noSOC**, a pliki ze spin-orbitą w sekcji **Pasma SOC**. Następnie w ustawieniach każdego panelu wybierz, który plik SOC ma zostać nałożony.

## Indeksy dolne

Najprościej:

- `WSe_2` -> WSe z 2 w indeksie dolnym,
- `WSe_{17}Al` -> 17 w indeksie dolnym,
- można też używać składni Matplotlib MathText, np. `$WSe_2$`.

## Zapis projektu

**JSON** jest pełnym projektem: zawiera ustawienia i dane wejściowe zakodowane w pliku. Po ponownym wczytaniu nie trzeba ustawiać wszystkiego od początku.

**GitHub Gist**: aplikacja może zapisać ten sam projekt jako prywatny Gist. Potrzebny jest GitHub Personal Access Token z uprawnieniem do Gistów. Token nie jest zapisywany przez aplikację w projekcie.

Nie należy wpisywać tokena bezpośrednio do kodu ani commitować go do repozytorium. Przy wdrożeniu na Streamlit Community Cloud najlepiej trzymać token w Streamlit Secrets.

## Domyslne style v3
- noSOC: czarna linia ciagla, grubosc 0.8
- SOC: czerwona linia przerywana, grubosc 0.8

## GitHub Gist - lista projektow
W sekcji projektu podaj token GitHub i kliknij "Odswiez liste projektow z GitHub". Aplikacja pokazuje Gisty zawierajace plik `bandplot_project.json`, ich nazwe, date aktualizacji i ID. Wybrany projekt mozna od razu wczytac lub nadpisac.

## Streamlit Community Cloud
Repozytorium powinno zawierac co najmniej `app.py` oraz `requirements.txt`. Token GitHub dodaj jako sekret `GITHUB_TOKEN` w ustawieniach aplikacji Streamlit; nie commituj `secrets.toml` ani tokena do GitHuba.
