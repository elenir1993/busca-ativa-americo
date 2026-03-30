import streamlit as st
import pandas as pd
import os
import json
import matplotlib.pyplot as plt
import uuid
from datetime import datetime
from fpdf import FPDF
import re
import io
import urllib.parse
import gspread 

st.set_page_config(page_title="Busca Ativa Escolar", layout="wide")

# ============================================================
# FUNÇÕES AUXILIARES (EXCEL E CORREÇÃO DE ACENTOS NO PDF)
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

def txt(texto):
    """Corrige problemas de acentuação no gerador de PDF"""
    return str(texto).encode('latin-1', 'replace').decode('latin-1')

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

CHAVE_HISTORICO = "HISTORICO_SISTEMA"
CHAVE_META_BASE = "CURRENT_DATA_META"
PREFIXO_BASE = "CURRENT_DATA::"
CHAVE_LOGS = "LOG_SISTEMA"


def semana_iso_atual():
    hoje = datetime.now().isocalendar()
    return f"{hoje.year}-W{hoje.week:02d}"


def atualizar_ou_criar_linha(chave, valor):
    todas_linhas = planilha.get_all_values()
    for i, linha in enumerate(todas_linhas):
        if i > 0 and len(linha) > 0 and str(linha[0]) == chave:
            planilha.update_cell(i + 1, 2, valor)
            return
    planilha.append_row([chave, valor])


def registrar_log(evento, detalhe, nivel="INFO"):
    try:
        payload = {
            "data_hora": datetime.now().strftime("%d/%m/%Y %H:%M:%S"),
            "nivel": nivel,
            "evento": evento,
            "detalhe": detalhe,
        }
        planilha.append_row([CHAVE_LOGS, json.dumps(payload, ensure_ascii=False)])
    except Exception:
        pass


def carregar_json_seguro(texto_json, contexto):
    try:
        return json.loads(texto_json)
    except Exception as e:
        registrar_log("JSON_INVALIDO", f"{contexto}: {str(e)}", nivel="ERRO")
        return None


def classificar_prioridade(dias_sem_contato, frequencia=None):
    score = dias_sem_contato
    if frequencia is not None:
        if frequencia <= 0.25:
            score += 4
        elif frequencia <= 0.50:
            score += 3
        elif frequencia <= 0.75:
            score += 2
        else:
            score += 1

    if score >= 10:
        return "🔴 Crítica", score
    if score >= 7:
        return "🟠 Alta", score
    if score >= 4:
        return "🟡 Média", score
    return "🟢 Baixa", score


def carregar_base_nuvem():
    todas_linhas = planilha.get_all_values()
    meta = None
    for i, linha in enumerate(todas_linhas):
        if i > 0 and len(linha) > 1 and str(linha[0]) == CHAVE_META_BASE:
            meta = carregar_json_seguro(linha[1], "meta_base")
            break

    if not meta or not meta.get("batch_id"):
        return None, meta

    batch_id = meta["batch_id"]
    registros = []
    for i, linha in enumerate(todas_linhas):
        if i > 0 and len(linha) > 1 and str(linha[0]) == f"{PREFIXO_BASE}{batch_id}":
            item = carregar_json_seguro(linha[1], "linha_base_compartilhada")
            if item:
                registros.append(
                    {
                        "Turma": item.get("turma"),
                        "RA": str(item.get("ra", "")),
                        "Nome": item.get("nome"),
                        "Presenca_Anual": item.get("presenca_anual"),
                    }
                )

    if not registros:
        return None, meta
    df = pd.DataFrame(registros)
    df["Presenca_Anual"] = pd.to_numeric(df["Presenca_Anual"], errors="coerce")
    return df, meta


def resetar_base_semanal_se_necessario(meta):
    semana_atual = semana_iso_atual()
    semana_registrada = (meta or {}).get("week_key")

    if semana_registrada and semana_registrada != semana_atual:
        nova_meta = {
            "batch_id": "",
            "uploaded_at": "",
            "total_alunos": 0,
            "week_key": semana_atual,
            "reset_at": datetime.now().strftime("%d/%m/%Y %H:%M"),
        }
        atualizar_ou_criar_linha(CHAVE_META_BASE, json.dumps(nova_meta, ensure_ascii=False))
        registrar_log("RESET_SEMANAL_BASE", f"Base semanal resetada para {semana_atual}", nivel="INFO")
        return nova_meta, True
    return meta, False


def salvar_base_nuvem(df_escola):
    df_escola = df_escola.copy()
    if "RA" in df_escola.columns:
        df_escola["RA"] = df_escola["RA"].astype(str)
        df_escola = df_escola.drop_duplicates(subset=["RA"], keep="last")

    batch_id = uuid.uuid4().hex[:10]
    momento = datetime.now().strftime("%d/%m/%Y %H:%M")
    week_key = semana_iso_atual()

    linhas = []
    for _, row in df_escola.iterrows():
        payload = {
            "batch_id": batch_id,
            "uploaded_at": momento,
            "turma": str(row.get("Turma", "")),
            "ra": str(row.get("RA", "")),
            "nome": str(row.get("Nome", "")),
            "presenca_anual": float(row.get("Presenca_Anual", 0)) if pd.notnull(row.get("Presenca_Anual")) else None,
        }
        linhas.append([f"{PREFIXO_BASE}{batch_id}", json.dumps(payload, ensure_ascii=False)])

    if linhas:
        planilha.append_rows(linhas, value_input_option="RAW")
    else:
        registrar_log("UPLOAD_BASE_VAZIA", "Nenhuma linha salva na base compartilhada.", nivel="ALERTA")

    meta = {
        "batch_id": batch_id,
        "uploaded_at": momento,
        "total_alunos": int(len(df_escola)),
        "week_key": week_key,
        "reset_at": "",
    }
    atualizar_ou_criar_linha(CHAVE_META_BASE, json.dumps(meta, ensure_ascii=False))
    registrar_log("UPLOAD_BASE", f"Batch {batch_id} salvo com {len(df_escola)} alunos.", nivel="INFO")
    return meta

# ============================================================
# SESSION STATE E MENU
# ============================================================
if "dados_escola" not in st.session_state: st.session_state.dados_escola = None
if "turma_selecionada" not in st.session_state: st.session_state.turma_selecionada = None
if "ra_selecionado" not in st.session_state: st.session_state.ra_selecionado = ""

st.title("Sistema de Busca Ativa")
st.subheader("EE Dr. Américo Brasiliense")

menu = st.sidebar.radio("Menu", ["Diagnóstico Geral", "Prontuário do Aluno", "Painel de Lembretes e Disparo"])

if st.sidebar.button("Deslogar / Reiniciar"):
    st.session_state.clear(); st.rerun()
    # ============================================================
# MOMENTO 1 — DIAGNÓSTICO GERAL E GRÁFICOS
# ============================================================
if menu == "Diagnóstico Geral":
    st.header("Diagnóstico de Frequência Escolar (Evolutivo)")
    base_nuvem, meta_base = carregar_base_nuvem()
    meta_base, houve_reset = resetar_base_semanal_se_necessario(meta_base)
    if houve_reset:
        st.session_state.dados_escola = None
        base_nuvem = None
        st.info("📅 A base semanal foi reiniciada automaticamente para a nova semana. Faça o upload das novas planilhas.")

    if st.session_state.dados_escola is None and base_nuvem is not None:
        st.session_state.dados_escola = base_nuvem

    if meta_base and meta_base.get("uploaded_at"):
        st.caption(
            f"Base compartilhada ativa: {meta_base.get('total_alunos', 0)} alunos | "
            f"Último upload em {meta_base['uploaded_at']} | Semana {meta_base.get('week_key', '-')}"
        )

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
        meta_base = salvar_base_nuvem(escola)
        st.success(f"Planilhas processadas e publicadas para toda a escola. Upload: {meta_base['uploaded_at']}")

    if st.session_state.dados_escola is not None:
        escola = st.session_state.dados_escola
        
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
        
        dl1, dl2, dl3, dl4 = st.columns(4)
        if not f1.empty: dl1.download_button("📥 Baixar 0-25%", gerar_excel_faixa(f1, "0_25"), f"Lista_0_25_{datetime.now().strftime('%d-%m-%Y')}.xlsx", use_container_width=True)
        if not f2.empty: dl2.download_button("📥 Baixar 26-50%", gerar_excel_faixa(f2, "26_50"), f"Lista_26_50_{datetime.now().strftime('%d-%m-%Y')}.xlsx", use_container_width=True)
        if not f3.empty: dl3.download_button("📥 Baixar 51-75%", gerar_excel_faixa(f3, "51_75"), f"Lista_51_75_{datetime.now().strftime('%d-%m-%Y')}.xlsx", use_container_width=True)
        if not f4.empty: dl4.download_button("📥 Baixar 76-100%", gerar_excel_faixa(f4, "76_100"), f"Lista_76_100_{datetime.now().strftime('%d-%m-%Y')}.xlsx", use_container_width=True)

        st.write(f"**Total de alunos processados:** {len(escola)}")
        
        st.markdown("---")
        st.subheader("Concentração de Faltas por Turma (< 76%)")
        resumo = criticos_geral["Turma"].value_counts()
        
        fig_turmas, ax_turmas = plt.subplots(figsize=(12, 6))
        bars = ax_turmas.bar(resumo.index, resumo.values, color="#3B82F6", edgecolor="#2563EB", linewidth=1.2, alpha=0.8)
        ax_turmas.spines['top'].set_visible(False); ax_turmas.spines['right'].set_visible(False); ax_turmas.spines['left'].set_visible(False)
        ax_turmas.yaxis.grid(True, linestyle='--', alpha=0.4); plt.xticks(rotation=45, ha='right', fontsize=9, color="#374151")
        ax_turmas.set_ylabel("Quantidade de Alunos", fontsize=10, fontweight='bold', color="#4B5563")
        ax_turmas.bar_label(bars, padding=3, fontsize=10, fontweight='bold', color="#1E3A8A")
        plt.tight_layout(); st.pyplot(fig_turmas)
        fig_turmas.savefig("turmas.png", bbox_inches="tight")

        # ------------------------------------------------
        # DADOS NA NUVEM PARA RELATÓRIO E FUNIL DE AÇÕES
        # ------------------------------------------------
        todas_linhas = planilha.get_all_values()
        linha_hist = -1; hist_dados = []
        acoes_totais = {"WhatsApp": 0, "Contato Telefônico": 0, "Notificação Formal": 0, "Reunião Presencial": 0, "Visita Domiciliar": 0, "Acionamento Conselho Tutelar": 0, "Outros": 0}
        acoes_por_turma = {}
        acompanhamento_por_ra = {}
        
        for i, linha in enumerate(todas_linhas):
            if i > 0 and len(linha) > 0:
                chave_linha = str(linha[0])
                if chave_linha == CHAVE_HISTORICO:
                    linha_hist = i + 1
                    if len(linha) > 1:
                        hist_dados = carregar_json_seguro(linha[1], "historico_sistema") or []
                elif chave_linha == CHAVE_META_BASE or chave_linha.startswith(PREFIXO_BASE):
                    continue
                elif len(linha) > 1:
                    dados_aluno = carregar_json_seguro(linha[1], "acoes_totais_prontuario")
                    if dados_aluno:
                        ra_ref = str(linha[0])
                        cadastro = dados_aluno.get("cadastro", {})
                        turma_ref = cadastro.get("turma", "Não informada")
                        qtd_acoes = len(dados_aluno.get("acoes", []))
                        acoes_por_turma[turma_ref] = acoes_por_turma.get(turma_ref, 0) + qtd_acoes
                        acompanhamento_por_ra[ra_ref] = {
                            "entrada": cadastro.get("data_entrada_acompanhamento", ""),
                            "qtd_acoes": qtd_acoes,
                        }
                        for acao in dados_aluno.get("acoes", []):
                            nome_acao = acao.get("acao", "").lower()
                            if "whatsapp" in nome_acao: acoes_totais["WhatsApp"] += 1
                            elif "telefônico" in nome_acao or "telefonico" in nome_acao: acoes_totais["Contato Telefônico"] += 1
                            elif "notificação" in nome_acao or "notificacao" in nome_acao: acoes_totais["Notificação Formal"] += 1
                            elif "reunião" in nome_acao or "reuniao" in nome_acao: acoes_totais["Reunião Presencial"] += 1
                            elif "visita" in nome_acao: acoes_totais["Visita Domiciliar"] += 1
                            elif "conselho" in nome_acao: acoes_totais["Acionamento Conselho Tutelar"] += 1
                            else: acoes_totais["Outros"] += 1

        st.markdown("---")
        st.subheader("📊 Relatório Oficial SEDUC (Com Evolução e Funil)")
        analise_qualitativa = st.text_area("Análise Qualitativa para o Relatório:", placeholder="Descreva os avanços observados e o trabalho da equipe...")

        if st.button("📄 Gravar Hoje e Gerar Relatório PDF"):
            hoje = datetime.now().strftime("%d/%m/%Y")
            
            hist_dados_limpos = {}
            for item in hist_dados:
                d_str = item["data"]
                if "-" in d_str:
                    try: d_str = datetime.strptime(d_str, "%Y-%m-%d").strftime("%d/%m/%Y")
                    except: pass
                if "f1" in item: hist_dados_limpos[d_str] = {"f1": item["f1"], "f2": item["f2"], "f3": item["f3"], "f4": item["f4"]}
                else: hist_dados_limpos[d_str] = {"f1": 0, "f2": 0, "f3": item.get("busca_ativa", 0), "f4": 0}
                    
            hist_dados_limpos[hoje] = {"f1": len(f1), "f2": len(f2), "f3": len(f3), "f4": len(f4)}
            hist_dados_novo = [{"data": k, "f1": v["f1"], "f2": v["f2"], "f3": v["f3"], "f4": v["f4"]} for k, v in hist_dados_limpos.items()]
            try: hist_dados_novo.sort(key=lambda x: datetime.strptime(x["data"], "%d/%m/%Y"))
            except: pass
                
            dados_str = json.dumps(hist_dados_novo)
            if linha_hist != -1: planilha.update_cell(linha_hist, 2, dados_str)
            else: planilha.append_row([CHAVE_HISTORICO, dados_str])

            hist_df = pd.DataFrame(hist_dados_novo)
            fig_evol, ax_evol = plt.subplots(figsize=(10, 4))
            ax_evol.plot(hist_df["data"], hist_df["f1"], marker="o", color="darkred", linewidth=2.5, label="0-25%")
            ax_evol.plot(hist_df["data"], hist_df["f2"], marker="o", color="red", linewidth=2.5, label="26-50%")
            ax_evol.plot(hist_df["data"], hist_df["f3"], marker="o", color="orange", linewidth=2.5, label="51-75%")
            ax_evol.plot(hist_df["data"], hist_df["f4"], marker="o", color="green", linewidth=2.5, label="76-100%")
            ax_evol.set_title("Evolução Histórica por Faixas de Frequência", fontweight="bold")
            ax_evol.set_ylabel("Quantidade de Alunos")
            ax_evol.spines['top'].set_visible(False); ax_evol.spines['right'].set_visible(False)
            ax_evol.yaxis.grid(True, linestyle='--', alpha=0.4); plt.xticks(rotation=45)
            ax_evol.legend(loc="upper left", bbox_to_anchor=(1, 1))
            fig_evol.savefig("evolucao_pdf.png", bbox_inches="tight")
            plt.close(fig_evol)

            pdf = FPDF(); pdf.add_page()
            pdf.set_font("Arial", "B", 14); pdf.cell(0, 8, txt("ESCOLA ESTADUAL DOUTOR AMÉRICO BRASILIENSE"), 0, 1, "C")
            pdf.set_font("Arial", "B", 12); pdf.cell(0, 8, txt("RELATÓRIO DE DIAGNÓSTICO E BUSCA ATIVA"), 0, 1, "C"); pdf.ln(2)
            pdf.set_font("Arial", "", 10)
            cab = "CIE: 8266 | Diretoria de Ensino: SANTO ANDRÉ\nEndereço: PRAÇA QUARTO CENTENÁRIO, 7 - CENTRO - SANTO ANDRÉ - SP\nTelefone: (11) 4432-2021 | E-mail: E008266A@EDUCACAO.SP.GOV.BR"
            pdf.multi_cell(0, 5, txt(cab)); pdf.line(10, pdf.get_y()+2, 200, pdf.get_y()+2); pdf.ln(5)
            
            pdf.set_font("Arial", "B", 11); pdf.cell(0, 6, txt(f"Data da emissão: {datetime.now().strftime('%d/%m/%Y')}"), 0, 1); pdf.ln(5)
                        pdf.cell(0, 8, txt("1. Distribuição por Turma (Cenário Atual < 76%)"), 0, 1)
            pdf.set_font("Arial", "B", 10)
            pdf.cell(110, 8, "Turma", 1)
            pdf.cell(30, 8, "Qtd Alunos", 1, 0, "C")
            pdf.cell(40, 8, "Ações da Turma", 1, 1, "C")
            pdf.set_font("Arial", "", 10)
            for t, q in resumo.items():
                acoes_turma = acoes_por_turma.get(str(t), 0)
                pdf.cell(110, 8, txt(str(t)), 1)
                pdf.cell(30, 8, str(q), 1, 0, "C")
                pdf.cell(40, 8, str(acoes_turma), 1, 1, "C")
            
            pdf.ln(5)
            if os.path.exists("turmas.png"): pdf.image("turmas.png", x=10, w=190)

            pdf.add_page()
            pdf.set_font("Arial", "B", 12); pdf.cell(0, 8, txt("2. Acompanhamento e Evolução Quantitativa"), 0, 1)
            pdf.ln(2); pdf.image("evolucao_pdf.png", x=10, w=190)
            
            pdf.set_y(120); pdf.set_font("Arial", "B", 9)
            pdf.cell(40, 8, "Data", 1, 0, "C"); pdf.cell(35, 8, "0% a 25%", 1, 0, "C"); pdf.cell(35, 8, "26% a 50%", 1, 0, "C"); pdf.cell(35, 8, "51% a 75%", 1, 0, "C"); pdf.cell(35, 8, "76% a 100%", 1, 1, "C")
            pdf.set_font("Arial", "", 9)
            for item in hist_dados_novo[-10:]:
                pdf.cell(40, 8, item["data"], 1, 0, "C"); pdf.cell(35, 8, str(item.get("f1", 0)), 1, 0, "C"); pdf.cell(35, 8, str(item.get("f2", 0)), 1, 0, "C"); pdf.cell(35, 8, str(item.get("f3", 0)), 1, 0, "C"); pdf.cell(35, 8, str(item.get("f4", 0)), 1, 1, "C")

            pdf.ln(8)
            pdf.set_font("Arial", "B", 12)
            pdf.cell(0, 8, txt("3. Funil de Ações Realizadas (Trabalho da Equipe)"), 0, 1)
            pdf.set_font("Arial", "", 10)
            for k, v in acoes_totais.items():
                if v > 0:
                    pdf.cell(0, 6, txt(f"- {k}: {v} intervenções registradas na plataforma"), 0, 1)

            pdf.ln(4)
            pdf.set_font("Arial", "B", 12)
            pdf.cell(0, 8, txt("4. Casos de Maior Urgência (Base Atual)"), 0, 1)
            pdf.set_font("Arial", "B", 9)
            pdf.cell(70, 8, "Nome", 1, 0, "C")
            pdf.cell(40, 8, "Turma", 1, 0, "C")
            pdf.cell(35, 8, "RA", 1, 0, "C")
            pdf.cell(35, 8, "Presença", 1, 1, "C")
            pdf.set_font("Arial", "", 9)
            urgentes_pdf = escola[escola["Presenca_Anual"] <= 0.50].sort_values("Presenca_Anual", ascending=True).head(10)
            for _, urg in urgentes_pdf.iterrows():
                info_urg = acompanhamento_por_ra.get(str(urg.get("RA", "")), {"entrada": "", "qtd_acoes": 0})
                pdf.cell(70, 8, txt(str(urg.get("Nome", ""))[:35]), 1, 0)
                pdf.cell(40, 8, txt(str(urg.get("Turma", ""))[:20]), 1, 0)
                pdf.cell(35, 8, txt(str(urg.get("RA", ""))[:15]), 1, 0)
                pres_txt = f"{(urg.get('Presenca_Anual', 0) or 0) * 100:.1f}%"
                pdf.cell(35, 8, pres_txt, 1, 1, "C")
                if info_urg.get("entrada") or info_urg.get("qtd_acoes", 0) > 0:
                    txt_and = f"  ↳ Em acompanhamento desde: {info_urg.get('entrada') or 'não informado'} | Ações registradas: {info_urg.get('qtd_acoes', 0)}"
                    pdf.set_font("Arial", "I", 8)
                    pdf.cell(0, 6, txt(txt_and), 0, 1)
                    pdf.set_font("Arial", "", 9)

            pdf.ln(5)
            pdf.set_font("Arial", "B", 12)
            pdf.cell(0, 8, txt("5. Análise Qualitativa"), 0, 1)
            pdf.set_font("Arial", "", 11)
            texto = analise_qualitativa if analise_qualitativa.strip() else "A análise aponta a evolução quantitativa dos dados e a mobilidade dos estudantes entre os degraus de risco, evidenciando o resultado contínuo do funil de ações da equipe escolar."
            pdf.multi_cell(0, 7, txt(texto))

            # Anexo: Planilha textual dos casos mais críticos (<= 50%)
            anex_df = escola[escola["Presenca_Anual"] <= 0.50].copy().sort_values("Presenca_Anual", ascending=True)
            if not anex_df.empty:
                pdf.add_page()
                pdf.set_font("Arial", "B", 12)
                pdf.cell(0, 8, txt("ANEXO I - Casos Críticos (Frequência <= 50%)"), 0, 1)
                pdf.set_font("Arial", "B", 8)
                pdf.cell(70, 7, "Nome", 1, 0, "C")
                pdf.cell(28, 7, "RA", 1, 0, "C")
                pdf.cell(35, 7, "Turma", 1, 0, "C")
                pdf.cell(22, 7, "Presença", 1, 0, "C")
                pdf.cell(35, 7, "Ações", 1, 1, "C")
                pdf.set_font("Arial", "", 8)
                for _, ar in anex_df.iterrows():
                    info_ar = acompanhamento_por_ra.get(str(ar.get("RA", "")), {"qtd_acoes": 0})
                    pdf.cell(70, 7, txt(str(ar.get("Nome", ""))[:32]), 1, 0)
                    pdf.cell(28, 7, txt(str(ar.get("RA", ""))[:14]), 1, 0, "C")
                    pdf.cell(35, 7, txt(str(ar.get("Turma", ""))[:15]), 1, 0)
                    pdf.cell(22, 7, f"{(ar.get('Presenca_Anual', 0) or 0)*100:.1f}%", 1, 0, "C")
                    pdf.cell(35, 7, str(info_ar.get("qtd_acoes", 0)), 1, 1, "C")

            pdf_out = pdf.output(dest="S").encode("latin1", "ignore")
            st.download_button("📥 Baixar Relatório Oficial Completo", data=pdf_out, file_name="Relatorio_SEDUC.pdf")
            if os.path.exists("evolucao_pdf.png"): os.remove("evolucao_pdf.png")

        # ------------------------------------------------
        # MÁQUINA DO TEMPO (INSERIR LENDO PLANILHAS/EXCLUIR)
        # ------------------------------------------------
        st.markdown("---")
        with st.expander("⚙️ Gerenciar Histórico de Dados (A Máquina do Tempo)"):
            st.warning("Se precisar registrar uma data retroativa (ex: 13/03/2026), suba os arquivos daquele dia lá no topo, digite a data abaixo e clique em Salvar.")
            
            tab_add, tab_del = st.tabs(["➕ Salvar Leitura na Nuvem", "🗑️ Excluir Data"])
            
            with tab_add:
                with st.form("form_correcao"):
                    dt_manual = st.text_input("Data do Registro (DD/MM/AAAA):", value=datetime.now().strftime("%d/%m/%Y"))
                    if st.form_submit_button("Salvar Dados Processados com esta Data"):
                        # Ele usa os valores lidos automaticamente das planilhas que subiu no topo
                        hist_dados_limpos = [item for item in hist_dados if item["data"] != dt_manual]
                        hist_dados_limpos.append({"data": dt_manual, "f1": len(f1), "f2": len(f2), "f3": len(f3), "f4": len(f4)})
                        try: hist_dados_limpos.sort(key=lambda x: datetime.strptime(x["data"], "%d/%m/%Y"))
                        except: pass
                        dados_str = json.dumps(hist_dados_limpos)
                        if linha_hist != -1: planilha.update_cell(linha_hist, 2, dados_str)
                        else: planilha.append_row([CHAVE_HISTORICO, dados_str])
                        st.success(f"Os dados da planilha lida foram gravados no dia {dt_manual} com sucesso!")
                        st.rerun()

            with tab_del:
                if hist_dados:
                    datas_disp = [item["data"] for item in hist_dados]
                    dt_excluir = st.selectbox("Selecione a data para remover do histórico:", datas_disp)
                    if st.button("Excluir Data Selecionada"):
                        hist_dados_novo = [item for item in hist_dados if item["data"] != dt_excluir]
                        planilha.update_cell(linha_hist, 2, json.dumps(hist_dados_novo))
                        st.success(f"Os dados do dia {dt_excluir} foram apagados com sucesso!")
                        st.rerun()
                else: st.info("Nenhum dado histórico gravado ainda.")

        st.markdown("---")
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
                    st.session_state.ra_selecionado = row["RA"]; st.success("Acesse a aba 'Prontuário do Aluno' no menu ao lado.")
                    # ============================================================
# MOMENTO 2 — PRONTUÁRIO DO ALUNO E AÇÕES
# ============================================================
elif menu == "Prontuário do Aluno":
    st.header("Prontuário Individual de Acompanhamento")
    if st.session_state.dados_escola is None:
        base_nuvem, _ = carregar_base_nuvem()
        if base_nuvem is not None:
            st.session_state.dados_escola = base_nuvem
    
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
            dados = carregar_json_seguro(dados_texto, f"prontuario_ra_{ra}") or {}
            if "cadastro" not in dados: dados["cadastro"] = {"nome": nome_aluno, "turma": turma_aluno, "status": "Em acompanhamento"}
            if "responsavel" not in dados["cadastro"]: dados["cadastro"]["responsavel"] = ""
            if "telefone" not in dados["cadastro"]: dados["cadastro"]["telefone"] = ""
            if "email" not in dados["cadastro"]: dados["cadastro"]["email"] = ""
            if "endereco" not in dados["cadastro"]: dados["cadastro"]["endereco"] = ""
            if "data_entrada_acompanhamento" not in dados["cadastro"]: dados["cadastro"]["data_entrada_acompanhamento"] = datetime.now().strftime("%d/%m/%Y")
            if "frequencia_inicial" not in dados["cadastro"]: dados["cadastro"]["frequencia_inicial"] = frequencia_atual if frequencia_atual is not None else 0
            if "data_saida_acompanhamento" not in dados["cadastro"]: dados["cadastro"]["data_saida_acompanhamento"] = ""
            if "frequencia" not in dados: dados["frequencia"] = []
        else:
            dados = {
                "cadastro": {
                    "nome": nome_aluno, "turma": turma_aluno, "status": "Em acompanhamento",
                    "responsavel": "", "telefone": "", "email": "", "endereco": "",
                    "data_entrada_acompanhamento": datetime.now().strftime("%d/%m/%Y"),
                    "frequencia_inicial": frequencia_atual if frequencia_atual is not None else 0,
                    "data_saida_acompanhamento": "",
                },
                "acoes": [], "frequencia": []
            }

        def salvar_dados_nuvem(dados_atualizados):
            dados_str = json.dumps(dados_atualizados, ensure_ascii=False)
            if linha_aluno != -1: planilha.update_cell(linha_aluno, 2, dados_str)
            else: planilha.append_row([str(ra), dados_str])

        st.markdown("---")
        col_i1, col_i2, col_i3 = st.columns(3)
        col_i1.metric("Nome do Estudante", dados["cadastro"]["nome"])
        col_i2.metric("Turma", dados["cadastro"]["turma"])
        
        status_atual = dados["cadastro"].get("status", "Em acompanhamento")
        if status_atual == "Em acompanhamento": col_i3.success(f"Status: {status_atual}")
        else: col_i3.error(f"Status: {status_atual}")
        col_a1, col_a2 = st.columns(2)
        data_entrada = dados["cadastro"].get("data_entrada_acompanhamento", "não informado")
        col_a1.info(f"📅 Em acompanhamento desde: **{data_entrada}**")
        freq_inicial = dados["cadastro"].get("frequencia_inicial")
        if frequencia_atual is not None and freq_inicial is not None:
            delta = (frequencia_atual - float(freq_inicial)) * 100
            tendencia = "progredindo ✅" if delta > 0 else ("regredindo ⚠️" if delta < 0 else "estável")
            col_a2.info(f"📈 Tendência: **{tendencia}** ({delta:+.1f} p.p.)")
        st.markdown("---")
                with st.expander("📞 Dados de Contato e Responsável", expanded=True):
            with st.form("form_dados_cadastrais"):
                col_cad1, col_cad2 = st.columns(2)
                responsavel_input = col_cad1.text_input("Nome do Responsável Legal:", value=dados["cadastro"].get("responsavel", ""))
                telefone_input = col_cad2.text_input("Telefone / WhatsApp (Com DDD):", value=dados["cadastro"].get("telefone", ""))
                email_input = col_cad1.text_input("E-mail do Responsável:", value=dados["cadastro"].get("email", ""))
                endereco_input = col_cad2.text_input("Endereço Completo:", value=dados["cadastro"].get("endereco", ""))
                
                if st.form_submit_button("💾 Salvar/Atualizar Dados Cadastrais"):
                    dados["cadastro"]["responsavel"] = responsavel_input; dados["cadastro"]["telefone"] = telefone_input; dados["cadastro"]["email"] = email_input; dados["cadastro"]["endereco"] = endereco_input
                    salvar_dados_nuvem(dados)
                    st.success("Dados de contato atualizados na nuvem com sucesso!")
                    st.rerun()

            st.markdown("**Ações Rápidas de Comunicação:**")
            col_b1, col_b2 = st.columns(2)
            freq_str = f"{frequencia_atual*100:.1f}%" if frequencia_atual is not None else "nível crítico"
            freq_ini = float(dados["cadastro"].get("frequencia_inicial", 0) or 0)
            freq_at = frequencia_atual if frequencia_atual is not None else freq_ini
            delta_txt = f"{(freq_at - freq_ini)*100:+.1f} p.p."
            msg_tipo = st.selectbox(
                "Tipo de mensagem para WhatsApp",
                ["1º contato (15 dias)", "2º contato (evolução/desevolução)", "Saída do acompanhamento"],
            )
            
            num_zap = ''.join(filter(str.isdigit, dados["cadastro"].get("telefone", "")))
            if num_zap:
                if msg_tipo == "1º contato (15 dias)":
                    texto_zap = f"⚠️ *Notificação Escolar - EE Dr. Américo Brasiliense*\n\nPrezado(a) responsável,\n\nInformamos que a frequência escolar do(a) estudante *{dados['cadastro']['nome']}* está em *{freq_str}*.\n\nA família tem *15 dias* para apresentar melhora e justificar as ausências junto à escola.\n\nCaso não haja evolução, o caso poderá ser encaminhado ao Conselho Tutelar.\n\nSala do Futuro: https://saladofuturo.educacao.sp.gov.br/login-responsaveis"
                elif msg_tipo == "2º contato (evolução/desevolução)":
                    texto_zap = f"📌 *Acompanhamento Escolar - 2º contato*\n\nEstudante: *{dados['cadastro']['nome']}*\nFrequência atual: *{freq_str}*\nEvolução desde o início do acompanhamento: *{delta_txt}*.\n\nO estudante segue em acompanhamento. Solicitamos presença da família para alinhamento e justificativas."
                else:
                    texto_zap = f"✅ *Saída do acompanhamento - EE Dr. Américo Brasiliense*\n\nAgradecemos o apoio da família no acompanhamento de *{dados['cadastro']['nome']}*.\n\nNo momento, o estudante está saindo do acompanhamento ativo.\n\nImportante: caso a frequência volte a ficar abaixo de *75%*, o estudante retornará automaticamente para acompanhamento."
                msg_zap = urllib.parse.quote(texto_zap)
                col_b1.link_button("📲 Chamar no WhatsApp", f"https://wa.me/55{num_zap}?text={msg_zap}")
            else:
                col_b1.button("📲 Chamar no WhatsApp (Insira e salve o telefone acima primeiro)", disabled=True)
                
            email_resp = dados["cadastro"].get("email", "")
            if email_resp and "@" in email_resp:
                assunto = urllib.parse.quote("⚠️ URGENTE: Frequência Escolar e Risco de Retenção")
                texto_email = f"Prezado(a) responsável,\n\nInformamos que a frequência escolar do(a) estudante {dados['cadastro']['nome']} está em {freq_str}. O(a) aluno(a) encontra-se em acompanhamento pela equipe escolar.\n\nCaso a frequência não aumente nos próximos 15 dias, o caso será encaminhado ao Conselho Tutelar.\n\nPedimos que acompanhe a frequência pela Sala do Futuro: https://saladofuturo.educacao.sp.gov.br/login-responsaveis \n\nPara sanar dúvidas ou justificar faltas, compareça à escola presencialmente às terças ou quintas-feiras, das 14:00 às 20:00, e procure por Giovana (Vice-diretora), Elenir (Coordenadora) ou Vinicius (Diretor)."
                col_b2.link_button("📧 Enviar E-mail", f"mailto:{email_resp}?subject={assunto}&body={urllib.parse.quote(texto_email)}")
            else:
                col_b2.button("📧 Enviar E-mail (Insira e salve um e-mail válido acima)", disabled=True)

        st.markdown("### 📈 Acompanhamento de Frequência Individual")
        if frequencia_atual is not None:
            col_f1, col_f2 = st.columns([0.7, 0.3])
            col_f1.info(f"O BI atual aponta que a frequência deste aluno é de **{frequencia_atual*100:.1f}%**.")
            if col_f2.button("Gravar Frequência Atual do BI"):
                dados["frequencia"].append({"data": datetime.now().strftime("%d/%m/%Y"), "valor": frequencia_atual})
                salvar_dados_nuvem(dados); st.success("Frequência salva!"); st.rerun()

        if len(dados["frequencia"]) > 0:
            df_freq = pd.DataFrame(dados["frequencia"])
            fig_f, ax_f = plt.subplots(figsize=(10, 3))
            ax_f.plot(df_freq["data"], df_freq["valor"] * 100, marker='o', color='#10B981', linewidth=2)
            ax_f.axhline(76, color='red', linestyle='--', label='Meta SEDUC (76%)')
            ax_f.set_title("Evolução da Presença do Aluno (%)", fontweight='bold')
            ax_f.set_ylabel("Presença (%)"); ax_f.set_ylim(0, 105)
            ax_f.spines['top'].set_visible(False); ax_f.spines['right'].set_visible(False)
            ax_f.yaxis.grid(True, linestyle='--', alpha=0.3); ax_f.legend()
            st.pyplot(fig_f); fig_f.savefig(f"grafico_freq_{ra}.png", dpi=300); plt.close(fig_f)

        st.markdown("---")

        if status_atual == "Em acompanhamento":
            with st.form("reg_acao"):
                st.subheader("Registrar Nova Intervenção")
                acao = st.selectbox("Qual ação foi executada?", ["Contato telefônico", "Contato via WhatsApp", "1ª Notificação Formal", "2ª Notificação Formal", "Reunião Presencial", "Visita Domiciliar", "Acionamento Conselho Tutelar", "Outros"])
                relato = st.text_area("Descreva o que foi acordado / Justificativa:")
                if st.form_submit_button("Salvar no Prontuário"):
                    dados["acoes"].append({"data": datetime.now().strftime("%d/%m/%Y %H:%M"), "acao": acao, "relato": relato})
                    salvar_dados_nuvem(dados); st.success("Ação salva na nuvem com sucesso!"); st.rerun()
            
            with st.expander("⚠️ Encerrar Acompanhamento (Excluir da Busca Ativa)"):
                st.warning("Ao confirmar, o prontuário deste aluno será encerrado.")
                motivo = st.selectbox("Qual o motivo do encerramento?", ["Transferência", "Abandono (Esgotado)", "Frequência Regularizada"])
                if st.button("Confirmar Encerramento Definitivo"):
                    dados["cadastro"]["status"] = motivo
                    dados["cadastro"]["data_saida_acompanhamento"] = datetime.now().strftime("%d/%m/%Y")
                    dados["acoes"].append({"data": datetime.now().strftime("%d/%m/%Y %H:%M"), "acao": f"ENCERRAMENTO: {motivo}", "relato": "Estudante retirado do painel ativo."})
                    salvar_dados_nuvem(dados); st.success("Prontuário encerrado!"); st.rerun()
        else:
            st.info(f"🔒 Este prontuário encontra-se FECHADO pelo motivo: {status_atual}.")
            # ------------------------------------------------
        # PDFs DO PRONTUÁRIO INDIVIDUAL
        # ------------------------------------------------
        if dados["acoes"]:
            st.markdown("### Histórico de Intervenções e Relatos")
            st.table(pd.DataFrame(dados["acoes"]))
            
            col_bpdf1, col_bpdf2 = st.columns(2)
            if col_bpdf1.button("Gerar PDF de Resumo do Prontuário"):
                pdf_al = FPDF(); pdf_al.add_page()
                pdf_al.set_font("Arial", "B", 14); pdf_al.cell(0, 10, txt("RESUMO DE PRONTUÁRIO - BUSCA ATIVA"), 0, 1, "C"); pdf_al.ln(5)
                pdf_al.set_font("Arial", "B", 11)
                pdf_al.cell(0, 8, txt(f"Estudante: {dados['cadastro']['nome']} (RA: {ra})"), 0, 1)
                pdf_al.cell(0, 8, txt(f"Turma: {dados['cadastro']['turma']}"), 0, 1)
                pdf_al.cell(0, 8, txt(f"Responsável: {dados['cadastro'].get('responsavel', 'Não informado')}"), 0, 1)
                pdf_al.cell(0, 8, txt(f"Telefone: {dados['cadastro'].get('telefone', 'Não informado')}"), 0, 1)
                pdf_al.set_font("Arial", "", 11); pdf_al.multi_cell(0, 6, txt(f"Endereço: {dados['cadastro'].get('endereco', 'Não informado')}")); pdf_al.ln(2)
                pdf_al.set_font("Arial", "B", 11); pdf_al.cell(0, 8, txt(f"Situação Final: {status_atual.upper()}"), 0, 1)
                pdf_al.line(10, pdf_al.get_y(), 200, pdf_al.get_y()); pdf_al.ln(5)

                if os.path.exists(f"grafico_freq_{ra}.png"):
                    pdf_al.cell(0, 8, txt("Evolução da Frequência do Aluno:"), 0, 1)
                    pdf_al.image(f"grafico_freq_{ra}.png", x=10, w=190); pdf_al.ln(5)
                    os.remove(f"grafico_freq_{ra}.png")
                
                pdf_al.set_font("Arial", "B", 12); pdf_al.cell(0, 8, txt("Histórico de Intervenções:"), 0, 1); pdf_al.ln(2)
                pdf_al.set_font("Arial", "", 10)
                for a in dados["acoes"]:
                    pdf_al.set_font("Arial", "B", 10); pdf_al.cell(0, 7, txt(f"Data: {a['data']} | Ação: {a['acao']}"), 0, 1)
                    pdf_al.set_font("Arial", "", 10); pdf_al.multi_cell(0, 6, txt(f"Relato: {a['relato']}")); pdf_al.ln(4)
                
                col_bpdf1.download_button("Baixar Resumo em PDF", data=pdf_al.output(dest="S").encode("latin1", "ignore"), file_name=f"Resumo_{ra}.pdf")

            if col_bpdf2.button("✉️ Gerar Carta de Convocação Física"):
                pdf_carta = FPDF(); pdf_carta.add_page()
                pdf_carta.set_font("Arial", "B", 14); pdf_carta.cell(0, 10, txt("GOVERNO DO ESTADO DE SÃO PAULO"), 0, 1, "C")
                pdf_carta.cell(0, 10, txt("ESCOLA ESTADUAL DOUTOR AMÉRICO BRASILIENSE"), 0, 1, "C"); pdf_carta.ln(10)
                pdf_carta.set_font("Arial", "B", 16); pdf_carta.cell(0, 10, txt("NOTIFICAÇÃO DE COMPARECIMENTO"), 0, 1, "C"); pdf_carta.ln(10)
                pdf_carta.set_font("Arial", "", 12)
                texto_carta = f"Prezado(a) Responsável ({dados['cadastro'].get('responsavel', '________________________')}),\n\nConvocamos o(a) senhor(a) a comparecer, com urgência, à EE Dr. Américo Brasiliense para tratarmos da baixa frequência do(a) estudante {dados['cadastro']['nome']}, matriculado(a) na turma {dados['cadastro']['turma']} (RA: {ra}).\n\nO não comparecimento acarretará nas devidas providências legais junto ao Conselho Tutelar.\n\nSanto André, {datetime.now().strftime('%d/%m/%Y')}."
                pdf_carta.multi_cell(0, 8, txt(texto_carta)); pdf_carta.ln(20)
                pdf_carta.cell(0, 8, "___________________________________________________", 0, 1, "C")
                pdf_carta.cell(0, 8, txt("Assinatura da Direção / Coordenação"), 0, 1, "C"); pdf_carta.ln(10)
                pdf_carta.cell(0, 8, txt("Ciente do Responsável: ___________________________________  Data: ___/___/___"), 0, 1, "C")
                col_bpdf2.download_button("📥 Baixar Carta em PDF", data=pdf_carta.output(dest="S").encode("latin1", "ignore"), file_name=f"Carta_{ra}.pdf")

# ============================================================
# MOMENTO 3 — PAINEL DE LEMBRETES E DISPARO
# ============================================================
elif menu == "Painel de Lembretes e Disparo":
    st.header("🚨 Central de Ações e Disparos")
    if st.session_state.dados_escola is None:
        base_nuvem, _ = carregar_base_nuvem()
        if base_nuvem is not None:
            st.session_state.dados_escola = base_nuvem

    lembretes = []
    todas_linhas = planilha.get_all_values()
    alunos_ativos = []
    
    for i, linha in enumerate(todas_linhas):
        chave_linha = str(linha[0]) if len(linha) > 0 else ""
        if i > 0 and len(linha) > 1 and chave_linha != CHAVE_HISTORICO and chave_linha != CHAVE_META_BASE and not chave_linha.startswith(PREFIXO_BASE):
            dados_aluno = carregar_json_seguro(linha[1], "painel_lembretes")
            if dados_aluno:
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
                        except Exception as e:
                            registrar_log("DATA_ACAO_INVALIDA", f"RA {linha[0]}: {str(e)}", nivel="ALERTA")
                    
                    alunos_ativos.append({
                        "RA": str(linha[0]),
                        "Nome": dados_aluno["cadastro"]["nome"],
                        "Turma": dados_aluno["cadastro"]["turma"],
                        "Zap": num_zap,
                        "Email": dados_aluno["cadastro"].get("email", ""),
                        "Responsavel": dados_aluno["cadastro"].get("responsavel", ""),
                        "Dias": dias_passados
                    })

    df_lemb = pd.DataFrame(lembretes) if lembretes else pd.DataFrame()
    if not df_lemb.empty:
        if st.session_state.dados_escola is not None and not st.session_state.dados_escola.empty:
            mapa_freq = (
                st.session_state.dados_escola[["RA", "Presenca_Anual"]]
                .dropna(subset=["RA"])
                .drop_duplicates(subset=["RA"], keep="last")
                .set_index("RA")["Presenca_Anual"]
                .to_dict()
            )
            df_lemb["Frequência BI"] = df_lemb["RA"].map(mapa_freq)
        else:
            df_lemb["Frequência BI"] = None
        prioridades = df_lemb.apply(
            lambda r: classificar_prioridade(
                int(r.get("Dias sem contato", 0)),
                r.get("Frequência BI") if pd.notnull(r.get("Frequência BI")) else None,
            ),
            axis=1,
        )
        df_lemb["Prioridade"] = [p[0] for p in prioridades]
        df_lemb["Score"] = [p[1] for p in prioridades]
        df_lemb = df_lemb.sort_values(by=["Score", "Dias sem contato"], ascending=False)

    col_p1, col_p2, col_p3, col_p4 = st.columns(4)
    col_p1.metric("Alunos em acompanhamento", len(alunos_ativos))
    col_p2.metric("Casos parados (>=5 dias)", len(df_lemb))
    col_p3.metric("Casos críticos", len(df_lemb[df_lemb["Prioridade"].str.contains("Crítica")]) if not df_lemb.empty else 0)
    col_p4.metric("Sem contato >10 dias", len(df_lemb[df_lemb["Dias sem contato"] > 10]) if not df_lemb.empty else 0)

    tab1, tab2 = st.tabs(["📲 Disparo em Massa (WhatsApp)", "⚠️ Casos Parados"])

    with tab1:
        st.subheader("Disparo Rápido para Alunos em Acompanhamento")
        st.write("A mensagem abaixo já está formatada com as regras institucionais e o link da Sala do Futuro.")
        tipo_msg_massa = st.selectbox(
            "Tipo de mensagem em massa",
            ["1º contato (15 dias)", "2º contato (evolução)", "Saída do acompanhamento"],
            key="tipo_mensagem_massa",
        )
        if tipo_msg_massa == "1º contato (15 dias)":
            texto_base = "⚠️ *Notificação Escolar - EE Dr. Américo Brasiliense*\n\nPrezado(a) responsável,\n\nInformamos que a frequência escolar do(a) estudante encontra-se em nível crítico.\n\nA família possui *15 dias* para apresentar melhora e justificar faltas.\n\nCaso não haja evolução, o caso poderá ser encaminhado ao Conselho Tutelar."
        elif tipo_msg_massa == "2º contato (evolução)":
            texto_base = "📌 *Acompanhamento Escolar - 2º contato*\n\nPrezado(a) responsável,\n\nO estudante segue em acompanhamento.\n\nSolicitamos comparecimento da família na escola para alinhamento das justificativas e plano de melhoria de frequência."
        else:
            texto_base = "✅ *Saída do acompanhamento*\n\nAgradecemos o apoio da família no processo de acompanhamento escolar.\n\nInformamos que o estudante está saindo do acompanhamento ativo.\n\nSe a frequência voltar a ficar abaixo de 75%, o acompanhamento será reativado."
        
        msg_padrao = st.text_area("Mensagem Padrão para Disparo:", value=texto_base, height=250)
        
        if not alunos_ativos: st.info("Nenhum aluno em acompanhamento na nuvem no momento.")
        else:
            st.write(f"**Total na lista de disparo:** {len(alunos_ativos)} alunos")
            opcoes_disparo = [f"{a['Nome']} | RA {a['RA']} | {a['Turma']}" for a in alunos_ativos]
            selecionados = st.multiselect("Selecione alunos para ações em massa:", opcoes_disparo)
            selecionados_ra = [item.split("| RA ")[1].split(" |")[0].strip() for item in selecionados] if selecionados else []
            selecionados_obj = [a for a in alunos_ativos if a["RA"] in selecionados_ra]

            if selecionados_obj:
                st.markdown("#### Ações em massa")
                m1, m2, m3 = st.columns(3)
                contatos_zap = [a for a in selecionados_obj if a.get("Zap")]
                contatos_mail = [a for a in selecionados_obj if a.get("Email") and "@" in a.get("Email")]
                
                if contatos_zap:
                    texto_links = "\n".join(
                        [f"- {a['Nome']}: https://wa.me/55{a['Zap']}?text={urllib.parse.quote(msg_padrao)}" for a in contatos_zap]
                    )
                    m1.download_button(
                        "📥 Links WhatsApp (TXT)",
                        data=texto_links,
                        file_name=f"links_whatsapp_{datetime.now().strftime('%d%m%Y_%H%M')}.txt",
                        use_container_width=True,
                    )
                else:
                    m1.button("📥 Links WhatsApp (TXT)", disabled=True, use_container_width=True)

                if contatos_mail:
                    linhas_email = []
                    for a in contatos_mail:
                        linhas_email.append(f"Nome: {a['Nome']}")
                        linhas_email.append(f"E-mail: {a['Email']}")
                        linhas_email.append(f"Assunto: Notificação Escolar - Busca Ativa")
                        linhas_email.append(f"Mensagem: {texto_base}")
                        linhas_email.append("")
                    m2.download_button(
                        "📥 E-mails em massa (TXT)",
                        data="\n".join(linhas_email),
                        file_name=f"emails_massa_{datetime.now().strftime('%d%m%Y_%H%M')}.txt",
                        use_container_width=True,
                    )
                else:
                    m2.button("📥 E-mails em massa (TXT)", disabled=True, use_container_width=True)

                if m3.button("📄 Gerar Cartas em Massa (PDF)", use_container_width=True):
                    pdf_massa = FPDF()
                    for al in selecionados_obj:
                        pdf_massa.add_page()
                        pdf_massa.set_font("Arial", "B", 14); pdf_massa.cell(0, 10, txt("ESCOLA ESTADUAL DOUTOR AMÉRICO BRASILIENSE"), 0, 1, "C")
                        pdf_massa.set_font("Arial", "B", 12); pdf_massa.cell(0, 10, txt("NOTIFICAÇÃO DE COMPARECIMENTO"), 0, 1, "C")
                        pdf_massa.ln(8); pdf_massa.set_font("Arial", "", 12)
                        texto_c = (
                            f"Responsável: {al.get('Responsavel') or '________________________'}\n\n"
                            f"Convocamos o(a) responsável pelo(a) estudante {al['Nome']} (RA {al['RA']}), "
                            f"turma {al['Turma']}, para comparecimento na escola com urgência devido à baixa frequência.\n\n"
                            f"Data de emissão: {datetime.now().strftime('%d/%m/%Y')}."
                        )
                        pdf_massa.multi_cell(0, 8, txt(texto_c))
                    st.download_button(
                        "📥 Baixar Cartas em Massa (PDF)",
                        data=pdf_massa.output(dest="S").encode("latin1", "ignore"),
                        file_name=f"Cartas_Massa_{datetime.now().strftime('%d%m%Y_%H%M')}.pdf",
                        use_container_width=True,
                    )

            for al in alunos_ativos:
                c1, c2, c3 = st.columns([3, 1, 1])
                c1.write(f"**{al['Nome']}** ({al['Turma']})")
                if al['Zap']:
                    c2.write(f"📱 {al['Zap']}")
                    link = f"https://wa.me/55{al['Zap']}?text={urllib.parse.quote(msg_padrao)}"
                    c3.link_button("📤 Enviar Msg", link)
                else:
                    c2.write("❌ Sem número")

    with tab2:
        st.subheader("Casos com ação atrasada")
        st.caption("Lista automática para priorização de acompanhamento (5 dias ou mais sem nova intervenção).")

        if df_lemb.empty:
            st.success("Nenhum caso parado no momento 🎉")
        else:
            total_critica = len(df_lemb[df_lemb["Prioridade"].str.contains("Crítica")])
            total_alta = len(df_lemb[df_lemb["Prioridade"].str.contains("Alta")])
            total_media = len(df_lemb[df_lemb["Prioridade"].str.contains("Média")])
            kc1, kc2, kc3 = st.columns(3)
            kc1.error(f"Crítica: {total_critica}")
            kc2.warning(f"Alta: {total_alta}")
            kc3.info(f"Média: {total_media}")

            st.dataframe(
                df_lemb[
                    [
                        "Prioridade",
                        "Nome",
                        "RA",
                        "Turma",
                        "Dias sem contato",
                        "Última Ação Realizada",
                        "Primeiro Contato",
                        "Frequência BI",
                    ]
                ],
                use_container_width=True,
                hide_index=True,
            )

            st.markdown("### Ações rápidas")
            for _, caso in df_lemb.head(15).iterrows():
                c1, c2, c3 = st.columns([4, 1, 1])
                freq_txt = (
                    f"{caso['Frequência BI']*100:.1f}%"
                    if pd.notnull(caso.get("Frequência BI"))
                    else "sem BI"
                )
                c1.write(
                    f"{caso['Prioridade']} **{caso['Nome']}** | RA {caso['RA']} | "
                    f"{caso['Dias sem contato']} dias sem contato | Frequência: {freq_txt}"
                )
                if c2.button("Abrir prontuário", key=f"abrir_pront_{caso['RA']}"):
                    st.session_state.ra_selecionado = str(caso["RA"])
                    st.session_state.menu_destino = "Prontuário do Aluno"
                    st.success("RA selecionado! Vá para 'Prontuário do Aluno' no menu lateral.")
                if c3.button("Registrar lembrete", key=f"log_lemb_{caso['RA']}"):
                    registrar_log(
                        "LEMBRETE_CASO_PARADO",
                        f"RA {caso['RA']} | {caso['Dias sem contato']} dias sem contato",
                        nivel="INFO",
                    )
                    st.success("Lembrete registrado no log da nuvem.")
        
