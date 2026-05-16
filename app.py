import streamlit as st
import pandas as pd
import requests
import io
import datetime
import re, streamlit as st
SHEET_ID = "1wZ4h2oiptatvfYddT8xIllGBRSEfCRy4WAenTTvUDoc"
SHEET_URL = st.secrets["SHEET_URL"]
SHEET_ID = re.search(r"/spreadsheets/d/([a-zA-Z0-9-_]+)", SHEET_URL).group(1)



def baixar_xlsx(sheet_id: str) -> io.BytesIO:
    url = f"https://docs.google.com/spreadsheets/d/{sheet_id}/export?format=xlsx"
    r = requests.get(url, timeout=60)
    if r.status_code != 200:
        raise RuntimeError(f"Falha ao baixar XLSX. Status={r.status_code}. Resposta curta={r.text[:200]}")
    return io.BytesIO(r.content)

@st.cache_data(ttl=300)
def carregar_dados():
    arquivo = baixar_xlsx(SHEET_ID)
    xls = pd.ExcelFile(arquivo, engine="openpyxl")

    dfs = {}
    for sheet in xls.sheet_names:
        df_raw = xls.parse(sheet, header=None).dropna(axis=1, how="all")

        header_idx = 2
        for idx, row in df_raw.head(15).iterrows():
            vals = [str(x).strip().upper() for x in row.dropna().values]
            if ("NOME" in vals) or ("OCORRÊNCIAS" in vals) or ("OCORRÊNCIA" in vals):
                header_idx = idx
                break
            if ("TIPO" in vals) and ("DATA" in vals) and ("LOCAL" in vals):
                header_idx = idx
                break

        df = xls.parse(sheet, header=header_idx).dropna(axis=1, how="all")
        df.columns = df.columns.astype(str).str.strip().str.upper()
        dfs[sheet] = df

    # data atualização (AC8) - tenta 1ª CPM-I
    sheet_ref = "1ª CPM-I" if "1ª CPM-I" in xls.sheet_names else xls.sheet_names[0]
    raw = xls.parse(sheet_ref, header=None)
    try:
        data_val = raw.iloc[7, 28]
        if isinstance(data_val, (pd.Timestamp, datetime.datetime, datetime.date)):
            data_atual = data_val.strftime("%d/%m/%Y")
        else:
            data_atual = str(data_val)
    except Exception:
        data_atual = "não localizada"

    return dfs, data_atual

def login():
    st.title("Acesso restrito")
    senha = st.text_input("Senha", type="password")
    if senha and senha == st.secrets["APP_PASSWORD"]:
        st.session_state["auth"] = True
        st.rerun()
    st.stop()

def main():
    st.set_page_config(layout="wide")
    if not st.session_state.get("auth"):
        login()

    dfs, data_atual = carregar_dados()
    st.title("Ferramenta para Análise de Ocorrências (Web)")
    st.caption(f"Dados atualizados em: {data_atual}")

    st.write("Abas:", list(dfs.keys()))
    aba = st.selectbox("Abrir aba", list(dfs.keys()))
    st.dataframe(dfs[aba], use_container_width=True)

if __name__ == "__main__":
    main()
