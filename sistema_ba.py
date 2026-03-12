import streamlit as st
import pandas as pd
import os
import json
import matplotlib.pyplot as plt
from datetime import datetime
from fpdf import FPDF
import re
import io
import urllib.parse # NOVA IMPORTAÇÃO PARA O WHATSAPP E EMAIL

# ============================================================
# CONFIGURAÇÃO DE PASTAS E PÁGINA
# ============================================================
PASTA_RAIZ = "SISTEMA_BUSCA_ATIVA"
PASTA_FICHAS = os.path.join(PASTA_RAIZ, "FICHAS_ALUNOS")

os.makedirs(PASTA_RAIZ, exist_ok=True)
os.makedirs(PASTA_FICHAS, exist_ok=True)

st.set_page_config(page_title="Busca Ativa Escolar", layout="wide")

# ============================================================
# SESSION STATE (Persistência de Dados)
# ============================================================
if "dados_escola" not in st.session_state:
    st.session_state.dados_escola = None
if "criticos" not in st.session_state:
    st.session_state.criticos = None
if "turma_selecionada" not in st.session_state:
    st.session_state.turma_selecionada = None
if "ra_selecionado" not in st.session_state:
    st.session_state.ra_selecionado = ""

# ============================================================
# CABEÇALHO E MENU (COM A NOVA ABA)
# ============================================================
st.title("Sistema de Busca Ativa")
st.subheader("EE Dr. Américo Brasiliense")

menu = st.sidebar.radio(
    "Menu",
    ["Diagnóstico Geral", "Prontuário do Aluno", "Lembretes e Agenda"] # NOVA ABA ADICIONADA AQUI
)

if st.sidebar.button("Deslogar / Reiniciar"):
    st.session_state.clear()
    st.rerun()

# ============================================================
# MOMENTO 1 — DIAGNÓSTICO
# ============================================================
if menu == "Diagnóstico Geral":

    st.header("Diagnóstico de Frequência Escolar")

    arquivos = st.file_uploader(
        "Carregar planilhas do BI",
        type=["xlsx"],
        accept_multiple_files=True
    )

    if arquivos:
        lista = []
        for arq in arquivos:
            df = pd.read_excel(arq)
            df.columns = [str(c).strip() for c in df.columns]

            # Padronização das colunas do BI
            df.rename(columns={
                "Aluno(a)": "Nome",
                "(%) Presença Anual na Turma Atual": "Presenca_Anual",
                "(%) Presença na Semana Atual": "Presenca_Semana",
                "(%) Presença na Semana Anterior": "Presenca_Semana_Anterior"
            }, inplace=True)

            turma_original = arq.name.replace(".xlsx", "")
            
            # Limpeza inteligente do nome da turma (remove só os códigos SEDUC gigantes no final)
            turma_limpa = re.sub(r'\s*-\s*\d{5,}.*$', '', turma_original).strip()
            df["Turma"] = turma_limpa

            # Limpeza do RA (remove o .0 do final se o Excel converter para float)
            if "RA" in df.columns:
                df["RA"] = df["RA"].astype(str).str.replace(r'\.0$', '', regex=True)

            lista.append(df)

        escola = pd.concat(lista, ignore_index=True)

        # Garante que a coluna seja numérica para aplicar o filtro
        escola["Presenca_Anual"] = pd.to_numeric(escola["Presenca_Anual"], errors="coerce")

        criticos = escola[escola["Presenca_Anual"] < 0.76].copy()

        st.session_state.dados_escola = escola
        st.session_state.criticos = criticos

    # ============================================================
    # MOSTRAR DADOS E GRÁFICOS
    # ============================================================
    if st.session_state.dados_escola is not None:
        escola = st.session_state.dados_escola
        criticos = st.session_state.criticos

        col1, col2 = st.columns(2)
        col1.metric("Total de alunos matriculados", len(escola))
        col2.metric("Alunos em zona crítica (< 76%)", len(criticos))

        # ------------------------------------------------
        # GRÁFICO POR TURMA (DESIGN PROFISSIONAL APENAS PARA A TELA)
        # ------------------------------------------------
        st.subheader("Concentração de Faltas por Turma")
        resumo = criticos["Turma"].value_counts()
        
        fig, ax = plt.subplots(figsize=(12, 6))
        
        # Cria as barras com azul moderno
        bars = ax.bar(resumo.index, resumo.values, color="#3B82F6", edgecolor="#2563EB", linewidth=1.2, alpha=0.8)
        
        # Estética avançada (Removendo bordas e adicionando grade)
        ax.spines['top'].set_visible(False)
        ax.spines['right'].set_visible(False)
        ax.spines['left'].set_visible(False)
        ax.yaxis.grid(True, linestyle='--', alpha=0.4)
        
        # Rótulos no eixo X angulados
        plt.xticks(rotation=45, ha='right', fontsize=9, color="#374151")
        ax.set_ylabel("Quantidade de Alunos", fontsize=10, fontweight='bold', color="#4B5563")
        
        # Números em cima das barras
        ax.bar_label(bars, padding=3, fontsize=10, fontweight='bold', color="#1E3A8A")
        
        plt.tight_layout()
        st.pyplot(fig)

        # ------------------------------------------------
        # CASCATA POR TURMA
        # ------------------------------------------------
        st.subheader("Selecionar Turma para Ação")
        turmas = sorted(criticos["Turma"].unique())
        
        # Organiza os botões em 4 colunas
        cols_turma = st.columns(4)
        for i, t in enumerate(turmas):
            qtd = len(criticos[criticos["Turma"] == t])
            if cols_turma[i % 4].button(f"{t} ({qtd} alunos)", key=f"btn_{t}"):
                st.session_state.turma_selecionada = t

        # ------------------------------------------------
        # MOSTRAR ALUNOS DA TURMA
        # ------------------------------------------------
        if st.session_state.turma_selecionada:
            turma_sel = st.session_state.turma_selecionada
            st.subheader(f"Lista da Turma: {turma_sel}")

            alunos_turma = criticos[criticos["Turma"] == turma_sel]

            for _, row in alunos_turma.iterrows():
                c1, c2 = st.columns([4, 1])
                c1.write(f"**{row['Nome']}** (RA: {row['RA']} | Presença Anual: {row['Presenca_Anual']:.2%})")
                
                if c2.button("Abrir prontuário", key=f"ficha_{row['RA']}"):
                    st.session_state.ra_selecionado = row["RA"]
                    st.success("Aluno selecionado! Acesse a aba 'Prontuário do Aluno' no menu ao lado.")

        # ------------------------------------------------
        # EXCEL NOMINAL BONITO
        # ------------------------------------------------
        st.markdown("---")
        st.subheader("📥 Exportação de Dados")
        
        output = io.BytesIO()
        with pd.ExcelWriter(output, engine='xlsxwriter') as writer:
            # Seleciona as colunas mais importantes para o Excel
            colunas_excel = ['Turma', 'RA', 'Nome', 'Presenca_Anual']
            df_excel = criticos[colunas_excel].copy() if set(colunas_excel).issubset(criticos.columns) else criticos
            
            df_excel.to_excel(writer, index=False, sheet_name='Busca Ativa')
            workbook = writer.book
            worksheet = writer.sheets['Busca Ativa']
            
            # Ocultar linhas de grade
            worksheet.hide_gridlines(2)
            
            # Formatos de Design
            formato_cabecalho = workbook.add_format({
                'bold': True, 'font_color': 'white', 'bg_color': '#1E3A8A',
                'border': 1, 'align': 'center', 'valign': 'vcenter'
            })
            formato_celula = workbook.add_format({'border': 1, 'valign': 'vcenter'})
            
            # Aplica os formatos nas colunas
            for col_num, value in enumerate(df_excel.columns.values):
                worksheet.write(0, col_num, value, formato_cabecalho)
                # Ajusta a largura das colunas
                if value == "Nome":
                    worksheet.set_column(col_num, col_num, 40, formato_celula)
                elif value == "Turma":
                    worksheet.set_column(col_num, col_num, 30, formato_celula)
                else:
                    worksheet.set_column(col_num, col_num, 15, formato_celula)

        excel_data = output.getvalue()
        
        st.download_button(
            label="📄 Baixar Planilha Nominal (Excel Formatado)",
            data=excel_data,
            file_name=f"Lista_Busca_Ativa_{datetime.now().strftime('%d-%m-%Y')}.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        )
        st.markdown("---")

        # ------------------------------------------------
        # RELATÓRIO PDF SEDUC OFICIAL (AGORA SEM O GRÁFICO DE BARRAS)
        # ------------------------------------------------
        if st.button("Gerar Relatório PDF SEDUC"):
            hoje = datetime.now().strftime("%d/%m/%Y")
            resumo = criticos["Turma"].value_counts()

            # Lógica de Histórico Quinzenal
            hist_file = "historico_quinzenal.csv"
            data_reg = datetime.now().strftime("%Y-%m-%d")
            total_b = len(criticos)
            
            if os.path.exists(hist_file):
                hist = pd.read_csv(hist_file)
                if data_reg not in hist['data'].values:
                    novo = pd.DataFrame({"data": [data_reg], "busca_ativa": [total_b]})
                    hist = pd.concat([hist, novo])
            else:
                hist = pd.DataFrame({"data": [data_reg], "busca_ativa": [total_b]})
            
            hist.to_csv(hist_file, index=False)

            # Gráfico de Evolução (Unico grafico mantido no PDF)
            fig_evol, ax_evol = plt.subplots(figsize=(8, 4))
            ax_evol.plot(hist["data"], hist["busca_ativa"], marker="o", color="red", linewidth=2)
            ax_evol.set_title("Evolucao Quinzenal de Casos Criticos")
            plt.xticks(rotation=45)
            plt.tight_layout()
            plt.savefig("evolucao.png")
            plt.close(fig_evol)

            # Geração do PDF
            pdf = FPDF()
            pdf.add_page()
            
            # Título
            pdf.set_font("Arial", "B", 14)
            pdf.cell(0, 10, "RELATORIO DE DIAGNOSTICO DE FREQUENCIA ESCOLAR", 0, 1, "C")
            pdf.ln(5)
            
            # Cabeçalho da Escola
            pdf.set_font("Arial", "", 10)
            cabecalho = "Diretoria de Ensino: SANTO ANDRE\nCIE: 8266\nEndereco: PRACA QUARTO CENTENARIO, 7 - CENTRO\nMunicipio: SANTO ANDRE - SP\nTelefone: (11) 4432-2021\nE-mail: E008266A@EDUCACAO.SP.GOV.BR"
            pdf.multi_cell(0, 6, cabecalho)
            pdf.line(10, pdf.get_y()+2, 200, pdf.get_y()+2)
            pdf.ln(5)
            
            # Dados Principais
            pdf.set_font("Arial", "B", 11)
            pdf.cell(0, 6, f"Data do relatorio: {hoje}", 0, 1)
            pdf.set_font("Arial", "", 10)
            pdf.cell(0, 6, f"Total de alunos matriculados analisados: {len(escola)}", 0, 1)
            pdf.cell(0, 6, f"Total de alunos em zona de risco (< 76%): {len(criticos)}", 0, 1)
            
            # Tabela de Turmas
            pdf.ln(8)
            pdf.set_font("Arial", "B", 11)
            pdf.cell(0, 8, "Distribuicao por Turma", 0, 1)
            pdf.set_font("Arial", "B", 10)
            pdf.cell(140, 8, "Turma", 1)
            pdf.cell(40, 8, "Qtd", 1, 1)
            
            pdf.set_font("Arial", "", 10)
            for t, q in resumo.items():
                pdf.cell(140, 8, str(t), 1)
                pdf.cell(40, 8, str(q), 1, 1)

            # Nova página para o Gráfico de Evolução (Centralizado e Bonito)
            pdf.add_page()
            pdf.set_font("Arial", "B", 12)
            pdf.cell(0, 8, "Acompanhamento e Grafico de Evolucao", 0, 1, "C")
            pdf.ln(5)
            pdf.image("evolucao.png", x=15, y=25, w=170)

            # Nova página para a Análise Diagnóstica
            pdf.add_page()
            pdf.set_font("Arial", "B", 12)
            pdf.cell(0, 8, "Analise Diagnostica e Medidas Preventivas", 0, 1)
            pdf.set_font("Arial", "", 11)
            texto_analise = f"A analise dos registros do BI indica que {len(criticos)} estudantes apresentam frequencia inferior a 76%. Esse indicador representa risco eminente de evasao e retencao, sendo objeto de monitoramento sistematico pela equipe gestora da unidade. As estrategias de contencao envolvem o acionamento do protocolo de Busca Ativa SEDUC, com contato aos responsaveis, averiguacao de vulnerabilidades e, esgotadas as vias escolares, acionamento da rede de protecao (Conselho Tutelar)."
            pdf.multi_cell(0, 7, texto_analise)
            
            pdf_out = pdf.output(dest="S").encode("latin1", "ignore")
            
            st.download_button(
                "Baixar Relatório Oficial",
                data=pdf_out,
                file_name=f"Relatorio_SEDUC_{hoje.replace('/','-')}.pdf"
            )
            
            # Limpa as imagens geradas do computador
            if os.path.exists("evolucao.png"): os.remove("evolucao.png")

# ============================================================
# MOMENTO 2 — PRONTUÁRIO INDIVIDUAL
# ============================================================
elif menu == "Prontuário do Aluno":
    st.header("Prontuário Individual de Acompanhamento")
    
    ra = st.text_input("RA do aluno (Apenas números)", value=st.session_state.ra_selecionado)
    
    if ra:
        caminho = os.path.join(PASTA_FICHAS, f"{ra}.json")
        
        nome_aluno = "Estudante não identificado na planilha atual"
        turma_aluno = "Não informada"
        frequencia_atual = None
        
        if st.session_state.dados_escola is not None:
            busca_aluno = st.session_state.dados_escola[st.session_state.dados_escola["RA"] == ra]
            if not busca_aluno.empty:
                nome_aluno = busca_aluno.iloc[0]["Nome"]
                # Aplica a mesma limpeza do nome da turma aqui
                turma_aluno = str(busca_aluno.iloc[0]["Turma"]).split('-')[0].strip()
                frequencia_atual = busca_aluno.iloc[0]["Presenca_Anual"]

        # Carrega o histórico salvo
        if os.path.exists(caminho):
            dados = json.load(open(caminho, "r", encoding="utf8"))
            if "cadastro" not in dados:
                dados["cadastro"] = {"nome": nome_aluno, "turma": turma_aluno, "status": "Em acompanhamento"}
            if "responsavel" not in dados["cadastro"]: dados["cadastro"]["responsavel"] = ""
            if "telefone" not in dados["cadastro"]: dados["cadastro"]["telefone"] = ""
            if "email" not in dados["cadastro"]: dados["cadastro"]["email"] = "" # NOVO CAMPO EMAIL ADICIONADO AQUI
            if "endereco" not in dados["cadastro"]: dados["cadastro"]["endereco"] = ""
            if "frequencia" not in dados: dados["frequencia"] = [] 
        else:
            dados = {
                "cadastro": {
                    "nome": nome_aluno, 
                    "turma": turma_aluno, 
                    "status": "Em acompanhamento",
                    "responsavel": "",
                    "telefone": "",
                    "email": "", # NOVO CAMPO EMAIL ADICIONADO AQUI
                    "endereco": ""
                }, 
                "acoes": [],
                "frequencia": []
            }

        # ------------------------------------------------
        # PAINEL DE INFORMAÇÕES DO ALUNO
        # ------------------------------------------------
        st.markdown("---")
        col_i1, col_i2, col_i3 = st.columns(3)
        col_i1.metric("Nome do Estudante", dados["cadastro"]["nome"])
        col_i2.metric("Turma", dados["cadastro"]["turma"])
        
        status_atual = dados["cadastro"].get("status", "Em acompanhamento")
        if status_atual == "Em acompanhamento":
            col_i3.success(f"Status: {status_atual}")
        else:
            col_i3.error(f"Status: {status_atual}")
        st.markdown("---")

        # ------------------------------------------------
        # DADOS CADASTRAIS E BOTÕES RÁPIDOS DE CONTATO
        # ------------------------------------------------
        with st.expander("📞 Dados de Contato e Responsável", expanded=True):
            with st.form("form_dados_cadastrais"):
                col_cad1, col_cad2 = st.columns(2)
                responsavel_input = col_cad1.text_input("Nome do Responsável Legal:", value=dados["cadastro"].get("responsavel", ""))
                telefone_input = col_cad2.text_input("Telefone / WhatsApp (Com DDD):", value=dados["cadastro"].get("telefone", ""))
                email_input = col_cad1.text_input("E-mail do Responsável:", value=dados["cadastro"].get("email", "")) # CAMPO EMAIL
                endereco_input = col_cad2.text_input("Endereço Completo:", value=dados["cadastro"].get("endereco", ""))
                
                if st.form_submit_button("💾 Salvar/Atualizar Dados Cadastrais"):
                    dados["cadastro"]["responsavel"] = responsavel_input
                    dados["cadastro"]["telefone"] = telefone_input
                    dados["cadastro"]["email"] = email_input # SALVA O EMAIL
                    dados["cadastro"]["endereco"] = endereco_input
                    json.dump(dados, open(caminho, "w", encoding="utf8"), indent=4)
                    st.success("Dados de contato atualizados e salvos com sucesso!")
                    st.rerun()

            # BOTÕES DE AÇÃO RÁPIDA (ZAP E EMAIL) - TEXTOS ATUALIZADOS AQUI
            st.markdown("**Ações Rápidas de Comunicação:**")
            col_b1, col_b2 = st.columns(2)
            
            # Preparar o texto da frequência dinamicamente
            if frequencia_atual is not None:
                freq_str = f"{frequencia_atual*100:.1f}%"
            else:
                freq_str = "nível crítico (abaixo de 76%)"
            
            # Botão WhatsApp
            num_zap = ''.join(filter(str.isdigit, dados["cadastro"].get("telefone", "")))
            if num_zap:
                texto_zap = f"⚠️ *Notificação Escolar - EE Dr. Américo Brasiliense*\n\nOlá! Entramos em contato porque a frequência escolar do(a) estudante *{dados['cadastro']['nome']}* encontra-se em *{freq_str}*.\n\nEsse índice representa um alto risco de *reprovação por faltas*.\n\nPedimos que responda esta mensagem enviando uma justificativa (como atestado médico) ou compareça à escola urgentemente. Caso não haja retorno, o próximo passo do protocolo obrigatório da SEDUC será a emissão de *Notificação Formal e acionamento do Conselho Tutelar*.\n\nAguardamos retorno imediato."
                msg_zap = urllib.parse.quote(texto_zap)
                link_zap = f"https://wa.me/55{num_zap}?text={msg_zap}"
                col_b1.link_button("📲 Chamar no WhatsApp", link_zap)
            else:
                col_b1.button("📲 Chamar no WhatsApp (Insira e salve o telefone acima primeiro)", disabled=True)
                
            # Botão E-mail
            email_resp = dados["cadastro"].get("email", "")
            if email_resp and "@" in email_resp:
                assunto = urllib.parse.quote("⚠️ URGENTE: Frequência Escolar e Risco de Retenção - EE Dr. Américo Brasiliense")
                texto_email = f"Prezado(a) responsável,\n\nEntramos em contato em nome da equipe gestora da EE Dr. Américo Brasiliense para tratar de um assunto de extrema importância: a frequência escolar do(a) estudante {dados['cadastro']['nome']}.\n\nAtualmente, a presença do(a) aluno(a) encontra-se em {freq_str}. Alertamos que esse percentual está muito abaixo do exigido por lei, colocando o(a) estudante em grave risco de retenção (reprovação) por faltas e defasagem na aprendizagem.\n\nSolicitamos que o(a) senhor(a) entre em contato com a escola com urgência para apresentar uma justificativa legal (como atestado médico) para as ausências.\n\nRessaltamos que a assiduidade escolar é obrigatória. Caso não tenhamos retorno e a infrequência persista, daremos andamento ao protocolo oficial de Busca Ativa da SEDUC, que tem como próximo passo a emissão de Notificação Formal impressa e o subsequente acionamento da rede de proteção (Conselho Tutelar).\n\nAtenciosamente,\nEquipe Gestora - EE Dr. Américo Brasiliense"
                corpo = urllib.parse.quote(texto_email)
                link_email = f"mailto:{email_resp}?subject={assunto}&body={corpo}"
                col_b2.link_button("📧 Enviar E-mail", link_email)
            else:
                col_b2.button("📧 Enviar E-mail (Insira e salve um e-mail válido acima primeiro)", disabled=True)

        # ------------------------------------------------
        # HISTÓRICO DE FREQUÊNCIA DO ALUNO
        # ------------------------------------------------
        st.markdown("### 📈 Acompanhamento de Frequência Individual")
        
        if frequencia_atual is not None:
            col_f1, col_f2 = st.columns([0.7, 0.3])
            col_f1.info(f"O BI atual aponta que a frequência deste aluno é de **{frequencia_atual*100:.1f}%**.")
            if col_f2.button("Gravar Frequência Atual do BI"):
                dados["frequencia"].append({
                    "data": datetime.now().strftime("%d/%m/%Y"), 
                    "valor": frequencia_atual
                })
                json.dump(dados, open(caminho, "w", encoding="utf8"), indent=4)
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

        # ------------------------------------------------
        # ÁREA DE REGISTRO DE AÇÕES E ENCERRAMENTO
        # ------------------------------------------------
        if status_atual == "Em acompanhamento":
            with st.form("reg_acao"):
                st.subheader("Registrar Nova Intervenção")
                acao = st.selectbox(
                    "Qual ação foi executada?", 
                    [
                        "Contato telefônico", 
                        "Contato via WhatsApp", 
                        "1ª Notificação Formal (Ciência)", 
                        "2ª Notificação Formal", 
                        "Reunião Presencial com Responsáveis", 
                        "Visita Domiciliar", 
                        "Acionamento do Conselho Tutelar"
                    ]
                )
                relato = st.text_area("Descreva o que foi acordado / Justificativa:")
                
                if st.form_submit_button("Salvar no Prontuário"):
                    dados["acoes"].append({
                        "data": datetime.now().strftime("%d/%m/%Y %H:%M"), 
                        "acao": acao, 
                        "relato": relato
                    })
                    json.dump(dados, open(caminho, "w", encoding="utf8"), indent=4)
                    st.success("Ação salva com sucesso!")
                    st.rerun()
            
            with st.expander("⚠️ Encerrar Acompanhamento (Excluir da Busca Ativa)"):
                st.warning("Ao confirmar, o prontuário deste aluno será encerrado e bloqueado para novas ações.")
                motivo = st.selectbox("Qual o motivo do encerramento?", ["Transferência", "Abandono (Esgotadas todas as vias da escola)", "Frequência Regularizada (Aluno Recuperado)"])
                
                if st.button("Confirmar Encerramento Definitivo"):
                    dados["cadastro"]["status"] = motivo
                    dados["acoes"].append({
                        "data": datetime.now().strftime("%d/%m/%Y %H:%M"),
                        "acao": f"ENCERRAMENTO DE CASO: {motivo}",
                        "relato": "Estudante retirado do painel ativo de Busca Ativa."
                    })
                    json.dump(dados, open(caminho, "w", encoding="utf8"), indent=4)
                    st.success("Prontuário encerrado com sucesso!")
                    st.rerun()
        else:
            st.info(f"🔒 Este prontuário encontra-se FECHADO pelo motivo: {status_atual}.")

        # ------------------------------------------------
        # HISTÓRICO GERAL, PDF RESUMO E CARTA PARA IMPRESSÃO
        # ------------------------------------------------
        if dados["acoes"]:
            st.markdown("### Histórico de Intervenções e Relatos")
            st.table(pd.DataFrame(dados["acoes"]))
            
            col_bpdf1, col_bpdf2 = st.columns(2) # COLUNAS PARA OS DOIS BOTOES DE PDF
            
            if col_bpdf1.button("Gerar PDF de Resumo do Prontuário"):
                pdf_al = FPDF()
                pdf_al.add_page()
                
                # Cabeçalho do Dossiê
                pdf_al.set_font("Arial", "B", 14)
                pdf_al.cell(0, 10, "RESUMO DE PRONTUARIO - BUSCA ATIVA", 0, 1, "C")
                pdf_al.ln(5)
                
                # Dados Principais e de Contato
                pdf_al.set_font("Arial", "B", 11)
                pdf_al.cell(0, 8, f"Estudante: {dados['cadastro']['nome']} (RA: {ra})", 0, 1)
                pdf_al.cell(0, 8, f"Turma: {dados['cadastro']['turma']}", 0, 1)
                pdf_al.cell(0, 8, f"Responsavel: {dados['cadastro'].get('responsavel', 'Nao informado')}", 0, 1)
                pdf_al.cell(0, 8, f"Telefone: {dados['cadastro'].get('telefone', 'Nao informado')}", 0, 1)
                
                pdf_al.set_font("Arial", "", 11)
                pdf_al.multi_cell(0, 6, f"Endereco: {dados['cadastro'].get('endereco', 'Nao informado')}")
                pdf_al.ln(2)
                
                pdf_al.set_font("Arial", "B", 11)
                pdf_al.cell(0, 8, f"Situacao Final: {status_atual.upper()}", 0, 1)
                
                pdf_al.line(10, pdf_al.get_y(), 200, pdf_al.get_y())
                pdf_al.ln(5)

                # Insere o gráfico de frequência no PDF se ele existir
                if os.path.exists(f"grafico_freq_{ra}.png"):
                    pdf_al.cell(0, 8, "Evolucao da Frequencia do Aluno:", 0, 1)
                    pdf_al.image(f"grafico_freq_{ra}.png", x=10, w=190)
                    pdf_al.ln(5)
                    os.remove(f"grafico_freq_{ra}.png") # Limpa a imagem depois de usar
                
                # Histórico de Ações
                pdf_al.set_font("Arial", "B", 12)
                pdf_al.cell(0, 8, "Historico de Intervencoes Escolares:", 0, 1)
                pdf_al.ln(2)
                
                pdf_al.set_font("Arial", "", 10)
                for a in dados["acoes"]:
                    pdf_al.set_font("Arial", "B", 10)
                    pdf_al.cell(0, 7, f"Data: {a['data']} | Acao: {a['acao']}", 0, 1)
                    pdf_al.set_font("Arial", "", 10)
                    pdf_al.multi_cell(0, 6, f"Relato: {a['relato']}")
                    pdf_al.ln(4)
                
                out_al = pdf_al.output(dest="S").encode("latin1", "ignore")
                col_bpdf1.download_button(
                    "Baixar Resumo em PDF", 
                    data=out_al, 
                    file_name=f"Resumo_BA_{ra}.pdf"
                )

            # --- NOVO RECURSO ADICIONADO AQUI: GERADOR DE CARTA DE CONVOCAÇÃO ---
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
                texto_carta = f"Prezado(a) Responsavel legal ({dados['cadastro'].get('responsavel', '________________________')}),\n\n" \
                              f"Convocamos o(a) senhor(a) a comparecer, com urgencia, a EE Dr. Americo Brasiliense para tratarmos de assuntos relacionados a vida escolar e a baixa frequencia do(a) estudante {dados['cadastro']['nome']}, matriculado(a) na turma {dados['cadastro']['turma']} (RA: {ra}).\n\n" \
                              f"Lembramos que, conforme a Lei Estadual 13.068/2008 e a Resolucao SEDUC 39/2023, a frequencia escolar regular e um direito do estudante e dever dos responsaveis.\n\n" \
                              f"O nao comparecimento acarretara nas devidas providencias legais junto ao Conselho Tutelar e a rede de protecao.\n\n" \
                              f"Santo Andre, {datetime.now().strftime('%d/%m/%Y')}."
                
                pdf_carta.multi_cell(0, 8, texto_carta)
                pdf_carta.ln(20)
                
                pdf_carta.cell(0, 8, "___________________________________________________", 0, 1, "C")
                pdf_carta.cell(0, 8, "Assinatura da Direcao / Coordenacao", 0, 1, "C")
                pdf_carta.ln(10)
                pdf_carta.cell(0, 8, "Ciente do Responsavel: ___________________________________  Data: ___/___/___", 0, 1, "C")
                
                out_carta = pdf_carta.output(dest="S").encode("latin1", "ignore")
                col_bpdf2.download_button("📥 Baixar Carta em PDF", data=out_carta, file_name=f"Carta_Convocacao_{ra}.pdf")

# ============================================================
# MOMENTO 3 — PAINEL DE LEMBRETES E PRIORIDADES (NOVO MENU ADICIONADO)
# ============================================================
elif menu == "Lembretes e Agenda":
    st.header("🚨 Painel de Prioridades e Acompanhamento")
    st.write("Abaixo estão listados os estudantes que estão na Busca Ativa e **não recebem nenhum contato ou intervenção há mais de 5 dias**. Priorize estes atendimentos!")

    lembretes = []
    
    for arquivo in os.listdir(PASTA_FICHAS):
        if arquivo.endswith(".json"):
            with open(os.path.join(PASTA_FICHAS, arquivo), "r", encoding="utf8") as f:
                dados_aluno = json.load(f)
            
            if dados_aluno.get("cadastro", {}).get("status") == "Em acompanhamento":
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
                                "RA": arquivo.replace(".json", ""),
                                "Nome": dados_aluno["cadastro"]["nome"],
                                "Turma": dados_aluno["cadastro"]["turma"],
                                "Dias sem contato": dias_passados,
                                "Primeiro Contato": primeira_acao_data,
                                "Última Ação Realizada": ultima_acao["acao"]
                            })
                    except:
                        pass

    if lembretes:
        df_lembretes = pd.DataFrame(lembretes)
        df_lembretes = df_lembretes.sort_values(by="Dias sem contato", ascending=False).reset_index(drop=True)
        
        st.error(f"⚠️ Atenção! Você tem **{len(lembretes)}** casos parados precisando de intervenção urgente.")
        st.dataframe(df_lembretes, use_container_width=True)
        st.info("💡 Para registrar uma nova ação, copie o RA do estudante acima e cole na aba 'Prontuário do Aluno'.")
    else:
        st.success("🎉 Parabéns! Todos os alunos em acompanhamento receberam contato nos últimos 5 dias. Ninguém está esquecido!")