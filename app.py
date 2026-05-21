import io
import time
import datetime
import requests
import pandas as pd
import streamlit as st
import matplotlib.pyplot as plt
import re
import folium
from folium.plugins import HeatMap
from streamlit_folium import st_folium

# ==========================================================
# CONFIG
# ==========================================================
SHEET_ID = "1wZ4h2oiptatvfYddT8xIllGBRSEfCRy4WAenTTvUDoc"

MESES = [
    "JANEIRO","FEVEREIRO","MARÇO","ABRIL","MAIO","JUNHO",
    "JULHO","AGOSTO","SETEMBRO","OUTUBRO","NOVEMBRO","DEZEMBRO"
]

LOCALIDADES_UI = ["1ª CPM/I", "SÃO MIGUEL DOS CAMPOS", "CAMPO ALEGRE", "BOCA DA MATA", "ANADIA", "ROTEIRO"]
MAP_LOCALIDADE = {"1ª CPM/I": "1ª CPM-I"}

ABA_CVLI  = "CVLI"
ABA_TENT  = "TENTATIVA"
ABA_CVP   = "CVP"
ABA_GRUPO = "GRUPO"

# P3 (nomes das abas no Sheets)
ABA_P3_DETERMINACOES_SHEET = "ORIENTACOES"
ABA_P3_EVENTOS_SHEET       = "EVENTOS"
ABA_P3_VISITAS_SHEET       = "VISITAS"

# Colunas com variações (com/sem acento)
COL_ALIASES = {
    "DATA": ["DATA"],
    "HORÁRIO": ["HORÁRIO", "HORARIO"],
    "CIDADE": ["CIDADE"],
    "LOCAL": ["LOCAL"],
    "EVENTO": ["EVENTO"],
    "GUARNIÇÃO": ["GUARNIÇÃO", "GUARNICAO"],
    "PROCEDIMENTO": ["PROCEDIMENTO"],
    "PRIORIDADE": ["PRIORIDADE"],
    "ORIENTAÇÕES": ["ORIENTAÇÕES", "ORIENTACOES", "ORIENTAÇÔES", "ORIENTAÇÕES "],
    "LATITUDE": ["LATITUDE", "LAT"],
    "LONGITUDE": ["LONGITUDE", "LON", "LONG"],
}

# ==========================================================
# ESTILO
# ==========================================================
st.set_page_config(page_title="Seção de Planejamento e Instrução", layout="wide")

st.markdown("""
<style>
.center-title {text-align:center; font-weight:700; font-size:28px; margin-top:0.25rem;}
.center-sub   {text-align:center; font-weight:700; font-size:18px; margin-top:-0.25rem;}
.center {text-align:center;}
hr { border: none; border-top: 1px solid #cfcfcf; margin: 1.2rem 0; }

div[data-testid="stCheckbox"] label { font-size: 13px; }

/* centralizar tabelas */
div[data-testid="stDataFrame"] * { text-align: center !important; }
div[data-testid="stDataFrame"] td, div[data-testid="stDataFrame"] th { text-align: center !important; }
button[data-baseweb="tab"] { justify-content: center; }

/* botões */
.stButton>button {padding: 0.35rem 0.9rem;}
div.stButton > button {
  white-space: pre-line;
  line-height: 1.15;
  text-align: center;
}
</style>
""", unsafe_allow_html=True)

# ==========================================================
# HELPERS
# ==========================================================
def altura_df(n_rows: int, row_h: int = 35, header_h: int = 42, min_h: int = 140, max_h: int = 520) -> int:
    h = header_h + row_h * n_rows
    return max(min_h, min(max_h, h))

def _limpar_data_series(s: pd.Series) -> pd.Series:
    s = s.astype(str).str.strip()
    su = s.str.upper()
    invalid = su.isin(["", "NI", "N/I", "N\\I", "-", "NÃO INFORMADO", "NA", "NAN"])
    return s.mask(invalid, None)

def _format_percent_br_from_any(x):
    if pd.isna(x):
        return ""
    if isinstance(x, (int, float)):
        val = float(x)
        if abs(val) <= 1:
            val *= 100
        return f"{val:.2f}%".replace(".", ",")
    s = str(x).strip()
    if s == "":
        return ""
    has_pct = "%" in s
    s = s.replace("%", "").strip()
    if "," in s:
        s = s.replace(".", "").replace(",", ".")
    try:
        val = float(s)
    except Exception:
        return ""
    if (not has_pct) and abs(val) <= 1:
        val *= 100
    return f"{val:.2f}%".replace(".", ",")

def _is_unnamed(colname: str) -> bool:
    return str(colname).strip().upper().startswith("UNNAMED")

def _has_month_year_token(v: str) -> bool:
    s = str(v).strip().upper()
    return ("/" in s) and any(ch.isdigit() for ch in s)

def _remove_acentos_upper(s: str) -> str:
    s = s.upper()
    return (s.replace("Á","A").replace("Ã","A").replace("Â","A")
             .replace("É","E").replace("Ê","E")
             .replace("Í","I")
             .replace("Ó","O").replace("Õ","O").replace("Ô","O")
             .replace("Ú","U").replace("Ç","C"))

def _mes_para_nome_pt(token_mes: str) -> str:
    nomes = {1:"JANEIRO",2:"FEVEREIRO",3:"MARÇO",4:"ABRIL",5:"MAIO",6:"JUNHO",
             7:"JULHO",8:"AGOSTO",9:"SETEMBRO",10:"OUTUBRO",11:"NOVEMBRO",12:"DEZEMBRO"}
    abrev = {"JAN":"JANEIRO","FEV":"FEVEREIRO","MAR":"MARÇO","ABR":"ABRIL","MAI":"MAIO","JUN":"JUNHO",
             "JUL":"JULHO","AGO":"AGOSTO","SET":"SETEMBRO","OUT":"OUTUBRO","NOV":"NOVEMBRO","DEZ":"DEZEMBRO"}
    t = str(token_mes).strip()
    if t.isdigit():
        return nomes.get(int(t), "MÊS")
    t2 = _remove_acentos_upper(t)
    if t2[:3] in abrev:
        return abrev[t2[:3]]
    for k, v in abrev.items():
        if t2.startswith(k):
            return v
    return t.upper()

def detectar_mes_grupo(dfs) -> str:
    if ABA_GRUPO not in dfs:
        return "MÊS"
    df = dfs[ABA_GRUPO].copy().dropna(axis=1, how="all").dropna(how="all")
    if df.empty:
        return "MÊS"
    pattern = re.compile(r"^\s*([A-Za-zÀ-ÿ]{3,}|0?[1-9]|1[0-2])\s*/\s*20(25|26)\s*$")
    for i in range(min(6, len(df))):
        for cell in df.iloc[i].tolist():
            if pd.isna(cell):
                continue
            s = str(cell).strip()
            m = pattern.match(s)
            if m:
                return _mes_para_nome_pt(m.group(1))
    for c in df.columns:
        s = str(c).strip()
        m = pattern.match(s)
        if m:
            return _mes_para_nome_pt(m.group(1))
    return "MÊS"

def resolve_cols(df: pd.DataFrame, canonical_cols: list[str]) -> list[str]:
    cols = []
    dfcols = set(df.columns)
    for canon in canonical_cols:
        cands = COL_ALIASES.get(canon, [canon])
        found = next((c for c in cands if c in dfcols), None)
        if found:
            cols.append(found)
    return cols

def get_first_col(df: pd.DataFrame, canonical: str):
    cands = COL_ALIASES.get(canonical, [canonical])
    for c in cands:
        if c in df.columns:
            return c
    return None

def tabela_resumo_com_detalhes(
    df: pd.DataFrame,
    cols_resumo_canon: list[str],
    cols_detalhe_canon: list[str],
    label_func,
    key_prefix: str,
    highlight_mask: pd.Series | None = None
):
    """
    - Mostra tabela resumo (colunas curtas)
    - Preferência: seleção por clique na linha (sem selectbox)
    - Fallback: selectbox (caso Streamlit não suporte seleção)
    - Mostra colunas longas completas em text_area (sem cortar)
    - highlight_mask: True pinta a linha na tabela resumo (azul claro)
    """
    if df is None or df.empty:
        st.info("Sem registros neste mês.")
        return

    df_show = df.copy().reset_index(drop=True)
    cols_resumo = resolve_cols(df_show, cols_resumo_canon)
    cols_detalhe = resolve_cols(df_show, cols_detalhe_canon)

    # Monta tabela resumo
    df_resumo = df_show[cols_resumo].copy() if cols_resumo else df_show.copy()

    # Aplica highlight (PRIORIDADE etc.)
    use_styler = False
    if highlight_mask is not None:
        hm = highlight_mask.reset_index(drop=True)

        def _style_row(row):
            if bool(hm.iloc[row.name]):
                return ["background-color:#BBDEFB; color:#000000; font-weight:700;"] * len(row)
            return [""] * len(row)

        styler = df_resumo.style.set_properties(**{"text-align": "center"}).hide(axis="index")
        styler = styler.apply(_style_row, axis=1)
        use_styler = True

    # ============================
    # TENTAR SELEÇÃO POR CLIQUE
    # ============================
    sel = None
    try:
        state = st.dataframe(
            styler if use_styler else df_resumo,
            use_container_width=True,
            height=altura_df(len(df_resumo), max_h=420),
            hide_index=True,
            on_select="rerun",
            selection_mode="single-row",
            key=f"{key_prefix}_tbl",
        )
        rows = getattr(getattr(state, "selection", None), "rows", None)
        if rows:
            sel = int(rows[0])
    except TypeError:
        # Streamlit antigo (não aceita on_select/selection_mode)
        st.dataframe(
            styler if use_styler else df_resumo,
            use_container_width=True,
            height=altura_df(len(df_resumo), max_h=420),
            hide_index=True,
        )

    # ============================
    # FALLBACK: SELECTBOX
    # ============================
    if sel is None:
        st.caption("Clique em uma linha (se disponível) ou selecione abaixo para ver detalhes.")
        sel = st.selectbox(
            "Ver detalhes do registro:",
            options=list(df_show.index),
            format_func=lambda i: label_func(df_show, i),
            key=f"{key_prefix}_sel",
        )

    # ============================
    # DETALHES (TEXTO COMPLETO)
    # ============================
    if cols_detalhe:
        st.markdown("**DETALHES (texto completo)**")
        for c in cols_detalhe:
            val = df_show.at[sel, c]
            txt = "" if pd.isna(val) else str(val)
            st.text_area(
                c,
                value=txt,
                height=160 if len(txt) < 250 else 240,
                key=f"{key_prefix}_{c}_{sel}",
            )



# ==========================================================
# MAPAS (CVLI / TENTATIVA)
# ==========================================================
def preparar_coordenadas(df: pd.DataFrame) -> tuple[pd.DataFrame, str | None, str | None]:
    """
    Converte LATITUDE/LONGITUDE para número, aceitando vírgula ou ponto.
    Registros sem coordenadas válidas são ignorados nos mapas.
    """
    df = df.copy()
    df.columns = df.columns.astype(str).str.strip().str.upper()

    lat_col = get_first_col(df, "LATITUDE")
    lon_col = get_first_col(df, "LONGITUDE")

    if not lat_col or not lon_col:
        return pd.DataFrame(), lat_col, lon_col

    df[lat_col] = (
        df[lat_col]
        .astype(str)
        .str.strip()
        .str.replace(",", ".", regex=False)
    )
    df[lon_col] = (
        df[lon_col]
        .astype(str)
        .str.strip()
        .str.replace(",", ".", regex=False)
    )

    df[lat_col] = pd.to_numeric(df[lat_col], errors="coerce")
    df[lon_col] = pd.to_numeric(df[lon_col], errors="coerce")

    df = df.dropna(subset=[lat_col, lon_col]).copy()

    # Limite básico para evitar coordenadas inválidas
    df = df[
        df[lat_col].between(-90, 90) &
        df[lon_col].between(-180, 180)
    ].copy()

    return df, lat_col, lon_col


def _popup_ocorrencia(row: pd.Series) -> str:
    def get(col):
        val = row[col] if col in row.index else ""
        if pd.isna(val):
            return ""
        return str(val)

    campos = [
        ("Nome", get("NOME")),
        ("Idade", get("IDADE")),
        ("Data", get("DATA")),
        ("Local", get("LOCAL")),
        ("Meio empregado", get("MEIO EMPREGADO")),
        ("BOU", get("BOU")),
    ]

    linhas = [f"<b>{titulo}:</b> {valor}" for titulo, valor in campos if str(valor).strip()]
    return "<br>".join(linhas)


def criar_mapa_pontos(df_map: pd.DataFrame, lat_col: str, lon_col: str, key: str):
    if df_map.empty:
        st.info("Sem coordenadas para exibir o mapa.")
        return

    centro = [df_map[lat_col].mean(), df_map[lon_col].mean()]
    mapa = folium.Map(location=centro, zoom_start=12, control_scale=True)

    pontos_bounds = []
    for _, row in df_map.iterrows():
        lat = float(row[lat_col])
        lon = float(row[lon_col])
        pontos_bounds.append([lat, lon])

        folium.CircleMarker(
            location=[lat, lon],
            radius=6,
            color="#D32F2F",
            fill=True,
            fill_color="#D32F2F",
            fill_opacity=0.75,
            popup=folium.Popup(_popup_ocorrencia(row), max_width=350),
        ).add_to(mapa)

    if pontos_bounds:
        mapa.fit_bounds(pontos_bounds)

    st_folium(mapa, use_container_width=True, height=550, key=key)


def criar_mapa_calor(df_map: pd.DataFrame, lat_col: str, lon_col: str, key: str):
    if df_map.empty:
        st.info("Sem coordenadas para exibir o mapa de calor.")
        return

    centro = [df_map[lat_col].mean(), df_map[lon_col].mean()]
    mapa = folium.Map(location=centro, zoom_start=12, control_scale=True)

    heat_data = df_map[[lat_col, lon_col]].dropna().values.tolist()

    HeatMap(
        heat_data,
        radius=22,
        blur=18,
        min_opacity=0.35,
    ).add_to(mapa)

    if heat_data:
        mapa.fit_bounds(heat_data)

    st_folium(mapa, use_container_width=True, height=550, key=key)


def detalhamento_cvli_tentativa_com_mapa(dfs, aba: str):
    """
    Para CVLI e TENTATIVA:
    - Aba Tabela: mantém detalhamento mensal.
    - Aba Mapa de pontos: mostra pontos com popup.
    - Aba Mapa de calor: mostra concentração.
    """
    if aba not in dfs:
        st.error(f"Aba '{aba}' não encontrada.")
        return

    df = dfs[aba].copy()
    df.columns = df.columns.astype(str).str.strip().str.upper()

    df.rename(
        columns={
            "ENDEREÇO": "LOCAL",
            "ENDERECO": "LOCAL",
            "COP": "BOU",
        },
        inplace=True,
    )

    # Prepara datas para tabela e popup
    if "DATA" in df.columns:
        s = _limpar_data_series(df["DATA"])
        df["DATA_DT"] = pd.to_datetime(s, errors="coerce", dayfirst=True)
        df["MES_NUM"] = df["DATA_DT"].dt.month
        df["DATA"] = df["DATA_DT"].dt.strftime("%d/%m/%Y")
        df["DATA"] = df["DATA"].fillna("")
    else:
        df["DATA_DT"] = pd.NaT
        df["MES_NUM"] = pd.NA

    abas = st.tabs(["Tabela", "Mapa de pontos", "Mapa de calor"])

    with abas[0]:
        # A tabela permanece como antes, organizada por mês
        df_tabela = df.copy()
        if aba.upper() == "CVP":
            colunas_exibir = ["TIPO", "DATA", "HORA", "LOCAL", "INSTRUMENTO", "BOU PC"]
            chave_dropna = "TIPO"
        else:
            colunas_exibir = ["NOME", "IDADE", "DATA", "LOCAL", "MEIO EMPREGADO", "BOU"]
            chave_dropna = "NOME"

        colunas_presentes = [c for c in colunas_exibir if c in df_tabela.columns]

        if chave_dropna in df_tabela.columns:
            df_tabela = df_tabela.dropna(subset=[chave_dropna])

        tabs_meses = st.tabs([m.title() for m in MESES])
        for i, _ in enumerate(MESES, start=1):
            with tabs_meses[i - 1]:
                dfm = df_tabela[df_tabela["MES_NUM"] == i].copy()
                if dfm.empty:
                    st.info("Sem registros neste mês.")
                    continue

                df_show = dfm[colunas_presentes].copy().reset_index(drop=True)
                st.dataframe(
                    df_show,
                    use_container_width=True,
                    height=altura_df(len(df_show)),
                    hide_index=True,
                )

    df_map, lat_col, lon_col = preparar_coordenadas(df)

    with abas[1]:
        criar_mapa_pontos(df_map, lat_col, lon_col, key=f"mapa_pontos_{aba}")

    with abas[2]:
        criar_mapa_calor(df_map, lat_col, lon_col, key=f"mapa_calor_{aba}")


# ==========================================================
# LOGIN
# ==========================================================
def login():
    if st.session_state.get("auth"):
        return
    st.markdown("<div class='center-title'>Acesso restrito</div>", unsafe_allow_html=True)
    senha = st.text_input("Senha", type="password")
    if senha and senha == st.secrets["APP_PASSWORD"]:
        st.session_state["auth"] = True
        st.rerun()
    st.stop()

# ==========================================================
# DOWNLOAD / LEITURA (XLSX)
# ==========================================================
def baixar_xlsx(sheet_id: str, cache_bust: int = 0) -> io.BytesIO:
    url = f"https://docs.google.com/spreadsheets/d/{sheet_id}/export?format=xlsx&cb={cache_bust}"
    headers = {"Cache-Control": "no-cache", "Pragma": "no-cache", "User-Agent": "Mozilla/5.0"}
    r = requests.get(url, headers=headers, timeout=60)
    if r.status_code != 200:
        raise RuntimeError(f"Falha ao baixar XLSX. Status={r.status_code}.")
    return io.BytesIO(r.content)

@st.cache_data(ttl=300)
def carregar_dados(sheet_id: str, refresh_token: int):
    arquivo = baixar_xlsx(sheet_id, cache_bust=refresh_token)
    xls = pd.ExcelFile(arquivo, engine="openpyxl")

    dfs = {}
    for sheet in xls.sheet_names:
        df_raw = xls.parse(sheet, header=None).dropna(axis=1, how="all")
        n_rows = len(df_raw)

        if n_rows == 0:
            dfs[sheet] = pd.DataFrame()
            continue

        header_idx = 2 if n_rows > 3 else 0

        for idx, row in df_raw.head(min(30, n_rows)).iterrows():
            vals = [str(x).strip().upper() for x in row.dropna().values]
            vals_set = set(vals)

            if ("NOME" in vals_set) or ("OCORRÊNCIAS" in vals_set) or ("OCORRÊNCIA" in vals_set):
                header_idx = int(idx); break

            if ("TIPO" in vals_set) and ("DATA" in vals_set) and ("LOCAL" in vals_set):
                header_idx = int(idx); break

            if (("PERÍODO" in vals_set) or ("PERIODO" in vals_set)) and ("STATUS" in vals_set):
                header_idx = int(idx); break

            if ("DATA" in vals_set) and ("EVENTO" in vals_set):
                header_idx = int(idx); break

            if ("DATA" in vals_set) and (("ORIENTAÇÕES" in vals_set) or ("ORIENTACOES" in vals_set)):
                header_idx = int(idx); break

            if ("ORIENTADO" in vals_set) and (("ENDEREÇO" in vals_set) or ("ENDERECO" in vals_set)):
                header_idx = int(idx); break

        header_idx = max(0, min(int(header_idx), n_rows - 1))

        try:
            df = xls.parse(sheet, header=header_idx).dropna(axis=1, how="all")
        except ValueError:
            df = xls.parse(sheet, header=0).dropna(axis=1, how="all")

        df.columns = df.columns.astype(str).str.strip().str.upper()
        dfs[sheet] = df

    sheet_ref = "1ª CPM-I" if "1ª CPM-I" in xls.sheet_names else xls.sheet_names[0]
    raw = xls.parse(sheet_ref, header=None)
    try:
        data_val = raw.iloc[7, 28]  # AC8
        if isinstance(data_val, (pd.Timestamp, datetime.datetime, datetime.date)):
            data_atual = data_val.strftime("%d/%m/%Y")
        else:
            data_atual = str(data_val)
    except Exception:
        data_atual = "não localizada"

    return dfs, data_atual

# ==========================================================
# GRÁFICOS
# ==========================================================
def grafico_por_ocorrencia(df, selecionadas, titulo_prefixo):
    for ocorrencia in selecionadas:
        df_o = df[df["OCORRÊNCIAS"] == ocorrencia]
        if df_o.empty:
            continue
        d25 = df_o.iloc[:, 1::2].values.flatten()[:12]
        d26 = df_o.iloc[:, 2::2].values.flatten()[:12]
        df_p = pd.DataFrame({"2025": d25, "2026": d26}, index=MESES).fillna(0)
        df_p.loc["TOTAL"] = df_p.sum()
        fig = plt.figure(figsize=(9, 5))
        ax = df_p.plot(kind="bar", ax=plt.gca(), title=f"{ocorrencia} - {titulo_prefixo}")
        for c in ax.containers:
            ax.bar_label(c, fmt="%.0f")
        plt.xticks(rotation=45, ha="right")
        plt.tight_layout()
        st.pyplot(fig, use_container_width=True)

def grafico_anual_totais(df, titulo_prefixo):
    def _total(linha, cols):
        s = pd.to_numeric(linha.iloc[:, cols].values.flatten(), errors="coerce")
        return float(s[12]) if len(s) >= 13 and pd.notna(s[12]) else float(pd.Series(s[:12]).fillna(0).sum())
    reg = []
    for _, r in df.dropna(subset=["OCORRÊNCIAS"]).iterrows():
        df_l = df[df["OCORRÊNCIAS"] == r["OCORRÊNCIAS"]].head(1)
        reg.append({"OC": str(r["OCORRÊNCIAS"]),
                    "2025": _total(df_l, slice(1, None, 2)),
                    "2026": _total(df_l, slice(2, None, 2))})
    df_t = pd.DataFrame(reg)
    dkw = ["drogas", "maconha", "cocaína", "crack"]
    m_dr = df_t["OC"].str.contains("|".join(dkw), case=False, na=False) & (df_t["OC"].str.upper() != "OCORRÊNCIAS A. DROGAS")
    m_ot = ~df_t["OC"].str.contains("|".join(dkw), case=False, na=False) | (df_t["OC"].str.upper() == "OCORRÊNCIAS A. DROGAS")
    for d, t in [(df_t[m_dr], "DROGAS"), (df_t[m_ot], "OUTRAS")]:
        if d.empty:
            continue
        fig = plt.figure(figsize=(10, 5))
        ax = d.set_index("OC")[["2025", "2026"]].plot(kind="bar", ax=plt.gca(), title=f"{t} - {titulo_prefixo}")
        for c in ax.containers:
            ax.bar_label(c, fmt="%.0f")
        plt.xticks(rotation=45, ha="right")
        plt.tight_layout()
        st.pyplot(fig, use_container_width=True)

def grafico_mensal(df, mes, titulo_prefixo):
    mes = mes.upper()
    if mes not in MESES:
        st.warning("Selecione um mês válido.")
        return
    idx = MESES.index(mes)
    d25 = df.iloc[:, 1::2].iloc[:, idx].fillna(0)
    d26 = df.iloc[:, 2::2].iloc[:, idx].fillna(0)
    df_m = pd.DataFrame({"OC": df["OCORRÊNCIAS"], "2025": d25, "2026": d26}).dropna(subset=["OC"])
    dkw = ["drogas", "maconha", "cocaína", "crack"]
    m_dr = df_m["OC"].str.contains("|".join(dkw), case=False, na=False) & (df_m["OC"].str.upper() != "OCORRÊNCIAS A. DROGAS")
    m_ot = ~df_m["OC"].str.contains("|".join(dkw), case=False, na=False) | (df_m["OC"].str.upper() == "OCORRÊNCIAS A. DROGAS")
    for d, t in [(df_m[m_dr], "Drogas"), (df_m[m_ot], "Outras")]:
        if d.empty:
            continue
        fig = plt.figure(figsize=(9, 5))
        ax = d.set_index("OC")[["2025", "2026"]].plot(kind="bar", ax=plt.gca(), title=f"{t} - {mes} - {titulo_prefixo}")
        for c in ax.containers:
            ax.bar_label(c, fmt="%.0f")
        plt.xticks(rotation=45, ha="right")
        plt.tight_layout()
        st.pyplot(fig, use_container_width=True)

# ==========================================================
# DETALHAMENTO (CVLI/TENTATIVA/CVP)
# ==========================================================
def detalhamento_por_mes_padrao(dfs, aba: str):
    if aba not in dfs:
        st.error(f"Aba '{aba}' não encontrada.")
        return

    df = dfs[aba].copy()
    df.rename(columns={"ENDERECO": "LOCAL", "COP": "BOU"}, inplace=True)

    if aba.upper() == "CVP":
        colunas_exibir = ["TIPO", "DATA", "HORA", "LOCAL", "INSTRUMENTO", "BOU PC"]
        chave_dropna = "TIPO"
    else:
        colunas_exibir = ["NOME", "IDADE", "DATA", "LOCAL", "MEIO EMPREGADO", "BOU"]
        chave_dropna = "NOME"

    colunas_exibir = [c.upper() for c in colunas_exibir]
    df.columns = df.columns.astype(str).str.strip().str.upper()
    colunas_presentes = [c for c in colunas_exibir if c in df.columns]

    if "DATA" in df.columns:
        s = _limpar_data_series(df["DATA"])
        df["DATA_DT"] = pd.to_datetime(s, errors="coerce", dayfirst=True)
        df["MES_NUM"] = df["DATA_DT"].dt.month
    else:
        df["DATA_DT"] = pd.NaT
        df["MES_NUM"] = pd.NA

    if chave_dropna.upper() in df.columns:
        df = df.dropna(subset=[chave_dropna.upper()])

    tabs = st.tabs([m.title() for m in MESES])
    for i, _ in enumerate(MESES, start=1):
        with tabs[i-1]:
            dfm = df[df["MES_NUM"] == i].copy()
            if dfm.empty:
                st.info("Sem registros neste mês.")
                continue
            if "DATA" in colunas_presentes:
                dfm["DATA"] = dfm["DATA_DT"].dt.strftime("%d/%m/%Y")
            df_show = dfm[colunas_presentes].copy().reset_index(drop=True)
            st.dataframe(df_show, use_container_width=True, height=altura_df(len(df_show)), hide_index=True)

# ==========================================================
# GRUPO
# ==========================================================
def detalhamento_grupo(dfs):
    if ABA_GRUPO not in dfs:
        st.error("Aba 'GRUPO' não encontrada.")
        return

    df = dfs[ABA_GRUPO].copy().dropna(axis=1, how="all").dropna(how="all")
    df.columns = [str(c).strip().upper() for c in df.columns]

    header_row_idx = None
    for i in range(min(6, len(df))):
        row = df.iloc[i].tolist()
        row_str = [("" if pd.isna(x) else str(x).strip()) for x in row]
        row_up = [s.upper() for s in row_str if s != ""]
        has_pct = any("PORCENT" in s for s in row_up)
        has_status = any(s == "STATUS" for s in row_up)
        has_months = sum(_has_month_year_token(s) for s in row_str) >= 1
        if has_pct or has_status or has_months:
            header_row_idx = i
            break

    if header_row_idx is not None:
        header_vals = df.iloc[header_row_idx].tolist()
        new_cols = list(df.columns)
        for j, col in enumerate(new_cols):
            hv = header_vals[j] if j < len(header_vals) else None
            hv_str = "" if pd.isna(hv) else str(hv).strip().upper()
            col_up = str(col).strip().upper()
            if (col_up in ("PERÍODO", "PERIODO") or _is_unnamed(col_up)) and hv_str not in ("", "NONE"):
                new_cols[j] = hv_str
        df.columns = new_cols
        df = df.iloc[header_row_idx + 1:].copy()

    if "OCORRÊNCIAS" in df.columns:
        oc = df["OCORRÊNCIAS"].astype(str).str.strip()
        df = df[oc.ne("") & oc.str.upper().ne("NONE") & oc.str.upper().ne("OCORRÊNCIAS")]

    df = df.loc[:, [c for c in df.columns if not _is_unnamed(c)]].copy()

    col_pct = next((c for c in df.columns if "PORCENT" in str(c).upper() or "PERCENT" in str(c).upper()), None)
    if col_pct is not None:
        df[col_pct] = df[col_pct].apply(_format_percent_br_from_any)

    status_col = next((c for c in df.columns if str(c).strip().upper() == "STATUS"), None)

    def _style_status(v):
        s = str(v).strip().upper()
        if "POSIT" in s:
            return "background-color:#00C853; color:#000000; font-weight:700;"
        if "NEGAT" in s:
            return "background-color:#D50000; color:#000000; font-weight:700;"
        if "EST" in s:
            return "background-color:#FFAB00; color:#000000; font-weight:700;"
        return "color:#000000; font-weight:700;"

    styler = df.style.set_properties(**{"text-align": "center"}).hide(axis="index")
    if status_col is not None:
        styler = styler.map(_style_status, subset=[status_col])

    st.dataframe(styler, use_container_width=True, height=altura_df(len(df), max_h=650), hide_index=True)

# ==========================================================
# P3: DETERMINAÇÕES / EVENTOS / VISITAS
# ==========================================================
def p3_determinacoes(dfs):
    sh = ABA_P3_DETERMINACOES_SHEET
    if sh not in dfs or dfs[sh].empty:
        st.info(f"Sem dados na aba **{sh}**.")
        return

    df = dfs[sh].copy().dropna(axis=1, how="all").dropna(how="all")
    df.columns = df.columns.astype(str).str.strip().str.upper()

    col_data = get_first_col(df, "DATA")
    col_cidade = get_first_col(df, "CIDADE")
    col_orient = get_first_col(df, "ORIENTAÇÕES")

    if not col_data:
        st.dataframe(df.reset_index(drop=True), use_container_width=True, hide_index=True)
        return

    s = _limpar_data_series(df[col_data])
    df["_DATA_DT"] = pd.to_datetime(s, errors="coerce", dayfirst=True)
    df["_MES_NUM"] = df["_DATA_DT"].dt.month

    tabs = st.tabs([m.title() for m in MESES])
    for mes_idx in range(1, 13):
        with tabs[mes_idx-1]:
            dfm = df[df["_MES_NUM"] == mes_idx].copy()
            if dfm.empty:
                st.info("Sem registros neste mês.")
                continue

            dfm[col_data] = dfm["_DATA_DT"].dt.strftime("%d/%m/%Y")
            dfm = dfm.drop(columns=["_DATA_DT", "_MES_NUM"], errors="ignore").reset_index(drop=True)

            def _label(df_, i_):
                d = df_.at[i_, col_data] if col_data in df_.columns else ""
                c = df_.at[i_, col_cidade] if col_cidade and col_cidade in df_.columns else ""
                return f"{i_+1} | {d} | {c}"

            tabela_resumo_com_detalhes(
                df=dfm,
                cols_resumo_canon=["DATA", "CIDADE"],
                cols_detalhe_canon=["ORIENTAÇÕES"],
                label_func=_label,
                key_prefix=f"p3_det_{mes_idx}",
                highlight_mask=None
            )

def p3_eventos(dfs):
    sh = ABA_P3_EVENTOS_SHEET
    if sh not in dfs or dfs[sh].empty:
        st.info(f"Sem dados na aba **{sh}**.")
        return

    df = dfs[sh].copy().dropna(axis=1, how="all").dropna(how="all")
    df.columns = df.columns.astype(str).str.strip().str.upper()

    col_data = get_first_col(df, "DATA")
    col_pri  = get_first_col(df, "PRIORIDADE")

    if not col_data:
        st.dataframe(df.reset_index(drop=True), use_container_width=True, hide_index=True)
        return

    s = _limpar_data_series(df[col_data])
    df["_DATA_DT"] = pd.to_datetime(s, errors="coerce", dayfirst=True)
    df["_MES_NUM"] = df["_DATA_DT"].dt.month

    tabs = st.tabs([m.title() for m in MESES])
    for mes_idx in range(1, 13):
        with tabs[mes_idx-1]:
            dfm = df[df["_MES_NUM"] == mes_idx].copy()
            if dfm.empty:
                st.info("Sem registros neste mês.")
                continue

            # máscara prioridade
            if col_pri and col_pri in dfm.columns:
                mask = dfm[col_pri].fillna("").astype(str).str.strip().str.upper().eq("SIM")
            else:
                mask = pd.Series([False]*len(dfm), index=dfm.index)

            # formata DATA
            dfm[col_data] = dfm["_DATA_DT"].dt.strftime("%d/%m/%Y")

            dfm_clean = dfm.drop(columns=["_DATA_DT", "_MES_NUM"], errors="ignore").reset_index(drop=True)
            mask_reset = mask.reset_index(drop=True)

            # remove PRIORIDADE (não exibir)
            if col_pri and col_pri in dfm_clean.columns:
                dfm_clean = dfm_clean.drop(columns=[col_pri], errors="ignore")

            def _label(df_, i_):
                c_data = get_first_col(df_, "DATA") or col_data
                c_cid = get_first_col(df_, "CIDADE")
                c_evt = get_first_col(df_, "EVENTO")
                d = df_.at[i_, c_data] if c_data in df_.columns else ""
                c = df_.at[i_, c_cid] if c_cid and c_cid in df_.columns else ""
                e = df_.at[i_, c_evt] if c_evt and c_evt in df_.columns else ""
                return f"{i_+1} | {d} | {c} | {e}"

            tabela_resumo_com_detalhes(
                df=dfm_clean,
                cols_resumo_canon=["DATA", "LOCAL", "CIDADE", "GUARNIÇÃO"],
                cols_detalhe_canon=["HORÁRIO", "EVENTO", "LOCAL", "PROCEDIMENTO"],
                label_func=_label,
                key_prefix=f"p3_evt_{mes_idx}",
                highlight_mask=mask_reset
            )

def p3_visitas(dfs):
    sh = ABA_P3_VISITAS_SHEET
    st.markdown("<div class='center' style='font-weight:600;'>VISITAS</div>", unsafe_allow_html=True)
    if sh not in dfs or dfs[sh].empty:
        st.info(f"Sem dados na aba **{sh}**.")
        return
    dfv = dfs[sh].copy().dropna(axis=1, how="all").dropna(how="all")
    dfv = dfv.loc[:, [c for c in dfv.columns if not _is_unnamed(c)]].copy()
    st.dataframe(dfv.reset_index(drop=True), use_container_width=True, height=altura_df(len(dfv), max_h=650), hide_index=True)

# ==========================================================
# APP
# ==========================================================
def main():
    login()

    if "refresh_token" not in st.session_state:
        st.session_state["refresh_token"] = 0

    _, top_right = st.columns([6, 1])
    with top_right:
        if st.button("🔄 Atualizar agora", use_container_width=True, key="refresh_btn"):
            st.session_state["refresh_token"] = int(time.time())
            st.cache_data.clear()
            st.session_state.pop("sel_oc_by_sheet", None)
            st.rerun()

    dfs, data_atual = carregar_dados(SHEET_ID, st.session_state["refresh_token"])

    st.markdown("<div class='center-title'>Seção de Planejamento e Instrução</div>", unsafe_allow_html=True)
    st.markdown("<div class='center-sub'>*** 1ª CPM/I ***</div>", unsafe_allow_html=True)

    # ======================================================
    # PRIMEIRO: DETERMINAÇÕES E ORIENTAÇÕES
    # ======================================================
    st.markdown("<hr/>", unsafe_allow_html=True)
    st.markdown("<div class='center' style='font-weight:700; font-size:18px;'>DETERMINAÇÕES E ORIENTAÇÕES</div>", unsafe_allow_html=True)

    if "aba_p3" not in st.session_state:
        st.session_state["aba_p3"] = "DETERMINACOES"

    p1, p2, p3 = st.columns(3)
    with p1:
        if st.button("DETERMINAÇÕES", use_container_width=True, key="p3_det_btn"):
            st.session_state["aba_p3"] = "DETERMINACOES"
    with p2:
        if st.button("EVENTOS", use_container_width=True, key="p3_evt_btn"):
            st.session_state["aba_p3"] = "EVENTOS"
    with p3:
        if st.button("VISITAS", use_container_width=True, key="p3_vis_btn"):
            st.session_state["aba_p3"] = "VISITAS"

    st.write("")
    if st.session_state["aba_p3"] == "DETERMINACOES":
        p3_determinacoes(dfs)
    elif st.session_state["aba_p3"] == "EVENTOS":
        p3_eventos(dfs)
    else:
        p3_visitas(dfs)

    # ======================================================
    # DEPOIS: DEMAIS FUNÇÕES
    # ======================================================
    st.markdown("<hr/>", unsafe_allow_html=True)

    _, cC, _ = st.columns([1, 2, 1])
    with cC:
        localidade = st.selectbox("Selecione a localidade:", LOCALIDADES_UI, key="localidade_sel")

    planilha = MAP_LOCALIDADE.get(localidade, localidade)
    if planilha not in dfs:
        st.error("Planilha/localidade não encontrada.")
        st.stop()

    df_loc = dfs[planilha]
    if "OCORRÊNCIAS" not in df_loc.columns:
        st.error('Coluna "OCORRÊNCIAS" não encontrada nessa aba.')
        st.stop()

    ocorrencias = df_loc["OCORRÊNCIAS"].dropna().drop_duplicates().astype(str).tolist()

    if "sel_oc_by_sheet" not in st.session_state:
        st.session_state["sel_oc_by_sheet"] = {}
    if planilha not in st.session_state["sel_oc_by_sheet"]:
        st.session_state["sel_oc_by_sheet"][planilha] = set()

    st.write("")
    cols = st.columns(4)
    for i, oc in enumerate(ocorrencias):
        col = cols[i % 4]
        key = f"oc_{planilha}_{i}"
        checked = oc in st.session_state["sel_oc_by_sheet"][planilha]
        val = col.checkbox(oc, value=checked, key=key)
        if val:
            st.session_state["sel_oc_by_sheet"][planilha].add(oc)
        else:
            st.session_state["sel_oc_by_sheet"][planilha].discard(oc)

    selecionadas = [o for o in ocorrencias if o in st.session_state["sel_oc_by_sheet"][planilha]]

    st.markdown("<hr/>", unsafe_allow_html=True)

    st.markdown("<div class='center' style='font-weight:700; font-size:18px;'>Gráfico Anual: 2025 vs 2026</div>", unsafe_allow_html=True)
    b1, b2 = st.columns(2)
    with b1:
        if st.button("GRÁFICO POR OCORRÊNCIA", use_container_width=True, key="graf_oc_btn"):
            if not selecionadas:
                st.warning("Selecione pelo menos uma ocorrência.")
            else:
                grafico_por_ocorrencia(df_loc, selecionadas, planilha)
    with b2:
        if st.button("GRÁFICO ANUAL", use_container_width=True, key="graf_anual_btn"):
            grafico_anual_totais(df_loc, planilha)

    st.markdown("<hr/>", unsafe_allow_html=True)

    st.markdown("<div class='center' style='font-weight:700; font-size:18px;'>Gráfico Mensal:</div>", unsafe_allow_html=True)
    _, c2, _ = st.columns([1, 1, 1])
    with c2:
        mes = st.selectbox(" ", MESES, label_visibility="collapsed", key="mes_sel")
        if st.button("GERAR GRÁFICO MENSAL", use_container_width=True, key="graf_mensal_btn"):
            grafico_mensal(df_loc, mes, planilha)

    st.markdown("<hr/>", unsafe_allow_html=True)

    st.markdown("<div class='center' style='font-weight:700; font-size:18px;'>DADOS DAS OCORRÊNCIAS</div>", unsafe_allow_html=True)

    if "aba_dados" not in st.session_state:
        st.session_state["aba_dados"] = ABA_CVLI

    mes_grupo = detectar_mes_grupo(dfs)

    bb1, bb2, bb3, bb4 = st.columns(4)
    with bb1:
        if st.button("CVLI", use_container_width=True, key="dados_cvli_btn"):
            st.session_state["aba_dados"] = ABA_CVLI
    with bb2:
        if st.button("TENTATIVA", use_container_width=True, key="dados_tent_btn"):
            st.session_state["aba_dados"] = ABA_TENT
    with bb3:
        if st.button("CVP", use_container_width=True, key="dados_cvp_btn"):
            st.session_state["aba_dados"] = ABA_CVP
    with bb4:
        if st.button(f"COMPARATIVO DE {mes_grupo}\n2025 x 2026", use_container_width=True, key="dados_grupo_btn"):
            st.session_state["aba_dados"] = ABA_GRUPO

    st.write("")
    aba_sel = st.session_state["aba_dados"]
    if aba_sel == ABA_GRUPO:
        st.markdown(f"<div class='center' style='font-weight:600;'>COMPARATIVO DE {mes_grupo} — 2025 x 2026</div>", unsafe_allow_html=True)
        detalhamento_grupo(dfs)
    else:
        st.markdown(f"<div class='center' style='font-weight:600;'>Detalhamento - {aba_sel}</div>", unsafe_allow_html=True)
        if aba_sel in [ABA_CVLI, ABA_TENT]:
            detalhamento_cvli_tentativa_com_mapa(dfs, aba_sel)
        else:
            detalhamento_por_mes_padrao(dfs, aba_sel)

    st.caption(f"Dados atualizados em: {data_atual}")

if __name__ == "__main__":
    main()
