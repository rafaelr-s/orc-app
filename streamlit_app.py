import streamlit as st
from datetime import datetime
import pytz
from fpdf import FPDF
from io import BytesIO
import sqlite3

# ============================
# Banco SQLite
# ============================
def init_db():
    conn = sqlite3.connect("orcamentos.db")
    cur = conn.cursor()
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
            observacao TEXT
        )
    """)
    cur.execute("""
        CREATE TABLE IF NOT EXISTS itens_confeccionados (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            orcamento_id INTEGER,
            produto TEXT,
            comprimento REAL,
            largura REAL,
            quantidade INTEGER,
            cor TEXT,
            FOREIGN KEY (orcamento_id) REFERENCES orcamentos(id)
        )
    """)
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

def salvar_orcamento(cliente, vendedor, itens_confeccionados, itens_bobinas, observacao):
    conn = sqlite3.connect("orcamentos.db")
    cur = conn.cursor()

    cur.execute("""
        INSERT INTO orcamentos (data_hora, cliente_nome, cliente_cnpj, tipo_cliente, estado, frete, tipo_pedido, vendedor_nome, vendedor_tel, vendedor_email, observacao)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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
        observacao
    ))
    orcamento_id = cur.lastrowid

    for item in itens_confeccionados:
        cur.execute("""
            INSERT INTO itens_confeccionados (orcamento_id, produto, comprimento, largura, quantidade, cor)
            VALUES (?, ?, ?, ?, ?, ?)
        """, (orcamento_id, item['produto'], item['comprimento'], item['largura'], item['quantidade'], item.get('cor','')))

    for item in itens_bobinas:
        cur.execute("""
            INSERT INTO itens_bobinas (orcamento_id, produto, comprimento, largura, quantidade, cor, espessura, preco_unitario)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """, (orcamento_id, item['produto'], item['comprimento'], item['largura'], item['quantidade'], item.get('cor',''), item.get('espessura'), item.get('preco_unitario')))

    conn.commit()
    conn.close()
    return orcamento_id

def buscar_orcamentos():
    conn = sqlite3.connect("orcamentos.db")
    cur = conn.cursor()
    cur.execute("SELECT id, data_hora, cliente_nome, vendedor_nome FROM orcamentos ORDER BY id DESC")
    rows = cur.fetchall()
    conn.close()
    return rows

def carregar_orcamento_por_id(orcamento_id):
    conn = sqlite3.connect("orcamentos.db")
    cur = conn.cursor()
    cur.execute("SELECT * FROM orcamentos WHERE id=?", (orcamento_id,))
    orc = cur.fetchone()
    cur.execute("SELECT produto, comprimento, largura, quantidade, cor FROM itens_confeccionados WHERE orcamento_id=?", (orcamento_id,))
    confecc = cur.fetchall()
    cur.execute("SELECT produto, comprimento, largura, quantidade, cor, espessura, preco_unitario FROM itens_bobinas WHERE orcamento_id=?", (orcamento_id,))
    bob = cur.fetchall()
    conn.close()
    return orc, confecc, bob

# ============================
# Formatação R$
# ============================
def _format_brl(v):
    return f"R$ {v:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")

# ============================
# Gerar PDF
# ============================
def gerar_pdf(cliente, vendedor, itens_confeccionados, itens_bobinas, observacao, preco_m2):
    pdf = FPDF()
    pdf.add_page()
    pdf.set_auto_page_break(auto=True, margin=15)
    pdf.set_font("Arial", "B", 14)

    # Cabeçalho
    pdf.cell(0, 12, "Orçamento - Grupo Locomotiva", ln=True, align="C")
    pdf.ln(10)
    pdf.set_font("Arial", size=9)
    brasilia_tz = pytz.timezone("America/Sao_Paulo")
    pdf.cell(0, 6, f"Data e Hora: {datetime.now(brasilia_tz).strftime('%d/%m/%Y %H:%M')}", ln=True)
    pdf.cell(0, 6, "Validade da Cotação: 7 dias corridos.", ln=True, align="L")
    pdf.ln(4)

    # Dados Cliente
    pdf.set_font("Arial", "B", 11)
    pdf.cell(0, 6, "Cliente", ln=True)
    pdf.set_font("Arial", size=10)
    largura_util = pdf.w - 2*pdf.l_margin
    for chave, nome in [("nome","Nome"),("cnpj","CNPJ"),("tipo_cliente","Tipo Cliente"),("estado","Estado"),("frete","Frete"),("tipo_pedido","Tipo Pedido")]:
        valor = cliente.get(chave,"")
        if valor:
            pdf.cell(0, 6, f"{nome}: {valor}", ln=True)
    pdf.ln(5)

    # Itens Confeccionados
    if itens_confeccionados:
        pdf.set_font("Arial", "B", 11)
        pdf.cell(0, 8, "Itens Confeccionados", ln=True)
        pdf.set_font("Arial", size=8)
        for item in itens_confeccionados:
            txt = f"{item[0]} - {item[1]}x{item[2]} m | Qtd: {item[3]} | Cor: {item[4]}"
            pdf.multi_cell(largura_util, 6, txt)
            pdf.ln(1)

    # Itens Bobinas
    if itens_bobinas:
        pdf.set_font("Arial", "B", 11)
        pdf.cell(0, 8, "Itens Bobina", ln=True)
        pdf.set_font("Arial", size=8)
        for item in itens_bobinas:
            txt = f"{item[0]} - {item[1]}x{item[2]} m | Qtd: {item[3]} | Cor: {item[4]}"
            if item[5]:
                txt += f" | Esp: {item[5]} mm | Preço: {_format_brl(item[6])}"
            pdf.multi_cell(largura_util, 6, txt)
            pdf.ln(1)

    # Observações
    if observacao:
        pdf.set_font("Arial", "B", 11)
        pdf.cell(0, 11, "Observações", ln=True)
        pdf.set_font("Arial", size=10)
        pdf.multi_cell(largura_util, 10, observacao)
        pdf.ln(10)

    # Vendedor
    pdf.set_font("Arial", "", 10)
    pdf.multi_cell(largura_util, 8, f"Vendedor: {vendedor.get('nome','')}\nTelefone: {vendedor.get('tel','')}\nE-mail: {vendedor.get('email','')}")
    pdf.ln(5)

    buffer = BytesIO()
    pdf.output(buffer)
    buffer.seek(0)
    return buffer

# ============================
# Inicialização
# ============================
init_db()
if "itens_confeccionados" not in st.session_state:
    st.session_state["itens_confeccionados"] = []
if "bobinas_adicionadas" not in st.session_state:
    st.session_state["bobinas_adicionadas"] = []

# ============================
# Streamlit UI
# ============================
st.set_page_config(page_title="Calculadora Grupo Locomotiva", page_icon="📏", layout="centered")
st.title("Orçamento - Grupo Locomotiva")

# --- Menu ---
menu = st.sidebar.selectbox("Menu", ["Novo Orçamento","Histórico de Orçamentos"])

# ============================
# Novo Orçamento
# ============================
if menu == "Novo Orçamento":
    st.subheader("👤 Dados do Cliente")
    col1, col2 = st.columns(2)
    with col1:
        Cliente_nome = st.text_input("Nome/Razão", value=st.session_state.get("Cliente_nome",""))
    with col2:
        Cliente_CNPJ = st.text_input("CNPJ/CPF", value=st.session_state.get("Cliente_CNPJ",""))

    tipo_cliente = st.selectbox("Tipo Cliente", ["Consumidor Final","Revenda"])
    estado = st.selectbox("Estado", ["SP","RJ","MG","ES","PR","RS","SC","BA","PE","CE","DF","GO","MT","MS","PA","PB","PI","RN","RO","RR","SE","TO"])
    tipo_pedido = st.radio("Tipo Pedido", ["Direta","Industrialização"])
    preco_m2 = st.number_input("Preço m² ou metro linear (R$)", min_value=0.0, value=0.0)

    # Itens
    st.subheader("➕ Adicionar Itens")
    produto = st.text_input("Produto")
    tipo_produto = st.radio("Tipo Produto", ["Confeccionado","Bobina"])
    col1, col2, col3 = st.columns(3)
    with col1:
        comprimento = st.number_input("Comprimento (m)", min_value=0.01, value=1.0)
    with col2:
        largura = st.number_input("Largura (m)", min_value=0.01, value=1.0)
    with col3:
        quantidade = st.number_input("Quantidade", min_value=1, value=1)

    if tipo_produto=="Confeccionado" and st.button("➕ Adicionar Confeccionado"):
        st.session_state["itens_confeccionados"].append({
            "produto": produto, "comprimento": comprimento, "largura": largura, "quantidade": quantidade, "cor":""
        })
    if tipo_produto=="Bobina" and st.button("➕ Adicionar Bobina"):
        st.session_state["bobinas_adicionadas"].append({
            "produto": produto, "comprimento": comprimento, "largura": largura, "quantidade": quantidade, "cor":"", "espessura": None, "preco_unitario": preco_m2
        })

    # Observações e vendedor
    Observacao = st.text_area("Observações")
    st.subheader("Vendedor")
    vendedor_nome = st.text_input("Nome")
    vendedor_tel = st.text_input("Telefone")
    vendedor_email = st.text_input("E-mail")

    if st.button("📄 Gerar PDF e Salvar Orçamento"):
        cliente = {"nome":Cliente_nome,"cnpj":Cliente_CNPJ,"tipo_cliente":tipo_cliente,"estado":estado,"frete":"CIF","tipo_pedido":tipo_pedido}
        vendedor = {"nome":vendedor_nome,"tel":vendedor_tel,"email":vendedor_email}
        orcamento_id = salvar_orcamento(cliente, vendedor, st.session_state["itens_confeccionados"], st.session_state["bobinas_adicionadas"], Observacao)
        st.success(f"Orçamento salvo com ID {orcamento_id}")
        pdf_buffer = gerar_pdf(cliente, vendedor, st.session_state["itens_confeccionados"], st.session_state["bobinas_adicionadas"], Observacao, preco_m2)
        st.download_button("⬇️ Baixar PDF", pdf_buffer, file_name="orcamento.pdf", mime="application/pdf")

# ============================
# Histórico de Orçamentos
# ============================
if menu=="Histórico de Orçamentos":
    st.subheader("📋 Histórico de Orçamentos")
    orcamentos = buscar_orcamentos()
    for o in orcamentos:
        st.write(f"ID {o[0]} | Data: {o[1]} | Cliente: {o[2]} | Vendedor: {o[3]}")
        if st.button(f"🔄 Reabrir ID {o[0]}", key=f"reabrir_{o[0]}"):
            orc, confecc, bob = carregar_orcamento_por_id(o[0])
            st.session_state["itens_confeccionados"] = [{"produto":c[0],"comprimento":c[1],"largura":c[2],"quantidade":c[3],"cor":c[4]} for c in confecc]
            st.session_state["bobinas_adicionadas"] = [{"produto":b[0],"comprimento":b[1],"largura":b[2],"quantidade":b[3],"cor":b[4],"espessura":b[5],"preco_unitario":b[6]} for b in bob]
            st.experimental_rerun()
