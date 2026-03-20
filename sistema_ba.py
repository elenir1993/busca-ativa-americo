import streamlit as st
import pandas as pd
import os
import json
import matplotlib.pyplot as plt
from datetime import datetime
from fpdf import FPDF
import re
import io
import urllib.parse
import gspread 

st.set_page_config(page_title="Busca Ativa Escolar", layout="wide")

# ============================================================
# FUNÇÃO AUXILIAR PARA GERAR EXCEL
# ============================================================
def gerar_excel_faixa(df, nome_aba):
    output = io.BytesIO()
    with pd.ExcelWriter(output, engine='xlsxwriter') as writer:
        colunas = ['Turma', 'RA', 'Nome', 'Presenca_Anual']
        df_ex = df[colunas].copy() if set(colunas).issubset(df.columns) else df.copy()
        df_ex.to_excel(writer, index=False, sheet_name=nome_aba)
        ws = writer.sheets[nome_aba]
        ws.hide_gridlines(2)
        try:
            fmt_cab = writer.book.add_format({'bold': True, 'font_color': 'white', 'bg_color': '#1E3A8A', 'border': 1, 'align': 'center', 'valign': 'vcenter'})
            fmt_cel = writer.book.add_format({'border': 1, 'valign': 'vcenter'})
            fmt_perc = writer.book.add_format({'border': 1, 'valign': 'vcenter', 'num_format': '0.00%'})
            for col_num, value in enumerate(df_ex.columns.values):
                ws.write(0, col_num, value, fmt_cab)
                if value == "Nome": ws.set_column(col_num, col_num, 40, fmt_cel)
                elif value == "Presenca_Anual": ws.set_column(col_num, col_num, 18, fmt_perc)
                else: ws.set_column(col_num, col_num, 20, fmt_cel)
        except: pass
    return output.getvalue()

# ============================================================
# CONEXÃO COM A NUVEM (GOOGLE SHEETS)
# ============================================================
@st.cache_resource
def obter_planilha():
    cred_dict = json.loads(st.secrets["GOOGLE_KEY"])
    gc = gspread.service_account_from_dict(cred_dict)
    sh = gc.open_by_url(st.secrets["SHEET_URL"].strip())
    return sh.sheet1

planilha = obter_planilha()

# ============================================================
# SESSION STATE
# ============================================================
if "dados_escola" not in st.session_state: st.session_state.dados_escola = None
if "turma_selecionada" not in st.session_state: st.session_state.turma_selecionada = None
if "ra_selecionado" not in st.session_state: st.session_state.ra_selecionado = ""

# ============================================================
# CABEÇALHO E MENU
# ============================================================
st.title("Sistema de Busca Ativa")
st.subheader("EE Dr. Américo Brasiliense")

menu = st.sidebar.radio("Menu", ["Diagnóstico Geral", "Prontuário do Aluno", "Painel de Lembretes e Disparo"])

if st.sidebar.button("Deslogar / Reiniciar"):
    st.session_state.clear()
    st.rerun()

# ============================================================
# MOMENTO 1 — DIAGNÓSTICO (FAIXAS DE 25%)
# ============================================================
if menu == "Diagnóstico Geral":
    st.header("Diagnóstico de Frequência Escolar (Evolutivo)")
    arquivos = st.file_uploader("Carregar planilhas do BI", type=["xlsx"], accept_multiple_files=True)

    if arquivos:
        lista = []
        for arq in arquivos:
            df = pd.read_excel(arq)
            df.columns = [str(c).strip() for c in df.columns]
            df.rename(columns={
                "Aluno(a)": "Nome", "(%) Presença Anual na Turma Atual": "Presenca_Anual",
                "(%) Presença na Semana Atual": "Presenca_Semana", "(%) Presença na Semana Anterior": "Presenca_Semana_Anterior"
            }, inplace=True)
            turma_limpa = re.sub(r'\s*-\s*\d{5,}.*$', '', arq.name.replace(".xlsx", "")).strip()
            df["Turma"] = turma_limpa
            if "RA" in df.columns: df["RA"] = df["RA"].astype(str).str.replace(r'\.0$', '', regex=True)
            lista.append(df)

        escola = pd.concat(lista, ignore_index=True)
        escola["Presenca_Anual"] = pd.to_numeric(escola["Presenca_Anual"], errors="coerce")
        st.session_state.dados_escola = escola

    if st.session_state.dados_escola is not None:
        escola = st.session_state.dados_escola
        
        # Divisão em Faixas de 25%
        f1 = escola[escola["Presenca_Anual"] <= 0.25]
        f2 = escola[(escola["Presenca_Anual"] > 0.25) & (escola["Presenca_Anual"] <= 0.50)]
        f3 = escola[(escola["Presenca_Anual"] > 0.50) & (escola["Presenca_Anual"] <= 0.75)]
        f4 = escola[escola["Presenca_Anual"] > 0.75]
        
        criticos_geral = escola[escola["Presenca_Anual"] <= 0.75]

        col1, col2, col3, col4 = st.columns(4)
        col1.error(f"🔴 0% a 25%: {len(f1)} alunos")
        col2.warning(f"🟠 26% a 50%: {len(f2)} alunos")
        col3.info(f"🟡 51% a 75%: {len(f3)} alunos")
        col4.success(f"🟢 76% a 100%: {len(f4)} alunos")
        
        # BOTÕES DE DOWNLOAD POR FAIXA
        dl1, dl2, dl3, dl4 = st.columns(4)
        if not f1.empty: dl1.download_button("📥 Baixar 0-25%", gerar_excel_faixa(f1, "0_a_25"), f"Lista_0_25_{datetime.now().strftime('%d-%m-%Y')}.xlsx", use_container_width=True)
        if not f2.empty: dl2.download_button("📥 Baixar 26-50%", gerar_excel_faixa(f2, "26_a_50"), f"Lista_26_50_{datetime.now().strftime('%d-%m-%Y')}.xlsx", use_container_width=True)
        if not f3.empty: dl3.download_button("📥 Baixar 51-75%", gerar_excel_faixa(f3, "51_a_75"), f"Lista_51_75_{datetime.now().strftime('%d-%m-%Y')}.xlsx", use_container_width=True)
        if not f4.empty: dl4.download_button("📥 Baixar 76-100%", gerar_excel_faixa(f4, "76_a_100"), f"Lista_76_100_{datetime.now().strftime('%d-%m-%Y')}.xlsx", use_container_width=True)

        st.write(f"**Total de alunos matriculados processados:** {len(escola)}")
        st.markdown("---")

        st.subheader("Concentração de Faltas por Turma (< 76%)")
        resumo = criticos_geral["Turma"].value_counts()
        
        fig, ax = plt.subplots(figsize=(12, 6))
        bars = ax.bar(resumo.index, resumo.values, color="#3B82F6", edgecolor="#2563EB", linewidth=1.2, alpha=0.8)
        
        ax.spines['top'].set_visible(False); ax.spines['right'].set_visible(False); ax.spines['left'].set_visible(False)
        ax.yaxis.grid(True, linestyle='--', alpha=0.4); plt.xticks(rotation=45, ha='right', fontsize=9, color="#374151")
        ax.set_ylabel("Quantidade de Alunos", fontsize=10, fontweight='bold', color="#4B5563")
        ax.bar_label(bars, padding=3, fontsize=10, fontweight='bold', color="#1E3A8A")
        plt.tight_layout(); st.pyplot(fig)

        st.subheader("Selecionar Turma para Ação")
        turmas = sorted(criticos_geral["Turma"].unique())
        cols_turma = st.columns(4)
        for i, t in enumerate(turmas):
            qtd = len(criticos_geral[criticos_geral["Turma"] == t])
            if cols_turma[i % 4].button(f"{t} ({qtd} alunos)", key=f"btn_{t}"): st.session_state.turma_selecionada = t

        if st.session_state.turma_selecionada:
            turma_sel = st.session_state.turma_selecionada
            st.subheader(f"Lista da Turma: {turma_sel}")
            alunos_turma = criticos_geral[criticos_geral["Turma"] == turma_sel]
            for _, row in alunos_turma.iterrows():
                c1, c2 = st.columns([4, 1])
                c1.write(f"**{row['Nome']}** (RA: {row['RA']} | Presença Anual: {row['Presenca_Anual']:.2%})")
                if c2.button("Abrir prontuário", key=f"ficha_{row['RA']}"):
                    st.session_state.ra_selecionado = row["RA"]
                    st.success("Aluno selecionado! Acesse a aba 'Prontuário do Aluno' no menu ao lado.")

        st.markdown("---")
        st.subheader("📥 Exportação Geral (< 76%)")
        st.download_button("📄 Baixar Planilha Nominal Geral", data=gerar_excel_faixa(criticos_geral, "Busca Ativa"), file_name=f"Lista_Geral_{datetime.now().strftime('%d-%m-%Y')}.xlsx")

        # ------------------------------------------------
        # LÓGICA DE HISTÓRICO NA NUVEM
        # ------------------------------------------------
        todas_linhas = planilha.get_all_values()
        linha_hist = -1; hist_dados = []
        for i, linha in enumerate(todas_linhas):
            if i > 0 and len(linha) > 0 and str(linha[0]) == "HISTORICO_SISTEMA":
                linha_hist = i + 1
                if len(linha) > 1: hist_dados = json.loads(linha[1])
                break

        st.markdown("---")
        st.subheader("📊 Relatório Oficial SEDUC (Com Evolução)")
        analise_qualitativa = st.text_area("Análise Qualitativa:", placeholder="Descreva os avanços observados nas faixas de percentual...")

        if st.button("Gravar Hoje e Gerar Relatório PDF"):
            hoje = datetime.now().strftime("%d/%m/%Y")
            
            hist_dados_limpos = {}
            for item in hist_dados:
                d_str = item["data"]
                if "-" in d_str: 
                    try: d_str = datetime.strptime(d_str, "%Y-%m-%d").strftime("%d/%m/%Y")
                    except: pass
                if "f1" in item:
                    hist_dados_limpos[d_str] = {"f1": item["f1"], "f2": item["f2"], "f3": item["f3"], "f4": item["f4"]}
                else:
                    hist_dados_limpos[d_str] = {"f1": 0, "f2": 0, "f3": item.get("busca_ativa", 0), "f4": 0}
                    
            hist_dados_limpos[hoje] = {"f1": len(f1), "f2": len(f2), "f3": len(f3), "f4": len(f4)}
            hist_dados = [{"data": k, "f1": v["f1"], "f2": v["f2"], "f3": v["f3"], "f4": v["f4"]} for k, v in hist_dados_limpos.items()]
            
            # Ordenar por data
            try:
                hist_dados.sort(key=lambda x: datetime.strptime(x["data"], "%d/%m/%Y"))
            except: pass
                
            dados_str = json.dumps(hist_dados)
            if linha_hist != -1: planilha.update_cell(linha_hist, 2, dados_str)
            else: planilha.append_row(["HISTORICO_SISTEMA", dados_str])

            # Gráfico de Evolução Quantitativa (4 Linhas)
            hist_df = pd.DataFrame(hist_dados)
            fig_evol, ax_evol = plt.subplots(figsize=(10, 5))
            ax_evol.plot(hist_df["data"], hist_df["f1"], marker="o", color="darkred", linewidth=2.5, label="0-25%")
            ax_evol.plot(hist_df["data"], hist_df["f2"], marker="o", color="red", linewidth=2.5, label="26-50%")
            ax_evol.plot(hist_df["data"], hist_df["f3"], marker="o", color="orange", linewidth=2.5, label="51-75%")
            ax_evol.plot(hist_df["data"], hist_df["f4"], marker="o", color="green", linewidth=2.5, label="76-100%")
            ax_evol.set_title("Evolução Histórica por Faixas de Frequência", fontweight="bold")
            ax_evol.set_ylabel("Quantidade de Alunos")
            ax_evol.spines['top'].set_visible(False); ax_evol.spines['right'].set_visible(False)
            ax_evol.yaxis.grid(True, linestyle='--', alpha=0.4); plt.xticks(rotation=45)
            ax_evol.legend(loc="upper left", bbox_to_anchor=(1, 1))
            plt.tight_layout(); plt.savefig("evolucao.png"); plt.close(fig_evol)

            # --- GERAÇÃO DO PDF ---
            pdf = FPDF(); pdf.add_page()
            pdf.set_font("Arial", "B", 14); pdf.cell(0, 8, "ESCOLA ESTADUAL DOUTOR AMERICO BRASILIENSE", 0, 1, "C")
            pdf.set_font("Arial", "B", 12); pdf.cell(0, 8, "RELATORIO DE DIAGNOSTICO E BUSCA ATIVA", 0, 1, "C"); pdf.ln(2)
            pdf.set_font("Arial", "", 10)
            cabecalho = "CIE: 8266 | Diretoria de Ensino: SANTO ANDRE\nEndereco: PRACA QUARTO CENTENARIO, 7 - CENTRO - SANTO ANDRE - SP\nTelefone: (11) 4432-2021 | E-mail: E008266A@EDUCACAO.SP.GOV.BR"
            pdf.multi_cell(0, 5, cabecalho); pdf.line(10, pdf.get_y()+2, 200, pdf.get_y()+2); pdf.ln(5)
            
            pdf.set_font("Arial", "B", 11); pdf.cell(0, 6, f"Data do relatorio: {hoje}", 0, 1)
            pdf.set_font("Arial", "", 10); pdf.cell(0, 6, f"Total de alunos matriculados analisados: {len(escola)}", 0, 1)
            pdf.cell(0, 6, f"Total atual de alunos em risco (< 76%): {len(criticos_geral)}", 0, 1); pdf.ln(5)

            pdf.set_font("Arial", "B", 11); pdf.cell(0, 8, "Distribuicao por Turma (Cenario < 76%)", 0, 1)
            pdf.set_font("Arial", "B", 10); pdf.cell(140, 8, "Turma", 1); pdf.cell(40, 8, "Qtd", 1, 1)
            pdf.set_font("Arial", "", 10)
            for t, q in resumo.items():
                pdf.cell(140, 8, str(t), 1); pdf.cell(40, 8, str(q), 1, 1)

            pdf.add_page()
            pdf.set_font("Arial", "B", 12); pdf.cell(0, 8, "Acompanhamento e Evolucao Quantitativa", 0, 1, "C")
            pdf.ln(5); pdf.image("evolucao.png", x=10, y=25, w=190)
            
            pdf.set_y(130); pdf.set_font("Arial", "B", 9)
            pdf.cell(40, 8, "Data", 1, 0, "C"); pdf.cell(35, 8, "0% a 25%", 1, 0, "C"); pdf.cell(35, 8, "26% a 50%", 1, 0, "C"); pdf.cell(35, 8, "51% a 75%", 1, 0, "C"); pdf.cell(35, 8, "76% a 100%", 1, 1, "C")
            pdf.set_font("Arial", "", 9)
            
            for item in hist_dados[-10:]:
                pdf.cell(40, 8, item["data"], 1, 0, "C"); pdf.cell(35, 8, str(item.get("f1", 0)), 1, 0, "C"); pdf.cell(35, 8, str(item.get("f2", 0)), 1, 0, "C"); pdf.cell(35, 8, str(item.get("f3", 0)), 1, 0, "C"); pdf.cell(35, 8, str(item.get("f4", 0)), 1, 1, "C")

            pdf.ln(10); pdf.set_font("Arial", "B", 12); pdf.cell(0, 8, "Analise Qualitativa e Medidas Preventivas", 0, 1); pdf.set_font("Arial", "", 11)
            texto_analise = analise_qualitativa if analise_qualitativa.strip() else "A analise aponta a distribuicao da frequencia nas 4 faixas da escola, comprovando a evolucao quantitativa dos dados e a mobilidade dos estudantes entre os degraus de risco."
            pdf.multi_cell(0, 7, texto_analise.encode('latin-1', 'replace').decode('latin-1')) 
            
            pdf_out = pdf.output(dest="S").encode("latin1", "ignore")
            st.download_button("Baixar Relatório Oficial com Evolução", data=pdf_out, file_name=f"Relatorio_SEDUC_{hoje.replace('/','-')}.pdf")
            if os.path.exists("evolucao.png"): os.remove("evolucao.png")

        # ------------------------------------------------
        # BOTÃO PARA EXCLUIR OU INSERIR REGISTROS
        # ------------------------------------------------
        st.markdown("---")
        with st.expander("⚙️ Gerenciar Histórico de Dados (Gráfico e Tabela)"):
            st.warning("Aqui você pode excluir uma data errada ou **INSERIR** manualmente os dados de um dia que ficou vazio/corrompido (ex: dia 13/03/2026).")
            
            tab_del, tab_add = st.tabs(["🗑️ Excluir Data", "➕ Inserir/Corrigir Data Manual"])
            
            with tab_del:
                if hist_dados:
                    datas_disponiveis = [item["data"] for item in hist_dados]
                    data_excluir = st.selectbox("Selecione a data para remover do histórico:", datas_disponiveis)
                    if st.button("Excluir Data Selecionada"):
                        hist_dados_novo = [item for item in hist_dados if item["data"] != data_excluir]
                        planilha.update_cell(linha_hist, 2, json.dumps(hist_dados_novo))
                        st.success(f"Os dados do dia {data_excluir} foram apagados com sucesso!")
                        st.rerun()
                else:
                    st.info("Nenhum dado histórico gravado ainda.")
                    
            with tab_add:
                with st.form("form_correcao"):
                    st.write("Digite a data e a quantidade de alunos em cada faixa para salvar no histórico.")
                    c_dt, c_f1, c_f2, c_f3, c_f4 = st.columns(5)
                    dt_manual = c_dt.text_input("Data (DD/MM/AAAA):", value=datetime.now().strftime("%d/%m/%Y"))
                    val_f1 = c_f1.number_input("Qtd 0-25%", min_value=0, value=0)
                    val_f2 = c_f2.number_input("Qtd 26-50%", min_value=0, value=0)
                    val_f3 = c_f3.number_input("Qtd 51-75%", min_value=0, value=0)
                    val_f4 = c_f4.number_input("Qtd 76-100%", min_value=0, value=0)
                    
                    if st.form_submit_button("Salvar Registro Manual"):
                        hist_dados_limpos = [item for item in hist_dados if item["data"] != dt_manual]
                        hist_dados_limpos.append({"data": dt_manual, "f1": val_f1, "f2": val_f2, "f3": val_f3, "f4": val_f4})
                        try:
                            hist_dados_limpos.sort(key=lambda x: datetime.strptime(x["data"], "%d/%m/%Y"))
                        except: pass
                            
                        dados_str = json.dumps(hist_dados_limpos)
                        if linha_hist != -1: planilha.update_cell(linha_hist, 2, dados_str)
                        else: planilha.append_row(["HISTORICO_SISTEMA", dados_str])
                        st.success(f"Dados do dia {dt_manual} registrados com sucesso!")
                        st.rerun()
                
# ============================================================
# MOMENTO 2 — PRONTUÁRIO DO ALUNO
# ============================================================
elif menu == "Prontuário do Aluno":
    st.header("Prontuário Individual de Acompanhamento")
    
    ra = st.text_input("RA do aluno (Apenas números)", value=st.session_state.ra_selecionado)
    
    if ra:
        nome_aluno = "Estudante não identificado na planilha atual"
        turma_aluno = "Não informada"
        frequencia_atual = None
        
        if st.session_state.dados_escola is not None:
            busca_aluno = st.session_state.dados_escola[st.session_state.dados_escola["RA"] == ra]
            if not busca_aluno.empty:
                nome_aluno = busca_aluno.iloc[0]["Nome"]
                turma_aluno = str(busca_aluno.iloc[0]["Turma"]).split('-')[0].strip()
                frequencia_atual = busca_aluno.iloc[0]["Presenca_Anual"]

        todas_linhas = planilha.get_all_values()
        linha_aluno = -1
        dados_texto = ""
        
        for i, linha in enumerate(todas_linhas):
            if i > 0 and len(linha) > 0 and str(linha[0]) == str(ra):
                linha_aluno = i + 1 
                if len(linha) > 1: dados_texto = linha[1]
                break

        if dados_texto:
            dados = json.loads(dados_texto)
            if "cadastro" not in dados: dados["cadastro"] = {"nome": nome_aluno, "turma": turma_aluno, "status": "Em acompanhamento"}
            if "responsavel" not in dados["cadastro"]: dados["cadastro"]["responsavel"] = ""
            if "telefone" not in dados["cadastro"]: dados["cadastro"]["telefone"] = ""
            if "email" not in dados["cadastro"]: dados["cadastro"]["email"] = ""
            if "endereco" not in dados["cadastro"]: dados["cadastro"]["endereco"] = ""
            if "frequencia" not in dados: dados["frequencia"] = [] 
        else:
            dados = {"cadastro": {"nome": nome_aluno, "turma": turma_aluno, "status": "Em acompanhamento", "responsavel": "", "telefone": "", "email": "", "endereco": ""}, "acoes": [], "frequencia": []}

        def salvar_dados_nuvem(dados_atualizados):
            dados_str = json.dumps(dados_atualizados, ensure_ascii=False)
            if linha_aluno != -1:
                planilha.update_cell(linha_aluno, 2, dados_str)
            else:
                planilha.append_row([str(ra), dados_str])

        st.markdown("---")
        col_i1, col_i2, col_i3 = st.columns(3)
        col_i1.metric("Nome do Estudante", dados["cadastro"]["nome"])
        col_i2.metric("Turma", dados["cadastro"]["turma"])
        
        status_atual = dados["cadastro"].get("status", "Em acompanhamento")
        if status_atual == "Em acompanhamento": col_i3.success(f"Status: {status_atual}")
        else: col_i3.error(f"Status: {status_atual}")
        st.markdown("---")

        with st.expander("📞 Dados de Contato e Responsável", expanded=True):
            with st.form("form_dados_cadastrais"):
                col_cad1, col_cad2 = st.columns(2)
                responsavel_input = col_cad1.text_input("Nome do Responsável Legal:", value=dados["cadastro"].get("responsavel", ""))
                telefone_input = col_cad2.text_input("Telefone / WhatsApp (Com DDD):", value=dados["cadastro"].get("telefone", ""))
                email_input = col_cad1.text_input("E-mail do Responsável:", value=dados["cadastro"].get("email", ""))
                endereco_input = col_cad2.text_input("Endereço Completo:", value=dados["cadastro"].get("endereco", ""))
                
                if st.form_submit_button("💾 Salvar/Atualizar Dados Cadastrais"):
                    dados["cadastro"]["responsavel"] = responsavel_input
                    dados["cadastro"]["telefone"] = telefone_input
                    dados["cadastro"]["email"] = email_input
                    dados["cadastro"]["endereco"] = endereco_input
                    salvar_dados_nuvem(dados)
                    st.success("Dados de contato atualizados na nuvem com sucesso!")
                    st.rerun()

            st.markdown("**Ações Rápidas de Comunicação:**")
            col_b1, col_b2 = st.columns(2)
            freq_str = f"{frequencia_atual*100:.1f}%" if frequencia_atual is not None else "nível crítico (abaixo de 76%)"
            
            num_zap = ''.join(filter(str.isdigit, dados["cadastro"].get("telefone", "")))
            if num_zap:
                texto_zap = f"⚠️ *Notificação Escolar - EE Dr. Américo Brasiliense*\n\nOlá! Entramos em contato porque a frequência escolar do(a) estudante *{dados['cadastro']['nome']}* encontra-se em *{freq_str}*.\n\nEsse índice representa um alto risco de *reprovação por faltas*.\n\nPedimos que responda esta mensagem enviando uma justificativa (como atestado médico) ou compareça à escola urgentemente. Caso não haja retorno, o próximo passo do protocolo obrigatório da SEDUC será a emissão de *Notificação Formal e acionamento do Conselho Tutelar*.\n\nAguardamos retorno imediato."
                msg_zap = urllib.parse.quote(texto_zap)
                link_zap = f"https://wa.me/55{num_zap}?text={msg_zap}"
                col_b1.link_button("📲 Chamar no WhatsApp", link_zap)
            else:
                col_b1.button("📲 Chamar no WhatsApp (Insira e salve o telefone acima primeiro)", disabled=True)
                
            email_resp = dados["cadastro"].get("email", "")
            if email_resp and "@" in email_resp:
                assunto = urllib.parse.quote("⚠️ URGENTE: Frequência Escolar e Risco de Retenção - EE Dr. Américo Brasiliense")
                texto_email = f"Prezado(a) responsável,\n\nEntramos em contato em nome da equipe gestora da EE Dr. Américo Brasiliense para tratar de um assunto de extrema importância: a frequência escolar do(a) estudante {dados['cadastro']['nome']}.\n\nAtualmente, a presença do(a) aluno(a) encontra-se em {freq_str}. Alertamos que esse percentual está muito abaixo do exigido por lei, colocando o(a) estudante em grave risco de retenção (reprovação) por faltas e defasagem na aprendizagem.\n\nSolicitamos que o(a) senhor(a) entre em contato com a escola com urgência para apresentar uma justificativa legal (como atestado médico) para as ausências.\n\nRessaltamos que a assiduidade escolar é obrigatória. Caso não tenhamos retorno e a infrequência persista, daremos andamento ao protocolo oficial de Busca Ativa da SEDUC, que tem como próximo passo a emissão de Notificação Formal impressa e o subsequente acionamento da rede de proteção (Conselho Tutelar).\n\nAtenciosamente,\nEquipe Gestora - EE Dr. Américo Brasiliense"
                corpo = urllib.parse.quote(texto_email)
                link_email = f"mailto:{email_resp}?subject={assunto}&body={corpo}"
                col_b2.link_button("📧 Enviar E-mail", link_email)
            else:
                col_b2.button("📧 Enviar E-mail (Insira e salve um e-mail válido acima primeiro)", disabled=True)

        st.markdown("### 📈 Acompanhamento de Frequência Individual")
        if frequencia_atual is not None:
            col_f1, col_f2 = st.columns([0.7, 0.3])
            col_f1.info(f"O BI atual aponta que a frequência deste aluno é de **{frequencia_atual*100:.1f}%**.")
            if col_f2.button("Gravar Frequência Atual do BI"):
                dados["frequencia"].append({"data": datetime.now().strftime("%d/%m/%Y"), "valor": frequencia_atual})
                salvar_dados_nuvem(dados)
                st.success("Frequência salva no histórico do aluno!")
                st.rerun()

        if len(dados["frequencia"]) > 0:
            df_freq = pd.DataFrame(dados["frequencia"])
            fig_f, ax_f = plt.subplots(figsize=(10, 3))
            ax_f.plot(df_freq["data"], df_freq["valor"] * 100, marker='o', color='#10B981', linewidth=2)
            ax_f.axhline(76, color='red', linestyle='--', label='Meta SEDUC (76%)')
            ax_f.set_title("Evolução da Presença do Aluno (%)", fontweight='bold')
            ax_f.set_ylabel("Presença (%)")
            ax_f.set_ylim(0, 105)
            ax_f.spines['top'].set_visible(False)
            ax_f.spines['right'].set_visible(False)
            ax_f.yaxis.grid(True, linestyle='--', alpha=0.3)
            ax_f.legend()
            st.pyplot(fig_f)
            fig_f.savefig(f"grafico_freq_{ra}.png", dpi=300)
            plt.close(fig_f)

        st.markdown("---")

        if status_atual == "Em acompanhamento":
            with st.form("reg_acao"):
                st.subheader("Registrar Nova Intervenção")
                acao = st.selectbox(
                    "Qual ação foi executada?", 
                    ["Contato telefônico", "Contato via WhatsApp", "1ª Notificação Formal (Ciência)", "2ª Notificação Formal", "Reunião Presencial com Responsáveis", "Visita Domiciliar", "Acionamento do Conselho Tutelar"]
                )
                relato = st.text_area("Descreva o que foi acordado / Justificativa:")
                
                if st.form_submit_button("Salvar no Prontuário"):
                    dados["acoes"].append({"data": datetime.now().strftime("%d/%m/%Y %H:%M"), "acao": acao, "relato": relato})
                    salvar_dados_nuvem(dados)
                    st.success("Ação salva na nuvem com sucesso!")
                    st.rerun()
            
            with st.expander("⚠️ Encerrar Acompanhamento (Excluir da Busca Ativa)"):
                st.warning("Ao confirmar, o prontuário deste aluno será encerrado e bloqueado para novas ações.")
                motivo = st.selectbox("Qual o motivo do encerramento?", ["Transferência", "Abandono (Esgotadas todas as vias da escola)", "Frequência Regularizada (Aluno Recuperado)"])
                if st.button("Confirmar Encerramento Definitivo"):
                    dados["cadastro"]["status"] = motivo
                    dados["acoes"].append({"data": datetime.now().strftime("%d/%m/%Y %H:%M"), "acao": f"ENCERRAMENTO DE CASO: {motivo}", "relato": "Estudante retirado do painel ativo de Busca Ativa."})
                    salvar_dados_nuvem(dados)
                    st.success("Prontuário encerrado com sucesso!")
                    st.rerun()
        else:
            st.info(f"🔒 Este prontuário encontra-se FECHADO pelo motivo: {status_atual}.")

        if dados["acoes"]:
            st.markdown("### Histórico de Intervenções e Relatos")
            st.table(pd.DataFrame(dados["acoes"]))
            
            col_bpdf1, col_bpdf2 = st.columns(2)
            if col_bpdf1.button("Gerar PDF de Resumo do Prontuário"):
                pdf_al = FPDF()
                pdf_al.add_page()
                pdf_al.set_font("Arial", "B", 14); pdf_al.cell(0, 10, "RESUMO DE PRONTUARIO - BUSCA ATIVA", 0, 1, "C"); pdf_al.ln(5)
                pdf_al.set_font("Arial", "B", 11)
                pdf_al.cell(0, 8, f"Estudante: {dados['cadastro']['nome']} (RA: {ra})", 0, 1)
                pdf_al.cell(0, 8, f"Turma: {dados['cadastro']['turma']}", 0, 1)
                pdf_al.cell(0, 8, f"Responsavel: {dados['cadastro'].get('responsavel', 'Nao informado')}", 0, 1)
                pdf_al.cell(0, 8, f"Telefone: {dados['cadastro'].get('telefone', 'Nao informado')}", 0, 1)
                pdf_al.set_font("Arial", "", 11); pdf_al.multi_cell(0, 6, f"Endereco: {dados['cadastro'].get('endereco', 'Nao informado')}"); pdf_al.ln(2)
                pdf_al.set_font("Arial", "B", 11); pdf_al.cell(0, 8, f"Situacao Final: {status_atual.upper()}", 0, 1)
                pdf_al.line(10, pdf_al.get_y(), 200, pdf_al.get_y()); pdf_al.ln(5)

                if os.path.exists(f"grafico_freq_{ra}.png"):
                    pdf_al.cell(0, 8, "Evolucao da Frequencia do Aluno:", 0, 1)
                    pdf_al.image(f"grafico_freq_{ra}.png", x=10, w=190); pdf_al.ln(5)
                    os.remove(f"grafico_freq_{ra}.png")
                
                pdf_al.set_font("Arial", "B", 12); pdf_al.cell(0, 8, "Historico de Intervencoes Escolares:", 0, 1); pdf_al.ln(2)
                pdf_al.set_font("Arial", "", 10)
                for a in dados["acoes"]:
                    pdf_al.set_font("Arial", "B", 10); pdf_al.cell(0, 7, f"Data: {a['data']} | Acao: {a['acao']}", 0, 1)
                    pdf_al.set_font("Arial", "", 10); pdf_al.multi_cell(0, 6, f"Relato: {a['relato']}"); pdf_al.ln(4)
                
                out_al = pdf_al.output(dest="S").encode("latin1", "ignore")
                col_bpdf1.download_button("Baixar Resumo em PDF", data=out_al, file_name=f"Resumo_BA_{ra}.pdf")

            if col_bpdf2.button("✉️ Gerar Carta de Convocação Física"):
                pdf_carta = FPDF()
                pdf_carta.add_page()
                pdf_carta.set_font("Arial", "B", 14)
                pdf_carta.cell(0, 10, "GOVERNO DO ESTADO DE SAO PAULO - SECRETARIA DA EDUCACAO", 0, 1, "C")
                pdf_carta.cell(0, 10, "EE DR. AMERICO BRASILIENSE", 0, 1, "C")
                pdf_carta.ln(10)
                pdf_carta.set_font("Arial", "B", 16)
                pdf_carta.cell(0, 10, "NOTIFICACAO DE COMPARECIMENTO - BUSCA ATIVA", 0, 1, "C")
                pdf_carta.ln(10)
                pdf_carta.set_font("Arial", "", 12)
                texto_carta = f"Prezado(a) Responsavel legal ({dados['cadastro'].get('responsavel', '________________________')}),\n\nConvocamos o(a) senhor(a) a comparecer, com urgencia, a EE Dr. Americo Brasiliense para tratarmos de assuntos relacionados a vida escolar e a baixa frequencia do(a) estudante {dados['cadastro']['nome']}, matriculado(a) na turma {dados['cadastro']['turma']} (RA: {ra}).\n\nLembramos que, conforme a Lei Estadual 13.068/2008 e a Resolucao SEDUC 39/2023, a frequencia escolar regular e um direito do estudante e dever dos responsaveis.\n\nO nao comparecimento acarretara nas devidas providencias legais junto ao Conselho Tutelar e a rede de protecao.\n\nSanto Andre, {datetime.now().strftime('%d/%m/%Y')}."
                pdf_carta.multi_cell(0, 8, texto_carta)
                pdf_carta.ln(20)
                pdf_carta.cell(0, 8, "___________________________________________________", 0, 1, "C")
                pdf_carta.cell(0, 8, "Assinatura da Direcao / Coordenacao", 0, 1, "C")
                pdf_carta.ln(10)
                pdf_carta.cell(0, 8, "Ciente do Responsavel: ___________________________________  Data: ___/___/___", 0, 1, "C")
                
                out_carta = pdf_carta.output(dest="S").encode("latin1", "ignore")
                col_bpdf2.download_button("📥 Baixar Carta em PDF", data=out_carta, file_name=f"Carta_Convocacao_{ra}.pdf")

# ============================================================
# MOMENTO 3 — PAINEL DE LEMBRETES E DISPARO
# ============================================================
elif menu == "Painel de Lembretes e Disparo":
    st.header("🚨 Central de Ações e Disparos")

    lembretes = []
    todas_linhas = planilha.get_all_values()
    alunos_ativos = []
    
    for i, linha in enumerate(todas_linhas):
        if i > 0 and len(linha) > 1 and str(linha[0]) != "HISTORICO_SISTEMA":
            dados_aluno = json.loads(linha[1])
            
            if dados_aluno.get("cadastro", {}).get("status") == "Em acompanhamento":
                tel_bruto = dados_aluno["cadastro"].get("telefone", "")
                num_zap = ''.join(filter(str.isdigit, tel_bruto))
                
                dias_passados = 0
                acoes = dados_aluno.get("acoes", [])
                
                if acoes:
                    primeira_acao_data = acoes[0]["data"][:10]
                    ultima_acao = acoes[-1]
                    data_ultima_str = ultima_acao["data"][:10]
                    try:
                        data_ultima_obj = datetime.strptime(data_ultima_str, "%d/%m/%Y")
                        dias_passados = (datetime.now() - data_ultima_obj).days
                        if dias_passados >= 5:
                            lembretes.append({
                                "RA": str(linha[0]),
                                "Nome": dados_aluno["cadastro"]["nome"],
                                "Turma": dados_aluno["cadastro"]["turma"],
                                "Dias sem contato": dias_passados,
                                "Primeiro Contato": primeira_acao_data,
                                "Última Ação Realizada": ultima_acao["acao"]
                            })
                    except:
                        pass
                
                alunos_ativos.append({
                    "RA": str(linha[0]),
                    "Nome": dados_aluno["cadastro"]["nome"],
                    "Turma": dados_aluno["cadastro"]["turma"],
                    "Zap": num_zap,
                    "Dias": dias_passados
                })

    tab1, tab2 = st.tabs(["📲 Disparo em Massa (WhatsApp)", "⚠️ Casos Parados"])

    with tab1:
        st.subheader("Disparo Rápido para Alunos em Acompanhamento")
        st.write("Envie mensagens individuais com apenas um clique para todos os alunos monitorados.")
        
        msg_padrao = st.text_area(
            "Mensagem Padrão para Disparo:", 
            value="⚠️ *Notificação Escolar - EE Dr. Américo Brasiliense*\n\nPrezado responsável, notamos a ausência recorrente do(a) estudante. Solicitamos o comparecimento urgente na escola ou o envio de atestado médico. A assiduidade escolar é obrigatória, evite o acionamento da rede de proteção (Conselho Tutelar)."
        )
        
        if not alunos_ativos:
            st.info("Nenhum aluno em acompanhamento na nuvem no momento.")
        else:
            st.write(f"**Total na lista de disparo:** {len(alunos_ativos)} alunos")
            for al in alunos_ativos:
                c1, c2, c3 = st.columns([3, 1, 1])
                c1.write(f"**{al['Nome']}** ({al['Turma']})")
                
                if al['Zap']:
                    c2.write(f"📱 {al['Zap']}")
                    msg_url = urllib.parse.quote(msg_padrao)
                    link = f"https://wa.me/55{al['Zap']}?text={msg_url}"
                    c3.link_button("📤 Enviar Msg", link)
                else:
                    c2.write("❌ Sem número")
                    c3.button("📤 Enviar Msg", disabled=True, key=f"d_{al['RA']}")
                st.divider()

    with tab2:
        st.write("Abaixo estão listados os estudantes que estão na Busca Ativa e **não recebem nenhum contato ou intervenção há mais de 5 dias**.")
        if lembretes:
            df_lembretes = pd.DataFrame(lembretes)
            df_lembretes = df_lembretes.sort_values(by="Dias sem contato", ascending=False).reset_index(drop=True)
            st.error(f"⚠️ Atenção! Você tem **{len(lembretes)}** casos parados precisando de intervenção urgente.")
            st.dataframe(df_lembretes, use_container_width=True)
        else:
            st.success("🎉 Todos os alunos estão sendo acompanhados regularmente!")
