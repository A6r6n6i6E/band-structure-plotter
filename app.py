import base64
import io
import json
import math
import re
from pathlib import Path
from urllib import error, request

import matplotlib as mpl
import matplotlib.pyplot as plt
import numpy as np
import streamlit as st
from matplotlib.lines import Line2D

st.set_page_config(page_title='Band Structure Plotter', layout='wide')
PROJECT_VERSION = 3


def parse_gnu_bytes(data: bytes):
    """Parse GNU-style band file: x y pairs; blank lines separate bands."""
    text = data.decode('utf-8', errors='replace')
    bands, current = [], []
    for raw in text.splitlines():
        line = raw.strip()
        if not line:
            if current:
                bands.append(np.asarray(current, dtype=float))
                current = []
            continue
        if line.startswith('#'):
            continue
        parts = line.replace(',', '.').split()
        if len(parts) < 2:
            continue
        try:
            current.append((float(parts[0]), float(parts[1])))
        except ValueError:
            continue
    if current:
        bands.append(np.asarray(current, dtype=float))
    if not bands:
        raise ValueError('Nie znaleziono par liczbowych x y.')
    return bands


def parse_csv_floats(text):
    return [float(x.strip()) for x in text.split(',') if x.strip()]


def mathtext_label(text):
    """Support Γ and simple subscripts such as WSe_2 or WSe_{17}Al."""
    text = str(text).strip()
    text = text.replace('Gamma', 'Γ')
    if '$' in text:  # user supplied MathText/LaTeX explicitly
        return text
    text = text.replace('Γ', r'$\Gamma$')
    # Convert _2 and _{17} to Matplotlib MathText while keeping normal text outside math mode.
    text = re.sub(r'_\{([^{}]+)\}', lambda m: r'$_{' + m.group(1) + r'}$', text)
    text = re.sub(r'_([A-Za-z0-9.+-]+)', lambda m: r'$_{' + m.group(1) + r'}$', text)
    return text


def default_global_config():
    return {
        'ncols': 4, 'share_y': True, 'normalize_x': True,
        'ylabel': r'E - E_F (eV)', 'xlabel': '', 'ymin': -2.0, 'ymax': 3.0,
        'k_labels_raw': 'Γ,M,K,Γ', 'k_positions_raw': '0,0.366,0.577,1',
        'font_family': 'DejaVu Sans', 'suptitle': '', 'suptitle_size': 14,
        'title_size': 12, 'label_size': 11, 'tick_size': 10,
        'show_k_lines': True, 'kline_color': '#B0B0B0', 'kline_width': 0.7,
        'kline_alpha': 0.7, 'show_zero': True, 'zero_color': '#222222',
        'zero_width': 0.8, 'zero_style_name': 'przerywana',
        'show_gap_band': False, 'gap_low': 0.0, 'gap_high': 1.0,
        'gap_color': '#E6E6E6', 'gap_alpha': 0.45,
        'fig_w': 12.0, 'fig_h': 8.0, 'dpi': 300,
        'wspace': 0.18, 'hspace': 0.28, 'margin_left': 0.08,
        'margin_right': 0.98, 'margin_bottom': 0.08, 'margin_top': 0.94,
        'title_pad': 8, 'spine_width': 0.9, 'grid_y': False,
        'tick_direction': 'out', 'legend': True, 'legend_loc': 'lower center',
        'legend_fontsize': 10,
    }


def default_panel_config(name, order):
    return {
        'base_name': name,
        'soc_name': '',
        'order': order,
        'title': Path(name).stem,
        'energy_ref_base': 0.0,
        'energy_ref_soc': 0.0,
        'base_color': '#000000',
        'base_line_width': 0.8,
        'base_alpha': 1.0,
        'base_style': '-',
        'base_label': 'noSOC',
        'soc_color': '#D62728',
        'soc_line_width': 0.8,
        'soc_alpha': 1.0,
        'soc_style': '--',
        'soc_label': 'SOC',
    }


def encode_sources(sources):
    return {name: base64.b64encode(data).decode('ascii') for name, data in sources.items()}


def decode_sources(encoded):
    out = {}
    for name, data in (encoded or {}).items():
        out[name] = base64.b64decode(data.encode('ascii'))
    return out


def make_project(config, panels, base_sources, soc_sources):
    return {
        'version': PROJECT_VERSION,
        'global': config,
        'panels': panels,
        'base_files': encode_sources(base_sources),
        'soc_files': encode_sources(soc_sources),
    }


def load_project_dict(project):
    if not isinstance(project, dict):
        raise ValueError('Nieprawidłowy plik projektu.')
    st.session_state['loaded_project'] = project
    st.session_state['project_base_sources'] = decode_sources(project.get('base_files', {}))
    st.session_state['project_soc_sources'] = decode_sources(project.get('soc_files', {}))
    # Clear panel widget state so the newly loaded project becomes authoritative.
    for key in list(st.session_state.keys()):
        if key.startswith('p_'):
            del st.session_state[key]


def gist_api(method, url, token, payload=None):
    headers = {'Accept': 'application/vnd.github+json', 'User-Agent': 'BandStructurePlotter'}
    if token:
        headers['Authorization'] = f'Bearer {token.strip()}'
    data = None if payload is None else json.dumps(payload).encode('utf-8')
    req = request.Request(url, data=data, headers=headers, method=method)
    try:
        with request.urlopen(req, timeout=15) as resp:
            return json.loads(resp.read().decode('utf-8'))
    except error.HTTPError as exc:
        msg = exc.read().decode('utf-8', errors='replace')
        raise RuntimeError(f'GitHub API: HTTP {exc.code}: {msg[:500]}') from exc
    except error.URLError as exc:
        raise RuntimeError(f'Nie można połączyć się z GitHub: {exc.reason}') from exc


def make_figure(panel_records, settings):
    n = len(panel_records)
    ncols = max(1, min(settings['ncols'], n))
    nrows = math.ceil(n / ncols)
    fig, axes = plt.subplots(
        nrows, ncols, figsize=(settings['fig_w'], settings['fig_h']),
        sharex=False, sharey=settings['share_y'], squeeze=False,
    )
    axes_flat = axes.ravel()
    for ax in axes_flat[n:]:
        ax.set_visible(False)

    tick_labels = [mathtext_label(x) for x in settings['k_labels']]
    tick_positions = settings['k_positions']

    for i, panel in enumerate(panel_records):
        ax = axes_flat[i]
        base_bands = panel['base_bands']
        soc_bands = panel.get('soc_bands')
        p = panel['config']

        x_arrays = [b[:, 0] for b in base_bands]
        if soc_bands:
            x_arrays.extend(b[:, 0] for b in soc_bands)
        all_x = np.concatenate(x_arrays)
        xmin, xmax = float(np.min(all_x)), float(np.max(all_x))
        span = xmax - xmin if xmax > xmin else 1.0

        def draw_bands(bands, eref, color, lw, alpha, ls):
            for band in bands:
                x = band[:, 0].copy()
                y = band[:, 1].copy() - eref
                if settings['normalize_x']:
                    x = (x - xmin) / span
                ax.plot(x, y, color=color, lw=lw, alpha=alpha, ls=ls, zorder=2)

        draw_bands(base_bands, p['energy_ref_base'], p['base_color'],
                   p['base_line_width'], p['base_alpha'], p['base_style'])
        if soc_bands:
            draw_bands(soc_bands, p['energy_ref_soc'], p['soc_color'],
                       p['soc_line_width'], p['soc_alpha'], p['soc_style'])

        if settings['show_k_lines']:
            for xpos in tick_positions:
                ax.axvline(xpos, color=settings['kline_color'], lw=settings['kline_width'],
                           alpha=settings['kline_alpha'], zorder=0)
        if settings['show_zero']:
            ax.axhline(0, color=settings['zero_color'], lw=settings['zero_width'],
                       ls=settings['zero_style'], alpha=0.9, zorder=1)
        if settings['show_gap_band'] and settings['gap_low'] < settings['gap_high']:
            ax.axhspan(settings['gap_low'], settings['gap_high'], color=settings['gap_color'],
                       alpha=settings['gap_alpha'], zorder=-2)

        ax.set_title(mathtext_label(p['title']), fontsize=settings['title_size'], pad=settings['title_pad'])
        _ = ax.set_ylim(settings['ymin'], settings['ymax'])
        if settings['normalize_x']:
            _ = ax.set_xlim(0, 1)
        else:
            _ = ax.set_xlim(xmin, xmax)

        if tick_positions and len(tick_positions) == len(tick_labels):
            _ = ax.set_xticks(tick_positions)
            _ = ax.set_xticklabels(tick_labels, fontsize=settings['tick_size'])
        ax.tick_params(axis='y', labelsize=settings['tick_size'], direction=settings['tick_direction'])
        ax.tick_params(axis='x', direction=settings['tick_direction'])
        for spine in ax.spines.values():
            spine.set_linewidth(settings['spine_width'])
        if settings['grid_y']:
            ax.grid(axis='y', alpha=0.18, lw=0.6)

        row, col = divmod(i, ncols)
        if (not settings['share_y']) or col == 0:
            ax.set_ylabel(mathtext_label(settings['ylabel']), fontsize=settings['label_size'])
        if settings['xlabel'] and row == nrows - 1:
            ax.set_xlabel(mathtext_label(settings['xlabel']), fontsize=settings['label_size'])

        if settings['legend'] and soc_bands:
            handles = [
                Line2D([0], [0], color=p['base_color'], lw=p['base_line_width'], ls=p['base_style'], label=p['base_label']),
                Line2D([0], [0], color=p['soc_color'], lw=p['soc_line_width'], ls=p['soc_style'], label=p['soc_label']),
            ]
            ax.legend(handles=handles, loc=settings['legend_loc'], fontsize=settings['legend_fontsize'], frameon=True)

    if settings['suptitle']:
        fig.suptitle(mathtext_label(settings['suptitle']), fontsize=settings['suptitle_size'], y=0.995)
    fig.subplots_adjust(
        left=settings['margin_left'], right=settings['margin_right'],
        bottom=settings['margin_bottom'], top=settings['margin_top'],
        wspace=settings['wspace'], hspace=settings['hspace'],
    )
    return fig


st.title('Band Structure Plotter')
st.caption('Wykresy struktur pasmowych z obsługą siatki paneli, SOC, MathText/indeksów dolnych oraz zapisu projektu.')

# ---- Project load/save ----------------------------------------------------
loaded_project = st.session_state.get('loaded_project', {})
project_global = default_global_config()
project_global.update(loaded_project.get('global', {}))
project_panels_saved = loaded_project.get('panels', [])

with st.expander('💾 Projekt: zapisz / wczytaj ustawienia i dane', expanded=False):
    st.write('Projekt JSON może zawierać również wczytane pliki pasm, więc po jego odtworzeniu nie trzeba ponownie wybierać danych.')
    project_upload = st.file_uploader('Wczytaj projekt .json', type=['json'], key='project_json_upload')
    if st.button('Wczytaj projekt z pliku', disabled=project_upload is None):
        try:
            project = json.loads(project_upload.getvalue().decode('utf-8'))
            load_project_dict(project)
            st.rerun()
        except Exception as exc:
            st.error(f'Nie udało się wczytać projektu: {exc}')

    st.markdown('**GitHub Gist (opcjonalnie)**')
    secret_token = ''
    try:
        secret_token = str(st.secrets.get('GITHUB_TOKEN', ''))
    except Exception:
        secret_token = ''
    gh_token = st.text_input(
        'GitHub Personal Access Token',
        value=secret_token,
        type='password',
        help='Możesz wpisać token ręcznie albo ustawić GITHUB_TOKEN w Streamlit Secrets. Token nie jest zapisywany w projekcie.',
    )
    project_name = st.text_input('Nazwa projektu na GitHub', value=st.session_state.get('project_name', 'Mój projekt pasmowy'))

    lc1, lc2 = st.columns([1, 2])
    if lc1.button('Odśwież listę projektów z GitHub', disabled=not gh_token.strip()):
        try:
            gists = gist_api('GET', 'https://api.github.com/gists?per_page=100', gh_token)
            projects = []
            for item in gists:
                files = item.get('files', {})
                if 'bandplot_project.json' in files:
                    desc = item.get('description') or 'Projekt bez nazwy'
                    if desc.startswith('Band Structure Plotter | '):
                        desc = desc.split(' | ', 1)[1]
                    projects.append({
                        'id': item.get('id', ''),
                        'name': desc,
                        'updated_at': item.get('updated_at', ''),
                        'url': item.get('html_url', ''),
                    })
            st.session_state['github_projects'] = projects
            if projects:
                st.success(f'Znaleziono {len(projects)} projekt(ów).')
            else:
                st.info('Nie znaleziono Gistów zawierających bandplot_project.json.')
        except Exception as exc:
            st.error(str(exc))

    projects = st.session_state.get('github_projects', [])
    selected_gist_id = ''
    if projects:
        labels = [f"{p['name']}  |  {p['updated_at'][:10]}  |  {p['id'][:8]}…" for p in projects]
        selected_label = st.selectbox('Zapisane projekty na GitHub', labels)
        selected = projects[labels.index(selected_label)]
        selected_gist_id = selected['id']
        st.caption(f"Wybrany Gist: {selected['id']}")
        if selected.get('url'):
            st.markdown(f"[Otwórz Gist na GitHub]({selected['url']})")

    gist_id = st.text_input(
        'ID Gista (opcjonalnie: ręcznie, do wczytania lub nadpisania)',
        value=st.session_state.get('gist_id', ''),
    )
    active_gist_id = selected_gist_id or gist_id.strip()
    c1, c2 = st.columns(2)
    if c1.button('Wczytaj wybrany projekt z GitHub', disabled=not active_gist_id):
        try:
            data = gist_api('GET', f'https://api.github.com/gists/{active_gist_id}', gh_token)
            files = data.get('files', {})
            if 'bandplot_project.json' not in files:
                raise ValueError('Gist nie zawiera pliku bandplot_project.json')
            project = json.loads(files['bandplot_project.json']['content'])
            load_project_dict(project)
            st.session_state['gist_id'] = active_gist_id
            desc = data.get('description') or ''
            if desc.startswith('Band Structure Plotter | '):
                st.session_state['project_name'] = desc.split(' | ', 1)[1]
            st.rerun()
        except Exception as exc:
            st.error(str(exc))
    st.caption('Zapis do Gista pojawi się niżej po utworzeniu bieżącej konfiguracji projektu.')

# ---- Data upload ----------------------------------------------------------
st.subheader('1. Dane')
st.write('Wczytaj podstawowe pasma jako panele. Pliki SOC wczytaj osobno i przypisz do wybranego panelu.')
base_uploads = st.file_uploader('Pasma podstawowe / noSOC', type=['gnu', 'dat', 'txt'], accept_multiple_files=True, key='base_uploads')
soc_uploads = st.file_uploader('Pasma SOC (opcjonalnie)', type=['gnu', 'dat', 'txt'], accept_multiple_files=True, key='soc_uploads')

base_sources = dict(st.session_state.get('project_base_sources', {}))
soc_sources = dict(st.session_state.get('project_soc_sources', {}))
for f in base_uploads or []:
    base_sources[f.name] = f.getvalue()
for f in soc_uploads or []:
    soc_sources[f.name] = f.getvalue()

if not base_sources:
    st.info('Wczytaj co najmniej jeden plik z pasmami podstawowymi albo załaduj zapisany projekt.')
    st.stop()

base_datasets, soc_datasets, errors = {}, {}, []
for name, raw in base_sources.items():
    try:
        base_datasets[name] = parse_gnu_bytes(raw)
    except Exception as exc:
        errors.append(f'{name}: {exc}')
for name, raw in soc_sources.items():
    try:
        soc_datasets[name] = parse_gnu_bytes(raw)
    except Exception as exc:
        errors.append(f'{name}: {exc}')
if errors:
    st.error('Nie udało się odczytać:\n' + '\n'.join(errors))
if not base_datasets:
    st.stop()

# ---- Global settings -----------------------------------------------------
g = project_global
with st.sidebar:
    st.header('Układ')
    ncols = st.number_input('Liczba kolumn', 1, max(1, len(base_datasets)), min(int(g['ncols']), len(base_datasets)), 1)
    share_y = st.checkbox('Wspólna oś Y', value=bool(g['share_y']))
    normalize_x = st.checkbox('Normalizuj każdą ścieżkę k do 0–1', value=bool(g['normalize_x']))

    st.header('Osie i etykiety')
    ylabel = st.text_input('Etykieta osi Y', value=g['ylabel'], help='Możesz używać np. E - E_F (eV), WSe_2 albo składni MathText $E_F$.')
    xlabel = st.text_input('Etykieta osi X', value=g['xlabel'])
    ymin = st.number_input('Y min [eV]', value=float(g['ymin']), step=0.1, format='%.3f')
    ymax = st.number_input('Y max [eV]', value=float(g['ymax']), step=0.1, format='%.3f')
    k_labels_raw = st.text_input('Etykiety punktów k', value=g['k_labels_raw'])
    default_positions = g['k_positions_raw']
    if normalize_x and not loaded_project:
        default_positions = '0,0.366,0.577,1'
    k_positions_raw = st.text_input('Pozycje punktów k', value=default_positions)

    st.header('Typografia')
    fonts = ['DejaVu Sans', 'DejaVu Serif', 'STIXGeneral', 'sans-serif', 'serif']
    font_family = st.selectbox('Rodzina czcionki', fonts, index=fonts.index(g['font_family']) if g['font_family'] in fonts else 0)
    suptitle = st.text_input('Tytuł całej figury', value=g['suptitle'])
    suptitle_size = st.slider('Rozmiar tytułu głównego', 8, 30, int(g['suptitle_size']))
    title_size = st.slider('Rozmiar tytułów paneli', 7, 26, int(g['title_size']))
    label_size = st.slider('Rozmiar opisów osi', 7, 24, int(g['label_size']))
    tick_size = st.slider('Rozmiar ticków', 6, 22, int(g['tick_size']))

    st.header('Linie pomocnicze')
    show_k_lines = st.checkbox('Pionowe linie w punktach k', value=bool(g['show_k_lines']))
    kline_color = st.color_picker('Kolor linii k', g['kline_color'])
    kline_width = st.slider('Grubość linii k', 0.2, 2.0, float(g['kline_width']), 0.1)
    kline_alpha = st.slider('Przezroczystość linii k', 0.05, 1.0, float(g['kline_alpha']), 0.05)
    show_zero = st.checkbox('Linia E = 0', value=bool(g['show_zero']))
    zero_color = st.color_picker('Kolor E = 0', g['zero_color'])
    zero_width = st.slider('Grubość E = 0', 0.2, 2.5, float(g['zero_width']), 0.1)
    styles_named = ['kropkowana', 'przerywana', 'ciągła']
    zero_style_name = st.selectbox('Styl E = 0', styles_named, index=styles_named.index(g['zero_style_name']) if g['zero_style_name'] in styles_named else 1)
    zero_style = {'kropkowana': ':', 'przerywana': '--', 'ciągła': '-'}[zero_style_name]

    st.header('Legenda SOC')
    legend = st.checkbox('Pokaż legendę, gdy panel ma SOC', value=bool(g.get('legend', True)))
    legend_locs = ['best', 'upper right', 'upper left', 'lower left', 'lower right', 'lower center', 'upper center']
    legend_loc = st.selectbox('Położenie legendy', legend_locs, index=legend_locs.index(g.get('legend_loc', 'lower center')) if g.get('legend_loc') in legend_locs else 5)
    legend_fontsize = st.slider('Rozmiar legendy', 6, 20, int(g.get('legend_fontsize', 10)))

    st.header('Tło / przerwa energetyczna')
    show_gap_band = st.checkbox('Zaznacz poziomy przedział energii', value=bool(g['show_gap_band']))
    gap_low = st.number_input('Dolna granica przedziału', value=float(g['gap_low']), step=0.1)
    gap_high = st.number_input('Górna granica przedziału', value=float(g['gap_high']), step=0.1)
    gap_color = st.color_picker('Kolor przedziału', g['gap_color'])
    gap_alpha = st.slider('Przezroczystość przedziału', 0.05, 0.8, float(g['gap_alpha']), 0.05)

    st.header('Rozmiar figury')
    fig_w = st.slider('Szerokość [cale]', 4.0, 24.0, float(g['fig_w']), 0.5)
    fig_h = st.slider('Wysokość [cale]', 3.0, 24.0, float(g['fig_h']), 0.5)
    dpi = st.slider('DPI PNG', 100, 600, int(g['dpi']), 50)

    with st.expander('Zaawansowany układ'):
        wspace = st.slider('Odstęp poziomy', 0.0, 1.0, float(g['wspace']), 0.01)
        hspace = st.slider('Odstęp pionowy', 0.0, 1.0, float(g['hspace']), 0.01)
        margin_left = st.slider('Margines lewy', 0.02, 0.25, float(g['margin_left']), 0.01)
        margin_right = st.slider('Margines prawy', 0.70, 0.99, float(g['margin_right']), 0.01)
        margin_bottom = st.slider('Margines dolny', 0.02, 0.25, float(g['margin_bottom']), 0.01)
        margin_top = st.slider('Margines górny', 0.70, 0.99, float(g['margin_top']), 0.01)
        title_pad = st.slider('Odstęp tytułu od panelu', 0, 30, int(g['title_pad']))
        spine_width = st.slider('Grubość ramek', 0.4, 2.5, float(g['spine_width']), 0.1)
        grid_y = st.checkbox('Delikatna siatka pozioma', value=bool(g['grid_y']))
        tick_dirs = ['out', 'in', 'inout']
        tick_direction = st.selectbox('Kierunek ticków', tick_dirs, index=tick_dirs.index(g['tick_direction']) if g['tick_direction'] in tick_dirs else 0)

mpl.rcParams['font.family'] = font_family
try:
    k_positions = parse_csv_floats(k_positions_raw)
except Exception:
    st.error('Niepoprawny zapis pozycji punktów k. Użyj np. 0,0.366,0.577,1')
    st.stop()
k_labels = [x.strip() for x in k_labels_raw.split(',') if x.strip()]
if len(k_positions) != len(k_labels):
    st.warning('Liczba pozycji punktów k i etykiet jest różna — ticki k nie zostaną ustawione.')

# ---- Panels --------------------------------------------------------------
st.subheader('2. Panele, kolejność i SOC')
st.caption('Kolejność zmieniasz polem „Pozycja”. Dla indeksu dolnego wpisz np. WSe_2 lub WSe_{17}Al.')

saved_by_base = {p.get('base_name'): p for p in project_panels_saved}
panel_configs = []
columns = st.columns(min(3, len(base_datasets)))
line_styles = {'ciągła': '-', 'przerywana': '--', 'kropkowana': ':', 'kreska-kropka': '-.'}
line_style_names = list(line_styles.keys())

def style_name_from_value(value, fallback):
    for name, val in line_styles.items():
        if val == value:
            return name
    return fallback

for i, (name, bands) in enumerate(base_datasets.items()):
    saved = default_panel_config(name, i + 1)
    saved.update(saved_by_base.get(name, {}))
    with columns[i % len(columns)]:
        with st.expander(f'{i+1}. {name}', expanded=(i < 3)):
            order = st.number_input('Pozycja w siatce', 1, len(base_datasets), int(min(max(saved['order'], 1), len(base_datasets))), 1, key=f'p_order_{name}')
            title = st.text_input('Tytuł panelu', value=saved['title'], key=f'p_title_{name}', help='Np. WSe_2 albo WSe_{17}Al. Możesz też używać MathText, np. $WSe_2$.')
            energy_ref_base = st.number_input('Eref noSOC [eV]', value=float(saved['energy_ref_base']), step=0.1, format='%.6f', key=f'p_eref_base_{name}')

            st.markdown('**Pasma podstawowe / noSOC**')
            base_color = st.color_picker('Kolor noSOC', saved['base_color'], key=f'p_base_color_{name}')
            base_lw = st.slider('Grubość noSOC', 0.2, 3.0, float(saved['base_line_width']), 0.1, key=f'p_base_lw_{name}')
            base_alpha = st.slider('Przezroczystość noSOC', 0.1, 1.0, float(saved['base_alpha']), 0.05, key=f'p_base_alpha_{name}')
            bsn = st.selectbox('Styl noSOC', line_style_names, index=line_style_names.index(style_name_from_value(saved['base_style'], 'ciągła')), key=f'p_base_style_{name}')
            base_label = st.text_input('Nazwa w legendzie noSOC', value=saved['base_label'], key=f'p_base_label_{name}')

            st.markdown('**Spin-orbita (SOC)**')
            soc_options = ['— brak —'] + list(soc_datasets.keys())
            saved_soc = saved.get('soc_name', '')
            soc_index = soc_options.index(saved_soc) if saved_soc in soc_options else 0
            soc_choice = st.selectbox('Plik SOC nakładany na ten panel', soc_options, index=soc_index, key=f'p_soc_{name}')
            soc_name = '' if soc_choice == '— brak —' else soc_choice
            energy_ref_soc = st.number_input('Eref SOC [eV]', value=float(saved['energy_ref_soc']), step=0.1, format='%.6f', key=f'p_eref_soc_{name}')
            soc_color = st.color_picker('Kolor SOC', saved['soc_color'], key=f'p_soc_color_{name}')
            soc_lw = st.slider('Grubość SOC', 0.2, 3.0, float(saved['soc_line_width']), 0.1, key=f'p_soc_lw_{name}')
            soc_alpha = st.slider('Przezroczystość SOC', 0.1, 1.0, float(saved['soc_alpha']), 0.05, key=f'p_soc_alpha_{name}')
            ssn = st.selectbox('Styl SOC', line_style_names, index=line_style_names.index(style_name_from_value(saved['soc_style'], 'przerywana')), key=f'p_soc_style_{name}')
            soc_label = st.text_input('Nazwa w legendzie SOC', value=saved['soc_label'], key=f'p_soc_label_{name}')

            st.caption(f'noSOC: {len(bands)} pasm; {len(bands[0])} punktów w pierwszym paśmie.' + (f'  SOC: {len(soc_datasets[soc_name])} pasm.' if soc_name else ''))
            panel_configs.append({
                'base_name': name, 'soc_name': soc_name, 'order': int(order), 'title': title,
                'energy_ref_base': float(energy_ref_base), 'energy_ref_soc': float(energy_ref_soc),
                'base_color': base_color, 'base_line_width': float(base_lw), 'base_alpha': float(base_alpha),
                'base_style': line_styles[bsn], 'base_label': base_label,
                'soc_color': soc_color, 'soc_line_width': float(soc_lw), 'soc_alpha': float(soc_alpha),
                'soc_style': line_styles[ssn], 'soc_label': soc_label,
            })

settings = {
    'ncols': int(ncols), 'share_y': share_y, 'normalize_x': normalize_x,
    'ylabel': ylabel, 'xlabel': xlabel, 'ymin': float(ymin), 'ymax': float(ymax),
    'k_labels': k_labels, 'k_positions': k_positions, 'k_labels_raw': k_labels_raw,
    'k_positions_raw': k_positions_raw, 'font_family': font_family,
    'show_k_lines': show_k_lines, 'kline_color': kline_color, 'kline_width': kline_width,
    'kline_alpha': kline_alpha, 'show_zero': show_zero, 'zero_color': zero_color,
    'zero_width': zero_width, 'zero_style': zero_style, 'zero_style_name': zero_style_name,
    'show_gap_band': show_gap_band, 'gap_low': float(gap_low), 'gap_high': float(gap_high),
    'gap_color': gap_color, 'gap_alpha': gap_alpha, 'fig_w': fig_w, 'fig_h': fig_h, 'dpi': dpi,
    'suptitle': suptitle, 'suptitle_size': suptitle_size, 'title_size': title_size,
    'label_size': label_size, 'tick_size': tick_size, 'wspace': wspace, 'hspace': hspace,
    'margin_left': margin_left, 'margin_right': margin_right, 'margin_bottom': margin_bottom,
    'margin_top': margin_top, 'title_pad': title_pad, 'spine_width': spine_width,
    'grid_y': grid_y, 'tick_direction': tick_direction, 'legend': legend,
    'legend_loc': legend_loc, 'legend_fontsize': legend_fontsize,
}

if ymin >= ymax:
    st.error('Y min musi być mniejsze od Y max.')
    st.stop()

# Stable ordering even if two panels have the same requested position.
original_index = {name: i for i, name in enumerate(base_datasets.keys())}
panel_configs_sorted = sorted(panel_configs, key=lambda p: (p['order'], original_index[p['base_name']]))
panel_records = []
for p in panel_configs_sorted:
    panel_records.append({
        'config': p,
        'base_bands': base_datasets[p['base_name']],
        'soc_bands': soc_datasets.get(p['soc_name']) if p['soc_name'] else None,
    })

# ---- Preview and export --------------------------------------------------
st.subheader('3. Podgląd')
fig = make_figure(panel_records, settings)
st.pyplot(fig, use_container_width=True)

st.subheader('4. Eksport wykresu')
export_cols = st.columns(3)
for col, fmt, mime, label in [
    (export_cols[0], 'png', 'image/png', 'Pobierz PNG'),
    (export_cols[1], 'pdf', 'application/pdf', 'Pobierz PDF'),
    (export_cols[2], 'svg', 'image/svg+xml', 'Pobierz SVG'),
]:
    buf = io.BytesIO()
    fig.savefig(buf, format=fmt, dpi=dpi if fmt == 'png' else None, bbox_inches='tight')
    buf.seek(0)
    col.download_button(label, data=buf.getvalue(), file_name=f'band_structures.{fmt}', mime=mime)
plt.close(fig)

# ---- Project export / cloud save ----------------------------------------
st.subheader('5. Zapis projektu')
project = make_project(settings, panel_configs_sorted, base_sources, soc_sources)
project_bytes = json.dumps(project, ensure_ascii=False, indent=2).encode('utf-8')
sc1, sc2 = st.columns(2)
sc1.download_button('Pobierz projekt JSON', data=project_bytes, file_name='bandplot_project.json', mime='application/json')

with sc2:
    st.caption('GitHub Gist przechowuje cały projekt (ustawienia + dane) w chmurze.')
    if st.button('Zapisz projekt do GitHub Gist', disabled=not gh_token.strip()):
        try:
            payload = {
                'description': f'Band Structure Plotter | {project_name.strip() or "Mój projekt pasmowy"}',
                'public': False,
                'files': {'bandplot_project.json': {'content': project_bytes.decode('utf-8')}},
            }
            save_gist_id = selected_gist_id or gist_id.strip()
            if save_gist_id:
                result = gist_api('PATCH', f'https://api.github.com/gists/{save_gist_id}', gh_token, payload)
            else:
                result = gist_api('POST', 'https://api.github.com/gists', gh_token, payload)
            new_id = result['id']
            st.session_state['gist_id'] = new_id
            st.session_state['project_name'] = project_name.strip() or 'Mój projekt pasmowy'
            st.session_state.pop('github_projects', None)
            st.success(f'Zapisano. ID Gista: {new_id}. Odśwież listę projektów, aby zobaczyć aktualny wpis.')
            st.code(new_id)
        except Exception as exc:
            st.error(str(exc))

st.info('Uwaga: Zapisując nowy projekt nadaj mu nową nazwę w zakładce " Projekt: zapisz / wczytaj ustawienia i dane" u góry strony.')

