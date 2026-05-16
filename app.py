import io
import time
import datetime
import requests
import pandas as pd
import streamlit as st
import matplotlib.pyplot as plt

# ==========================================================
# CONFIG
# ==========================================================
SHEET_ID = "1wZ4h2oiptatvfYddT8xIllGBRSEfCRy4WAenTTvUDoc"

MESES = ["JANEIRO","FEVEREIRO","MARÇO","ABRIL","MAIO","JUNHO","JULHO","AGOSTO","SETEMBRO","OUTUBRO","NOVEMBRO","DEZEMBRO"]
LOCALIDADES_UI = ["1ª CPM/I", "SÃO MIGUEL DOS CAMPOS", "CAMPO ALEGRE", "BOCA DA MATA", "ANADIA", "ROTEIRO"]
MAP_LOCALIDADE = {"1ª CPM/I": "1ª CPM-I"}  # nome exibido -> nome real da aba

# Abas “detalhamento”
ABA_CVLI = "CVLI"
ABA_TENT = "TENTATIVA"
ABA_CVP  = "CVP"
ABA_GRUPO = "GRUPO"  # comparativo 2025x2026

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
.stButton>button {padding: 0.35rem 0.9rem;}
/* centralizar tabelas */
div[data-testid="stDataFrame"] * { text-align: center !important; }
div[data-testid="stDataFrame"] td, div[data-testid="stDataFrame"] th { text-align: center !important; }
button[data-baseweb="tab"] { justify-content: center; }
</style>
""", unsafe_allow_html=True)

# ==========================================================
# HELPERS
# ==========================================================
def altura_df(n_rows: int, row_h: int = 35, header_h: int = 42, min_h: int = 120, max_h: int = 520) -> int:
    """Altura dinâmica (sem linha extra)."""
    h = header_h + row_h * n_rows
    return max(min_h, min(max_h, h))

def _limpar_data_series(s: pd.Series) -> pd.Series:
    """Normaliza valores comuns inválidos para NaN antes do parse."""
    s = s.astype(str).str.strip()
    su = s.str.upper()
    invalid = su.isin(["", "NI", "N/I", "N\\I", "-", "NÃO INFORMADO", "NA", "NAN"])
    s = s.mask(invalid, None)
    return s

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

            # localidade / CVLI / TENTATIVA / GRUPO (tende a ter "OCORRÊNCIAS")
            if ("NOME" in vals) or ("OCORRÊNCIAS" in vals) or ("OCORRÊNCIA" in vals):
                header_idx = idx
                break

            # CVP
            if ("TIPO" in vals) and ("DATA" in vals) and ("LOCAL" in vals):
                header_idx = idx
                break

            # GRUPO: geralmente tem "PERÍODO" e "STATUS"
            if ("PERÍODO" in vals) and ("STATUS" in vals):
                header_idx = idx
                break

        df = xls.parse(sheet, header=header_idx).dropna(axis=1, how="all")
        df.columns = df.columns.astype(str).str.strip().str.upper()
        dfs[sheet] = df

    # Data de atualização (AC8) – tenta 1ª CPM-I
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
# GRÁFICOS (mantendo lógica do desktop)
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
        reg.append({
            "OC": str(r["OCORRÊNCIAS"]),
            "2025": _total(df_l, slice(1, None, 2)),
            "2026": _total(df_l, slice(2, None, 2))
        })

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
# DETALHAMENTO por mês (CVLI/TENTATIVA/CVP) + ALERTA (sem aba Data indefinida)
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

    # DATA parse robusto (com DATA_ORIG)
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

    # ALERTA: inválida = DATA_DT NaT
    df_invalid = df[df["DATA_DT"].isna()].copy()
    if not df_invalid.empty:
        st.warning(f"⚠️ {len(df_invalid)} registro(s) com DATA vazia/inválida (não entrou em nenhum mês).")
        with st.expander("Ver registros com DATA inválida"):
            df_bad = df_invalid[colunas_presentes].copy().reset_index(drop=True)

            # DATA original legível
            if "DATA" in df_bad.columns:
                def fmt_data(x):
                    if isinstance(x, (pd.Timestamp, datetime.datetime, datetime.date)):
                        return x.strftime("%d/%m/%Y")
                    return "" if pd.isna(x) else str(x)
                df_bad["DATA"] = df_invalid["DATA_ORIG"].apply(fmt_data).reset_index(drop=True)

            df_bad.insert(0, "ORDEM", range(1, len(df_bad) + 1))
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
            df_show.insert(0, "ORDEM", range(1, len(df_show) + 1))

            st.dataframe(df_show, use_container_width=True, height=altura_df(len(df_show)), hide_index=True)

# ==========================================================
# DETALHAMENTO GRUPO (Comparativo 2025x2026)
# ==========================================================
def detalhamento_grupo(dfs):
    if ABA_GRUPO not in dfs:
        st.error("Aba 'GRUPO' não encontrada.")
        return

    df = dfs[ABA_GRUPO].copy().dropna(axis=1, how="all")
    df = df.dropna(how="all")

    # remove linhas “header duplicado” se existirem
    # (ex.: se a primeira coluna contiver o próprio nome "OCORRÊNCIAS" em linhas)
    if "OCORRÊNCIAS" in df.columns:
        df = df[df["OCORRÊNCIAS"].astype(str).str.upper().ne("OCORRÊNCIAS")]

    df_show = df.reset_index(drop=True)
    df_show.insert(0, "ORDEM", range(1, len(df_show) + 1))

    st.dataframe(
        df_show,
        use_container_width=True,
        height=altura_df(len(df_show), max_h=650),
        hide_index=True
    )

# ==========================================================
# APP
# ==========================================================
def main():
    login()

    # refresh token para forçar atualização
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

    # localidade central
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

    # seleção por planilha
    if "sel_oc_by_sheet" not in st.session_state:
        st.session_state["sel_oc_by_sheet"] = {}
    if planilha not in st.session_state["sel_oc_by_sheet"]:
        st.session_state["sel_oc_by_sheet"][planilha] = set()

    # checkboxes em 4 colunas
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
        if st.button("Comparativo 2025x2026", use_container_width=True):
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
