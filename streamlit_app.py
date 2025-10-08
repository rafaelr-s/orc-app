import os
import streamlit as st
from datetime import datetime, timedelta
import pytz
from fpdf import FPDF
import sqlite3
import pandas as pd
from io import BytesIO

# ============================
# Banco SQLite
# ============================
DB_NAME = "orcamentos.db"

def init_db():
    conn = sqlite3.connect(DB_NAME)
    cur = conn.cursor()

    # Tabela orcamentos (com preco_m2_base)
    cur.execute("""
        CREATE TABLE IF NOT EXISTS orcamentos (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            data_hora TEXT,
            cliente_nome TEXT,
            cliente_cnpj TEXT,
            tipo_cliente TEXT,
            estado TEXT,
            frete TEXT,
            tipo_pedido TEXT,
            vendedor_nome TEXT,
            vendedor_tel TEXT,
            vendedor_email TEXT,
            observacao TEXT,
            preco_m2_base REAL
        )
    """)

    # Garante coluna preco_m2_base (migracao)
    try:
        cur.execute("SELECT preco_m2_base FROM orcamentos LIMIT 1")
    except sqlite3.OperationalError:
        cur.execute("ALTER TABLE orcamentos ADD COLUMN preco_m2_base REAL")

    # Tabela itens_confeccionados (agora com preco_unitario)
    cur.execute("""
        CREATE TABLE IF NOT EXISTS itens_confeccionados (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            orcamento_id INTEGER,
            produto TEXT,
            comprimento REAL,
            largura REAL,
            quantidade INTEGER,
            cor TEXT,
            preco_unitario REAL,
            FOREIGN KEY (orcamento_id) REFERENCES orcamentos(id)
        )
    """)

    # Caso a tabela já existisse sem a coluna preco_unitario, tenta alterar
    try:
        cur.execute("SELECT preco_unitario FROM itens_confeccionados LIMIT 1")
    except sqlite3.OperationalError:
        try:
            cur.execute("ALTER TABLE itens_confeccionados ADD COLUMN preco_unitario REAL")
            print("Migração DB: coluna 'preco_unitario' adicionada em itens_confeccionados.")
        except Exception:
            pass

    # Tabela itens_bobinas (já com preco_unitario)
    cur.execute("""
        CREATE TABLE IF NOT EXISTS itens_bobinas (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            orcamento_id INTEGER,
            produto TEXT,
            comprimento REAL,
            largura REAL,
            quantidade INTEGER,
            cor TEXT,
            espessura REAL,
            preco_unitario REAL,
            FOREIGN KEY (orcamento_id) REFERENCES orcamentos(id)
        )
    """)

    conn.commit()
    conn.close()

def salvar_orcamento(cliente, vendedor, itens_confeccionados, itens_bobinas, observacao, preco_m2_base):
    conn = sqlite3.connect(DB_NAME)
    cur = conn.cursor()

    cur.execute("""
        INSERT INTO orcamentos (data_hora, cliente_nome, cliente_cnpj, tipo_cliente, estado, frete, tipo_pedido, vendedor_nome, vendedor_tel, vendedor_email, observacao, preco_m2_base)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        datetime.now(pytz.timezone("America/Sao_Paulo")).strftime("%d/%m/%Y %H:%M"),
        cliente.get("nome",""),
        cliente.get("cnpj",""),
        cliente.get("tipo_cliente",""),
        cliente.get("estado",""),
        cliente.get("frete",""),
        cliente.get("tipo_pedido",""),
        vendedor.get("nome",""),
        vendedor.get("tel",""),
        vendedor.get("email",""),
        observacao,
        preco_m2_base
    ))
    orcamento_id = cur.lastrowid

    # salva confeccionados com preco_unitario
    for item in itens_confeccionados:
        cur.execute("""
            INSERT INTO itens_confeccionados (orcamento_id, produto, comprimento, largura, quantidade, cor, preco_unitario)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        """, (
            orcamento_id,
            item.get('produto',''),
            item.get('comprimento', 0.0),
            item.get('largura', 0.0),
            item.get('quantidade', 0),
            item.get('cor',''),
            item.get('preco_unitario', 0.0)
        ))

    # salva bobinas com preco_unitario (já existia)
    for item in itens_bobinas:
        cur.execute("""
            INSERT INTO itens_bobinas (orcamento_id, produto, comprimento, largura, quantidade, cor, espessura, preco_unitario)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            orcamento_id,
            item.get('produto',''),
            item.get('comprimento', 0.0),
            item.get('largura', 0.0),
            item.get('quantidade', 0),
            item.get('cor',''),
            item.get('espessura'),
            item.get('preco_unitario', 0.0)
        ))

    conn.commit()
    conn.close()
    return orcamento_id

def buscar_orcamentos():
    conn = sqlite3.connect(DB_NAME)
    cur = conn.cursor()
    cur.execute("SELECT id, data_hora, cliente_nome, cliente_cnpj, vendedor_nome FROM orcamentos ORDER BY id DESC")
    rows = cur.fetchall()
    conn.close()
    return rows

def carregar_orcamento_por_id(orcamento_id):
    conn = sqlite3.connect(DB_NAME)
    cur = conn.cursor()
    orc_cols = ['id','data_hora','cliente_nome','cliente_cnpj','tipo_cliente','estado','frete','tipo_pedido','vendedor_nome','vendedor_tel','vendedor_email','observacao','preco_m2_base']
    cur.execute("SELECT * FROM orcamentos WHERE id=?", (orcamento_id,))
    orc = cur.fetchone()
    # inclui preco_unitario ao selecionar confeccionados
    cur.execute("SELECT produto, comprimento, largura, quantidade, cor, preco_unitario FROM itens_confeccionados WHERE orcamento_id=?", (orcamento_id,))
    confecc = cur.fetchall()
    cur.execute("SELECT produto, comprimento, largura, quantidade, cor, espessura, preco_unitario FROM itens_bobinas WHERE orcamento_id=?", (orcamento_id,))
    bob = cur.fetchall()
    conn.close()
    return orc, confecc, bob

# ============================
# Formatação R$
# ============================
def _format_brl(v):
    try:
        return f"R$ {v:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
    except Exception:
        return f"R$ {v}"

# ============================
# Cálculos (usando preco por item quando existir)
# ============================
st_por_estado = {}

def calcular_valores_confeccionados(itens, preco_m2_padrao, tipo_cliente="", estado="", tipo_pedido="Direta"):
    if not itens:
        return 0.0, 0.0, 0.0, 0.0, 0.0, 0

    # m2_total e valor_bruto usam preco por item, se existir
    m2_total = 0.0
    valor_bruto = 0.0
    for item in itens:
        preco_item = item.get('preco_unitario', preco_m2_padrao)
        area_item = item['comprimento'] * item['largura'] * item['quantidade']
        m2_total += area_item
        valor_bruto += area_item * preco_item

    if tipo_pedido == "Industrialização":
        return m2_total, valor_bruto, 0.0, valor_bruto, 0.0, 0

    IPI_CONFECCIONADO_DEFAULT = 0.0325
    IPI_ZERO_PRODS = ["Acrylic", "Agora"]
    IPI_ZERO_PREFIXES = ["Tela de Sombreamento"]

    valor_ipi_acumulado = 0.0
    for item in itens:
        produto = item.get('produto','')
        preco_item = item.get('preco_unitario', preco_m2_padrao)
        area_item = item['comprimento'] * item['largura'] * item['quantidade']
        ipi_rate = IPI_CONFECCIONADO_DEFAULT
        if produto in IPI_ZERO_PRODS or any(produto.startswith(prefix) for prefix in IPI_ZERO_PREFIXES):
            ipi_rate = 0.0
        valor_ipi_acumulado += area_item * preco_item * ipi_rate

    valor_final = valor_bruto + valor_ipi_acumulado

    valor_st = 0.0
    aliquota_st = 0
    if any(item.get('produto') == "Encerado" for item in itens) and tipo_cliente == "Revenda":
        aliquota_st = st_por_estado.get(estado, 0)
        valor_st = valor_final * aliquota_st / 100
        valor_final += valor_st

    return m2_total, valor_bruto, valor_ipi_acumulado, valor_final, valor_st, aliquota_st

def calcular_valores_bobinas(itens, preco_m2_padrao, tipo_pedido="Direta"):
    IPI_RATE_DEFAULT = 0.0975 # 9.75%
    if not itens:
        return 0.0, 0.0, 0.0, 0.0, IPI_RATE_DEFAULT

    m_total = sum(item['comprimento'] * item['quantidade'] for item in itens)

    valor_bruto = 0.0
    for item in itens:
        preco_item = item.get('preco_unitario', preco_m2_padrao)
        valor_bruto += (item['comprimento'] * item['quantidade']) * preco_item

    if tipo_pedido == "Industrialização":
        return m_total, valor_bruto, 0.0, valor_bruto, 0.0

    IPI_RATE_CAPOTA = 0.0325
    has_capota = any(item.get('produto') == "Capota Marítima" for item in itens)
    ipi_rate_to_use = IPI_RATE_CAPOTA if has_capota else IPI_RATE_DEFAULT

    valor_ipi = valor_bruto * ipi_rate_to_use
    valor_final = valor_bruto + valor_ipi

    return m_total, valor_bruto, valor_ipi, valor_final, ipi_rate_to_use

# ============================
# Geração de PDF (usa preco por item)
# ============================
def gerar_pdf(orcamento_id, cliente, vendedor, itens_confeccionados, itens_bobinas, resumo_conf, resumo_bob, observacao, preco_m2, tipo_cliente="", estado=""):
    pdf = FPDF()
    pdf.add_page()
    pdf.set_auto_page_break(auto=True, margin=15)
    pdf.set_font("Arial", "B", 14)

    # Cabeçalho
    pdf.cell(0, 12, "Orçamento - Grupo Locomotiva", ln=True, align="C")
    if orcamento_id:
        pdf.set_font("Arial", "B", 11)
        pdf.cell(0, 6, f"ID do Orçamento: {orcamento_id}", ln=True, align="C")
    pdf.ln(6)

    pdf.set_font("Arial", size=9)
    brasilia_tz = pytz.timezone("America/Sao_Paulo")
    pdf.cell(0, 6, f"Data e Hora: {datetime.now(brasilia_tz).strftime('%d/%m/%Y %H:%M')}", ln=True)
    pdf.cell(0, 6, "Validade da Cotação: 7 dias.", ln=True)
    pdf.ln(4)

    # Cliente
    pdf.set_font("Arial", "B", 11)
    pdf.cell(0, 6, "Cliente", ln=True)
    pdf.set_font("Arial", size=10)
    largura_util = pdf.w - 2*pdf.l_margin
    for chave in ["nome", "cnpj", "tipo_cliente", "estado", "frete", "tipo_pedido"]:
        valor = str(cliente.get(chave, "") or "")
        if valor.strip():
            pdf.cell(0, 6, f"{chave.replace('_',' ').title()}: {valor}", align="L")
            pdf.ln(5)
    pdf.ln(5)

    # Itens Confeccionados (detalhado)
    if itens_confeccionados:
        pdf.set_font("Arial", "B", 11)
        pdf.cell(0, 8, "Itens Confeccionados", ln=True)
        pdf.set_font("Arial", size=8)
        for item in itens_confeccionados:
            area_item = item['comprimento'] * item['largura'] * item['quantidade']
            preco_item = item.get('preco_unitario', preco_m2)
            valor_item = area_item * preco_item
            txt = (
                f"{item['quantidade']}x {item['produto']} - {item['comprimento']:.2f}m x {item['largura']:.2f}m "
                f"= {area_item:.2f} m² × { _format_brl(preco_item) }/m² → {_format_brl(valor_item)}"
            )
            if item.get('cor'):
                txt += f" | Cor: {item.get('cor')}"
            pdf.multi_cell(largura_util, 6, txt)
            pdf.ln(1)

    # Resumo confeccionados
    if resumo_conf:
        m2_total, valor_bruto, valor_ipi, valor_final, valor_st, aliquota_st = resumo_conf
        pdf.ln(3)
        pdf.set_font("Arial", "B", 11)
        pdf.cell(0, 10, "Resumo - Confeccionados", ln=True)
        pdf.set_font("Arial", "", 10)
        pdf.cell(0, 8, f"Área Total: {str(f'{m2_total:.2f}'.replace('.', ','))} m²", ln=True)
        pdf.cell(0, 8, f"Valor Bruto: {_format_brl(valor_bruto)}", ln=True)
        if valor_ipi>0:
            pdf.cell(0, 8, f"IPI: {_format_brl(valor_ipi)}", ln=True)
        if valor_st>0:
            pdf.cell(0, 8, f"ST ({aliquota_st}%): {_format_brl(valor_st)}", ln=True)
        pdf.set_font("Arial", "B", 10)
        pdf.cell(0, 8, f"Valor Total: {_format_brl(valor_final)}", ln=True)
        pdf.ln(6)

    # Itens Bobinas (detalhado)
    if itens_bobinas:
        pdf.set_font("Arial", "B", 11)
        pdf.cell(0, 8, "Itens Bobina", ln=True)
        pdf.set_font("Arial", size=8)
        for item in itens_bobinas:
            metros_item = item['comprimento'] * item['quantidade']
            preco_item = item.get('preco_unitario', preco_m2)
            valor_item = metros_item * preco_item
            txt = (
                f"{item['quantidade']}x {item['produto']} - {item['comprimento']:.2f}m | Largura: {item['largura']:.2f}m "
                f"= {metros_item:.2f} m × { _format_brl(preco_item) }/m → {_format_brl(valor_item)}"
            )
            if item.get('cor'):
                txt += f" | Cor: {item.get('cor')}"
            if 'espessura' in item and item.get('espessura') is not None:
                esp = f"{item['espessura']:.2f}".replace(".", ",")
                txt += f" | Esp: {esp} mm"
            pdf.multi_cell(largura_util, 6, txt)
            pdf.ln(1)

        if resumo_bob:
            m_total, valor_bruto_bob, valor_ipi_bob, valor_final_bob, ipi_rate = resumo_bob
            pdf.ln(3)
            pdf.set_font("Arial", "B", 11)
            pdf.cell(0, 10, "Resumo - Bobinas", ln=True)
            pdf.set_font("Arial", "", 10)
            pdf.cell(0, 8, f"Total de Metros Lineares: {str(f'{m_total:.2f}'.replace('.', ','))} m", ln=True)
            pdf.cell(0, 8, f"Valor Bruto: {_format_brl(valor_bruto_bob)}", ln=True)
            if valor_ipi_bob>0:
                ipi_percent = ipi_rate * 100
                pdf.cell(0, 8, f"IPI ({ipi_percent:.2f}%): {_format_brl(valor_ipi_bob)}", ln=True)
            pdf.set_font("Arial", "B", 10)
            pdf.cell(0, 8, f"Valor Total: {_format_brl(valor_final_bob)}", ln=True)
        pdf.ln(6)

    # Observações
    if observacao:
        pdf.set_font("Arial", "B", 11)
        pdf.cell(0, 11, "Observações", ln=True)
        pdf.set_font("Arial", size=10)
        pdf.multi_cell(largura_util, 10, str(observacao))
        pdf.ln(6)

    # Vendedor
    if vendedor:
        pdf.set_font("Arial", "", 10)
        vendedor_txt = (
            f"Vendedor: {vendedor.get('nome','')}\n"
            f"Telefone: {vendedor.get('tel','')}\n"
            f"E-mail: {vendedor.get('email','')}"
        )
        pdf.multi_cell(largura_util, 8, vendedor_txt)
        pdf.ln(5)

    pdf_bytes = pdf.output(dest='S').encode('latin1')
    return pdf_bytes

# ============================
# Funções utilitárias e reset
# ============================
def reset_novo_orcamento_state():
    st.session_state["Cliente_nome"] = ""
    st.session_state["Cliente_CNPJ"] = ""
    st.session_state["tipo_cliente"] = " "
    st.session_state["estado"] = "SP"
    st.session_state["tipo_pedido"] = "Direta"
    st.session_state["frete_sel"] = "CIF"
    st.session_state["obs"] = ""
    st.session_state["vend_nome"] = ""
    st.session_state["vend_tel"] = ""
    st.session_state["vend_email"] = ""
    if "vendedor_select" in st.session_state:
        st.session_state["vendedor_select"] = VENDEDORES_NOMES[0]
    st.session_state["preco_m2"] = 0.0
    st.session_state["menu_index"] = 0
    st.session_state["produto_sel"] = " "
    st.session_state["tipo_prod_sel"] = "Confeccionado"
    st.session_state["comp_conf"] = 1.0
    st.session_state["larg_conf"] = 1.0
    st.session_state["qtd_conf"] = 1
    st.session_state["comp_bob"] = 50.0
    st.session_state["larg_bob"] = 1.4
    st.session_state["qtd_bob"] = 1
    if "esp_bob" in st.session_state:
        st.session_state["esp_bob"] = 0.10
    st.session_state["itens_confeccionados"] = []
    st.session_state["bobinas_adicionadas"] = []

def reset_historico_filters():
    st.session_state["filtro_cliente"] = "Todos"
    st.session_state["filtro_cnpj"] = "Todos"
    st.session_state["filtro_id"] = ""
    # O Streamlit faz o rerun automaticamente após a função on_click.

# ============================
# Constantes e inicialização
# ============================
VENDEDORES = {
    "Selecione um Vendedor": {"nome": "", "tel": "", "email": ""},
    "Rafael Rodrigues": {"nome": "Rafael Rodrigues", "tel": "11 99150-0804", "email": "rrodrigues@locomotiva.com.br"},
    "Tiago Vitor": {"nome": "Tiago Vitor", "tel": "11 97697-8167", "email": "tvitor@locomotiva.com.br"}
}
VENDEDORES_NOMES = list(VENDEDORES.keys())

def update_vendedor_details():
    selected_name = st.session_state["vendedor_select"]
    details = VENDEDORES.get(selected_name, {"nome": selected_name, "tel": "", "email": ""})
    st.session_state["vend_nome"] = details["nome"]
    st.session_state["vend_tel"] = details["tel"]
    st.session_state["vend_email"] = details["email"]

# ============================
# Funções de Resumo para Exportação Excel
# ============================
def get_order_summary_info(confecc, bob):
    has_conf = len(confecc) > 0
    has_bob = len(bob) > 0
    if has_conf and has_bob:
        tipo_item = "Misto (Conf. e Bobina)"
    elif has_conf:
        tipo_item = "Confeccionado"
    elif has_bob:
        tipo_item = "Bobina"
    else:
        tipo_item = "Nenhum"

    product_counts = {}
    for item in confecc:
        product = item[0]
        quantity = item[3]
        product_counts[product] = product_counts.get(product, 0) + quantity
    for item in bob:
        product = item[0]
        quantity = item[3]
        product_counts[product] = product_counts.get(product, 0) + quantity
    most_selected_product = max(product_counts, key=product_counts.get) if product_counts else ""
    m2_total_conf = sum(item[1] * item[2] * item[3] for item in confecc)
    return tipo_item, most_selected_product, m2_total_conf

# Inicia DB e session_state defaults
init_db()

defaults = {
    "Cliente_nome": "", "Cliente_CNPJ": "", "tipo_cliente": " ",
    "estado": "SP", "tipo_pedido": "Direta", "preco_m2": 0.0,
    "itens_confeccionados": [], "bobinas_adicionadas": [], "frete_sel": "CIF",
    "obs": "", "vend_nome": "", "vend_tel": "", "vend_email": "",
    "menu_index": 0, "filtro_cliente": "Todos", "filtro_cnpj": "Todos",
    "filtro_id": "", "vendedor_select": VENDEDORES_NOMES[0],
    "produto_sel": " "
}
for k, v in defaults.items():
    if k not in st.session_state:
        st.session_state[k] = v
        
# ============================
# Interface Streamlit
# ============================
st.set_page_config(page_title="Calculadora Grupo Locomotiva", page_icon="📏", layout="centered")
st.title("Orçamento - Grupo Locomotiva")

menu_options = ["Novo Orçamento","Histórico de Orçamentos"]
menu = st.sidebar.selectbox("Menu", menu_options, index=st.session_state['menu_index'], key='main_menu_select')
if menu != menu_options[st.session_state['menu_index']]:
    st.session_state['menu_index'] = menu_options.index(menu)

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
if st.session_state.get("estado") not in icms_por_estado:
     st.session_state["estado"] = "SP" 

st_por_estado.update({ 
    "SP": 14, "RJ": 27, "MG": 22, "ES": 0, "PR": 22, "RS": 20, "SC": 0,
    "BA": 29, "PE": 29, "CE": 19, "RN": 0, "PB": 29, "SE": 0, "AL": 29,
    "DF": 29, "GO": 0, "MS": 0, "MT": 22, "AM": 29, "PA": 26, "RO": 0,
    "RR": 27, "AC": 27, "AP": 29, "MA": 29, "PI": 22, "TO": 0
})

# Lista de produtos e prefixos para espessura
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

# ---------- Novo Orçamento ----------
if menu == "Novo Orçamento":
    st.button("🧹 Limpar Formulário", on_click=reset_novo_orcamento_state, key="clear_novo_orc_form")
    st.markdown("---")
    brasilia_tz = pytz.timezone("America/Sao_Paulo")
    data_hora_brasilia = datetime.now(brasilia_tz).strftime("%d/%m/%Y %H:%M")
    st.markdown(f"🕒 **Data e Hora:** {data_hora_brasilia}")

    # Cliente
    st.subheader("👤 Dados do Cliente")
    col1, col2 = st.columns(2)
    with col1:
        Cliente_nome = st.text_input("Razão ou Nome Fantasia", value=st.session_state.get("Cliente_nome",""), key="Cliente_nome")
    with col2:
        Cliente_CNPJ = st.text_input("CNPJ ou CPF (Opcional)", value=st.session_state.get("Cliente_CNPJ",""), key="Cliente_CNPJ")

    # Tipo de pedido, tipo cliente e estado (reordenado conforme arquivo original)
    tipo_pedido = st.radio("Tipo do Pedido:", ["Direta", "Industrialização"],
                          index=0 if st.session_state.get("tipo_pedido","Direta")=="Direta" else 1, key="tipo_pedido")
    tipo_cliente = st.selectbox("Tipo do Cliente:", [" ","Consumidor Final", "Revenda"],
                                index=0 if st.session_state.get("tipo_cliente"," ") == " " else (1 if st.session_state.get("tipo_cliente")=="Consumidor Final" else 2),
                                key="tipo_cliente")
    estado = st.selectbox("Estado do Cliente:", options=list(icms_por_estado.keys()),
                          index=list(icms_por_estado.keys()).index(st.session_state.get("estado")) if st.session_state.get("estado") in icms_por_estado else 0,
                          key="estado")

    # Preço global (utilizado como default no momento da adição; itens gravam seu próprio preço)
    preco_m2 = st.number_input("Preço por m² ou metro linear (R$):", min_value=0.0, value=st.session_state.get("preco_m2",0.0), step=0.01, key="preco_m2")

    # ICMS/ST avisos
    aliquota_icms = icms_por_estado.get(st.session_state.get("estado") or estado)
    st.info(f"🔹 Alíquota de ICMS para {estado}: **{aliquota_icms}% (já incluso no preço)**")
    produto = st.selectbox("Nome do Produto:", options=produtos_lista, index=produtos_lista.index(st.session_state.get("produto_sel")) if st.session_state.get("produto_sel") in produtos_lista else 0, key="produto_sel")
    if produto == "Encerado" and tipo_cliente == "Revenda":
        aliquota_st = st_por_estado.get(estado, 0)
        st.warning(f"⚠️ Este produto possui ST no estado {estado} aproximado a: **{aliquota_st}%**")

    # Tipo do produto
    tipo_produto = st.radio("Tipo do Produto:", ["Confeccionado", "Bobina"], key="tipo_prod_sel")

    # ---------- Confeccionado ----------
    if tipo_produto == "Confeccionado":
        st.subheader("➕ Adicionar Item Confeccionado")
        col1, col2, col3 = st.columns(3)
        with col1:
            comprimento = st.number_input("Comprimento (m):", min_value=0.010, value=st.session_state.get("comp_conf", 1.0), step=0.10, key="comp_conf")
        with col2:
            largura = st.number_input("Largura (m):", min_value=0.010, value=st.session_state.get("larg_conf", 1.0), step=0.10, key="larg_conf")
        with col3:
            quantidade = st.number_input("Quantidade:", min_value=1, value=st.session_state.get("qtd_conf", 1), step=1, key="qtd_conf")

        # Ao adicionar, salvamos preco_unitario naquele item (fixo)
        if st.button("➕ Adicionar Medida", key="add_conf"):
            st.session_state['itens_confeccionados'].append({
                'produto': produto,
                'comprimento': float(comprimento),
                'largura': float(largura),
                'quantidade': int(quantidade),
                'cor': "",
                'preco_unitario': st.session_state.get("preco_m2", 0.0)
            })

        # Lista de itens confeccionados - mostra preço por item
        if st.session_state['itens_confeccionados']:
            st.subheader("📋 Itens Adicionados")
            for idx, item in enumerate(st.session_state['itens_confeccionados'][:]):
                col1, col2, col3, col4 = st.columns([3,2,2,1])
                with col1:
                    area_item = item['comprimento'] * item['largura'] * item['quantidade']
                    preco_item = item.get('preco_unitario', st.session_state.get("preco_m2", 0.0))
                    valor_item = area_item * preco_item
                    st.markdown(f"**{item['produto']}**")
                    st.markdown(
                        f"🔹 {item['quantidade']}x {item['comprimento']:.2f}m x {item['largura']:.2f}m = {area_item:.2f} m² "
                        f"× {_format_brl(preco_item)}/m² → {_format_brl(valor_item)}"
                    )
                with col2:
                    cor = st.text_input("Cor:", value=item['cor'], key=f"cor_conf_{idx}")
                    st.session_state['itens_confeccionados'][idx]['cor'] = cor
                with col4:
                    remover = st.button("❌", key=f"remover_conf_{idx}")
                    if remover:
                        st.session_state['itens_confeccionados'].pop(idx)
                        st.rerun()

        if st.button("🧹 Limpar Itens Confeccionados", key="limpar_conf_list"):
            st.session_state['itens_confeccionados'] = []
            st.rerun()

        # Resumo confeccionados (usar preco por item)
        if st.session_state['itens_confeccionados']:
            m2_total, valor_bruto, valor_ipi, valor_final, valor_st, aliquota_st = calcular_valores_confeccionados(
                st.session_state['itens_confeccionados'], st.session_state.get("preco_m2",0.0), st.session_state.get("tipo_cliente"," "), st.session_state.get("estado",""), st.session_state.get("tipo_pedido","Direta")
            )
            st.markdown("---")
            st.success("💰 **Resumo do Pedido - Confeccionado**")
            st.write(f"📏 Área Total: **{m2_total:.2f} m²**".replace(".", ","))
            st.write(f"💵 Valor Bruto: **{_format_brl(valor_bruto)}**")
            if st.session_state.get("tipo_pedido","Direta") != "Industrialização":
                st.write(f"🧾 IPI: **{_format_brl(valor_ipi)}**")
                if valor_st > 0:
                    st.write(f"⚖️ ST ({aliquota_st}%): **{_format_brl(valor_st)}**")
                st.write(f"💰 Valor Final com IPI{(' + ST' if valor_st>0 else '')}: **{_format_brl(valor_final)}**")
            else:
                st.write(f"💰 Valor Final: **{_format_brl(valor_final)}**")

    # ---------- Bobina ----------
    if tipo_produto == "Bobina":
        st.subheader("➕ Adicionar Bobina")
        col1, col2, col3 = st.columns(3)
        with col1:
            comprimento = st.number_input("Comprimento (m):", min_value=0.010, value=st.session_state.get("comp_bob", 50.0), step=0.10, key="comp_bob")
        with col2:
            largura_bobina = st.number_input("Largura da Bobina (m):", min_value=0.010, value=st.session_state.get("larg_bob", 1.4), step=0.010, key="larg_bob")
        with col3:
            quantidade = st.number_input("Quantidade:", min_value=1, value=st.session_state.get("qtd_bob", 1), step=1, key="qtd_bob")

        espessura_bobina = None
        if produto.startswith(prefixos_espessura):
            espessura_bobina = st.number_input("Espessura da Bobina (mm):", min_value=0.010, value=st.session_state.get("esp_bob", 0.10), step=0.010, key="esp_bob")

        if st.button("➕ Adicionar Bobina", key="add_bob"):
            item_bobina = {
                'produto': produto,
                'comprimento': float(comprimento),
                'largura': float(largura_bobina),
                'quantidade': int(quantidade),
                'cor': "",
                'preco_unitario': st.session_state.get("preco_m2", 0.0)
            }
            if espessura_bobina is not None:
                item_bobina['espessura'] = float(espessura_bobina)
            st.session_state['bobinas_adicionadas'].append(item_bobina)

        if st.session_state['bobinas_adicionadas']:
            st.subheader("📋 Bobinas Adicionadas")
            for idx, item in enumerate(st.session_state['bobinas_adicionadas'][:]):
                col1, col2, col3, col4 = st.columns([4,2,2,1])
                with col1:
                    metros_item = item['comprimento'] * item['quantidade']
                    preco_item = item.get('preco_unitario', st.session_state.get("preco_m2", 0.0))
                    valor_item = metros_item * preco_item
                    detalhes = (
                        f"🔹 {item['quantidade']}x {item['comprimento']:.2f}m | Largura: {item['largura']:.2f}m "
                        f"= {metros_item:.2f} m × {_format_brl(preco_item)}/m → {_format_brl(valor_item)}"
                    )
                    if 'espessura' in item and item.get('espessura') is not None:
                        detalhes += f" | Esp: {item['espessura']:.2f}mm"
                    st.markdown(f"**{item['produto']}**")
                    st.markdown(detalhes)
                with col2:
                    cor = st.text_input("Cor:", value=item['cor'], key=f"cor_bob_{idx}")
                    st.session_state['bobinas_adicionadas'][idx]['cor'] = cor
                with col4:
                    remover = st.button("❌", key=f"remover_bob_{idx}")
                    if remover:
                        st.session_state['bobinas_adicionadas'].pop(idx)
                        st.rerun()

            # resumo bobinas com preco por item
            m_total, valor_bruto_bob, valor_ipi_bob, valor_final_bob, ipi_rate_bob = calcular_valores_bobinas(
                st.session_state['bobinas_adicionadas'], st.session_state.get("preco_m2",0.0), st.session_state.get("tipo_pedido","Direta")
            )
            ipi_percent = ipi_rate_bob * 100
            st.markdown("---")
            st.success("💰 **Resumo do Pedido - Bobinas**")
            st.write(f"📏 Total de Metros Lineares: **{m_total:.2f} m**".replace(".", ","))
            st.write(f"💵 Valor Bruto: **{_format_brl(valor_bruto_bob)}**")
            if st.session_state.get("tipo_pedido","Direta") != "Industrialização":
                st.write(f"🧾 IPI ({ipi_percent:.2f}%): **{_format_brl(valor_ipi_bob)}**")
                st.write(f"💰 Valor Final com IPI ({ipi_percent:.2f}%): **{_format_brl(valor_final_bob)}**")
            else:
                st.write(f"💰 Valor Final: **{_format_brl(valor_final_bob)}**")

            if st.button("🧹 Limpar Bobinas", key="limpar_bob_list"):
                st.session_state['bobinas_adicionadas'] = []
                st.rerun()

    # frete, observacoes e vendedor
    st.markdown("---")
    st.subheader("🚚 Tipo de Frete")
    frete = st.radio("Selecione o tipo de frete:", ["CIF", "FOB"], index=0 if st.session_state.get("frete_sel","CIF")=="CIF" else 1, key="frete_sel")

    st.subheader("🔎 Observações")
    Observacao = st.text_area("Insira aqui alguma observação sobre o orçamento (opcional)", value=st.session_state.get("obs",""), key="obs")

    st.subheader("🗣️ Vendedor(a)")
    current_name = st.session_state.get("vend_nome", "")
    try:
        current_index = VENDEDORES_NOMES.index(current_name)
    except ValueError:
        current_index = 0

    vendedor_selecionado = st.selectbox("Selecione o Vendedor:", options=VENDEDORES_NOMES, index=current_index, key="vendedor_select", on_change=update_vendedor_details)
    if st.session_state["vendedor_select"] != st.session_state.get("vend_nome", ""):
        update_vendedor_details()

    st.markdown("---")
    st.markdown(f"**Nome:** {st.session_state.get('vend_nome')}")
    st.markdown(f"**Telefone:** {st.session_state.get('vend_tel')}")
    st.markdown(f"**E-mail:** {st.session_state.get('vend_email')}")
    st.markdown("---")
    # -----------------------------------------------------

    # Botão gerar e salvar (monta orcamento, salva e gera pdf)
    if st.button("📄 Gerar PDF e Salvar Orçamento", key="gerar_e_salvar"):
        cliente = {
            "nome": st.session_state.get("Cliente_nome",""),
            "cnpj": st.session_state.get("Cliente_CNPJ",""),
            "tipo_cliente": st.session_state.get("tipo_cliente"," "),
            "estado": st.session_state.get("estado",""),
            "frete": st.session_state.get("frete_sel","CIF"),
            "tipo_pedido": st.session_state.get("tipo_pedido","Direta")
        }
        vendedor = {
            "nome": st.session_state.get("vend_nome",""),
            "tel": st.session_state.get("vend_tel",""),
            "email": st.session_state.get("vend_email","")
        }

        orcamento_id = salvar_orcamento(
            cliente,
            vendedor,
            st.session_state["itens_confeccionados"],
            st.session_state["bobinas_adicionadas"],
            st.session_state.get("obs",""),
            st.session_state.get("preco_m2",0.0)
        )
        st.success(f"✅ Orçamento salvo com ID {orcamento_id}")

        resumo_conf = calcular_valores_confeccionados(
            st.session_state["itens_confeccionados"], st.session_state.get("preco_m2",0.0), st.session_state.get("tipo_cliente"," "), st.session_state.get("estado",""), st.session_state.get("tipo_pedido","Direta")
        ) if st.session_state["itens_confeccionados"] else None

        resumo_bob = calcular_valores_bobinas(
            st.session_state["bobinas_adicionadas"], st.session_state.get("preco_m2",0.0), st.session_state.get("tipo_pedido","Direta")
        ) if st.session_state["bobinas_adicionadas"] else None

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

        pdf_path = f"orcamento_{orcamento_id}.pdf"
        try:
            with open(pdf_path, "wb") as f:
                f.write(pdf_bytes)
            st.success(f"✅ PDF salvo em disco: {pdf_path}")
        except Exception as e:
            st.warning(f"⚠️ Não foi possível salvar o PDF no disco: {e}")

        st.download_button("⬇️ Baixar PDF", data=pdf_bytes, file_name=pdf_path, mime="application/pdf", key=f"download_key_{orcamento_id}")

# ---------- Histórico de Orçamentos ----------
if menu == "Histórico de Orçamentos":
    st.subheader("📋 Histórico de Orçamentos Salvos")
    orcamentos = buscar_orcamentos()
    if not orcamentos:
        st.info("Nenhum orçamento encontrado.")
    else:
        clientes = sorted(list({o[2] for o in orcamentos if o[2]}))
        cnpjs = sorted(list({o[3] for o in orcamentos if o[3]}))

        orc_id_filtro = st.text_input("Filtrar por ID do Orçamento:", value=st.session_state.get("filtro_id", ""), key="filtro_id")
        cliente_filtro = st.selectbox("Filtrar por cliente:", ["Todos"] + clientes, key="filtro_cliente")
        cnpj_filtro = st.selectbox("Filtrar por CNPJ:", ["Todos"] + cnpjs, key="filtro_cnpj")
        st.button("🧹 Limpar Filtros", on_click=reset_historico_filters, key="clear_historico_filters")

        datas = [datetime.strptime(o[1], "%d/%m/%Y %H:%M") for o in orcamentos]
        min_data = min(datas) if datas else datetime.now(pytz.timezone("America/Sao_Paulo"))
        max_budget_date = max(datas).date() if datas else datetime.now(pytz.timezone("America/Sao_Paulo")).date()
        max_possible_date = datetime.now(pytz.timezone("America/Sao_Paulo")).date()

        data_inicio, data_fim = st.date_input(
            "Filtrar por intervalo de datas:",
            (min_data.date(), max_budget_date),
            min_value=min_data.date(),
            max_value=max_possible_date,
            key="filtro_datas"
        )

        orcamentos_filtrados = []
        for o in orcamentos:
            orc_id, data_hora, cliente_nome, cliente_cnpj, vendedor_nome = o
            data_obj = datetime.strptime(data_hora, "%d/%m/%Y %H:%M")
            id_ok = True
            if orc_id_filtro:
                if not str(orc_id).startswith(orc_id_filtro):
                    id_ok = False
            cliente_ok = (cliente_filtro == "Todos" or cliente_nome == cliente_filtro)
            cnpj_ok = (cnpj_filtro == "Todos" or cliente_cnpj == cnpj_filtro)
            data_ok = (data_inicio <= data_obj.date() <= data_fim)
            if cliente_ok and cnpj_ok and data_ok and id_ok:
                orcamentos_filtrados.append(o)

        if not orcamentos_filtrados:
            st.warning("Nenhum orçamento encontrado com os filtros selecionados.")
        else:
            # Exportar Excel do Histórico Filtrado
            if st.button("📊 Exportar Excel do Histórico Filtrado"):
                linhas_excel = []
                orc_cols = ['id','data_hora','cliente_nome','cliente_cnpj','tipo_cliente','estado','frete','tipo_pedido','vendedor_nome','vendedor_tel','vendedor_email','observacao','preco_m2_base']
                for o in orcamentos_filtrados:
                    orc_id, data_hora, cliente_nome, cliente_cnpj, vendedor_nome = o
                    orc, confecc, bob = carregar_orcamento_por_id(orc_id)
                    orc_data = dict(zip(orc_cols, orc))
                    preco_m2_base = orc_data.get('preco_m2_base') if orc_data.get('preco_m2_base') is not None else 0.0

                    tipo_item, produto_mais_sel, m2_total_conf = get_order_summary_info(confecc, bob)

                    itens_conf_calc = [dict(zip(['produto','comprimento','largura','quantidade','cor','preco_unitario'], c)) for c in confecc]
                    itens_bob_calc = [dict(zip(['produto','comprimento','largura','quantidade','cor','espessura','preco_unitario'], b)) for b in bob]

                    resumo_conf = calcular_valores_confeccionados(
                        itens_conf_calc, preco_m2_base, orc_data['tipo_cliente'], orc_data['estado'], orc_data['tipo_pedido']
                    ) if itens_conf_calc else (0,0,0,0,0,0)

                    resumo_bob = calcular_valores_bobinas(
                        itens_bob_calc, preco_m2_base, orc_data['tipo_pedido']
                    ) if itens_bob_calc else (0,0,0,0,0.0975)

                    valor_final_total = resumo_conf[3] + resumo_bob[3]

                    linhas_excel.append({
                        "ID": orc_id,
                        "Nome do Cliente": cliente_nome,
                        "CNPJ/CPF": cliente_cnpj,
                        "Tipo do Cliente": orc_data['tipo_cliente'],
                        "Estado": orc_data['estado'],
                        "Frete": orc_data['frete'],
                        "Tipo do Pedido": orc_data['tipo_pedido'],
                        "Produto Mais Selecionado": produto_mais_sel,
                        "Tipo do Item": tipo_item,
                        "Preço Base Utilizado (R$)": preco_m2_base,
                        "Área Total em m² (Confeccionado)": m2_total_conf,
                        "Final Total (R$)": valor_final_total
                    })

                df_excel = pd.DataFrame(linhas_excel)
                excel_bytes = BytesIO()
                df_excel.to_excel(excel_bytes, index=False)
                st.download_button(
                    "⬇️ Baixar Excel",
                    data=excel_bytes.getvalue(),
                    file_name="resumo_orcamentos.xlsx",
                    mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
                )

            # Exibe lista de orçamentos filtrados
            for o in orcamentos_filtrados:
                orc_id, data_hora, cliente_nome, cliente_cnpj, vendedor_nome = o
                orc, confecc, bob = carregar_orcamento_por_id(orc_id)

                orc_cols = ['id','data_hora','cliente_nome','cliente_cnpj','tipo_cliente','estado','frete','tipo_pedido','vendedor_nome','vendedor_tel','vendedor_email','observacao','preco_m2_base']
                orc_data = dict(zip(orc_cols, orc))
                preco_m2_base = orc_data.get('preco_m2_base') if orc_data.get('preco_m2_base') is not None else 0.0

                with st.expander(f"📝 ID {orc_id} - {cliente_nome} ({data_hora})"):
                    st.markdown(f"**Cliente:** {cliente_nome}")
                    st.markdown(f"**CNPJ:** {cliente_cnpj}")
                    st.markdown(f"**Vendedor:** {vendedor_nome}")
                    st.markdown(f"**Preço Base Utilizado (💵):** {_format_brl(preco_m2_base)}")

                    if confecc:
                        st.markdown("### ⬛ Itens Confeccionados")
                        for c in confecc:
                            # c = (produto, comprimento, largura, quantidade, cor, preco_unitario)
                            preco_item = c[5] if c[5] is not None else preco_m2_base
                            st.markdown(f"- **{c[0]}**: {c[3]}x {c[1]:.2f}m x {c[2]:.2f}m | {_format_brl(preco_item)}/m² | Cor: {c[4]}")

                    if bob:
                        st.markdown("### 🔘 Itens Bobinas")
                        for b in bob:
                            # b = (produto, comprimento, largura, quantidade, cor, espessura, preco_unitario)
                            esp = f" | Esp: {b[5]:.2f}mm" if b[5] is not None else ""
                            preco_item = b[6] if b[6] is not None else preco_m2_base
                            st.markdown(f"- **{b[0]}**: {b[3]}x {b[1]:.2f}m | Largura: {b[2]:.2f}m | {_format_brl(preco_item)}/m | Cor: {b[4]}{esp}")

                    col1, col2, col3 = st.columns([1,1,1])
                    with col1:
                        if st.button("🔄 Reabrir", key=f"reabrir_{orc_id}"):
                            primeiro_produto = None
                            if confecc:
                                primeiro_produto = confecc[0][0]
                            elif bob:
                                primeiro_produto = bob[0][0]

                            vendedor_nome_orc = orc[8] or ""
                            if vendedor_nome_orc not in VENDEDORES_NOMES:
                                st.session_state["vendedor_select"] = VENDEDORES_NOMES[0]
                            else:
                                st.session_state["vendedor_select"] = vendedor_nome_orc

                            st.session_state.update({
                                "Cliente_nome": orc[2] or "",
                                "Cliente_CNPJ": orc[3] or "",
                                "tipo_cliente": orc[4] or " ",
                                "estado": orc[5] or list(icms_por_estado.keys())[0],
                                "frete_sel": orc[6] or "CIF",
                                "tipo_pedido": orc[7] or "Direta",
                                "vend_nome": orc[8] or "",
                                "vend_tel": orc[9] or "",
                                "vend_email": orc[10] or "",
                                "obs": orc[11] or "",
                                "preco_m2": preco_m2_base,
                                "produto_sel": primeiro_produto if primeiro_produto else " ",
                                "itens_confeccionados": [dict(zip(['produto','comprimento','largura','quantidade','cor','preco_unitario'],c)) for c in confecc],
                                "bobinas_adicionadas": [dict(zip(['produto','comprimento','largura','quantidade','cor','espessura','preco_unitario'],b)) for b in bob],
                                "menu_index": 0
                            })
                            st.success(f"Orçamento ID {orc_id} carregado no formulário.")
                            st.rerun()

                    with col2:
                        itens_bob_calc = [dict(zip(['produto','comprimento','largura','quantidade','cor','espessura','preco_unitario'], b)) for b in bob]
                        resumo_bob_calc = calcular_valores_bobinas(
                            itens_bob_calc, preco_m2_base, orc_data['tipo_pedido']
                        ) if itens_bob_calc else (0,0,0,0,0.0975)

                        pdf_bytes = gerar_pdf(
                            orc_id,
                            cliente={
                                "nome": orc[2],
                                "cnpj": orc[3],
                                "tipo_cliente": orc[4],
                                "estado": orc[5],
                                "frete": orc[6],
                                "tipo_pedido": orc[7]
                            },
                            vendedor={
                                "nome": orc[8],
                                "tel": orc[9],
                                "email": orc[10]
                            },
                            itens_confeccionados=[dict(zip(['produto','comprimento','largura','quantidade','cor','preco_unitario'],c)) for c in confecc],
                            itens_bobinas=itens_bob_calc,
                            resumo_conf=None,
                            resumo_bob=resumo_bob_calc,
                            observacao=orc[11],
                            preco_m2=preco_m2_base
                        )
                        st.download_button(
                            "📄 Baixar PDF",
                            data=pdf_bytes,
                            file_name=f"orcamento_{orc_id}.pdf",
                            mime="application/pdf",
                            key=f"download_historico_{orc_id}"
                        )
