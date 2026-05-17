import io
import time
import datetime
import requests
import pandas as pd
import streamlit as st
import matplotlib.pyplot as plt
import re

# ==========================================================
# CONFIG
# ==========================================================
SHEET_ID = "1wZ4h2oiptatvfYddT8xIllGBRSEfCRy4WAenTTvUDoc"

MESES = ["JANEIRO","FEVEREIRO","MARÇO","ABRIL","MAIO","JUNHO","JULHO","AGOSTO","SETEMBRO","OUTUBRO","NOVEMBRO","DEZEMBRO"]
LOCALIDADES_UI = ["1ª CPM/I", "SÃO MIGUEL DOS CAMPOS", "CAMPO ALEGRE", "BOCA DA MATA", "ANADIA", "ROTEIRO"]
MAP_LOCALIDADE = {"1ª CPM/I": "1ª CPM-I"}  # nome exibido -> nome real da aba

ABA_CVLI = "CVLI"
ABA_TENT = "TENTATIVA"
ABA_CVP = "CVP"
ABA_GRUPO = "GRUPO"

# ==========================================================
# ESTILO + CENTRALIZAÇÃO
# ==========================================================
st.set_page_config(page_title="Ferramenta para Análise de Ocorrências", layout="wide")

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

/* permitir quebra de linha nos botões */
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
def altura_df(n_rows: int, row_h: int = 35, header_h: int = 42, min_h: int = 120, max_h: int = 520) -> int:
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
    nomes = {
        1:"JANEIRO",2:"FEVEREIRO",3:"MARÇO",4:"ABRIL",5:"MAIO",6:"JUNHO",
        7:"JULHO",8:"AGOSTO",9:"SETEMBRO",10:"OUTUBRO",11:"NOVEMBRO",12:"DEZEMBRO"
    }
    abrev = {
        "JAN":"JANEIRO","FEV":"FEVEREIRO","MAR":"MARÇO","ABR":"ABRIL","MAI":"MAIO","JUN":"JUNHO",
        "JUL":"JULHO","AGO":"AGOSTO","SET":"SETEMBRO","OUT":"OUTUBRO","NOV":"NOVEMBRO","DEZ":"DEZEMBRO"
    }

    t = str(token_mes).strip()
    if t.isdigit():
        n = int(t)
        return nomes.get(n, "MÊS")

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

    # procura nas primeiras linhas (cabeçalho interno)
    for i in range(min(6, len(df))):
        row = df.iloc[i].tolist()
        for cell in row:
            if pd.isna(cell):
                continue
            s = str(cell).strip()
            m = pattern.match(s)
            if m:
                return _mes_para_nome_pt(m.group(1))

    # procura nos nomes de colunas
    for c in df.columns:
        s = str(c).strip()
        m = pattern.match(s)
        if m:
            return _mes_para_nome_pt(m.group(1))

    return "MÊS"

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

        header_idx = 2
        for idx, row in df_raw.head(20).iterrows():
            vals = [str(x).strip().upper() for x in row.dropna().values]
            if ("NOME" in vals) or ("OCORRÊNCIAS" in vals) or ("OCORRÊNCIA" in vals):
                header_idx = idx
                break
            if ("TIPO" in vals) and ("DATA" in vals) and ("LOCAL" in vals):
                header_idx = idx
                break
            if ("PERÍODO" in vals) and ("STATUS" in vals):
                header_idx = idx
                break

        df = xls.parse(sheet, header=header_idx).dropna(axis=1, how="all")
        df.columns = df.columns.astype(str).str.strip().str.upper()
        dfs[sheet] = df

    # Data de atualização (AC8)
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
# DETALHAMENTO por mês (CVLI/TENTATIVA/CVP)
# ==========================================================
def detalhamento_por_mes(dfs, aba: str):
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

    colunas_presentes = [c for c in colunas_exibir if c in df.columns]

    if "DATA" in df.columns:
        df["DATA_ORIG"] = df["DATA"]
        s = _limpar_data_series(df["DATA_ORIG"])
        df["DATA_DT"] = pd.to_datetime(s, errors="coerce", dayfirst=True)
        df["MES_NUM"] = df["DATA_DT"].dt.month
    else:
        df["DATA_ORIG"] = None
        df["DATA_DT"] = pd.NaT
        df["MES_NUM"] = pd.NA

    if chave_dropna in df.columns:
        df = df.dropna(subset=[chave_dropna])

    df_invalid = df[df["DATA_DT"].isna()].copy()
    if not df_invalid.empty:
        st.warning(f"⚠️ {len(df_invalid)} registro(s) com DATA vazia/inválida (não entrou em nenhum mês).")
        with st.expander("Ver registros com DATA inválida"):
            df_bad = df_invalid[colunas_presentes].copy().reset_index(drop=True)
            st.dataframe(df_bad, use_container_width=True, height=altura_df(len(df_bad)), hide_index=True)

    tabs = st.tabs([m.title() for m in MESES])
    for i, m in enumerate(MESES, start=1):
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
# GRUPO (comparativo) + % + STATUS colorido (cores vivas)
# ==========================================================
def detalhamento_grupo(dfs):
    if ABA_GRUPO not in dfs:
        st.error("Aba 'GRUPO' não encontrada.")
        return

    df = dfs[ABA_GRUPO].copy().dropna(axis=1, how="all").dropna(how="all")
    df.columns = [str(c).strip().upper() for c in df.columns]

    # detecta cabeçalho interno
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

    st.dataframe(
        styler,
        use_container_width=True,
        height=altura_df(len(df), max_h=650),
    )

# ==========================================================
# APP
# ==========================================================
def main():
    login()

    if "refresh_token" not in st.session_state:
        st.session_state["refresh_token"] = 0

    top_left, top_right = st.columns([6, 1])
    with top_right:
        if st.button("🔄 Atualizar agora", use_container_width=True):
            st.session_state["refresh_token"] = int(time.time())
            st.cache_data.clear()
            st.session_state.pop("sel_oc_by_sheet", None)
            st.rerun()

    dfs, data_atual = carregar_dados(SHEET_ID, st.session_state["refresh_token"])

    st.markdown("<div class='center-title'>Ferramenta para Análise de Ocorrências</div>", unsafe_allow_html=True)
    st.markdown("<div class='center-sub'>*** 1ª CPM/I ***</div>", unsafe_allow_html=True)

    st.write("")
    cL, cC, cR = st.columns([1, 2, 1])
    with cC:
        localidade = st.selectbox("Selecione a localidade:", LOCALIDADES_UI)

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
        checked = (oc in st.session_state["sel_oc_by_sheet"][planilha])
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
        if st.button("GRÁFICO POR OCORRÊNCIA", use_container_width=True):
            if not selecionadas:
                st.warning("Selecione pelo menos uma ocorrência.")
            else:
                grafico_por_ocorrencia(df_loc, selecionadas, planilha)
    with b2:
        if st.button("GRÁFICO ANUAL", use_container_width=True):
            grafico_anual_totais(df_loc, planilha)

    st.markdown("<hr/>", unsafe_allow_html=True)

    st.markdown("<div class='center' style='font-weight:700; font-size:18px;'>Gráfico Mensal:</div>", unsafe_allow_html=True)
    c1, c2, c3 = st.columns([1, 1, 1])
    with c2:
        mes = st.selectbox(" ", MESES, label_visibility="collapsed")
        if st.button("GERAR GRÁFICO MENSAL", use_container_width=True):
            grafico_mensal(df_loc, mes, planilha)

    st.markdown("<hr/>", unsafe_allow_html=True)

    st.markdown("<div class='center' style='font-weight:700; font-size:18px;'>DADOS DAS OCORRÊNCIAS</div>", unsafe_allow_html=True)

    if "aba_dados" not in st.session_state:
        st.session_state["aba_dados"] = ABA_CVLI

    mes_grupo = detectar_mes_grupo(dfs)  # <-- automático

    bb1, bb2, bb3, bb4 = st.columns(4)
    with bb1:
        if st.button("CVLI", use_container_width=True):
            st.session_state["aba_dados"] = ABA_CVLI
    with bb2:
        if st.button("TENTATIVA", use_container_width=True):
            st.session_state["aba_dados"] = ABA_TENT
    with bb3:
        if st.button("CVP", use_container_width=True):
            st.session_state["aba_dados"] = ABA_CVP
    with bb4:
        if st.button(f"COMPARATIVO DE {mes_grupo}\n2025 x 2026", use_container_width=True):
            st.session_state["aba_dados"] = ABA_GRUPO

    st.write("")
    aba_sel = st.session_state["aba_dados"]
    if aba_sel == ABA_GRUPO:
        st.markdown("<div class='center' style='font-weight:600;'>Comparativo 2025x2026 - GRUPO</div>", unsafe_allow_html=True)
        detalhamento_grupo(dfs)
    else:
        st.markdown(f"<div class='center' style='font-weight:600;'>Detalhamento - {aba_sel}</div>", unsafe_allow_html=True)
        detalhamento_por_mes(dfs, aba_sel)

    st.caption(f"Dados atualizados em: {data_atual}")

if __name__ == "__main__":
    main()
