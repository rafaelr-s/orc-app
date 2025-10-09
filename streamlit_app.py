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
    
    # 1. Cria ou verifica a tabela orcamentos (com a nova coluna preco_m2)
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
            preco_m2 REAL
        )
    """)
    
    # 2. Migração de Schema: Adiciona a coluna preco_m2 se ela não existir
    try:
        cur.execute("SELECT preco_m2 FROM orcamentos LIMIT 1")
    except sqlite3.OperationalError:
        cur.execute("ALTER TABLE orcamentos ADD COLUMN preco_m2 REAL")
        print("Migração de DB: Coluna 'preco_m2' adicionada à tabela 'orcamentos'.")

    # 3. Criação de tabelas secundárias
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

def salvar_orcamento(cliente, vendedor, itens_confeccionados, itens_bobinas, observacao, preco_m2):
    conn = sqlite3.connect(DB_NAME)
    cur = conn.cursor()

    cur.execute("""
        INSERT INTO orcamentos (data_hora, cliente_nome, cliente_cnpj, tipo_cliente, estado, frete, tipo_pedido, vendedor_nome, vendedor_tel, vendedor_email, observacao, preco_m2)
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
        preco_m2 
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
    conn = sqlite3.connect(DB_NAME)
    cur = conn.cursor()
    cur.execute("SELECT id, data_hora, cliente_nome, cliente_cnpj, vendedor_nome FROM orcamentos ORDER BY id DESC") 
    rows = cur.fetchall()
    conn.close()
    return rows

def carregar_orcamento_por_id(orcamento_id):
    conn = sqlite3.connect(DB_NAME)
    cur = conn.cursor()
    orc_cols = ['id','data_hora','cliente_nome','cliente_cnpj','tipo_cliente','estado','frete','tipo_pedido','vendedor_nome','vendedor_tel','vendedor_email','observacao', 'preco_m2']
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
    try:
        return f"R$ {v:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
    except Exception:
        return f"R$ {v}"

# ============================
# Cálculos
# ============================
st_por_estado = {} 

def calcular_valores_confeccionados(itens, preco_m2, tipo_cliente="", estado="", tipo_pedido="Direta"):
    if not itens:
        return 0.0, 0.0, 0.0, 0.0, 0.0, 0

    # Agora calculamos usando o preco por item (se existir), senão usa o preco_m2 passado
    m2_total = 0.0
    valor_bruto = 0.0
    for item in itens:
        preco_item = item.get('preco_unitario', preco_m2)
        area_item = item['comprimento'] * item['largura'] * item['quantidade']
        m2_total += area_item
        valor_bruto += area_item * preco_item

    # Lógica de IPI e ST (mantida, mas aplicada sobre os valores por item)
    if tipo_pedido == "Industrialização":
        valor_ipi = 0.0
        valor_st = 0.0
        aliquota_st = 0
        valor_final = valor_bruto
    else:
        IPI_CONFECCIONADO_DEFAULT = 0.0325
        IPI_ZERO_PRODS = ["Acrylic", "Agora"]
        IPI_ZERO_PREFIXES = ["Tela de Sombreamento"]

        valor_ipi_acumulado = 0.0
        for item in itens:
            produto = item.get('produto', '')
            preco_item = item.get('preco_unitario', preco_m2)
            area_item = item['comprimento'] * item['largura'] * item['quantidade']
            ipi_rate = IPI_CONFECCIONADO_DEFAULT
            if produto in IPI_ZERO_PRODS or any(produto.startswith(prefix) for prefix in IPI_ZERO_PREFIXES):
                ipi_rate = 0.0
            valor_ipi_acumulado += area_item * preco_item * ipi_rate

        valor_ipi = valor_ipi_acumulado
        valor_final = valor_bruto + valor_ipi

        valor_st = 0.0
        aliquota_st = 0
        if any(item.get('produto') == "Encerado" for item in itens) and tipo_cliente == "Revenda":
            aliquota_st = st_por_estado.get(estado, 0)
            valor_st = valor_final * aliquota_st / 100
            valor_final += valor_st

    return m2_total, valor_bruto, valor_ipi, valor_final, valor_st, aliquota_st
    
# FUNÇÃO CORRIGIDA PARA IPI DE CAPOTA MARÍTIMA
def calcular_valores_bobinas(itens, preco_m2, tipo_pedido="Direta"):
    IPI_RATE_DEFAULT = 0.0975 # 9.75%
    
    if not itens:
        # Retorna a alíquota padrão se não houver itens
        return 0.0, 0.0, 0.0, 0.0, IPI_RATE_DEFAULT

    m_total = sum(item['comprimento'] * item['quantidade'] for item in itens)
    
    def preco_item_of(item):
        pu = item.get('preco_unitario') 
        return pu if (pu is not None) else preco_m2 

    valor_bruto = sum((item['comprimento'] * item['quantidade']) * preco_item_of(item) for item in itens)

    if tipo_pedido == "Industrialização":
        return m_total, valor_bruto, 0.0, valor_bruto, 0.0 # Retorna 0.0 como taxa de IPI
    else:
        IPI_RATE_CAPOTA = 0.0325 # 3.25%
        
        # Verifica se algum item é "Capota Marítima"
        has_capota_maritima = any(item.get('produto') == "Capota Marítima" for item in itens)
        
        # Define a alíquota a ser usada
        ipi_rate_to_use = IPI_RATE_CAPOTA if has_capota_maritima else IPI_RATE_DEFAULT
        
        valor_ipi = valor_bruto * ipi_rate_to_use
        valor_final = valor_bruto + valor_ipi

        # Novo: Retorna a taxa de IPI utilizada para exibição
        return m_total, valor_bruto, valor_ipi, valor_final, ipi_rate_to_use

# ============================
# Função para gerar PDF
# ============================
def gerar_pdf(orcamento_id, cliente, vendedor, itens_confeccionados, itens_bobinas, resumo_conf, resumo_bob, observacao, preco_m2, tipo_cliente="", estado=""):
    pdf = FPDF()
    pdf.add_page()
    pdf.set_auto_page_break(auto=True, margin=15)
    pdf.set_font("Arial", "B", 14)

    # Cabeçalho principal
    pdf.cell(0, 12, "Orçamento - Grupo Locomotiva", ln=True, align="C")
    
    # Inclusão do ID do Orçamento
    if orcamento_id:
        pdf.set_font("Arial", "B", 11)
        pdf.cell(0, 6, f"ID do Orçamento: {orcamento_id}", ln=True, align="C")
    
    pdf.ln(10)
    pdf.set_font("Arial", size=9)
    brasilia_tz = pytz.timezone("America/Sao_Paulo")
    pdf.cell(0, 6, f"Data e Hora: {datetime.now(brasilia_tz).strftime('%d/%m/%Y %H:%M')}", ln=True)
    pdf.cell(0, 6, "Validade da Cotação: 7 dias corridos.", ln=True, align="L")
    pdf.ln(4)

    # Dados do Cliente
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

    # Itens Confeccionados
    if itens_confeccionados:
        pdf.set_font("Arial", "B", 11)
        pdf.cell(0, 8, "Itens Confeccionados", ln=True)
        pdf.set_font("Arial", size=8)
        for item in itens_confeccionados:
            area_item = item['comprimento'] * item['largura'] * item['quantidade']
            preco_item = item.get('preco_unitario', preco_m2)
            valor_item = area_item * preco_item
            txt = (
            f"{item['quantidade']}x {item['produto']} - {item['comprimento']}m x {item['largura']}m "
            f"= {area_item:.2f} m² × {_format_brl(preco_item)}/m² → {_format_brl(valor_item)}"
        )
        if item.get('cor'):
            txt += f" | Cor: {item.get('cor')}"
            pdf.multi_cell(largura_util, 6, txt)
            pdf.ln(1)
    
    # Resumo Confeccionados
    if resumo_conf:
        m2_total, valor_bruto, valor_ipi, valor_final, valor_st, aliquota_st = resumo_conf
        pdf.ln(3)
        pdf.set_font("Arial", "B", 11)
        pdf.cell(0, 10, "Resumo - Confeccionados", ln=True)
        pdf.set_font("Arial", "", 10)
        pdf.cell(0, 8, f"Preço por m² utilizado: {_format_brl(preco_m2)}", ln=True)
        pdf.cell(0, 8, f"Área Total: {str(f'{m2_total:.2f}'.replace('.', ','))} m²", ln=True)
        pdf.cell(0, 8, f"Valor Bruto: {_format_brl(valor_bruto)}", ln=True)
        if valor_ipi>0:
            pdf.cell(0, 8, f"IPI: {_format_brl(valor_ipi)}", ln=True)
        if valor_st>0:
            pdf.cell(0, 8, f"ST ({aliquota_st}%): {_format_brl(valor_st)}", ln=True)
        pdf.set_font("Arial", "B", 10)
        pdf.cell(0, 8, f"Valor Total: {_format_brl(valor_final)}", ln=True)
        pdf.set_font("Arial", "", 10)
        pdf.ln(10)

    # Itens Bobinas
    if itens_bobinas:
        pdf.set_font("Arial", "B", 11)
        pdf.cell(0, 8, "Itens Bobina", ln=True)
        pdf.set_font("Arial", size=8)
        for item in itens_bobinas:
            metros_item = item['comprimento'] * item['quantidade']
            preco_item = item.get('preco_unitario') if item.get('preco_unitario') is not None else preco_m2
            valor_item = metros_item * preco_item
            txt = (
                f"{item['quantidade']}x {item['produto']} - {item['comprimento']}m | Largura: {item['largura']}m "
                f"| Cor: {item.get('cor','')} | Valor Bruto: {_format_brl(valor_item)}"
            )
            if "espessura" in item and item.get('espessura') is not None:
                esp = f"{item['espessura']:.2f}".replace(".", ",")
                txt += f" | Esp: {esp} mm"
                txt += f" | Preço metro: {_format_brl(preco_item)}"
            pdf.multi_cell(largura_util, 6, txt)
            pdf.ln(1)

        if resumo_bob:
            # Resumo Bobinas espera 5 valores
            m_total, valor_bruto, valor_ipi, valor_final, ipi_rate = resumo_bob 
            pdf.ln(3)
            pdf.set_font("Arial", "B", 11)
            pdf.cell(0, 10, "Resumo - Bobinas", ln=True)
            pdf.set_font("Arial", "", 10)
            pdf.cell(0, 8, f"Total de Metros Lineares: {str(f'{m_total:.2f}'.replace('.', ','))} m", ln=True)
            pdf.cell(0, 8, f"Valor Bruto: {_format_brl(valor_bruto)}", ln=True)
            if valor_ipi>0:
                ipi_percent = ipi_rate * 100
                # Exibe a alíquota correta
                pdf.cell(0, 8, f"IPI ({ipi_percent:.2f}%): {_format_brl(valor_ipi)}", ln=True)
            pdf.set_font("Arial", "B", 10)
            pdf.cell(0, 8, f"Valor Total: {_format_brl(valor_final)}", ln=True)
        pdf.ln(10)

    # Observações
    if observacao:
        pdf.set_font("Arial", "B", 11)
        pdf.cell(0, 11, "Observações", ln=True)
        pdf.set_font("Arial", size=10)
        pdf.multi_cell(largura_util, 10, str(observacao))
        pdf.ln(10)

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

    # Retorna bytes do PDF
    pdf_bytes = pdf.output(dest='S')
    return pdf_bytes

# ============================
# Funções de Reset
# ============================

def reset_novo_orcamento_state():
    """Reseta todos os campos do formulário de Novo Orçamento."""
    # Resetar campos principais
    st.session_state["Cliente_nome"] = ""
    st.session_state["Cliente_CNPJ"] = ""
    st.session_state["tipo_cliente"] = " "
    st.session_state["estado"] = "SP"
    st.session_state["tipo_pedido"] = "Direta"
    st.session_state["frete_sel"] = "CIF"
    st.session_state["obs"] = ""
    
    # Vendedor resetado para vazio/padrão
    st.session_state["vend_nome"] = ""
    st.session_state["vend_tel"] = ""
    st.session_state["vend_email"] = ""
    # Resetar o selectbox (NOVO)
    if "vendedor_select" in st.session_state:
        st.session_state["vendedor_select"] = VENDEDORES_NOMES[0] # Set to "Selecione um Vendedor"

    st.session_state["preco_m2"] = 0.0
    st.session_state["menu_index"] = 0 
    
    # Resetar listas e seletores de itens
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
    """Reseta todos os filtros do Histórico de Orçamentos."""
    st.session_state["filtro_cliente"] = "Todos"
    st.session_state["filtro_cnpj"] = "Todos"
    st.session_state["filtro_id"] = ""
    # O Streamlit faz o rerun automaticamente após a função on_click.

# ============================
# Constantes de Vendedores
# ============================
VENDEDORES = {
    "Selecione um Vendedor": {"nome": "", "tel": "", "email": ""},
    "Rafael Rodrigues": {"nome": "Rafael Rodrigues", "tel": "11 99150-0804", "email": "rrodrigues@locomotiva.com.br"},
    "Tiago Victor": {"nome": "Tiago Victor", "tel": "11 97697-8167", "email": "tvitor@locomotiva.com.br"}
}
VENDEDORES_NOMES = list(VENDEDORES.keys())

# Função para atualizar o Session State baseado na seleção
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
    # confecc: (produto, comprimento, largura, quantidade, cor)
    # bob: (produto, comprimento, largura, quantidade, cor, espessura, preco_unitario)
    
    has_conf = len(confecc) > 0
    has_bob = len(bob) > 0
    
    # 1. Tipo do Item
    if has_conf and has_bob:
        tipo_item = "Misto (Conf. e Bobina)"
    elif has_conf:
        tipo_item = "Confeccionado"
    elif has_bob:
        tipo_item = "Bobina"
    else:
        tipo_item = "Nenhum"

    # 2. Produto Mais Selecionado (por quantidade)
    product_counts = {}
    for item in confecc:
        product = item[0] # Produto
        quantity = item[3] # Quantidade
        product_counts[product] = product_counts.get(product, 0) + quantity
    
    for item in bob:
        product = item[0] # Produto
        quantity = item[3] # Quantidade
        product_counts[product] = product_counts.get(product, 0) + quantity

    most_selected_product = max(product_counts, key=product_counts.get) if product_counts else ""
        
    # 3. Área Total em m² (Apenas Confeccionado, conforme métrica do m² solicitado)
    m2_total_conf = sum(item[1] * item[2] * item[3] for item in confecc)

    return tipo_item, most_selected_product, m2_total_conf

# ============================
# Inicialização
# ============================
init_db()

# session state defaults
defaults = {
    "Cliente_nome": "", "Cliente_CNPJ": "", "tipo_cliente": " ",
    "estado": "SP", 
    "tipo_pedido": "Direta", "preco_m2": 0.0, "itens_confeccionados": [],
    "bobinas_adicionadas": [], "frete_sel": "CIF", "obs": "",
    "vend_nome": "", "vend_tel": "", "vend_email": "",
    "menu_index": 0,
    "filtro_cliente": "Todos", 
    "filtro_cnpj": "Todos",   
    "filtro_id": "",          
    "vendedor_select": VENDEDORES_NOMES[0] # Novo default
}
for k, v in defaults.items():
    if k not in st.session_state:
        st.session_state[k] = v

# ============================
# Configuração Streamlit
# ============================
st.set_page_config(page_title="Calculadora Grupo Locomotiva", page_icon="📏", layout="centered")
st.title("Orçamento - Grupo Locomotiva")

# --- Menu ---
menu_options = ["Novo Orçamento","Histórico de Orçamentos"]
menu = st.sidebar.selectbox(
    "Menu", 
    menu_options, 
    index=st.session_state['menu_index'], 
    key='main_menu_select' 
)

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

# ============================
# Interface - Novo Orçamento
# ============================
if menu == "Novo Orçamento":
    # Botão de Limpar Formulário (Novo)
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

    # --- INÍCIO DA REORDENAÇÃO (REQ. DO USUÁRIO) ---
    # 1. Dados do Cliente: Tipo do Pedido (Radio) antes do Tipo do Cliente e Estado (Selectboxes)
    tipo_pedido = st.radio("Tipo do Pedido:", ["Direta", "Industrialização"], index=0 if st.session_state.get("tipo_pedido","Direta")=="Direta" else 1, key="tipo_pedido")
    
    tipo_cliente = st.selectbox("Tipo do Cliente:", [" ","Consumidor Final", "Revenda"], index=0 if st.session_state.get("tipo_cliente"," ") == " " else (1 if st.session_state.get("tipo_cliente")=="Consumidor Final" else 2), key="tipo_cliente")
    estado = st.selectbox("Estado do Cliente:", options=list(icms_por_estado.keys()), index=list(icms_por_estado.keys()).index(st.session_state.get("estado")) if st.session_state.get("estado") in icms_por_estado else 0, key="estado")
    # --- FIM DA REORDENAÇÃO (REQ. DO USUÁRIO) ---

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
    
    # --- INÍCIO DA REORDENAÇÃO (REQ. DO USUÁRIO) ---
    # 2. Adicionar Produto: Tipo do Produto (Radio) antes do Nome do Produto (Selectbox)
    tipo_produto = st.radio("Tipo do Produto:", ["Confeccionado", "Bobina"], key="tipo_prod_sel")
    
    produto = st.selectbox("Nome do Produto:", options=produtos_lista, index=produtos_lista.index(st.session_state.get("produto_sel")) if st.session_state.get("produto_sel") in produtos_lista else 0, key="produto_sel")
    # --- FIM DA REORDENAÇÃO (REQ. DO USUÁRIO) ---
    
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
            comprimento = st.number_input("Comprimento (m):", min_value=0.010, value=st.session_state.get("comp_conf", 1.0), step=0.10, key="comp_conf")
        with col2:
            largura = st.number_input("Largura (m):", min_value=0.010, value=st.session_state.get("larg_conf", 1.0), step=0.10, key="larg_conf")
        with col3:
            quantidade = st.number_input("Quantidade:", min_value=1, value=st.session_state.get("qtd_conf", 1), step=1, key="qtd_conf")

        if st.button("➕ Adicionar Medida", key="add_conf"):
            st.session_state['itens_confeccionados'].append({
                'produto': produto,
                'comprimento': float(comprimento),
                'largura': float(largura),
                'quantidade': int(quantidade),
                'cor': "",
                'preco_unitario': st.session_state.get("preco_m2", 0.0)
            })

        if st.session_state['itens_confeccionados']:
            st.subheader("📋 Itens Adicionados")
            for idx, item in enumerate(st.session_state['itens_confeccionados'][:] ):
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
                    # Usando chaves únicas para inputs dinâmicos
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
            if tipo_pedido != "Industrialização":
                st.write(f"🧾 IPI: **{_format_brl(valor_ipi)}**") 
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
                'cor': ""
            }
            if espessura_bobina is not None:
                item_bobina['espessura'] = float(espessura_bobina)
                item_bobina['preco_unitario'] = preco_m2
            st.session_state['bobinas_adicionadas'].append(item_bobina)

        if st.session_state['bobinas_adicionadas']:
            st.subheader("📋 Bobinas Adicionadas")
            for idx, item in enumerate(st.session_state['bobinas_adicionadas'][:] ):
                col1, col2, col3, col4 = st.columns([4,2,2,1])
                with col1:
                    metros_item = item['comprimento'] * item['quantidade']
                    valor_item = metros_item * (item.get('preco_unitario') if item.get('preco_unitario') is not None else preco_m2)
                    detalhes = (
                        f"🔹 {item['quantidade']}x {item['comprimento']:.2f}m | Largura: {item['largura']:.2f}m "
                        f"= {metros_item:.2f} m → {_format_brl(valor_item)}"
                    )
                    if 'espessura' in item and item.get('espessura') is not None:
                        detalhes += f" | Esp: {item['espessura']:.2f}mm"
                        detalhes += f" | unit: {_format_brl(item.get('preco_unitario', preco_m2))}"
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

            # Recebe a taxa de IPI utilizada
            m_total, valor_bruto_bob, valor_ipi_bob, valor_final_bob, ipi_rate_bob = calcular_valores_bobinas(
                st.session_state['bobinas_adicionadas'], preco_m2, tipo_pedido
            )
            ipi_percent = ipi_rate_bob * 100 # Converte para porcentagem para exibição
            
            st.markdown("---")
            st.success("💰 **Resumo do Pedido - Bobinas**")
            st.write(f"📏 Total de Metros Lineares: **{m_total:.2f} m**".replace(".", ","))
            st.write(f"💵 Valor Bruto: **{_format_brl(valor_bruto_bob)}**")
            if tipo_pedido != "Industrialização":
                # Exibe a alíquota correta
                st.write(f"🧾 IPI ({ipi_percent:.2f}%): **{_format_brl(valor_ipi_bob)}**")
                st.write(f"💰 Valor Final com IPI ({ipi_percent:.2f}%): **{_format_brl(valor_final_bob)}**")
            else:
                st.write(f"💰 Valor Final: **{_format_brl(valor_final_bob)}**")

            if st.button("🧹 Limpar Bobinas", key="limpar_bob_list"):
                st.session_state['bobinas_adicionadas'] = []
                st.rerun()

    # Tipo de frete / observações / vendedor (com chaves para session_state)
    st.markdown("---")
    st.subheader("🚚 Tipo de Frete")
    frete = st.radio("Selecione o tipo de frete:", ["CIF", "FOB"], index=0 if st.session_state.get("frete_sel","CIF")=="CIF" else 1, key="frete_sel")

    st.subheader("🔎 Observações")
    Observacao = st.text_area("Insira aqui alguma observação sobre o orçamento (opcional)", value=st.session_state.get("obs",""), key="obs")

    # -----------------------------------------------------
    # Seleção do Vendedor por Dropdown 
    # -----------------------------------------------------
    st.subheader("🗣️ Vendedor(a)")
    
    # Tenta encontrar o nome do vendedor atual no session state na lista de vendedores, senão usa o primeiro
    current_name = st.session_state.get("vend_nome", "")
    try:
        current_index = VENDEDORES_NOMES.index(current_name)
    except ValueError:
        current_index = 0 

    vendedor_selecionado = st.selectbox(
        "Selecione o Vendedor:", 
        options=VENDEDORES_NOMES,
        index=current_index,
        key="vendedor_select", # Nova chave para o selectbox
        on_change=update_vendedor_details # Função para atualizar o Session State
    )

    # Garante que, ao carregar a página, as variáveis de telefone e email estejam corretas
    if st.session_state["vendedor_select"] != st.session_state.get("vend_nome", ""):
        # Chama a função para garantir que vend_tel e vend_email sejam preenchidos ao carregar o estado
        # O on_change não é disparado no primeiro load, então chamamos manualmente se necessário.
        update_vendedor_details() 

    # Exibe os dados do vendedor em modo somente leitura
    st.markdown("---")
    st.markdown(f"**Nome:** {st.session_state.get('vend_nome')}")
    st.markdown(f"**Telefone:** {st.session_state.get('vend_tel')}")
    st.markdown(f"**E-mail:** {st.session_state.get('vend_email')}")
    st.markdown("---")
    # -----------------------------------------------------

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
        # Vendedor é pego das variáveis de sessão, que foram atualizadas pelo selectbox
        vendedor = {
            "nome": st.session_state.get("vend_nome",""),
            "tel": st.session_state.get("vend_tel",""),
            "email": st.session_state.get("vend_email","")
        }

        # Salvar
        orcamento_id = salvar_orcamento(
            cliente,
            vendedor,
            st.session_state["itens_confeccionados"],
            st.session_state["bobinas_adicionadas"],
            st.session_state.get("obs",""),
            st.session_state.get("preco_m2",0.0) 
        )
        st.success(f"✅ Orçamento salvo com ID {orcamento_id}")

        # Resumos
        resumo_conf = calcular_valores_confeccionados(st.session_state["itens_confeccionados"], st.session_state.get("preco_m2",0.0), st.session_state.get("tipo_cliente"," "), st.session_state.get("estado",""), st.session_state.get("tipo_pedido","Direta")) if st.session_state["itens_confeccionados"] else None
        # Chamada retorna 5 valores
        resumo_bob = calcular_valores_bobinas(st.session_state["bobinas_adicionadas"], st.session_state.get("preco_m2",0.0), st.session_state.get("tipo_pedido","Direta")) if st.session_state["bobinas_adicionadas"] else None

        # Gerar PDF bytes (Passando orcamento_id)
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

        # Salvar no disco (opcional)
        pdf_path = f"orcamento_{orcamento_id}.pdf"
        try:
            with open(pdf_path, "wb") as f:
                f.write(pdf_bytes)
            st.success(f"✅ PDF salvo em disco: {pdf_path}")
        except Exception as e:
            st.warning(f"⚠️ Não foi possível salvar o PDF no disco: {e}")

        # Download button 
        st.download_button(
            "⬇️ Baixar PDF",
            data=pdf_bytes,
            file_name=pdf_path,
            mime="application/pdf",
            key=f"download_key_{orcamento_id}"
        ) 

# ============================
# Menu: Histórico de Orçamentos
# ============================
if menu == "Histórico de Orçamentos":
    st.session_state['menu_index'] = 1
    st.subheader("Histórico de Orçamentos Salvos")

    orcamentos = buscar_orcamentos()
    
    if not orcamentos:
        st.info("Nenhum orçamento encontrado no banco de dados.")
        st.stop()

    df_orcamentos = pd.DataFrame(orcamentos, columns=['ID', 'Data/Hora', 'Cliente', 'CNPJ/CPF', 'Vendedor'])
    
    # Filtros
    col_f1, col_f2, col_f3 = st.columns(3)
    with col_f1:
        filtro_cliente = st.text_input("Filtrar por Nome do Cliente:")
    with col_f2:
        filtro_vendedor = st.selectbox("Filtrar por Vendedor:", ["Todos"] + sorted(df_orcamentos['Vendedor'].unique()))
    with col_f3:
        filtro_id = st.text_input("Filtrar por ID:")

    orcamentos_filtrados = orcamentos
    
    # Aplicar filtros
    if filtro_cliente:
        orcamentos_filtrados = [o for o in orcamentos_filtrados if filtro_cliente.lower() in o[2].lower()]
    
    if filtro_vendedor != "Todos":
        orcamentos_filtrados = [o for o in orcamentos_filtrados if o[4] == filtro_vendedor]
        
    if filtro_id:
        try:
            id_int = int(filtro_id)
            orcamentos_filtrados = [o for o in orcamentos_filtrados if o[0] == id_int]
        except ValueError:
            st.error("ID deve ser um número inteiro.")
            orcamentos_filtrados = []

    
    if not orcamentos_filtrados:
        st.warning("Nenhum orçamento corresponde aos filtros.")
        st.stop()
        
    for o in orcamentos_filtrados:
        orc_id, data_hora, cliente_nome, cliente_cnpj, vendedor_nome = o
        orc, confecc, bob = carregar_orcamento_por_id(orc_id)
        
        if not orc:
             st.error(f"Dados do orçamento {orc_id} incompletos.")
             continue

        # Mapeamento do orçamento principal
        orc_data = {
            'tipo_cliente': orc[4],
            'estado': orc[5],
            'frete': orc[6],
            'tipo_pedido': orc[7],
            'vendedor_tel': orc[9],
            'vendedor_email': orc[10],
            'observacao': orc[11],
        }
        preco_m2 = orc[12] if orc[12] is not None else 0.0

        with st.expander(f"📝 ID {orc_id} - {cliente_nome} ({data_hora})"):
            st.markdown(f"**Cliente:** {cliente_nome} ({cliente_cnpj}) | **Vendedor:** {vendedor_nome}")
            st.markdown(f"**Detalhes:** {orc_data['tipo_cliente']} | {orc_data['estado']} | Frete: {orc_data['frete']} | Tipo Pedido: {orc_data['tipo_pedido']}")
            st.markdown(f"**Preço Base do Orçamento:** {_format_brl(preco_m2)}")
            if orc_data['observacao']:
                 st.info(f"Obs: {orc_data['observacao']}")

            if confecc:
                st.markdown("### ⬛ Itens Confeccionados")
                for c in confecc:
                    # c[5] é o preco_unitario (travado)
                    preco_unit = c[5] if (len(c) > 5 and c[5] is not None) else preco_m2
                    st.markdown(f"- **{c[0]}**: {c[3]}x {c[1]:.2f}m x {c[2]:.2f}m | Cor: {c[4]} | R$/m²: {_format_brl(preco_unit)}")

            if bob:
                st.markdown("### 🔘 Itens Bobinas")
                for b in bob:
                    # b[6] é o preco_unitario (travado)
                    esp = f" | Esp: {b[5]:.2f}mm" if b[5] is not None else ""
                    preco_unit = b[6] if b[6] is not None else preco_m2
                    st.markdown(f"- **{b[0]}**: {b[3]}x {b[1]:.2f}m | Largura: {b[2]:.2f}m{esp} | Cor: {b[4]} | R$/m: {_format_brl(preco_unit)}")

            st.markdown("---")
            col1, col2, col3 = st.columns([1,1,1])
            with col1:
                # Reabrir
                if st.button("🔄 Reabrir", key=f"reabrir_{orc_id}"):
                    
                    itens_confecc_reabrir = [dict(zip(['produto','comprimento','largura','quantidade','cor','preco_unitario'],c)) for c in confecc]
                    itens_bob_reabrir = [dict(zip(['produto','comprimento','largura','quantidade','cor','espessura','preco_unitario'],b)) for b in bob]

                    st.session_state.update({
                        "cliente_nome": orc[2],
                        "cliente_cnpj": orc[3],
                        "tipo_cliente": orc[4],
                        "estado": orc[5],
                        "frete": orc[6],
                        "tipo_pedido": orc[7],
                        "vendedor_nome": orc[8],
                        "vendedor_tel": orc[9],
                        "vendedor_email": orc[10],
                        "obs": orc[11],
                        "preco_m2": preco_m2, 
                        # PASSA OS ITENS COM O PREÇO TRAVADO
                        "itens_confeccionados": itens_confecc_reabrir,
                        "bobinas_adicionadas": itens_bob_reabrir,
                        "menu_index": 0 
                    })
                    st.success(f"Orçamento ID {orc_id} carregado no formulário.")
                    st.rerun()

            with col2:
                # Baixar PDF
                # Mapeia itens para dicionário antes de passar para o PDF
                itens_conf_pdf = [dict(zip(['produto','comprimento','largura','quantidade','cor','preco_unitario'], c)) for c in confecc]
                itens_bob_pdf = [dict(zip(['produto','comprimento','largura','quantidade','cor','espessura','preco_unitario'], b)) for b in bob]

                resumo_conf_calc = calcular_valores_confeccionados(
                    itens_conf_pdf, preco_m2, orc_data['tipo_cliente'], orc_data['estado'], orc_data['tipo_pedido']
                ) if itens_conf_pdf else None

                resumo_bob_calc = calcular_valores_bobinas(
                    itens_bob_pdf, preco_m2, orc_data['tipo_pedido']
                ) if itens_bob_pdf else None
                
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
                    itens_confeccionados=itens_conf_pdf,
                    itens_bobinas=itens_bob_pdf,
                    resumo_conf=resumo_conf_calc, 
                    resumo_bob=resumo_bob_calc,
                    observacao=orc[11],
                    preco_m2=preco_m2,
                    tipo_cliente=orc_data['tipo_cliente'],
                    estado=orc_data['estado']
                ) 
                st.download_button(
                    "📄 Baixar PDF",
                    data=pdf_bytes,
                    file_name=f"orcamento_{orc_id}.pdf",
                    mime="application/pdf",
                    key=f"download_historico_{orc_id}"
                )
