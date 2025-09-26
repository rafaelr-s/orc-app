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
# Função para gerar PDF
# ============================
def gerar_pdf(cliente, vendedor, itens_confeccionados, itens_bobinas, resumo_conf, resumo_bob, observacao, preco_m2, tipo_cliente="", estado=""):
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

    # Dados do Cliente
    pdf.set_font("Arial", "B", 11)
    pdf.cell(0, 6, "Cliente", ln=True)
    pdf.set_font("Arial", size=10)
    largura_util = pdf.w - 2*pdf.l_margin  # largura útil para multi_cell

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
        for item in list(itens_confeccionados):
            area_item = item['comprimento'] * item['largura'] * item['quantidade']
            # Confeccionados seguem preço global (mantive comportamento original)
            valor_item = area_item * preco_m2
            txt = (
                f"{item['quantidade']}x {item['produto']} - {item['comprimento']}m x {item['largura']}m "
                f"| Cor: {item.get('cor','')} | Valor Bruto: {_format_brl(valor_item)}"
            )
            pdf.multi_cell(largura_util, 6, txt)
            pdf.ln(1)

    if resumo_conf:
        m2_total, valor_bruto, valor_ipi, valor_final, valor_st, aliquota_st = resumo_conf
        pdf.ln(3)
        pdf.set_font("Arial", "B", 11)
        pdf.cell(0, 10, "Resumo - Confeccionados", ln=True)
        pdf.set_font("Arial", "", 10)
        pdf.cell(0, 8, f"Preço por m² utilizado: {_format_brl(preco_m2)}", ln=True)
        pdf.cell(0, 8, f"Área Total: {str(f'{m2_total:.2f}'.replace('.', ','))} m²", ln=True)
        pdf.cell(0, 8, f"Valor Bruto: {_format_brl(valor_bruto)}", ln=True)

        if cliente.get("tipo_pedido") != "Industrialização":
            pdf.cell(0, 8, f"IPI: {_format_brl(valor_ipi)}", ln=True)

        if valor_st > 0:
            pdf.cell(0, 8, f"ST ({aliquota_st}%): {_format_brl(valor_st)}", ln=True)

        # Valor Final em negrito
        pdf.set_font("Arial", "B", 10)
        pdf.cell(0, 8, f"Valor Total{(' + ST' if valor_st>0 else '')}: {_format_brl(valor_final)}", ln=True)
        pdf.set_font("Arial", "", 10)  # volta para fonte normal
        pdf.ln(10)

    # Itens Bobinas
    if itens_bobinas:
        pdf.set_font("Arial", "B", 11)
        pdf.cell(0, 8, "Itens Bobina", ln=True)
        pdf.set_font("Arial", size=8)
        for item in list(itens_bobinas):
            metros_item = item['comprimento'] * item['quantidade']
            # Usa preco_unitario se existir (fixado por espessura), senão usa preco_m2 global
            preco_item = item.get('preco_unitario', preco_m2)
            valor_item = metros_item * preco_item
            txt = (
                f"{item['quantidade']}x {item['produto']} - {item['comprimento']}m | Largura: {item['largura']}m "
                f"| Cor: {item.get('cor','')} | Valor Bruto: {_format_brl(valor_item)}"
            )
            if "espessura" in item:
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
            if not any("espessura" in item for item in itens_bobinas):
                pdf.cell(0, 8, f"Preço por metro linear utilizado: {_format_brl(preco_m2)}", ln=True)
            pdf.cell(0, 8, f"Total de Metros Lineares: {str(f'{m_total:.2f}'.replace('.', ','))} m", ln=True)
            pdf.cell(0, 8, f"Valor Bruto: {_format_brl(valor_bruto)}", ln=True)
            
            if cliente.get("tipo_pedido") != "Industrialização":
                pdf.cell(0, 8, f"IPI: {_format_brl(valor_ipi)}", ln=True)
            
            pdf.set_font("Arial", "B", 10)
            pdf.cell(0, 8, f"Valor Total: {_format_brl(valor_final)}", ln=True)
        else:
            pdf.cell(0, 8, f"Valor Total com IPI: {_format_brl(valor_final)}", ln=True)
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

    # ====== IMPORTANTE ======
    # Retorna o PDF como buffer
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

def calcular_valores_confeccionados(itens, preco_m2, tipo_cliente="", estado="", tipo_pedido="Direta"):
    m2_total = sum(item['comprimento'] * item['largura'] * item['quantidade'] for item in itens)
    valor_bruto = m2_total * preco_m2

    # Se for industrialização → sem impostos
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
    # m_total continua sendo soma dos metros (útil para exibição)
    m_total = sum(item['comprimento'] * item['quantidade'] for item in itens)
    # Valor bruto: soma item a item usando preco_unitario quando presente
    valor_bruto = sum(
        (item['comprimento'] * item['quantidade']) * item.get('preco_unitario', preco_m2)
        for item in itens
    )

    if tipo_pedido == "Industrialização":
        valor_ipi = 0
        valor_final = valor_bruto
    else:
        valor_ipi = valor_bruto * 0.0975
        valor_final = valor_bruto + valor_ipi

    return m_total, valor_bruto, valor_ipi, valor_final

# ============================
# Interface Streamlit
# ============================
brasilia_tz = pytz.timezone("America/Sao_Paulo")
data_hora_brasilia = datetime.now(brasilia_tz).strftime("%d/%m/%Y %H:%M")
st.markdown(f"🕒 **Data e Hora:** {data_hora_brasilia}")

# --- Cliente ---
st.subheader("👤 Dados do Cliente")
col1, col2 = st.columns(2)
with col1:
    Cliente_nome = st.text_input("Razão ou Nome Fantasia", value=st.session_state.get("Cliente_nome",""))
with col2:
    Cliente_CNPJ = st.text_input("CNPJ ou CPF (Opcional)", value=st.session_state.get("Cliente_CNPJ",""))

tipo_cliente = st.selectbox("Tipo do Cliente:", [" ","Consumidor Final", "Revenda"])
estado = st.selectbox("Estado do Cliente:", options=list(icms_por_estado.keys()))

tipo_pedido = st.radio("Tipo do Pedido:", ["Direta", "Industrialização"])

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

# ============================
# Seleção de Produto (MOVER PARA CIMA)
# ============================
produto = st.selectbox("Nome do Produto:", options=produtos_lista)
tipo_produto = st.radio("Tipo do Produto:", ["Confeccionado", "Bobina"])
preco_m2 = st.number_input("Preço por m² ou metro linear (R$):", min_value=0.0, value=0.0, step=0.01)

# ICMS automático
aliquota_icms = icms_por_estado[estado]
st.info(f"🔹 Alíquota de ICMS para {estado}: **{aliquota_icms}% (já incluso no preço)**")

# ST aparece só se Encerado + Revenda
aliquota_st = None
if produto == "Encerado" and tipo_cliente == "Revenda":
    aliquota_st = st_por_estado.get(estado, 0)
    st.warning(f"⚠️ Este produto possui ST no estado {estado} aproximado a: **{aliquota_st}%**")
    
# ============================
# Confeccionado
# ============================
if tipo_produto == "Confeccionado":
    st.subheader("➕ Adicionar Item Confeccionado")
    col1, col2, col3 = st.columns(3)
    with col1:
        comprimento = st.number_input("Comprimento (m):", min_value=0.010, value=1.0, step=0.10, key="comp_conf")
    with col2:
        largura = st.number_input("Largura (m):", min_value=0.010, value=1.0, step=0.10, key="larg_conf")
    with col3:
        quantidade = st.number_input("Quantidade:", min_value=1, value=1, step=1, key="qtd_conf")

    if st.button("➕ Adicionar Medida"):
        st.session_state['itens_confeccionados'].append({
            'produto': produto,
            'comprimento': comprimento,
            'largura': largura,
            'quantidade': quantidade,
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
                cor = st.text_input("Cor:", value=item['cor'], key=f"cor_conf_{idx}")
                st.session_state['itens_confeccionados'][idx]['cor'] = cor
            with col4:
                remover = st.button("❌", key=f"remover_conf_{idx}")
                if remover:
                    st.session_state['itens_confeccionados'].pop(idx)
                    st.rerun()

    if st.button("🧹 Limpar Itens"):
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

# ============================
# Bobina
# ============================
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

    if st.button("➕ Adicionar Bobina"):
        item_bobina = {
            'produto': produto,
            'comprimento': comprimento,
            'largura': largura_bobina,
            'quantidade': quantidade,
            'cor': ""
        }
        # se tem espessura (pertence aos prefixos), adiciona o campo 'espessura' e fixa o preço naquele momento
        if espessura_bobina:
            item_bobina['espessura'] = espessura_bobina
            # FIXAR preço por espessura: salva preco_unitario no item
            item_bobina['preco_unitario'] = preco_m2

        st.session_state['bobinas_adicionadas'].append(item_bobina)

    if st.session_state['bobinas_adicionadas']:
        st.subheader("📋 Bobinas Adicionadas")
        for idx, item in enumerate(st.session_state['bobinas_adicionadas'][:] ):
            col1, col2, col3, col4 = st.columns([4,2,2,1])
            with col1:
                metros_item = item['comprimento'] * item['quantidade']
                # usa preco_unitario se existir (fixado), senão usa preco_m2 global
                valor_item = metros_item * item.get('preco_unitario', preco_m2)
                detalhes = (
                    f"🔹 {item['quantidade']}x {item['comprimento']:.2f}m | Largura: {item['largura']:.2f}m "
                    f"= {metros_item:.2f} m → {_format_brl(valor_item)}"
                )
                if 'espessura' in item:
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

        m_total, valor_bruto, valor_ipi, valor_final = calcular_valores_bobinas(
            st.session_state['bobinas_adicionadas'], preco_m2, tipo_pedido
        )
        st.markdown("---")
        st.success("💰 **Resumo do Pedido - Bobinas**")
        st.write(f"📏 Total de Metros Lineares: **{m_total:.2f} m**".replace(".", ","))
        st.write(f"💵 Valor Bruto: **{_format_brl(valor_bruto)}**")

        if tipo_pedido != "Industrialização":
            st.write(f"🧾 IPI (9.75%): **{_format_brl(valor_ipi)}**")
            st.write(f"💰 Valor Final com IPI (9.75%): **{_format_brl(valor_final)}**")
        else:
            st.write(f"💰 Valor Final: **{_format_brl(valor_final)}**")

        if st.button("🧹 Limpar Bobinas"):
            st.session_state['bobinas_adicionadas'] = []
            st.rerun()

# ============================
# Tipo de Frete
# ============================
st.subheader("🚚 Tipo de Frete")
frete = st.radio("Selecione o tipo de frete:", ["CIF", "FOB"])

# ============================ 
# Observações e Vendedor 
# ============================
st.subheader("🔎 Observações")
Observacao = st.text_area("Insira aqui alguma observação sobre o orçamento (opcional)")

st.subheader("🗣️ Vendedor(a)")
col1, col2 = st.columns(2)
with col1:
    vendedor_nome = st.text_input("Nome")
    vendedor_tel = st.text_input("Telefone")
    with col2:
        vendedor_email = st.text_input("E-mail")

# ============================ 
# Botões PDF e Salve 
# ============================   
    if st.button("📄 Gerar PDF e Salvar Orçamento"):
    cliente = {
        "nome": Cliente_nome,
        "cnpj": Cliente_CNPJ,
        "tipo_cliente": tipo_cliente,
        "estado": estado,
        "frete": "CIF",
        "tipo_pedido": tipo_pedido
    }
    vendedor = {"nome": vendedor_nome, "tel": vendedor_tel, "email": vendedor_email}

    # Salvar orçamento no banco
    orcamento_id = salvar_orcamento(
        cliente, 
        vendedor, 
        st.session_state["itens_confeccionados"], 
        st.session_state["bobinas_adicionadas"], 
        Observacao
    )
    st.success(f"Orçamento salvo com ID {orcamento_id}")

    # ====== Corrigir chamada gerar_pdf ======
    resumo_conf = None
    resumo_bob = None
    if st.session_state["itens_confeccionados"]:
        resumo_conf = calcular_valores_confeccionados(
            st.session_state["itens_confeccionados"], 
            preco_m2, 
            tipo_cliente, 
            estado, 
            tipo_pedido
        )
    if st.session_state["bobinas_adicionadas"]:
        resumo_bob = calcular_valores_bobinas(
            st.session_state["bobinas_adicionadas"], 
            preco_m2, 
            tipo_pedido
        )

    pdf_buffer = gerar_pdf(
        cliente, 
        vendedor, 
        st.session_state["itens_confeccionados"], 
        st.session_state["bobinas_adicionadas"], 
        resumo_conf,          # <- corrigido
        resumo_bob,           # <- corrigido
        Observacao, 
        preco_m2,
        tipo_cliente=tipo_cliente,
        estado=estado
    )
    st.download_button("⬇️ Baixar PDF", pdf_buffer, file_name="orcamento.pdf", mime="application/pdf")
    
# ============================
# Histórico de Orçamentos (adicionado sem alterar funções originais)
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
            st.rerun()
        
        # Botão para reabrir orçamento
        if st.button(f"🔄 Reabrir ID {o[0]}", key=f"reabrir_{o[0]}"):
            st.session_state["itens_confeccionados"] = [{"produto":c[0],"comprimento":c[1],"largura":c[2],"quantidade":c[3],"cor":c[4]} for c in confecc]
            st.session_state["bobinas_adicionadas"] = [{"produto":b[0],"comprimento":b[1],"largura":b[2],"quantidade":b[3],"cor":b[4],"espessura":b[5],"preco_unitario":b[6]} for b in bob]
            st.rerun()
