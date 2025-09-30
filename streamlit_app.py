import os
import streamlit as st
from datetime import datetime
import pytz
from fpdf import FPDF
import sqlite3
import pandas as pd
from io import BytesIO

# ============================
# Banco de Dados
# ============================
def init_db():
    conn = sqlite3.connect("orcamentos.db")
    cur = conn.cursor()

    cur.execute("""
        CREATE TABLE IF NOT EXISTS orcamentos (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            cliente_nome TEXT,
            cliente_cnpj TEXT,
            vendedor_nome TEXT,
            observacao TEXT,
            valor_final REAL,
            data TEXT
        )
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS itens_confeccionados (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            orcamento_id INTEGER,
            produto TEXT,
            quantidade REAL,
            preco_unitario REAL,
            total REAL,
            FOREIGN KEY (orcamento_id) REFERENCES orcamentos (id)
        )
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS itens_bobinas (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            orcamento_id INTEGER,
            produto TEXT,
            metragem REAL,
            preco_metro REAL,
            total REAL,
            FOREIGN KEY (orcamento_id) REFERENCES orcamentos (id)
        )
    """)

    conn.commit()
    conn.close()

# ============================
# Funções do Banco
# ============================
def salvar_orcamento(cliente_nome, cliente_cnpj, vendedor_nome, observacao, valor_final, itens_conf, itens_bobinas):
    conn = sqlite3.connect("orcamentos.db")
    cur = conn.cursor()

    data = datetime.now(pytz.timezone("America/Sao_Paulo")).strftime("%Y-%m-%d %H:%M")

    cur.execute("""
        INSERT INTO orcamentos (cliente_nome, cliente_cnpj, vendedor_nome, observacao, valor_final, data)
        VALUES (?, ?, ?, ?, ?, ?)
    """, (cliente_nome, cliente_cnpj, vendedor_nome, observacao, valor_final, data))
    orcamento_id = cur.lastrowid

    for item in itens_conf:
        cur.execute("""
            INSERT INTO itens_confeccionados (orcamento_id, produto, quantidade, preco_unitario, total)
            VALUES (?, ?, ?, ?, ?)
        """, (orcamento_id, item["produto"], item["quantidade"], item["preco_unitario"], item["total"]))

    for item in itens_bobinas:
        cur.execute("""
            INSERT INTO itens_bobinas (orcamento_id, produto, metragem, preco_metro, total)
            VALUES (?, ?, ?, ?, ?)
        """, (orcamento_id, item["produto"], item["metragem"], item["preco_metro"], item["total"]))

    conn.commit()
    conn.close()
    return orcamento_id

def carregar_orcamentos():
    conn = sqlite3.connect("orcamentos.db")
    cur = conn.cursor()
    cur.execute("SELECT * FROM orcamentos ORDER BY id DESC")
    rows = cur.fetchall()
    conn.close()
    return rows

# ============================
# Exportar Excel
# ============================
def exportar_excel(orcamentos):
    dados_export = []
    for orc in orcamentos:
        dados_export.append({
            "ID Orçamento": orc[0],
            "Cliente": orc[1],
            "CNPJ/CPF": orc[2],
            "Vendedor": orc[3],
            "Observação": orc[4],
            "Valor Final (R$)": orc[5],
            "Data": orc[6],
        })

    df = pd.DataFrame(dados_export)
    output = BytesIO()
    with pd.ExcelWriter(output, engine="openpyxl") as writer:
        df.to_excel(writer, index=False, sheet_name="Orçamentos")
    return output.getvalue()

# ============================
# Gerar PDF
# ============================
def gerar_pdf(orcamento_id, cliente_nome, cliente_cnpj, vendedor_nome, observacao, valor_final, itens_conf, itens_bobinas):
    pdf = FPDF()
    pdf.add_page()

    pdf.set_font("Arial", "B", 14)
    pdf.cell(0, 10, f"Orçamento - Grupo Locomotiva (ID: {orcamento_id})", ln=True, align="C")
    pdf.ln(5)

    pdf.set_font("Arial", "", 12)
    pdf.cell(0, 10, f"Cliente: {cliente_nome}", ln=True)
    pdf.cell(0, 10, f"CNPJ/CPF: {cliente_cnpj}", ln=True)
    pdf.cell(0, 10, f"Vendedor: {vendedor_nome}", ln=True)
    pdf.cell(0, 10, f"Observação: {observacao}", ln=True)
    pdf.ln(5)

    if itens_conf:
        pdf.set_font("Arial", "B", 12)
        pdf.cell(0, 10, "Itens Confeccionados", ln=True)
        pdf.set_font("Arial", "", 11)
        for item in itens_conf:
            pdf.cell(0, 8, f"{item['produto']} - {item['quantidade']} un x R${item['preco_unitario']} = R${item['total']}", ln=True)

    if itens_bobinas:
        pdf.set_font("Arial", "B", 12)
        pdf.cell(0, 10, "Itens Bobinas", ln=True)
        pdf.set_font("Arial", "", 11)
        for item in itens_bobinas:
            pdf.cell(0, 8, f"{item['produto']} - {item['metragem']} m x R${item['preco_metro']} = R${item['total']}", ln=True)

    pdf.ln(5)
    pdf.set_font("Arial", "B", 12)
    pdf.cell(0, 10, f"Valor Final: R$ {valor_final}", ln=True)

    pdf_bytes = BytesIO()
    pdf.output(pdf_bytes, "F")
    pdf_bytes.seek(0)
    return pdf_bytes

# ============================
# App Streamlit
# ============================
def main():
    st.sidebar.title("Menu")
    menu = st.sidebar.radio("Navegação", ["Novo Orçamento", "📋 Histórico de Orçamentos"])

    init_db()

    if menu == "Novo Orçamento":
        st.title("Orçamento - Grupo Locomotiva")

        cliente_nome = st.text_input("Nome do Cliente")
        cliente_cnpj = st.text_input("CNPJ/CPF do Cliente")
        vendedor_nome = st.text_input("Nome do Vendedor")
        observacao = st.text_area("Observações")

        st.subheader("Itens Confeccionados")
        itens_conf = []
        if st.button("Adicionar Item Confeccionado"):
            itens_conf.append({"produto": "Lona Confeccionada", "quantidade": 10, "preco_unitario": 50, "total": 500})

        st.subheader("Itens Bobinas")
        itens_bobinas = []
        if st.button("Adicionar Item Bobina"):
            itens_bobinas.append({"produto": "Bobina PVC", "metragem": 20, "preco_metro": 30, "total": 600})

        valor_final = sum(item["total"] for item in itens_conf) + sum(item["total"] for item in itens_bobinas)

        st.subheader("Resumo do Orçamento")
        st.write(f"Cliente: {cliente_nome}")
        st.write(f"CNPJ/CPF: {cliente_cnpj}")
        st.write(f"Vendedor: {vendedor_nome}")
        st.write(f"Observação: {observacao}")
        st.write(f"Valor Final: R$ {valor_final}")

        if st.button("Salvar Orçamento"):
            orcamento_id = salvar_orcamento(cliente_nome, cliente_cnpj, vendedor_nome, observacao, valor_final, itens_conf, itens_bobinas)
            st.success(f"Orçamento {orcamento_id} salvo com sucesso!")

            pdf_bytes = gerar_pdf(orcamento_id, cliente_nome, cliente_cnpj, vendedor_nome, observacao, valor_final, itens_conf, itens_bobinas)
            st.download_button("⬇️ Baixar PDF", pdf_bytes, file_name=f"orcamento_{orcamento_id}.pdf")

    elif menu == "📋 Histórico de Orçamentos":
        st.title("📋 Histórico de Orçamentos Salvos")
        orcamentos = carregar_orcamentos()

        if orcamentos:
            df = pd.DataFrame(orcamentos, columns=["ID", "Cliente", "CNPJ/CPF", "Vendedor", "Observação", "Valor Final", "Data"])

            # ---- Filtros ----
            with st.expander("🔎 Filtros de Busca"):
                cliente_filtro = st.text_input("Buscar por Cliente", key="filtro_cliente")
                cnpj_filtro = st.text_input("Buscar por CNPJ/CPF", key="filtro_cnpj")
                col1, col2 = st.columns(2)
                with col1:
                    data_inicio = st.date_input("Data Inicial", value=None, key="filtro_data_ini")
                with col2:
                    data_fim = st.date_input("Data Final", value=None, key="filtro_data_fim")

                if st.button("Limpar Filtros"):
                    st.session_state["filtro_cliente"] = ""
                    st.session_state["filtro_cnpj"] = ""
                    st.session_state["filtro_data_ini"] = None
                    st.session_state["filtro_data_fim"] = None
                    st.experimental_rerun()

            # Aplicar filtros
            if cliente_filtro:
                df = df[df["Cliente"].str.contains(cliente_filtro, case=False, na=False)]
            if cnpj_filtro:
                df = df[df["CNPJ/CPF"].str.contains(cnpj_filtro, case=False, na=False)]
            if data_inicio and data_fim:
                df["Data_fmt"] = pd.to_datetime(df["Data"], errors="coerce")
                df = df[(df["Data_fmt"].dt.date >= data_inicio) & (df["Data_fmt"].dt.date <= data_fim)]
                df.drop(columns=["Data_fmt"], inplace=True)

            st.dataframe(df)

            excel_file = exportar_excel(df.values.tolist())
            st.download_button("⬇️ Exportar Excel", excel_file, file_name="orcamentos.xlsx")

        else:
            st.info("Nenhum orçamento salvo até o momento.")

if __name__ == "__main__":
    main()

# ============================
# Função de formatação R$
# ============================
def _format_brl(v):
    try:
        return f"R$ {v:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
    except Exception:
        return f"R$ {v}"

# ============================
# Cálculos (pequenas proteções)
# ============================
st_por_estado = {}

def calcular_valores_confeccionados(itens, preco_m2, tipo_cliente="", estado="", tipo_pedido="Direta"):
    if not itens:
        return 0.0, 0.0, 0.0, 0.0, 0.0, 0
    m2_total = sum(item['comprimento'] * item['largura'] * item['quantidade'] for item in itens)
    valor_bruto = m2_total * preco_m2

    if tipo_pedido == "Industrialização":
        valor_ipi = 0
        valor_st = 0
        aliquota_st = 0
        valor_final = valor_bruto
    else:
        valor_ipi = valor_bruto * 0.0325
        valor_final = valor_bruto + valor_ipi
        valor_st = 0
        aliquota_st = 0
        if any(item.get('produto') == "Encerado" for item in itens) and tipo_cliente == "Revenda":
            aliquota_st = st_por_estado.get(estado, 0)
            valor_st = valor_final * aliquota_st / 100
            valor_final += valor_st

    return m2_total, valor_bruto, valor_ipi, valor_final, valor_st, aliquota_st


def calcular_valores_bobinas(itens, preco_m2, tipo_pedido="Direta"):
    if not itens:
        return 0.0, 0.0, 0.0, 0.0

    produtos_sem_ipi = ["Acrylic", "Agora", "Tela de Sombreamento", "Encerado"]

    m_total = sum(item['comprimento'] * item['quantidade'] for item in itens)

    def preco_item_of(item):
        pu = item.get('preco_unitario')
        return pu if (pu is not None) else preco_m2

    valor_bruto = sum((item['comprimento'] * item['quantidade']) * preco_item_of(item) for item in itens)

    # Verifica se algum item está isento de IPI
    if tipo_pedido == "Industrialização" or all(item['produto'] in produtos_sem_ipi for item in itens):
        valor_ipi = 0
        valor_final = valor_bruto
    else:
        valor_ipi = valor_bruto * 0.0975
        valor_final = valor_bruto + valor_ipi

    return m_total, valor_bruto, valor_ipi, valor_final

# ============================
# Tabelas de ICMS e ST
# ============================
icms_por_estado = {
    "SP": 18, "MG": 12, "PR": 12, "RJ": 12, "RS": 12, "SC": 12
}
todos_estados = [
    "AC","AL","AM","AP","BA","CE","DF","ES","GO","MA","MT","MS",
    "PA","PB","PE","PI","RN","RO","RR","SE","TO"
]
for uf in todos_estados:
    if uf not in icms_por_estado:
        icms_por_estado[uf] = 7

st_por_estado = {
    "SP": 14, "RJ": 27, "MG": 22, "ES": 0, "PR": 22, "RS": 20, "SC": 0,
    "BA": 29, "PE": 29, "CE": 19, "RN": 0, "PB": 29, "SE": 0, "AL": 29,
    "DF": 29, "GO": 0, "MS": 0, "MT": 22, "AM": 29, "PA": 26, "RO": 0,
    "RR": 27, "AC": 27, "AP": 29, "MA": 29, "PI": 22, "TO": 0
}

# ============================
# Página - Novo Orçamento
# ============================
if menu == "Novo Orçamento":
    brasilia_tz = pytz.timezone("America/Sao_Paulo")
    data_hora_brasilia = datetime.now(brasilia_tz).strftime("%d/%m/%Y %H:%M")
    st.markdown(f"🕒 **Data e Hora:** {data_hora_brasilia}")

    # Se existe pedido para reabrir um orçamento, carrega os dados no session_state (evita conflito no DOM)
    if st.session_state.get("reabrir_id") is not None and st.session_state.get("menu_selected") == "Novo Orçamento":
        orc_id_to_reopen = st.session_state.get("reabrir_id")
        orc, confecc, bob = carregar_orcamento_por_id(orc_id_to_reopen)
        if orc:
            st.session_state["Cliente_nome"] = orc[2] or ""
            st.session_state["Cliente_CNPJ"] = orc[3] or ""
            st.session_state["tipo_cliente"] = orc[4] or " "
            st.session_state["estado"] = orc[5] or list(icms_por_estado.keys())[0]
            st.session_state["frete_sel"] = orc[6] or "CIF"
            st.session_state["tipo_pedido"] = orc[7] or "Direta"
            st.session_state["vend_nome"] = orc[8] or ""
            st.session_state["obs"] = orc[11] or ""
            st.session_state["preco_m2"] = float(orc[12]) if len(orc) > 12 and orc[12] is not None else 0.0

            st.session_state["itens_confeccionados"] = [
                {
                    "produto": c[0],
                    "comprimento": float(c[1]),
                    "largura": float(c[2]),
                    "quantidade": int(c[3]),
                    "cor": c[4] or "",
                }
                for c in confecc
            ] if confecc else []

            st.session_state["bobinas_adicionadas"] = [
                {
                    "produto": b[0],
                    "comprimento": float(b[1]),
                    "largura": float(b[2]),
                    "quantidade": int(b[3]),
                    "cor": b[4] or "",
                    "espessura": float(b[5]) if b[5] is not None else None,
                    "preco_unitario": float(b[6]) if b[6] is not None else None,
                }
                for b in bob
            ] if bob else []

        # Limpa a flag para não recarregar novamente
        st.session_state["reabrir_id"] = None

    # Cliente
    st.subheader("👤 Dados do Cliente")
    col1, col2 = st.columns(2)
    with col1:
        Cliente_nome = st.text_input("Razão ou Nome Fantasia", value=st.session_state.get("Cliente_nome",""), key="Cliente_nome")
    with col2:
        Cliente_CNPJ = st.text_input("CNPJ ou CPF (Opcional)", value=st.session_state.get("Cliente_CNPJ",""), key="Cliente_CNPJ")

    tipo_cliente = st.selectbox("Tipo do Cliente:", [" ","Consumidor Final", "Revenda"], index=0 if st.session_state.get("tipo_cliente"," ") == " " else (1 if st.session_state.get("tipo_cliente")=="Consumidor Final" else 2), key="tipo_cliente")
    estado = st.selectbox("Estado do Cliente:", options=list(icms_por_estado.keys()), index=list(icms_por_estado.keys()).index(st.session_state.get("estado")) if st.session_state.get("estado") in icms_por_estado else 0, key="estado")

    tipo_pedido = st.radio("Tipo do Pedido:", ["Direta", "Industrialização"], index=0 if st.session_state.get("tipo_pedido","Direta")=="Direta" else 1, key="tipo_pedido")

    produtos_lista = [
        " ","Lonil de PVC","Lonil KP","Lonil Inflável KP","Encerado","Duramax",
        "Lonaleve","Sider Truck Teto","Sider Truck Lateral","Capota Marítima",
        "Night&Day Plus 1,40","Night&Day Plus 2,00","Night&Day Listrado","Vitro 0,40",
        "Vitro 0,50","Vitro 0,60","Vitro 0,80","Vitro 1,00","Durasol","Poli Light",
        "Sunset","Tenda","Tenda 2,3x2,3","Acrylic","Agora","Lona Galpão Teto",
        "Lona Galpão Lateral","Tela de Sombreamento 30%","Tela de Sombreamento 50%",
        "Tela de Sombreamento 80%","Geomembrana RV 0,42","Geomembrana RV 0,80",
        "Geomembrana RV 1,00","Geomembrana ATX 0,80","Geomembrana ATX 1,00",
        "Geomembrana ATX 1,50","Geo Bio s/ reforço 1,00","Geo Bio s/ reforço 1,20",
        "Geo Bio s/ reforço 1,50","Geo Bio c/ reforço 1,20","Cristal com Pó",
        "Cristal com Papel","Cristal Colorido","Filme Liso","Filme Kamurcinha",
        "Filme Verniz","Block Lux","Filme Dimension","Filme Sarja","Filme Emborrachado",
        "Filme Pneumático","Adesivo Branco Brilho 0,08","Adesivo Branco Brilho 0,10",
        "Adesivo Branco Fosco 0,10","Adesivo Preto Brilho 0,08","Adesivo Preto Fosco 0,10",
        "Adesivo Transparente Brilho 0,08","Adesivo Transparente Jateado 0,08",
        "Adesivo Mascara Brilho 0,08","Adesivo Aço Escovado 0,08"
    ]

    prefixos_espessura = ("Geomembrana", "Geo", "Vitro", "Cristal", "Filme", "Adesivo", "Block Lux")

    # Seleção de Produto (interface para adicionar)
    st.markdown("---")
    st.subheader("➕ Adicionar Produto")
    produto = st.selectbox("Nome do Produto:", options=produtos_lista, key="produto_sel")
    tipo_produto = st.radio("Tipo do Produto:", ["Confeccionado", "Bobina"], key="tipo_prod_sel")
    preco_m2 = st.number_input("Preço por m² ou metro linear (R$):", min_value=0.0, value=st.session_state.get("preco_m2",0.0), step=0.01, key="preco_m2")

    # ICMS automático
    aliquota_icms = icms_por_estado.get(st.session_state.get("estado") or estado)
    st.info(f"🔹 Alíquota de ICMS para {estado}: **{aliquota_icms}% (já incluso no preço)**")

    # ST aviso
    if produto == "Encerado" and tipo_cliente == "Revenda":
        aliquota_st = st_por_estado.get(estado, 0)
        st.warning(f"⚠️ Este produto possui ST no estado {estado} aproximado a: **{aliquota_st}%**")

    # Confeccionado
    if tipo_produto == "Confeccionado":
        st.subheader("➕ Adicionar Item Confeccionado")
        col1, col2, col3 = st.columns(3)
        with col1:
            comprimento = st.number_input("Comprimento (m):", min_value=0.010, value=1.0, step=0.10, key="comp_conf")
        with col2:
            largura = st.number_input("Largura (m):", min_value=0.010, value=1.0, step=0.10, key="larg_conf")
        with col3:
            quantidade = st.number_input("Quantidade:", min_value=1, value=1, step=1, key="qtd_conf")

        if st.button("➕ Adicionar Medida", key="add_conf"):
            st.session_state['itens_confeccionados'].append({
                'produto': produto,
                'comprimento': float(comprimento),
                'largura': float(largura),
                'quantidade': int(quantidade),
                'cor': ""
            })
            st.rerun()

        if st.session_state['itens_confeccionados']:
            st.subheader("📋 Itens Adicionados")
            to_remove_conf = None  # marcar item a remover
            for idx, item in enumerate(st.session_state['itens_confeccionados'][:] ):
                col1, col2, col3, col4 = st.columns([3,2,2,1])
                with col1:
                    area_item = item['comprimento'] * item['largura'] * item['quantidade']
                    valor_item = area_item * preco_m2
                    st.markdown(f"**{item['produto']}**")
                    st.markdown(
                        f"🔹 {item['quantidade']}x {item['comprimento']:.2f}m x {item['largura']:.2f}m "
                        f"= {area_item:.2f} m² → {_format_brl(valor_item)}"
                    )
                with col2:
                    cor = st.text_input("Cor:", value=item['cor'], key=f"cor_conf_{idx}")
                    st.session_state['itens_confeccionados'][idx]['cor'] = cor
                with col4:
                    if st.button("❌", key=f"remover_conf_{idx}"):
                        to_remove_conf = idx

            # só remover e rerun depois do loop
            if to_remove_conf is not None:
                st.session_state['itens_confeccionados'].pop(to_remove_conf)
                st.rerun()

        if st.button("🧹 Limpar Itens", key="limpar_conf"):
            st.session_state['itens_confeccionados'] = []
            st.rerun()

        if st.session_state['itens_confeccionados']:
            m2_total, valor_bruto, valor_ipi, valor_final, valor_st, aliquota_st = calcular_valores_confeccionados(
                st.session_state['itens_confeccionados'], preco_m2, tipo_cliente, estado, tipo_pedido
            )
            st.markdown("---")
            st.success("💰 **Resumo do Pedido - Confeccionado**")
            st.write(f"📏 Área Total: **{m2_total:.2f} m²**".replace(".", ","))
            st.write(f"💵 Valor Bruto: **{_format_brl(valor_bruto)}**")
            if tipo_pedido != "Industrialização":
                st.write(f"🧾 IPI (3.25%): **{_format_brl(valor_ipi)}**")
                if valor_st > 0:
                    st.write(f"⚖️ ST ({aliquota_st}%): **{_format_brl(valor_st)}**")
                st.write(f"💰 Valor Final com IPI{(' + ST' if valor_st>0 else '')}: **{_format_brl(valor_final)}**")
            else:
                st.write(f"💰 Valor Final: **{_format_brl(valor_final)}**")

    # Bobina
    if tipo_produto == "Bobina":
        st.subheader("➕ Adicionar Bobina")
        col1, col2, col3 = st.columns(3)
        with col1:
            comprimento = st.number_input("Comprimento (m):", min_value=0.010, value=50.0, step=0.10, key="comp_bob")
        with col2:
            largura_bobina = st.number_input("Largura da Bobina (m):", min_value=0.010, value=1.4, step=0.010, key="larg_bob")
        with col3:
            quantidade = st.number_input("Quantidade:", min_value=1, value=1, step=1, key="qtd_bob")

        espessura_bobina = None
        if produto.startswith(prefixos_espessura):
            espessura_bobina = st.number_input("Espessura da Bobina (mm):", min_value=0.010, value=0.10, step=0.010, key="esp_bob")

        if st.button("➕ Adicionar Bobina", key="add_bob"):
            item_bobina = {
                'produto': produto,
                'comprimento': float(comprimento),
                'largura': float(largura_bobina),
                'quantidade': int(quantidade),
                'cor': "",
                'espessura': float(espessura_bobina) if espessura_bobina is not None else None,
                'preco_unitario': preco_m2
            }
            st.session_state['bobinas_adicionadas'].append(item_bobina)
            st.rerun()

        if st.session_state['bobinas_adicionadas']:
            st.subheader("📋 Bobinas Adicionadas")
            to_remove_bob = None
            for idx, item in enumerate(st.session_state['bobinas_adicionadas'][:] ):
                metros_item = item['comprimento'] * item['quantidade']
                preco_item = item.get('preco_unitario') if item.get('preco_unitario') is not None else preco_m2
                valor_item = metros_item * preco_item

                col1, col2, col3 = st.columns([4, 3, 1])
                with col1:
                    st.markdown(f"**{item['produto']}**")
                    st.markdown(
                        f"🔹 {item['quantidade']}x {item['comprimento']:.2f} m "
                        f"→ {metros_item:.2f} m | {_format_brl(valor_item)}"
                    )
                with col2:
                    cor = st.text_input("Cor:", value=item['cor'], key=f"cor_bob_{idx}")
                    st.session_state['bobinas_adicionadas'][idx]['cor'] = cor
                with col3:
                    if st.button("❌", key=f"remover_bob_{idx}"):
                        to_remove_bob = idx

            # remover apenas após o loop
            if to_remove_bob is not None:
                st.session_state['bobinas_adicionadas'].pop(to_remove_bob)
                st.rerun()

            # botão de limpar deve ficar fora do loop (único widget com a key "limpar_bob")
            if st.button("🧹 Limpar Bobinas", key="limpar_bob"):
                st.session_state['bobinas_adicionadas'] = []
                st.rerun()

        if st.session_state['bobinas_adicionadas']:
            m_total, valor_bruto, valor_ipi, valor_final = calcular_valores_bobinas(
                st.session_state['bobinas_adicionadas'], preco_m2, tipo_pedido
            )
            st.markdown("---")
            st.success("💰 **Resumo do Pedido - Bobinas**")
            st.write(f"📏 Total de Metros: **{m_total:.2f} m**".replace(".", ","))
            st.write(f"💵 Valor Bruto: **{_format_brl(valor_bruto)}**")
            if tipo_pedido != "Industrialização":
                st.write(f"🧾 IPI (9.75%): **{_format_brl(valor_ipi)}**")
                st.write(f"💰 Valor Final com IPI: **{_format_brl(valor_final)}**")
            else:
                st.write(f"💰 Valor Final: **{_format_brl(valor_final)}**")
                

    # Tipo de frete / observações / vendedor (com chaves para session_state)
    st.markdown("---")
    st.subheader("🚚 Tipo de Frete")
    frete = st.radio("Selecione o tipo de frete:", ["CIF", "FOB"], index=0 if st.session_state.get("frete_sel","CIF")=="CIF" else 1, key="frete_sel")

    st.subheader("🔎 Observações")
    Observacao = st.text_area("Insira aqui alguma observação sobre o orçamento (opcional)", value=st.session_state.get("obs",""), key="obs")

    st.subheader("🗣️ Vendedor(a)")
    col1, col2 = st.columns(2)
    with col1:
        vendedor_nome = st.text_input("Nome", value=st.session_state.get("vend_nome",""), key="vend_nome")
        vendedor_tel = st.text_input("Telefone", value=st.session_state.get("vend_tel",""), key="vend_tel")
    with col2:
        vendedor_email = st.text_input("E-mail", value=st.session_state.get("vend_email",""), key="vend_email")

    # Botão gerar e salvar
    if st.button("📄 Gerar PDF e Salvar Orçamento", key="gerar_e_salvar"):
        cliente = {
            "nome": st.session_state.get("Cliente_nome",""),
            "cnpj": st.session_state.get("Cliente_CNPJ",""),
            "tipo_cliente": st.session_state.get("tipo_cliente"," "),
            "estado": st.session_state.get("estado", ""),
            "frete": st.session_state.get("frete_sel","CIF"),
            "tipo_pedido": st.session_state.get("tipo_pedido","Direta")
        }
        vendedor = {
            "nome": st.session_state.get("vend_nome",""),
            "tel": st.session_state.get("vend_tel",""),
            "email": st.session_state.get("vend_email","")
        }

        # Salvar (agora passando preco_m2)
        orcamento_id = salvar_orcamento(
            cliente,
            vendedor,
            st.session_state["itens_confeccionados"],
            st.session_state["bobinas_adicionadas"],
            st.session_state.get("obs",""),
            preco_m2=st.session_state.get("preco_m2", 0.0)
        )
        st.success(f"✅ Orçamento salvo com ID {orcamento_id}")

        # Resumos
        resumo_conf = calcular_valores_confeccionados(st.session_state["itens_confeccionados"], st.session_state.get("preco_m2",0.0), st.session_state.get("tipo_cliente"," "), st.session_state.get("estado",""), st.session_state.get("tipo_pedido","Direta")) if st.session_state["itens_confeccionados"] else None
        resumo_bob = calcular_valores_bobinas(st.session_state["bobinas_adicionadas"], st.session_state.get("preco_m2",0.0), st.session_state.get("tipo_pedido","Direta")) if st.session_state["bobinas_adicionadas"] else None

        # Gerar PDF bytes (agora passando orcamento_id como primeiro arg)
        pdf_bytes = gerar_pdf(
            orcamento_id,
            cliente,
            vendedor,
            st.session_state["itens_confeccionados"],
            st.session_state["bobinas_adicionadas"],
            resumo_conf,
            resumo_bob,
            st.session_state.get("obs",""),
            st.session_state.get("preco_m2",0.0),
            tipo_cliente=st.session_state.get("tipo_cliente"," "),
            estado=st.session_state.get("estado","")
        )

        # Salvar no disco
        pdf_path = f"orcamento_{orcamento_id}.pdf"
        with open(pdf_path, "wb") as f:
            f.write(pdf_bytes)
        st.success(f"✅ PDF salvo em disco: {pdf_path}")

        # Download button (único key por orçamento)
        st.download_button(
            "⬇️ Baixar PDF",
            data=pdf_bytes,
            file_name=pdf_path,
            mime="application/pdf",
            key=f"download_generated_{orcamento_id}"
        )
st.markdown("🔒 Os dados acima são apenas para inclusão no orçamento (PDF ou impressão futura).")

            # Botão exportar Excel (fora do loop, exporta os filtrados)
            excel_file = exportar_excel(orcamentos_filtrados if orcamentos_filtrados else orcamentos)
            st.download_button(
                "📊 Exportar Relatório Excel",
                data=excel_file,
                file_name="relatorio_orcamentos.xlsx",
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
            )
