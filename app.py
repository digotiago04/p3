import tkinter as tk
from tkinter import ttk, messagebox, simpledialog
import matplotlib.pyplot as plt
import pandas as pd
import datetime
import sys
import requests
import io

# Variáveis globais
dfs = {}
checkbox_vars = {}
data_atualizacao_str = ""
senha_planilha = ""

# ==========================================================
#  DOWNLOAD XLSX DO GOOGLE SHEETS
# ==========================================================
def _baixar_xlsx_google_sheets(sheet_id: str) -> io.BytesIO:
    url = f"https://docs.google.com/spreadsheets/d/{sheet_id}/export?format=xlsx"
    headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}
    r = requests.get(url, headers=headers, timeout=60)
    r.raise_for_status()
    return io.BytesIO(r.content)

# ==========================================================
#  CARREGAR DADOS DA NUVEM (COM DETECÇÃO PRECISA DE CABEÇALHO)
# ==========================================================
def carregar_dados_da_nuvem():
    global dfs, data_atualizacao_str, senha_planilha
    try:
        SHEET_ID = "1wZ4h2oiptatvfYddT8xIllGBRSEfCRy4WAenTTvUDoc"
        arquivo_memoria = _baixar_xlsx_google_sheets(SHEET_ID)
        xls = pd.ExcelFile(arquivo_memoria, engine="openpyxl")
        
        dfs.clear()
        for sheet in xls.sheet_names:
            df_raw = xls.parse(sheet, header=None)
            df_raw = df_raw.dropna(axis=1, how="all")
            
            header_idx = 2  # Padrão caso não encontre
            
            # >>> AJUSTE: reconhecer também cabeçalho da aba CVP
            for idx, row in df_raw.head(15).iterrows():
                valores_celulas = [str(x).strip().upper() for x in row.dropna().values]

                # Padrões antigos (CVLI/TENTATIVA/ocorrências)
                if ("NOME" in valores_celulas) or ("OCORRÊNCIAS" in valores_celulas) or ("OCORRÊNCIA" in valores_celulas):
                    header_idx = idx
                    break

                # Padrão do CVP (como na sua foto)
                if ("TIPO" in valores_celulas) and ("DATA" in valores_celulas) and ("LOCAL" in valores_celulas):
                    header_idx = idx
                    break
            
            df = xls.parse(sheet, header=header_idx)
            df = df.dropna(axis=1, how="all")
            df.columns = df.columns.astype(str).str.strip().str.upper()
            dfs[sheet] = df

        sheet_ref = "1ª CPM-I" if "1ª CPM-I" in xls.sheet_names else xls.sheet_names[0]
        sheet_raw = xls.parse(sheet_ref, header=None)
        try:
            data_val = sheet_raw.iloc[7, 28]
            data_atualizacao_str = data_val.strftime("%d/%m/%Y") if isinstance(data_val, (pd.Timestamp, datetime.datetime)) else str(data_val)
        except:
            data_atualizacao_str = "não localizada"
        try:
            senha_planilha = str(sheet_raw.iloc[999, 28]).strip()
        except:
            senha_planilha = ""
        
        return True, "Sucesso"
    except Exception as e:
        return False, str(e)

# ==========================================================
#  FUNÇÃO PARA EXIBIR JANELA COM DADOS (CVLI / TENTATIVA / CVP)
# ==========================================================
def exibir_janela_detalhes(tipo_aba):
    if not dfs:
        messagebox.showwarning("Aviso", "Carregue os dados primeiro!")
        return

    if tipo_aba not in dfs:
        messagebox.showerror("Erro", f"Aba '{tipo_aba}' não encontrada na planilha!")
        return

    janela_detalhes = tk.Toplevel(root)
    janela_detalhes.title(f"Detalhamento - {tipo_aba}")
    janela_detalhes.geometry("1100x600")

    df = dfs[tipo_aba].copy()

    # Compatibilizações antigas
    df.rename(columns={"ENDERECO": "LOCAL", "COP": "BOU"}, inplace=True)

    # >>> AJUSTE: colunas específicas do CVP
    if tipo_aba.upper() == "CVP":
        colunas_exibir = ["TIPO", "DATA", "HORA", "LOCAL", "INSTRUMENTO", "BOU PC"]
        chave_dropna = "TIPO"  # para não “sumir” tudo (CVP não tem NOME)
    else:
        colunas_exibir = ["NOME", "IDADE", "DATA", "LOCAL", "MEIO EMPREGADO", "BOU"]
        chave_dropna = "NOME"

    colunas_presentes = [c for c in colunas_exibir if c in df.columns]

    # Ordenação por mês (pela coluna DATA)
    if "DATA" in df.columns:
        df['DATA_DT'] = pd.to_datetime(df['DATA'], errors='coerce', dayfirst=True)
        df['MES_NUM'] = df['DATA_DT'].dt.month.fillna(99)
        df = df.sort_values(by=['MES_NUM', 'DATA_DT'], na_position='last')
    else:
        df['DATA_DT'] = pd.NaT
        df['MES_NUM'] = 99

    # >>> AJUSTE: dropna conforme tipo
    if chave_dropna in df.columns:
        df = df.dropna(subset=[chave_dropna])

    tree_frame = tk.Frame(janela_detalhes)
    tree_frame.pack(fill="both", expand=True, padx=15, pady=15)

    tree = ttk.Treeview(tree_frame, columns=colunas_presentes, show="headings")
    vsb = ttk.Scrollbar(tree_frame, orient="vertical", command=tree.yview)
    hsb = ttk.Scrollbar(tree_frame, orient="horizontal", command=tree.xview)
    tree.configure(yscrollcommand=vsb.set, xscrollcommand=hsb.set)

    for col in colunas_presentes:
        tree.heading(col, text=col)
        largura = 280 if col in ["NOME", "LOCAL", "TIPO"] else 130
        tree.column(col, width=largura, anchor="w" if col in ["NOME", "LOCAL", "TIPO"] else "center")

    vsb.pack(side="right", fill="y")
    hsb.pack(side="bottom", fill="x")
    tree.pack(side="left", fill="both", expand=True)

    meses_pt = {
        1: "JANEIRO", 2: "FEVEREIRO", 3: "MARÇO", 4: "ABRIL", 5: "MAIO", 6: "JUNHO",
        7: "JULHO", 8: "AGOSTO", 9: "SETEMBRO", 10: "OUTUBRO", 11: "NOVEMBRO", 12: "DEZEMBRO", 99: "DATA INDEFINIDA"
    }
    
    mes_atual = ""
    for _, row in df.iterrows():
        mes_num = row['MES_NUM']
        nome_mes = meses_pt.get(mes_num, "DATA INDEFINIDA")
        
        if nome_mes != mes_atual:
            mes_atual = nome_mes
            sep_id = tree.insert("", "end", values=[f"--- {mes_atual} ---"] + [""]*(len(colunas_presentes)-1))
            tree.item(sep_id, tags=('separator',))

        valores = []
        for c in colunas_presentes:
            val = row.get(c, "")
            if c == "DATA" and pd.notna(row.get('DATA_DT', pd.NaT)):
                valores.append(row['DATA_DT'].strftime("%d/%m/%Y"))
            else:
                # mantém conversão só para campos que fazem sentido
                if c in ["IDADE", "BOU"] and pd.notna(val):
                    try:
                        val = str(int(float(val)))
                    except:
                        val = str(val)
                valores.append(str(val) if pd.notna(val) else "-")

        tree.insert("", "end", values=valores)

    tree.tag_configure('separator', background='#e0e0e0', font=('Arial', 10, 'bold'))

# ==========================================================
#  FUNÇÕES DE GRÁFICOS E CHECKBOXES
# ==========================================================
def exibir_checkboxes(event=None):
    global checkbox_vars
    planilha = cidade_var.get()
    if planilha == "1ª CPM/I": planilha = "1ª CPM-I"
    if not planilha or planilha not in dfs: return
    df = dfs[planilha]
    
    if "OCORRÊNCIAS" not in df.columns: 
        return
        
    checkbox_vars = {}
    ocorrencias = df["OCORRÊNCIAS"].dropna().drop_duplicates().astype(str).tolist()
    for widget in checkbox_frame.winfo_children(): widget.destroy()
    frame_grid = tk.Frame(checkbox_frame)
    frame_grid.pack(pady=10)
    max_por_coluna, col_idx, row_idx = 5, 0, 0
    for i, ocorrencia in enumerate(ocorrencias):
        var = tk.BooleanVar()
        cb = tk.Checkbutton(frame_grid, text=ocorrencia, variable=var)
        cb.grid(row=row_idx, column=col_idx, sticky="w", padx=10, pady=2)
        checkbox_vars[ocorrencia] = var
        row_idx += 1
        if row_idx >= max_por_coluna: row_idx, col_idx = 0, col_idx + 1

def gerar_graficos_por_ocorrencia():
    planilha = cidade_var.get().replace("1ª CPM/I", "1ª CPM-I")
    if not dfs or planilha not in dfs: return
    df = dfs[planilha]
    selecionadas = [o for o, v in checkbox_vars.items() if v.get()]
    if not selecionadas: return
    meses = ["JANEIRO", "FEVEREIRO", "MARÇO", "ABRIL", "MAIO", "JUNHO", "JULHO", "AGOSTO", "SETEMBRO", "OUTUBRO", "NOVEMBRO", "DEZEMBRO"]
    for ocorrencia in selecionadas:
        df_o = df[df["OCORRÊNCIAS"] == ocorrencia]
        if df_o.empty: continue
        d25 = df_o.iloc[:, 1::2].values.flatten()[:12]
        d26 = df_o.iloc[:, 2::2].values.flatten()[:12]
        df_p = pd.DataFrame({"2025": d25, "2026": d26}, index=meses).fillna(0)
        df_p.loc["TOTAL"] = df_p.sum()
        ax = df_p.plot(kind="bar", figsize=(10, 6), title=f"{ocorrencia} - {planilha}")
        for c in ax.containers: ax.bar_label(c, fmt="%.0f")
        plt.xticks(rotation=45, ha='right')
        plt.tight_layout(); plt.show()

def gerar_grafico_anual_totais():
    planilha = cidade_var.get().replace("1ª CPM/I", "1ª CPM-I")
    if not dfs or planilha not in dfs: return
    df = dfs[planilha]
    def _total(linha, cols):
        s = pd.to_numeric(linha.iloc[:, cols].values.flatten(), errors="coerce")
        return float(s[12]) if len(s) >= 13 and pd.notna(s[12]) else float(pd.Series(s[:12]).fillna(0).sum())
    reg = []
    for _, r in df.dropna(subset=["OCORRÊNCIAS"]).iterrows():
        df_l = df[df["OCORRÊNCIAS"] == r["OCORRÊNCIAS"]].head(1)
        reg.append({"OC": str(r["OCORRÊNCIAS"]), "2025": _total(df_l, slice(1,None,2)), "2026": _total(df_l, slice(2,None,2))})
    df_t = pd.DataFrame(reg)
    dkw = ["drogas", "maconha", "cocaína", "crack"]
    m_dr = df_t["OC"].str.contains("|".join(dkw), case=False) & (df_t["OC"].str.upper() != "OCORRÊNCIAS A. DROGAS")
    m_ot = ~df_t["OC"].str.contains("|".join(dkw), case=False) | (df_t["OC"].str.upper() == "OCORRÊNCIAS A. DROGAS")
    for d, t in [(df_t[m_dr], "DROGAS"), (df_t[m_ot], "OUTRAS")]:
        if d.empty: continue
        ax = d.set_index("OC").plot(kind="bar", figsize=(12, 6), title=f"{t} - {planilha}")
        for c in ax.containers: ax.bar_label(c, fmt="%.0f")
        plt.xticks(rotation=45, ha='right')
        plt.tight_layout(); plt.show()

def gerar_graficos_mensais():
    planilha = cidade_var.get().replace("1ª CPM/I", "1ª CPM-I")
    mes = mes_var.get().upper()
    meses = ["JANEIRO", "FEVEREIRO", "MARÇO", "ABRIL", "MAIO", "JUNHO", "JULHO", "AGOSTO", "SETEMBRO", "OUTUBRO", "NOVEMBRO", "DEZEMBRO"]
    if not dfs or planilha not in dfs or mes not in meses: return
    idx = meses.index(mes)
    df = dfs[planilha]
    d25, d26 = df.iloc[:, 1::2].iloc[:, idx].fillna(0), df.iloc[:, 2::2].iloc[:, idx].fillna(0)
    df_m = pd.DataFrame({"OC": df["OCORRÊNCIAS"], "2025": d25, "2026": d26}).dropna(subset=["OC"])
    dkw = ["drogas", "maconha", "cocaína", "crack"]
    m_dr = df_m["OC"].str.contains("|".join(dkw), case=False) & (df_m["OC"].str.upper() != "OCORRÊNCIAS A. DROGAS")
    m_ot = ~df_m["OC"].str.contains("|".join(dkw), case=False) | (df_m["OC"].str.upper() == "OCORRÊNCIAS A. DROGAS")
    for d, t in [(df_m[m_dr], "Drogas"), (df_m[m_ot], "Outras")]:
        if d.empty: continue
        ax = d.set_index("OC").plot(kind="bar", figsize=(10, 6), title=f"{t} - {mes} - {planilha}")
        for c in ax.containers: ax.bar_label(c, fmt="%.0f")
        plt.xticks(rotation=45, ha='right')
        plt.tight_layout(); plt.show()

# ==========================================================
#  INTERFACE PRINCIPAL
# ==========================================================
root = tk.Tk()
root.withdraw() 

sucesso, mensagem_erro = carregar_dados_da_nuvem()

if not sucesso:
    root.deiconify()
    messagebox.showerror("Erro Crítico", f"Não foi possível processar os dados.\n\nDetalhe do erro:\n{mensagem_erro}")
    sys.exit()

senha_digitada = simpledialog.askstring("Senha", "Digite a senha:", show="*")
if senha_digitada != senha_planilha:
    messagebox.showerror("Erro", "Senha incorreta!")
    sys.exit()

root.deiconify()
root.title("Ferramenta para Análise de Ocorrências – 1ª CPM/I")
root.geometry("800x750")

tk.Label(root, text="Ferramenta para Análise de Ocorrências", font=("Arial", 14, "bold")).pack(pady=5)
tk.Label(root, text="*** 1ª CPM/I ***", font=("Arial", 12, "bold")).pack(pady=5)

frame_loc = tk.Frame(root)
frame_loc.pack(pady=5)
tk.Label(frame_loc, text="Selecione a localidade:", font=("Arial", 12), fg="blue").pack(side="left", padx=5)
cidade_var = tk.StringVar(value="1ª CPM/I")
cidade_dropdown = ttk.Combobox(frame_loc, textvariable=cidade_var, width=30, values=["1ª CPM/I", "SÃO MIGUEL DOS CAMPOS", "CAMPO ALEGRE", "BOCA DA MATA", "ANADIA", "ROTEIRO"])
cidade_dropdown.pack(side="left", padx=5)
cidade_dropdown.bind("<<ComboboxSelected>>", exibir_checkboxes)

checkbox_frame = tk.Frame(root)
checkbox_frame.pack(pady=10)
exibir_checkboxes()

ttk.Separator(root, orient='horizontal').pack(fill='x', padx=20, pady=10)

tk.Label(root, text="Gráfico Anual: 2025 vs 2026", font=("Arial", 12, "bold")).pack(pady=5)
f_btns = tk.Frame(root)
f_btns.pack(pady=5)
tk.Button(f_btns, text="GRÁFICO POR OCORRÊNCIA", command=gerar_graficos_por_ocorrencia).pack(side="left", padx=10)
tk.Button(f_btns, text="GRÁFICO ANUAL", command=gerar_grafico_anual_totais).pack(side="left", padx=10)

ttk.Separator(root, orient='horizontal').pack(fill='x', padx=20, pady=10)

tk.Label(root, text="Gráfico Mensal:", font=("Arial", 12, "bold")).pack(pady=5)
mes_var = tk.StringVar()
mes_dropdown = ttk.Combobox(root, textvariable=mes_var, width=20, values=["JANEIRO", "FEVEREIRO", "MARÇO", "ABRIL", "MAIO", "JUNHO", "JULHO", "AGOSTO", "SETEMBRO", "OUTUBRO", "NOVEMBRO", "DEZEMBRO"])
mes_dropdown.pack()
tk.Button(root, text="GERAR GRÁFICO MENSAL", command=gerar_graficos_mensais).pack(pady=5)

ttk.Separator(root, orient='horizontal').pack(fill='x', padx=20, pady=10)

tk.Label(root, text="DADOS DAS OCORRÊNCIAS", font=("Arial", 12, "bold")).pack(pady=10)
frame_nominais = tk.Frame(root)
frame_nominais.pack(pady=5)

tk.Button(frame_nominais, text="CVLI", width=15, command=lambda: exibir_janela_detalhes("CVLI")).pack(side="left", padx=10)
tk.Button(frame_nominais, text="TENTATIVA", width=15, command=lambda: exibir_janela_detalhes("TENTATIVA")).pack(side="left", padx=10)

# >>> NOVO BOTÃO CVP (ao lado de TENTATIVA)
tk.Button(frame_nominais, text="CVP", width=15, command=lambda: exibir_janela_detalhes("CVP")).pack(side="left", padx=10)

tk.Label(root, text=f"Dados atualizados em: {data_atualizacao_str}", font=("Arial", 8, "italic")).pack(side="bottom", pady=10)

root.mainloop()