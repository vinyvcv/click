
from flask import Flask, render_template, request, jsonify, send_file, redirect, url_for, flash, session
import pandas as pd
from sqlalchemy import create_engine, text
import urllib
import os
import requests
from PIL import Image
from datetime import datetime
from jinja2 import Environment, FileSystemLoader
import pdfkit
import io
import base64
import qrcode
from io import BytesIO
from functools import wraps
from datetime import timedelta
import bcrypt
from functools import wraps
import platform

import numpy as np




app = Flask(__name__)
app.secret_key = 'clickvistoria2024'

# Rota de logout
@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('login'))
# Decorator para proteger rotas
def login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'user_id' not in session:
            flash('Por favor, faça login para acessar esta página', 'error')
            return redirect(url_for('login'))
        return f(*args, **kwargs)
    return decorated_function

# Rota de login com usuário/senha fixos
import bcrypt

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'GET':
        return render_template('login.html')

    email = request.form.get('email')
    senha_digitada = request.form.get('password')

    query = """
        SELECT id, nome, email, senha
        FROM usuarios
        WHERE email = :email
    """
    params = {"email": email}

    with engine.connect() as conn:
        result = conn.execute(text(query), params).fetchone()

    if result:
        hash_armazenado = result.senha

        if bcrypt.checkpw(senha_digitada.encode('utf-8'), hash_armazenado.encode('utf-8')):
            session['user_id'] = result.id
            session['user_name'] = result.nome
            session['user_email'] = result.email

            # Aqui trata requisição AJAX (JSON)
            if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
                return jsonify({'success': True, 'redirect': url_for('analise_vistoria')})

            return redirect(url_for('analise_vistoria'))

    # Login inválido
    if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
        return jsonify({'success': False, 'message': 'E-mail ou senha incorretos'})

    flash('Credenciais inválidas', 'error')
    return redirect(url_for('login'))


# Rota principal protegida
@app.route('/')
@login_required
def index():
    return redirect(url_for('analise_vistoria'))

# ---------- CONEXÃO COM O BANCO USANDO SQLALCHEMY ----------
def criar_engine():
    params = urllib.parse.quote_plus(
        "DRIVER={ODBC Driver 17 for SQL Server};"
        "SERVER=85.31.231.127;"
        "DATABASE=db_click_vistoria;"
        "UID=sa;"
        "PWD=Dagimas4045;"
        "Encrypt=no;"
    )
    return create_engine(f"mssql+pyodbc:///?odbc_connect={params}", fast_executemany=True)

engine = criar_engine()

# ---------- CARREGAR DADOS COMPLETOS COM INFORMAÇÕES RESUMIDAS ----------
def carregar_vistorias():
    query = '''
        SELECT v.vistoria_id, v.veiculo_id, v.user_id, v.tipo_veiculo, v.valor,
               v.data_solicitacao, v.data_realizacao, v.observacoes,
               p.nome, p.email, p.telefone, p.cpf,
               f.url_foto, f.tipo_foto_id,
               tf.descricao AS nome_foto,
               ve.placa  -- Adiciona placa do veículo
        FROM vistoria v
        JOIN pessoa p ON v.user_id = p.user_id
        LEFT JOIN veiculo ve ON v.veiculo_id = ve.veiculo_id  -- Join com veículo
        LEFT JOIN fotos_vistoria f ON v.vistoria_id = f.vistoria_id
        LEFT JOIN tipos_foto tf ON f.tipo_foto_id = tf.tipo_foto_id
        LEFT JOIN laudos_pdf l ON v.vistoria_id = l.vistoria_id
        WHERE l.status IS NULL OR l.status = 0
    '''
    with engine.connect() as conn:
        df = pd.read_sql(text(query), conn)
    return df

# ---------- CARREGAR LISTA RESUMIDA PARA O SELECT ----------
def carregar_lista_vistorias():
    """Carrega lista resumida de vistorias para o select"""
    query = query = '''
    SELECT DISTINCT 
        v.vistoria_id,
        p.nome,
        p.cpf,
        ve.placa,
        v.data_solicitacao,
        v.tipo_veiculo,
        u.nome AS nome_aprovador
    FROM vistoria v
    JOIN pessoa p ON v.user_id = p.user_id
    LEFT JOIN veiculo ve ON v.veiculo_id = ve.veiculo_id
    LEFT JOIN laudos_pdf l ON v.vistoria_id = l.vistoria_id
    LEFT JOIN usuarios u ON l.usuario_aprovador = u.id
    WHERE l.status IS NULL OR l.status = 0
    ORDER BY v.vistoria_id DESC
'''

    with engine.connect() as conn:
        df = pd.read_sql(text(query), conn)
    return df.to_dict('records')


  
# ---------- BUSCAR DADOS COMPLETOS DO VEÍCULO ----------
def carregar_dados_veiculo(veiculo_id):
    query = '''
        SELECT 
            v.veiculo_id, v.user_id, v.placa, v.renavam, v.chassi, 
            v.restricao, v.modelo, v.marca, v.versao, v.ano_fabricacao, 
            v.cor, v.status, v.tipo_veiculo_id,
            p.nome, p.cpf, p.cnh, p.email, p.data_nascimento, 
            p.telefone, p.cep, p.endereco
        FROM veiculo v
        LEFT JOIN pessoa p ON v.user_id = p.user_id
        WHERE v.veiculo_id = :veiculo_id
    '''
    with engine.connect() as conn:
        df = pd.read_sql(text(query), conn, params={"veiculo_id": veiculo_id})
    if df.empty:
        print(f"[⚠️] Veículo não encontrado para veiculo_id = {veiculo_id}")
    return df.iloc[0].to_dict() if not df.empty else None


# ---------- ATUALIZAR STATUS NO BANCO ----------
def atualizar_status(vistoria_id, novo_status, fotos_aprovadas):
    vistoria_id = int(vistoria_id)

    with engine.begin() as conn:
        # Zera tudo primeiro
        conn.execute(
            text("UPDATE fotos_vistoria SET status_foto = 0, justificativa = NULL WHERE vistoria_id = :vistoria_id"),
            {"vistoria_id": vistoria_id}
        )

        # Agora atualiza as aprovadas com ou sem justificativa
        for foto in fotos_aprovadas:
            url_foto = foto[0]
            justificativa = foto[2] if len(foto) > 2 else None  # caso não venha justificativa

            conn.execute(
                text("""
                    UPDATE fotos_vistoria 
                    SET status_foto = 1, justificativa = :justificativa
                    WHERE url_foto = :url
                """),
                {"url": url_foto, "justificativa": justificativa}
            )


# ---------- SALVAR PDF NO BANCO ----------
from datetime import datetime

def salvar_pdf_no_banco(vistoria_id, pdf_bytes, status, usuario_id, selo_bytes=None):
    with engine.begin() as conn:
        conn.execute(
            text("""
                INSERT INTO laudos_pdf (vistoria_id, arquivo, data_emissao, status, selo, usuario_aprovador)
                VALUES (:vistoria_id, :arquivo, :data_emissao, :status, :selo, :usuario_aprovador)
            """),
            {
                "vistoria_id": int(vistoria_id),
                "arquivo": pdf_bytes,
                "data_emissao": datetime.now(),
                "status": status,
                "selo": selo_bytes,
                "usuario_aprovador": usuario_id
            }
        )



def gerar_qr_base64(url):
    qr = qrcode.make(url)
    buffered = BytesIO()
    qr.save(buffered, format="PNG")
    img_b64 = base64.b64encode(buffered.getvalue()).decode()
    return f"data:image/png;base64,{img_b64}"
# ---------- GERAR PDF ETUFOR ----------
def gerar_laudo_etufor_pdf(dados_vistoria, dados_veiculo, fotos_confirmadas, status_vistoria):
    """Gera PDF usando o template ETUFOR"""

    # Preparar dados combinados para o template
    dados_template = {
        # Dados da vistoria
        'vistoria_id': dados_vistoria['vistoria_id'],
        'veiculo_id': dados_vistoria['veiculo_id'], 
        'user_id': dados_vistoria['user_id'],
        'tipo_veiculo': dados_vistoria['tipo_veiculo'],
        'status': status_vistoria,  # Usar o status passado como parâmetro
        'valor': dados_vistoria['valor'],
        'data_solicitacao': dados_vistoria['data_solicitacao'],
        'data_realizacao': dados_vistoria['data_realizacao'],
        'observacoes': dados_vistoria['observacoes'],
        
        # Dados da pessoa
        'nome': dados_veiculo['nome'] if dados_veiculo else 'Não informado',
        'cpf': dados_veiculo['cpf'] if dados_veiculo else 'Não informado',
        'email': dados_veiculo['email'] if dados_veiculo else 'Não informado',
        'telefone': dados_veiculo['telefone'] if dados_veiculo else 'Não informado',
        'endereco': dados_veiculo['endereco'] if dados_veiculo else 'Não informado',
        'cep': dados_veiculo['cep'] if dados_veiculo else 'Não informado',
        
        # Dados do veículo
        'placa': dados_veiculo['placa'] if dados_veiculo else 'Não informado',
        'renavam': dados_veiculo['renavam'] if dados_veiculo else 'Não informado',
        'chassi': dados_veiculo['chassi'] if dados_veiculo else 'Não informado',
        'marca': dados_veiculo['marca'] if dados_veiculo else 'Não informado',
        'modelo': dados_veiculo['modelo'] if dados_veiculo else 'Não informado',
        'versao': dados_veiculo['versao'] if dados_veiculo else 'Não informado',
        'ano_fabricacao': dados_veiculo['ano_fabricacao'] if dados_veiculo else 'Não informado',
        'cor': dados_veiculo['cor'] if dados_veiculo else 'Não informado',
    }

    # Carregar template ETUFOR
    from jinja2 import Environment, FileSystemLoader, select_autoescape

    env = Environment(
    loader=FileSystemLoader("templates"),
    autoescape=select_autoescape(['html', 'xml']),
    cache_size=0  # <--- ISSO LIMPA O CACHE!
)

    template = env.get_template("laudo_etufor.html")
    url_qr = f"https://clickvistoria.com.br/laudo/{dados_vistoria['vistoria_id']}"  # ou seu ngrok/url real
    qr_code_img = gerar_qr_base64(url_qr)

    # Renderizar HTML com os dados
    html = template.render(
    dados=dados_template,
    fotos=fotos_confirmadas,
    datetime=datetime,
    qr_code_img=qr_code_img  # novo argumento
)


    # Gerar arquivo temporário
    caminho_html = f"temp_laudo_etufor_{dados_template['vistoria_id']}.html"
    caminho_pdf = f"laudo_etufor_{dados_template['vistoria_id']}.pdf"

    with open(caminho_html, "w", encoding="utf-8") as f:
        f.write(html)

    # Configuração do wkhtmltopdf
    options = {
        'page-size': 'A4',
        'margin-top': '0.75in',
        'margin-right': '0.75in',
        'margin-bottom': '0.75in',
        'margin-left': '0.75in',
        'encoding': "UTF-8",
        'no-outline': None,
        'enable-local-file-access': None
    }

    if platform.system() == "Windows":
    	caminho_wkhtmltopdf = "C:/Program Files/wkhtmltopdf/bin/wkhtmltopdf.exe"
    else:
    	caminho_wkhtmltopdf = "/usr/bin/wkhtmltopdf"

    config = pdfkit.configuration(wkhtmltopdf=caminho_wkhtmltopdf)

    pdfkit.from_file(caminho_html, caminho_pdf, options=options, configuration=config)

    # Ler o PDF gerado
    with open(caminho_pdf, "rb") as f:
        pdf_bytes = f.read()

    # Limpar arquivos temporários
    os.remove(caminho_html)
    os.remove(caminho_pdf)
    
    return pdf_bytes
# ---------- GERAR PDF SELO ----------
def gerar_selo_pdf(dados_veiculo, selo_numero, qr_code_img, exercicio="2025"):
    from jinja2 import Environment, FileSystemLoader
    import pdfkit
    from datetime import datetime
    import os
    
    # Configurar o ambiente Jinja2
    template_dir = os.path.join(os.path.dirname(__file__), "templates")
    env = Environment(loader=FileSystemLoader(template_dir))
    template = env.get_template("selo.html")
    
    # Preparar dados para o template
    # Função auxiliar para tratar None
    def safe_upper(value):
        return str(value).upper() if value is not None else ''
    
    dados_template = {
        "selo": str(selo_numero),  # Converter para string
        "modalidade": "AGENDAMENTO ONLINE DE VISTORIA DE VEÍCULO DA PLATAFORMA DIGITAL",
        "marcaModelo": f"{safe_upper(dados_veiculo.get('marca'))}/{safe_upper(dados_veiculo.get('modelo'))}",
        "placa": safe_upper(dados_veiculo.get('placa')),
        "uf": "CE",
        "chassi": safe_upper(dados_veiculo.get('chassi')),
        "cor": safe_upper(dados_veiculo.get('cor')),
        "dataEmissao": datetime.now().strftime('%d/%m/%Y'),
        "exercicio": str(exercicio),
        "qrCode": qr_code_img
    }
    
    # Renderizar HTML
    html = template.render(**dados_template)
    
    # Salvar HTML temporário para debug (opcional)
    temp_html = f"temp_selo_{selo_numero}.html"
    with open(temp_html, "w", encoding="utf-8") as f:
        f.write(html)
    
    # Configurações otimizadas para wkhtmltopdf
    options = {
        'page-size': 'A4',
        'margin-top': '10mm',
        'margin-right': '10mm',
        'margin-bottom': '10mm',
        'margin-left': '10mm',
        'encoding': "UTF-8",
        'no-outline': None,
        'enable-local-file-access': None,
        'dpi': 96,  # DPI padrão para evitar problemas
        'disable-smart-shrinking': None,  # Evita redimensionamento automático
        'print-media-type': None,  # Força uso de estilos de impressão
        'javascript-delay': 1000,  # Aguarda renderização
        'no-stop-slow-scripts': None,
        'debug-javascript': None,
        'load-error-handling': 'ignore',
        'load-media-error-handling': 'ignore'
    }
    
    # Configurar wkhtmltopdf
    if platform.system() == "Windows":
    	caminho_wkhtmltopdf = "C:/Program Files/wkhtmltopdf/bin/wkhtmltopdf.exe"
    else:
    	caminho_wkhtmltopdf = "/usr/bin/wkhtmltopdf"
    config = pdfkit.configuration(wkhtmltopdf=caminho_wkhtmltopdf)
    
    # Gerar PDF a partir do arquivo HTML (mais confiável que from_string)
    pdf_bytes = pdfkit.from_file(temp_html, False, options=options, configuration=config)
    
    # Remover arquivo temporário
    os.remove(temp_html)
    
    return pdf_bytes
    
# ---------- ROTAS ----------



   

@app.route('/analise-vistoria')
@login_required
def analise_vistoria():
    # Query para buscar os dados
    query = '''
        SELECT DISTINCT 
            v.vistoria_id,
            v.veiculo_id,
            v.user_id,
            p.nome,
            p.cpf,
            ve.placa,
            v.data_solicitacao,
            v.tipo_veiculo
        FROM vistoria v
        JOIN pessoa p ON v.user_id = p.user_id
        LEFT JOIN veiculo ve ON v.veiculo_id = ve.veiculo_id
        LEFT JOIN laudos_pdf l ON v.vistoria_id = l.vistoria_id
        WHERE (l.status IS NULL OR l.status = 0)
        ORDER BY v.vistoria_id DESC
    '''
    
    with engine.connect() as conn:
        df = pd.read_sql(text(query), conn)
    
    # Debug: imprimir primeiras linhas
    print("=== DEBUG: Primeiras 5 linhas do DataFrame ===")
    print(df.head())
    print("=== Colunas disponíveis ===")
    print(df.columns.tolist())
    
    # Converter DataFrame para lista de dicionários
    vistorias_lista = []
    for _, row in df.iterrows():
        # Debug para primeira linha
        if _ == 0:
            print(f"=== DEBUG: Primeira linha ===")
            print(f"CPF: {row['cpf']} (tipo: {type(row['cpf'])})")
            print(f"Placa: {row.get('placa', 'CAMPO NAO EXISTE')} (tipo: {type(row.get('placa', None))})")
        
        vistorias_lista.append({
            'vistoria_id': int(row['vistoria_id']),
            'nome': str(row['nome']) if pd.notna(row['nome']) else 'Não informado',
            'cpf': str(row['cpf']) if pd.notna(row['cpf']) else 'Não informado',
            'placa': str(row['placa']) if pd.notna(row['placa']) else 'Sem placa',
            'data_solicitacao': row['data_solicitacao'],
            'tipo_veiculo': str(row['tipo_veiculo']) if pd.notna(row['tipo_veiculo']) else 'Não especificado'
        })
    
    # Também manter ids_disponiveis para compatibilidade
    ids_disponiveis = [v['vistoria_id'] for v in vistorias_lista]
    
    return render_template('analise_vistoria.html', 
                         vistorias_lista=vistorias_lista,
                         ids_disponiveis=ids_disponiveis)


@app.route('/carregar-vistoria/<int:vistoria_id>')
@login_required
def carregar_vistoria(vistoria_id):
    df = carregar_vistorias()
    df_vistoria = df[df["vistoria_id"] == vistoria_id]
    
    if df_vistoria.empty:
        return jsonify({'error': 'Vistoria não encontrada'}), 404
    
    dados_vistoria = df_vistoria.iloc[0].replace({np.nan: None}).to_dict()
    dados_veiculo = carregar_dados_veiculo(dados_vistoria['veiculo_id'])

    # Preparar fotos (já trazendo status e justificativa)
    query_fotos = '''
        SELECT f.url_foto, tf.descricao AS nome_foto, 
               f.status_foto, f.justificativa
        FROM fotos_vistoria f
        LEFT JOIN tipos_foto tf ON f.tipo_foto_id = tf.tipo_foto_id
        WHERE f.vistoria_id = :vistoria_id
    '''
    
    with engine.connect() as conn:
        df_fotos = pd.read_sql(text(query_fotos), conn, params={"vistoria_id": vistoria_id})

    fotos = []
    for _, row in df_fotos.iterrows():
        fotos.append({
            'url': row['url_foto'],
            'nome': row['nome_foto'] or f"Foto {len(fotos) + 1}",
            'status': 'aprovada' if row['status_foto'] == 1 else 'reprovada',
            'justificativa': row['justificativa'] or ''
        })
    
    return jsonify({
        'dados_vistoria': dados_vistoria,
        'dados_veiculo': dados_veiculo,
        'fotos': fotos
    })

@app.route('/gerar-laudo', methods=['POST'])
@login_required
def gerar_laudo():
    try:
        data = request.json
        vistoria_id = data['vistoria_id']
        status = data['status']
        fotos = data.get('fotos', [])



        # Carregar dados
        df = carregar_vistorias()
        df_vistoria = df[df["vistoria_id"] == int(vistoria_id)]
        dados_vistoria = df_vistoria.iloc[0].to_dict()
        dados_veiculo = carregar_dados_veiculo(dados_vistoria['veiculo_id'])

        # Gerar PDF do laudo
        pdf_bytes_laudo = gerar_laudo_etufor_pdf(dados_vistoria, dados_veiculo, fotos, status)

        # Selo somente se aprovado
        pdf_bytes_selo = None
        if status.lower() == "aprovado" and dados_veiculo:
            url_qr = f"https://clickvistoria.com.br/laudo/{vistoria_id}"
            qr_code_img = gerar_qr_base64(url_qr)
            pdf_bytes_selo = gerar_selo_pdf(dados_veiculo, vistoria_id, qr_code_img)

        status_int = 1 if status.lower() == "aprovado" else 0
        usuario_id = session.get('user_id')
        salvar_pdf_no_banco(vistoria_id, pdf_bytes_laudo, status_int, usuario_id, selo_bytes=pdf_bytes_selo)

        # Atualizar status individual das fotos (salva status e justificativa no banco)
        with engine.begin() as conn:
            for foto in fotos:
                conn.execute(text("""
                    UPDATE fotos_vistoria 
                    SET status_foto = :status_foto, justificativa = :justificativa 
                    WHERE url_foto = :url AND vistoria_id = :vistoria_id
                """), {
                    "status_foto": 1 if foto['status'] == 'aprovada' else 0,
                    "justificativa": foto['justificativa'],
                    "url": foto['url'],
                    "vistoria_id": vistoria_id
                })

        pdf_base64 = base64.b64encode(pdf_bytes_laudo).decode('utf-8')
        return jsonify({
            'success': True,
            'pdf_base64': pdf_base64,
            'filename': f'laudo_etufor_{vistoria_id}.pdf'
        })

    except Exception as e:
        import traceback
        traceback.print_exc()
        return jsonify({'success': False, 'error': str(e)}), 500




@app.route('/laudos-salvos')
@login_required
def laudos_salvos():
    data_inicio = request.args.get('data_inicio')
    data_fim = request.args.get('data_fim')
    placa = request.args.get('placa')
    renavam = request.args.get('renavam')

    query = '''
        SELECT 
    l.id, 
    l.vistoria_id, 
    l.data_emissao,
    l.status AS status,
    v.placa, 
    v.renavam, 
    v.chassi, 
    p.nome AS nome_proprietario,
    u.nome AS nome_aprovador
FROM laudos_pdf l
LEFT JOIN vistoria vi ON l.vistoria_id = vi.vistoria_id
LEFT JOIN veiculo v ON vi.veiculo_id = v.veiculo_id
LEFT JOIN pessoa p ON v.user_id = p.user_id
LEFT JOIN usuarios u ON l.usuario_aprovador = u.id
WHERE 1=1

    '''
    params = {}

    if data_inicio:
        query += " AND l.data_emissao >= :data_inicio"
        params["data_inicio"] = data_inicio

    if data_fim:
        query += " AND l.data_emissao <= :data_fim"
        params["data_fim"] = data_fim

    if placa:
        query += " AND v.placa LIKE :placa"
        params["placa"] = f"%{placa}%"

    if renavam:
        query += " AND v.renavam LIKE :renavam"
        params["renavam"] = f"%{renavam}%"

    query += " ORDER BY l.data_emissao DESC"

    df_laudos = pd.read_sql(text(query), engine, params=params)
    laudos = df_laudos.to_dict('records')

    return render_template('laudos_salvos.html', laudos=laudos)


@app.route('/download-laudo/<int:laudo_id>')
@login_required
def download_laudo(laudo_id):
    with engine.connect() as conn:
        result = conn.execute(
            text("SELECT arquivo FROM laudos_pdf WHERE id = :id"),
            {"id": laudo_id}
        ).fetchone()
        
        if result:
            pdf_bytes = result[0]
            return send_file(
                io.BytesIO(pdf_bytes),
                mimetype='application/pdf',
                as_attachment=True,
                download_name=f'laudo_{laudo_id}.pdf'
            )
        else:
            flash('Laudo não encontrado', 'error')
            return redirect(url_for('laudos_salvos'))
        
@app.route('/download-selo/<int:laudo_id>')
@login_required
def download_selo(laudo_id):
    with engine.connect() as conn:
        result = conn.execute(
            text("SELECT selo FROM laudos_pdf WHERE id = :id"),
            {"id": laudo_id}
        ).fetchone()
        
        if result and result[0]:
            selo_bytes = result[0]
            return send_file(
                io.BytesIO(selo_bytes),
                mimetype='application/pdf',
                as_attachment=True,
                download_name=f'selo_{laudo_id}.pdf'
            )
        else:
            flash('Selo não encontrado.', 'error')
            return redirect(url_for('laudos_salvos'))

from relatorios import relatorios_bp
app.register_blueprint(relatorios_bp)

if __name__ == '__main__':
    app.run(debug=True)

