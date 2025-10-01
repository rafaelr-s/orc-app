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
    
    # 1. Cria ou verifica a tabela orcamentos (com a nova coluna preco_m2_base)
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
    
    # 2. Migração de Schema: Adiciona a coluna preco_m2_base se ela não existir
    try:
        cur.execute("SELECT preco_m2_base FROM orcamentos LIMIT 1")
    except sqlite3.OperationalError:
        cur.execute("ALTER TABLE orcamentos ADD COLUMN preco_m2_base REAL")
        print("Migração de DB: Coluna 'preco_m2_base' adicionada à tabela 'orcamentos'.")

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
    orc_cols = ['id','data_hora','cliente_nome','cliente_cnpj','tipo_cliente','estado','frete','tipo_pedido','vendedor_nome','vendedor_tel','vendedor_email','observacao', 'preco_m2_base']
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
    m2_total = sum(item['comprimento'] * item['largura'] * item['quantidade'] for item in itens)
    valor_bruto = m2_total * preco_m2
    # Lógica de IPI e ST... (mantida)
    if tipo_pedido == "Industrialização":
        valor_ipi = 0
        valor_st = 0
        aliquota_st = 0
        valor_final = valor_bruto
    else:
        IPI_CONFECCIONADO_DEFAULT = 0.0325
        IPI_ZERO_PRODS = ["Acrylic", "Agora"]
        IPI_ZERO_PREFIXES = ["Tela de Sombreamento"]
        
        valor_ipi_acumulado = 0.0
        
        for item in itens:
            produto = item.get('produto', '')
            valor_item = item['comprimento'] * item['largura'] * item['quantidade'] * preco_m2
            ipi_rate = IPI_CONFECCIONADO_DEFAULT

            if produto in IPI_ZERO_PRODS or any(produto.startswith(prefix) for prefix in IPI_ZERO_PREFIXES):
                ipi_rate = 0.0
            
            valor_ipi_acumulado += valor_item * ipi_rate

        valor_ipi = valor_ipi_acumulado
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
    m_total = sum(item['comprimento'] * item['quantidade'] for item in itens)
    
    def preco_item_of(item):
        pu = item.get('preco_unitario') 
        return pu if (pu is not None) else preco_m2 

    valor_bruto = sum((item['comprimento'] * item['quantidade']) * preco_item_of(item) for item in itens)

    if tipo_pedido == "Industrialização":
        valor_ipi = 0
        valor_final = valor_bruto
    else:
        valor_ipi = valor_bruto * 0.0975
        valor_final = valor_bruto + valor_ipi

    return m_total, valor_bruto, valor_ipi, valor_final

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
            valor_item = area_item * preco_m2
            txt = (
                f"{item['quantidade']}x {item['produto']} - {item['comprimento']}m x {item['largura']}m "
                f"| Cor: {item.get('cor','')} | Valor Bruto: {_format_brl(valor_item)}"
            )
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
            m_total, valor_bruto, valor_ipi, valor_final = resumo_bob
            pdf.ln(3)
            pdf.set_font("Arial", "B", 11)
            pdf.cell(0, 10, "Resumo - Bobinas", ln=True)
            pdf.set_font("Arial", "", 10)
            pdf.cell(0, 8, f"Total de Metros Lineares: {str(f'{m_total:.2f}'.replace('.', ','))} m", ln=True)
            pdf.cell(0, 8, f"Valor Bruto: {_format_brl(valor_bruto)}", ln=True)
            if valor_ipi>0:
                pdf.cell(0, 8, f"IPI: {_format_brl(valor_ipi)}", ln=True)
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
    pdf_bytes = pdf.output(dest='S').encode('latin1')
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
    st.session_state["vend_nome"] = ""
    st.session_state["vend_tel"] = ""
    st.session_state["vend_email"] = ""
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
    # Se 'esp_bob' existe (foi usado), reseta
    if "esp_bob" in st.session_state:
        st.session_state["esp_bob"] = 0.10
        
    st.session_state["itens_confeccionados"] = []
    st.session_state["bobinas_adicionadas"] = []
    
    st.rerun() 

def reset_historico_filters():
    """Reseta todos os filtros do Histórico de Orçamentos."""
    st.session_state["filtro_cliente"] = "Todos"
    st.session_state["filtro_cnpj"] = "Todos"
    st.session_state["filtro_id"] = ""
    # Não resetamos o 'filtro_datas' diretamente, pois ele se reajustará ao intervalo padrão de todos os orçamentos após o rerun.
    st.rerun() 

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
    "filtro_cliente": "Todos", # Adicionado para filtro
    "filtro_cnpj": "Todos",   # Adicionado para filtro
    "filtro_id": "",          # Adicionado para filtro
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
    produto = st.selectbox("Nome do Produto:", options=produtos_lista, index=produtos_lista.index(st.session_state.get("produto_sel")) if st.session_state.get("produto_sel") in produtos_lista else 0, key="produto_sel")
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
                'cor': ""
            })

        if st.session_state['itens_confeccionados']:
            st.subheader("📋 Itens Adicionados")
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

        if st.session_state['itens_confeccionados']:
            m2_total, valor_bruto, valor_ipi, valor_final, valor_st, aliquota_st = calcular_valores_confeccionados(
                st.session_state['itens_confeccionados'], preco_m2, tipo_cliente, estado, tipo_pedido
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

            m_total, valor_bruto_bob, valor_ipi_bob, valor_final_bob = calcular_valores_bobinas(
                st.session_state['bobinas_adicionadas'], preco_m2, tipo_pedido
            )
            st.markdown("---")
            st.success("💰 **Resumo do Pedido - Bobinas**")
            st.write(f"📏 Total de Metros Lineares: **{m_total:.2f} m**".replace(".", ","))
            st.write(f"💵 Valor Bruto: **{_format_brl(valor_bruto_bob)}**")
            if tipo_pedido != "Industrialização":
                st.write(f"🧾 IPI (9.75%): **{_format_brl(valor_ipi_bob)}**")
                st.write(f"💰 Valor Final com IPI (9.75%): **{_format_brl(valor_final_bob)}**")
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
    st.subheader("📋 Histórico de Orçamentos Salvos")
    orcamentos = buscar_orcamentos()
    if not orcamentos:
        st.info("Nenhum orçamento encontrado.")
    else:
        clientes = sorted(list({o[2] for o in orcamentos if o[2]}))
        cnpjs = sorted(list({o[3] for o in orcamentos if o[3]}))
        
        # Filtro por ID (Novo)
        orc_id_filtro = st.text_input("Filtrar por ID do Orçamento:", value=st.session_state.get("filtro_id", ""), key="filtro_id")

        # Filtros de Seleção (mantendo state)
        cliente_filtro = st.selectbox("Filtrar por cliente:", ["Todos"] + clientes, key="filtro_cliente")
        cnpj_filtro = st.selectbox("Filtrar por CNPJ:", ["Todos"] + cnpjs, key="filtro_cnpj")
        
        # Botão Limpar Filtros (Novo)
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

            # Lógica de Filtragem
            id_ok = True
            if orc_id_filtro:
                # Permite pesquisa por prefixo do ID (string)
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
            # Exportar Excel
            if st.button("📊 Exportar Excel do Histórico Filtrado"):
                linhas_excel = []
                orc_cols = ['id','data_hora','cliente_nome','cliente_cnpj','tipo_cliente','estado','frete','tipo_pedido','vendedor_nome','vendedor_tel','vendedor_email','observacao', 'preco_m2_base']

                for o in orcamentos_filtrados:
                    orc_id, data_hora, cliente_nome, cliente_cnpj, vendedor_nome = o
                    orc, confecc, bob = carregar_orcamento_por_id(orc_id)
                    
                    orc_data = dict(zip(orc_cols, orc))
                    preco_m2_base = orc_data.get('preco_m2_base') if orc_data.get('preco_m2_base') is not None else 0.0

                    itens_conf_calc = [dict(zip(['produto','comprimento','largura','quantidade','cor'], c)) for c in confecc]
                    itens_bob_calc = [dict(zip(['produto','comprimento','largura','quantidade','cor','espessura','preco_unitario'], b)) for b in bob]

                    resumo_conf = calcular_valores_confeccionados(
                        itens_conf_calc, preco_m2_base, orc_data['tipo_cliente'], orc_data['estado'], orc_data['tipo_pedido']
                    ) if itens_conf_calc else (0, 0, 0, 0, 0, 0) 
                    
                    resumo_bob = calcular_valores_bobinas(
                        itens_bob_calc, preco_m2_base, orc_data['tipo_pedido']
                    ) if itens_bob_calc else (0, 0, 0, 0)
                    
                    valor_final_total = resumo_conf[3] + resumo_bob[3]
                    
                    for c in confecc:
                        linhas_excel.append({
                            "ID": orc_id, "Data": data_hora, "Cliente": cliente_nome, "CNPJ": cliente_cnpj,
                            "Tipo Cliente": orc_data['tipo_cliente'], "Estado": orc_data['estado'], "Frete": orc_data['frete'], "Tipo Pedido": orc_data['tipo_pedido'],
                            "Vendedor": vendedor_nome, "Produto": c[0], "Comprimento": c[1], "Largura": c[2],
                            "Quantidade": c[3], "Cor": c[4], "Tipo Item": "Confeccionado",
                            "Preço Base Utilizado (R$)": preco_m2_base, 
                            "Valor Final Total (R$)": valor_final_total 
                        })
                    for b in bob:
                        linhas_excel.append({
                            "ID": orc_id, "Data": data_hora, "Cliente": cliente_nome, "CNPJ": cliente_cnpj,
                            "Tipo Cliente": orc_data['tipo_cliente'], "Estado": orc_data['estado'], "Frete": orc_data['frete'], "Tipo Pedido": orc_data['tipo_pedido'],
                            "Vendedor": vendedor_nome, "Produto": b[0], "Comprimento": b[1], "Largura": b[2],
                            "Quantidade": b[3], "Cor": b[4], "Espessura": b[5], "Preço Unitário": b[6],
                            "Tipo Item": "Bobina",
                            "Preço Base Utilizado (R$)": preco_m2_base, 
                            "Valor Final Total (R$)": valor_final_total 
                        })
                df_excel = pd.DataFrame(linhas_excel)
                excel_bytes = BytesIO()
                df_excel.to_excel(excel_bytes, index=False)
                st.download_button(
                    "⬇️ Baixar Excel",
                    data=excel_bytes.getvalue(),
                    file_name="orcamentos_filtrados.xlsx",
                    mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
                )

            # Exibir orçamentos
            for o in orcamentos_filtrados:
                orc_id, data_hora, cliente_nome, cliente_cnpj, vendedor_nome = o
                orc, confecc, bob = carregar_orcamento_por_id(orc_id)
                
                orc_cols = ['id','data_hora','cliente_nome','cliente_cnpj','tipo_cliente','estado','frete','tipo_pedido','vendedor_nome','vendedor_tel','vendedor_email','observacao', 'preco_m2_base']
                orc_data = dict(zip(orc_cols, orc))

                with st.expander(f"📝 ID {orc_id} - {cliente_nome} ({data_hora})"):
                    st.markdown(f"**Cliente:** {cliente_nome}")
                    st.markdown(f"**CNPJ:** {cliente_cnpj}")
                    st.markdown(f"**Vendedor:** {vendedor_nome}")
                    preco_m2_base_display = orc_data.get('preco_m2_base') if orc_data.get('preco_m2_base') is not None else 0.0
                    st.markdown(f"**Preço Base Utilizado (💵):** {_format_brl(preco_m2_base_display)}")

                    if confecc:
                        st.markdown("### ⬛ Itens Confeccionados")
                        for c in confecc:
                            st.markdown(f"- **{c[0]}**: {c[3]}x {c[1]:.2f}m x {c[2]:.2f}m | Cor: {c[4]}")

                    if bob:
                        st.markdown("### 🔘 Itens Bobinas")
                        for b in bob:
                            esp = f" | Esp: {b[5]:.2f}mm" if b[5] is not None else ""
                            st.markdown(f"- **{b[0]}**: {b[3]}x {b[1]:.2f}m | Largura: {b[2]:.2f}m{esp} | Cor: {b[4]}")

                    col1, col2, col3 = st.columns([1,1,1])
                    with col1:
                        # Reabrir
                        if st.button("🔄 Reabrir", key=f"reabrir_{orc_id}"):
                            
                            preco_m2_base = orc_data.get('preco_m2_base') if orc_data.get('preco_m2_base') is not None else 0.0
                            
                            primeiro_produto = None
                            if confecc:
                                primeiro_produto = confecc[0][0] 
                            elif bob:
                                primeiro_produto = bob[0][0]
                                
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
                                "itens_confeccionados": [dict(zip(['produto','comprimento','largura','quantidade','cor'],c)) for c in confecc],
                                "bobinas_adicionadas": [dict(zip(['produto','comprimento','largura','quantidade','cor','espessura','preco_unitario'],b)) for b in bob],
                                "menu_index": 0 
                            })
                            st.success(f"Orçamento ID {orc_id} carregado no formulário.")
                            st.rerun()

                    with col2:
                        # Baixar PDF 
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
                            itens_confeccionados=[dict(zip(['produto','comprimento','largura','quantidade','cor'],c)) for c in confecc],
                            itens_bobinas=[dict(zip(['produto','comprimento','largura','quantidade','cor','espessura','preco_unitario'],b)) for b in bob],
                            resumo_conf=None, 
                            resumo_bob=None,  
                            observacao=orc[11],
                            preco_m2=orc_data.get('preco_m2_base') if orc_data.get('preco_m2_base') is not None else 0.0
                        ) 
                        st.download_button(
                            "📄 Baixar PDF",
                            data=pdf_bytes,
                            file_name=f"orcamento_{orc_id}.pdf",
                            mime="application/pdf",
                            key=f"download_historico_{orc_id}"
                        )
