from flask import Blueprint, render_template, request, jsonify, Response
from flask import session, redirect, url_for, flash
from functools import wraps
import pyodbc
from datetime import datetime, timedelta
import json
import csv
import io

# Proteção com login_required
def login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'user_id' not in session:
            flash('Por favor, faça login para acessar esta página', 'error')
            return redirect(url_for('login'))
        return f(*args, **kwargs)
    return decorated_function

# Configuração da conexão com o banco
def get_db_connection():
    try:
        # Substitua pela sua string de conexão real
        conn = pyodbc.connect(
           "DRIVER={ODBC Driver 17 for SQL Server};"
        "SERVER=85.31.231.127;"
        "DATABASE=db_click_vistoria;"
        "UID=sa;"
        "PWD=Dagimas4045;"
        "Encrypt=no;"
        )
        return conn
    except Exception as e:
        print(f"Erro ao conectar com o banco: {e}")
        return None

# Criação do Blueprint
relatorios_bp = Blueprint('relatorios', __name__)

@relatorios_bp.route('/relatorios')
@login_required
def relatorios():
    try:
        conn = get_db_connection()
        if not conn:
            flash('Erro ao conectar com o banco de dados', 'error')
            return render_template('relatorios.html', dados={})
        
        cursor = conn.cursor()
        
        # Dados gerais - estatísticas básicas
        dados = {
            'total_laudos': 0,
            'aprovados': 0,
            'recusados': 0,
            'taxa_aprovacao': 0,
            'laudos_hoje': 0,
            'laudos_semana': 0,
            'laudos_mes': 0,
            'aprovacoes_por_dia': [],
            'evolucao_mensal': [],
            'distribuicao_status': [],
            'ranking_usuarios': []
        }
        
        # Total de laudos
        cursor.execute("SELECT COUNT(*) FROM laudos_pdf")
        dados['total_laudos'] = cursor.fetchone()[0]
        
        # Laudos aprovados e recusados
        cursor.execute("SELECT status, COUNT(*) FROM laudos_pdf GROUP BY status")
        status_counts = cursor.fetchall()
        for status, count in status_counts:
            if status == 1:
                dados['aprovados'] = count
            else:
                dados['recusados'] = count
        
        # Taxa de aprovação
        if dados['total_laudos'] > 0:
            dados['taxa_aprovacao'] = round((dados['aprovados'] / dados['total_laudos']) * 100, 1)
        
        # Laudos de hoje
        cursor.execute("""
            SELECT COUNT(*) FROM laudos_pdf 
            WHERE CAST(data_emissao AS DATE) = CAST(GETDATE() AS DATE)
        """)
        dados['laudos_hoje'] = cursor.fetchone()[0]
        
        # Laudos da semana
        cursor.execute("""
            SELECT COUNT(*) FROM laudos_pdf 
            WHERE data_emissao >= DATEADD(week, -1, GETDATE())
        """)
        dados['laudos_semana'] = cursor.fetchone()[0]
        
        # Laudos do mês
        cursor.execute("""
            SELECT COUNT(*) FROM laudos_pdf 
            WHERE data_emissao >= DATEADD(month, -1, GETDATE())
        """)
        dados['laudos_mes'] = cursor.fetchone()[0]
        
        # Aprovações por dia (últimos 30 dias)
        cursor.execute("""
            SELECT 
                CAST(data_emissao AS DATE) as data,
                SUM(CASE WHEN status = 1 THEN 1 ELSE 0 END) as aprovados,
                SUM(CASE WHEN status = 0 THEN 1 ELSE 0 END) as recusados,
                COUNT(*) as total
            FROM laudos_pdf 
            WHERE data_emissao >= DATEADD(day, -30, GETDATE())
            GROUP BY CAST(data_emissao AS DATE)
            ORDER BY data
        """)
        
        aprovacoes_dia = cursor.fetchall()
        for row in aprovacoes_dia:
            dados['aprovacoes_por_dia'].append({
                'data': row[0].strftime('%Y-%m-%d'),
                'aprovados': row[1],
                'recusados': row[2],
                'total': row[3]
            })
        
        # Evolução mensal (últimos 12 meses)
        cursor.execute("""
            SELECT 
                YEAR(data_emissao) as ano,
                MONTH(data_emissao) as mes,
                SUM(CASE WHEN status = 1 THEN 1 ELSE 0 END) as aprovados,
                SUM(CASE WHEN status = 0 THEN 1 ELSE 0 END) as recusados,
                COUNT(*) as total
            FROM laudos_pdf 
            WHERE data_emissao >= DATEADD(month, -12, GETDATE())
            GROUP BY YEAR(data_emissao), MONTH(data_emissao)
            ORDER BY ano, mes
        """)
        
        evolucao = cursor.fetchall()
        meses = ['Jan', 'Fev', 'Mar', 'Abr', 'Mai', 'Jun', 
                'Jul', 'Ago', 'Set', 'Out', 'Nov', 'Dez']
        
        for row in evolucao:
            dados['evolucao_mensal'].append({
                'periodo': f"{meses[row[1]-1]}/{str(row[0])[2:]}",
                'aprovados': row[2],
                'recusados': row[3],
                'total': row[4]
            })
        
        # Distribuição de status para gráfico pizza
        dados['distribuicao_status'] = [
            {'label': 'Aprovados', 'value': dados['aprovados'], 'color': '#10B981'},
            {'label': 'Recusados', 'value': dados['recusados'], 'color': '#EF4444'}
        ]
        
        cursor.close()
        conn.close()
        
        return render_template('relatorios.html', dados=dados)
        
    except Exception as e:
        flash(f'Erro ao carregar relatórios: {str(e)}', 'error')
        return render_template('relatorios.html', dados={})

@relatorios_bp.route('/relatorios/api/dados-periodo')
@login_required
def dados_periodo():
    """API para filtrar dados por período"""
    try:
        data_inicio = request.args.get('data_inicio')
        data_fim = request.args.get('data_fim')
        
        if not data_inicio or not data_fim:
            return jsonify({'error': 'Período não informado'}), 400
        
        conn = get_db_connection()
        if not conn:
            return jsonify({'error': 'Erro de conexão'}), 500
        
        cursor = conn.cursor()
        
        # Query com filtro de período
        cursor.execute("""
            SELECT 
                CAST(data_emissao AS DATE) as data,
                SUM(CASE WHEN status = 1 THEN 1 ELSE 0 END) as aprovados,
                SUM(CASE WHEN status = 0 THEN 1 ELSE 0 END) as recusados,
                COUNT(*) as total
            FROM laudos_pdf 
            WHERE CAST(data_emissao AS DATE) BETWEEN ? AND ?
            GROUP BY CAST(data_emissao AS DATE)
            ORDER BY data
        """, (data_inicio, data_fim))
        
        resultados = []
        for row in cursor.fetchall():
            resultados.append({
                'data': row[0].strftime('%Y-%m-%d'),
                'aprovados': row[1],
                'recusados': row[2],
                'total': row[3]
            })
        
        # Totais do período
        cursor.execute("""
            SELECT 
                SUM(CASE WHEN status = 1 THEN 1 ELSE 0 END) as total_aprovados,
                SUM(CASE WHEN status = 0 THEN 1 ELSE 0 END) as total_recusados,
                COUNT(*) as total_geral
            FROM laudos_pdf 
            WHERE CAST(data_emissao AS DATE) BETWEEN ? AND ?
        """, (data_inicio, data_fim))
        
        totais = cursor.fetchone()
        
        cursor.close()
        conn.close()
        
        return jsonify({
            'dados_periodo': resultados,
            'totais': {
                'aprovados': totais[0],
                'recusados': totais[1],
                'total': totais[2],
                'taxa_aprovacao': round((totais[0] / totais[2] * 100), 1) if totais[2] > 0 else 0
            }
        })
        
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@relatorios_bp.route('/relatorios/api/teste')
@login_required
def teste_conexao():
    """Rota de teste para verificar conexão"""
    try:
        conn = get_db_connection()
        if not conn:
            return jsonify({'error': 'Falha na conexão com o banco', 'status': 'erro'}), 500
        
        cursor = conn.cursor()
        cursor.execute("SELECT COUNT(*) FROM laudos_pdf")
        total = cursor.fetchone()[0]
        cursor.close()
        conn.close()
        
        return jsonify({
            'status': 'sucesso',
            'total_laudos': total,
            'mensagem': 'Conexão com banco funcionando'
        })
        
    except Exception as e:
        return jsonify({
            'error': str(e),
            'status': 'erro',
            'mensagem': 'Erro na conexão'
        }), 500

@relatorios_bp.route('/relatorios/api/tabela-dados')
@login_required
def tabela_dados():
    """API para carregar dados da tabela com filtros"""
    try:
        data_inicio = request.args.get('data_inicio')
        data_fim = request.args.get('data_fim')
        
        conn = get_db_connection()
        if not conn:
            return jsonify({'error': 'Erro de conexão'}), 500
        
        cursor = conn.cursor()
        
        # Query base - evitando campos binários
        query = """
            SELECT 
                id,
                vistoria_id,
                data_emissao,
                status,
                selo
            FROM laudos_pdf
        """
        
        params = []
        if data_inicio and data_fim:
            query += " WHERE CAST(data_emissao AS DATE) BETWEEN ? AND ?"
            params = [data_inicio, data_fim]
        
        query += " ORDER BY data_emissao DESC"
        
        cursor.execute(query, params)
        resultados = cursor.fetchall()
        
        # Converter resultados para lista de dicionários - tratamento mais seguro
        laudos = []
        for row in resultados:
            try:
                # Extrair dados com verificação de tipos
                id_val = row[0]
                vistoria_id = row[1]
                data_emissao = row[2]
                status_num = row[3]
                
                
                # Converter para tipos seguros
                laudo = {
                    'id': int(id_val) if id_val is not None else 0,
                    'vistoria_id': str(vistoria_id) if vistoria_id is not None else f"VST-{id_val}",
                    'data_emissao': data_emissao.strftime('%d/%m/%Y %H:%M') if data_emissao is not None else 'Data não informada',
                    'status': 'Aprovado' if status_num == 1 else 'Recusado',
                    
                }
                laudos.append(laudo)
                
            except Exception as e:
                print(f"Erro ao processar linha {row}: {e}")
                # Adicionar linha com dados padrão em caso de erro
                laudos.append({
                    'id': row[0] if row[0] else 0,
                    'vistoria_id': f"VST-{row[0]}" if row[0] else "VST-000",
                    'data_emissao': 'Erro na data',
                    'status': 'Erro',
                    
                })
                continue
        
        cursor.close()
        conn.close()
        
        result = {
            'laudos': laudos,
            'total': len(laudos),
            'sucesso': True
        }
        
        print(f"Retornando {len(laudos)} laudos") # Debug
        
        return jsonify(result)
        
    except Exception as e:
        error_msg = f'Erro na API: {str(e)}'
        print(error_msg)
        return jsonify({
            'error': error_msg,
            'laudos': [],
            'total': 0,
            'sucesso': False
        }), 500
@login_required
def dados_periodo():
    """API para filtrar dados por período"""
    try:
        data_inicio = request.args.get('data_inicio')
        data_fim = request.args.get('data_fim')
        
        if not data_inicio or not data_fim:
            return jsonify({'error': 'Período não informado'}), 400
        
        conn = get_db_connection()
        if not conn:
            return jsonify({'error': 'Erro de conexão'}), 500
        
        cursor = conn.cursor()
        
        # Query com filtro de período
        cursor.execute("""
            SELECT 
                CAST(data_emissao AS DATE) as data,
                SUM(CASE WHEN status = 1 THEN 1 ELSE 0 END) as aprovados,
                SUM(CASE WHEN status = 0 THEN 1 ELSE 0 END) as recusados,
                COUNT(*) as total
            FROM laudos_pdf 
            WHERE CAST(data_emissao AS DATE) BETWEEN ? AND ?
            GROUP BY CAST(data_emissao AS DATE)
            ORDER BY data
        """, (data_inicio, data_fim))
        
        resultados = []
        for row in cursor.fetchall():
            resultados.append({
                'data': row[0].strftime('%Y-%m-%d'),
                'aprovados': row[1],
                'recusados': row[2],
                'total': row[3]
            })
        
        # Totais do período
        cursor.execute("""
            SELECT 
                SUM(CASE WHEN status = 1 THEN 1 ELSE 0 END) as total_aprovados,
                SUM(CASE WHEN status = 0 THEN 1 ELSE 0 END) as total_recusados,
                COUNT(*) as total_geral
            FROM laudos_pdf 
            WHERE CAST(data_emissao AS DATE) BETWEEN ? AND ?
        """, (data_inicio, data_fim))
        
        totais = cursor.fetchone()
        
        cursor.close()
        conn.close()
        
        return jsonify({
            'dados_periodo': resultados,
            'totais': {
                'aprovados': totais[0],
                'recusados': totais[1],
                'total': totais[2],
                'taxa_aprovacao': round((totais[0] / totais[2] * 100), 1) if totais[2] > 0 else 0
            }
        })
        
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@relatorios_bp.route('/relatorios/exportar')
@login_required
def exportar_relatorio():
    """Exportar relatório em CSV ou Excel"""
    try:
        formato = request.args.get('formato', 'csv')
        data_inicio = request.args.get('data_inicio')
        data_fim = request.args.get('data_fim')
        
        conn = get_db_connection()
        if not conn:
            return jsonify({'error': 'Erro de conexão com banco'}), 500
            
        cursor = conn.cursor()
        
        query = """
            SELECT 
                id,
                vistoria_id,
                data_emissao,
                arquivo,
                CASE WHEN status = 1 THEN 'Aprovado' ELSE 'Recusado' END as status,
                selo
            FROM laudos_pdf
        """
        
        params = []
        if data_inicio and data_fim:
            query += " WHERE CAST(data_emissao AS DATE) BETWEEN ? AND ?"
            params = [data_inicio, data_fim]
        
        query += " ORDER BY data_emissao DESC"
        
        cursor.execute(query, params)
        dados = cursor.fetchall()
        cursor.close()
        conn.close()
        
        if formato == 'csv':
            return gerar_csv(dados, data_inicio, data_fim)
        elif formato == 'excel':
            return gerar_excel(dados, data_inicio, data_fim)
        else:
            return jsonify({'error': 'Formato não suportado'}), 400
            
    except Exception as e:
        return jsonify({'error': str(e)}), 500

def gerar_csv(dados, data_inicio=None, data_fim=None):
    """Gerar arquivo CSV"""
    import csv
    import io
    from flask import Response
    
    output = io.StringIO()
    writer = csv.writer(output, delimiter=';', quoting=csv.QUOTE_ALL)
    
    # Cabeçalho
    writer.writerow(['ID', 'Vistoria ID', 'Data Emissão', 'Arquivo', 'Status', 'Selo'])
    
    # Dados
    for row in dados:
        writer.writerow([
            row[0],  # id
            row[1],  # vistoria_id
            row[2].strftime('%d/%m/%Y %H:%M') if row[2] else '',  # data_emissao
            row[3],  # arquivo
            row[4],  # status
            
        ])
    
    output.seek(0)
    
    # Nome do arquivo
    if data_inicio and data_fim:
        filename = f'relatorio_{data_inicio}_{data_fim}.csv'
    else:
        filename = f'relatorio_completo_{datetime.now().strftime("%Y%m%d")}.csv'
    
    return Response(
        output.getvalue(),
        mimetype='text/csv',
        headers={'Content-Disposition': f'attachment; filename={filename}'}
    )

def gerar_excel(dados, data_inicio=None, data_fim=None):
    """Gerar arquivo Excel"""
    try:
        import pandas as pd
        import io
        from flask import Response
        
        # Converter dados para DataFrame
        df_dados = []
        for row in dados:
            df_dados.append({
                'ID': row[0],
                'Vistoria ID': row[1],
                'Data Emissão': row[2].strftime('%d/%m/%Y %H:%M') if row[2] else '',
                'Arquivo': row[3],
                'Status': row[4],
                'Selo': row[5] if row[5] else ''
            })
        
        df = pd.DataFrame(df_dados)
        
        # Criar arquivo Excel em memória
        output = io.BytesIO()
        
        with pd.ExcelWriter(output, engine='openpyxl') as writer:
            # Planilha principal com dados
            df.to_excel(writer, sheet_name='Laudos', index=False)
            
            # Planilha de estatísticas
            stats_data = {
                'Métrica': ['Total de Laudos', 'Aprovados', 'Recusados', 'Taxa de Aprovação'],
                'Valor': [
                    len(df),
                    len(df[df['Status'] == 'Aprovado']),
                    len(df[df['Status'] == 'Recusado']),
                    f"{(len(df[df['Status'] == 'Aprovado']) / len(df) * 100):.1f}%" if len(df) > 0 else "0%"
                ]
            }
            
            df_stats = pd.DataFrame(stats_data)
            df_stats.to_excel(writer, sheet_name='Estatísticas', index=False)
            
            # Formatação das planilhas
            workbook = writer.book
            
            # Formatar planilha de laudos
            worksheet_laudos = writer.sheets['Laudos']
            worksheet_laudos.column_dimensions['A'].width = 8
            worksheet_laudos.column_dimensions['B'].width = 15
            worksheet_laudos.column_dimensions['C'].width = 18
            worksheet_laudos.column_dimensions['D'].width = 25
            worksheet_laudos.column_dimensions['E'].width = 12
            worksheet_laudos.column_dimensions['F'].width = 12
            
            # Formatar planilha de estatísticas
            worksheet_stats = writer.sheets['Estatísticas']
            worksheet_stats.column_dimensions['A'].width = 20
            worksheet_stats.column_dimensions['B'].width = 15
        
        output.seek(0)
        
        # Nome do arquivo
        if data_inicio and data_fim:
            filename = f'relatorio_{data_inicio}_{data_fim}.xlsx'
        else:
            filename = f'relatorio_completo_{datetime.now().strftime("%Y%m%d")}.xlsx'
        
        return Response(
            output.getvalue(),
            mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
            headers={'Content-Disposition': f'attachment; filename={filename}'}
        )
        
    except ImportError:
        # Fallback para CSV se pandas não estiver disponível
        return gerar_csv(dados, data_inicio, data_fim)