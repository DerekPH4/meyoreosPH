from flask import Flask, request, jsonify, render_template
from werkzeug.utils import secure_filename
import os, uuid, sqlite3, pdfplumber
from collections import defaultdict

app = Flask(__name__)
UPLOAD_FOLDER = 'uploads'
os.makedirs(UPLOAD_FOLDER, exist_ok=True)

DB_PATH = 'mayoreos.db'

def conectar_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def inicializar_db():
    conn = conectar_db()
    cur = conn.cursor()
    cur.executescript("""
    CREATE TABLE IF NOT EXISTS carpetas (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        nombre TEXT UNIQUE
    );

    CREATE TABLE IF NOT EXISTS archivos (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        carpeta_id INTEGER,
        nombre TEXT,
        FOREIGN KEY (carpeta_id) REFERENCES carpetas(id)
    );

    CREATE TABLE IF NOT EXISTS productos (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        carpeta_id INTEGER,
        modelo TEXT,
        material TEXT,
        qty INTEGER,
        FOREIGN KEY (carpeta_id) REFERENCES carpetas(id)
    );

    CREATE TABLE IF NOT EXISTS habientes (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        carpeta_id INTEGER,
        modelo TEXT,
        material TEXT,
        qty INTEGER,
        FOREIGN KEY (carpeta_id) REFERENCES carpetas(id)
    );
    """)
    conn.commit()
    conn.close()

inicializar_db()

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/crear_carpeta', methods=['POST'])
def crear_carpeta():
    data = request.get_json()
    nombre = data.get('nombre')
    if not nombre:
        return jsonify({'error': 'Nombre requerido'}), 400

    conn = conectar_db()
    cur = conn.cursor()
    cur.execute("INSERT OR IGNORE INTO carpetas (nombre) VALUES (?)", (nombre,))
    conn.commit()
    conn.close()

    return jsonify({'mensaje': f'Carpeta "{nombre}" creada'})

@app.route('/eliminar_carpeta/<nombre>', methods=['DELETE'])
def eliminar_carpeta(nombre):
    conn = conectar_db()
    cur = conn.cursor()
    cur.execute("DELETE FROM carpetas WHERE nombre = ?", (nombre,))
    conn.commit()
    conn.close()
    return jsonify({'mensaje': f'Carpeta "{nombre}" eliminada'})

@app.route('/carpetas')
def listar_carpetas():
    conn = conectar_db()
    carpetas = conn.execute("SELECT nombre FROM carpetas").fetchall()
    conn.close()
    return jsonify({'carpetas': [c['nombre'] for c in carpetas]})

@app.route('/subir/<carpeta>', methods=['POST'])
def subir_archivo(carpeta):
    if 'archivo' not in request.files:
        return jsonify({'error': 'Archivo no enviado'}), 400
    archivo = request.files['archivo']
    if archivo.filename == '':
        return jsonify({'error': 'Nombre vacío'}), 400

    nombre_seguro = secure_filename(archivo.filename)
    ruta_carpeta = os.path.join(UPLOAD_FOLDER, carpeta)
    os.makedirs(ruta_carpeta, exist_ok=True)
    ruta_archivo = os.path.join(ruta_carpeta, nombre_seguro)
    archivo.save(ruta_archivo)

    conn = conectar_db()
    cur = conn.cursor()
    cur.execute("SELECT id FROM carpetas WHERE nombre = ?", (carpeta,))
    row = cur.fetchone()
    if not row:
        conn.close()
        return jsonify({'error': 'Carpeta no encontrada'}), 404
    carpeta_id = row['id']

    cur.execute("INSERT INTO archivos (carpeta_id, nombre) VALUES (?, ?)", (carpeta_id, nombre_seguro))
    cur.execute("DELETE FROM productos WHERE carpeta_id = ?", (carpeta_id,))

    contador = defaultdict(int)
    with pdfplumber.open(ruta_archivo) as pdf:
        for pagina in pdf.pages:
            texto = pagina.extract_text()
            if not texto:
                continue
            lineas = texto.splitlines()
            for linea in lineas:
                if '$' not in linea:
                    continue
                palabras = linea.upper().split()
                try:
                    if 'PH' in palabras:
                        i = palabras.index('PH')
                        modelo = f"PH {palabras[i + 1]}"
                        material = 'STRAW'
                    elif 'RODEO' in palabras:
                        i = palabras.index('RODEO')
                        siguiente = palabras[i + 1] if i + 1 < len(palabras) else ''
                        siguiente2 = palabras[i + 2] if i + 2 < len(palabras) else ''

                        if siguiente == 'NIGHTS':
                            if siguiente2 in ['CATALOG', 'LEATHER']:
                                modelo = 'RODEO NIGHTS'
                            else:
                                modelo = siguiente2  # solo el color
                        else:
                            modelo = palabras[i + 1]
                        material = 'FELT'
                    else:
                        continue

                    clave = (modelo.strip(), material)
                    contador[clave] += 1
                except:
                    continue

    for (modelo, material), qty in contador.items():
        cur.execute("INSERT INTO productos (carpeta_id, modelo, material, qty) VALUES (?, ?, ?, ?)",
                    (carpeta_id, modelo, material, qty))

    conn.commit()
    conn.close()
    return jsonify({'mensaje': 'Archivo subido y productos guardados'})

@app.route('/productos/<carpeta>')
def obtener_productos(carpeta):
    conn = conectar_db()
    cur = conn.cursor()
    cur.execute("SELECT id FROM carpetas WHERE nombre = ?", (carpeta,))
    row = cur.fetchone()
    if not row:
        return jsonify({'tabla': []})
    carpeta_id = row['id']
    productos = cur.execute("SELECT modelo, material, qty FROM productos WHERE carpeta_id = ?", (carpeta_id,)).fetchall()
    conn.close()

    resultado = [[p['modelo'], p['material'], p['qty']] for p in productos]
    total = sum(p['qty'] for p in productos)
    resultado.append(["", "TOTAL", total])
    return jsonify({'tabla': resultado})

@app.route('/guardar_habientes/<carpeta>', methods=['POST'])
def guardar_habientes(carpeta):
    data = request.get_json()
    conn = conectar_db()
    cur = conn.cursor()
    cur.execute("SELECT id FROM carpetas WHERE nombre = ?", (carpeta,))
    row = cur.fetchone()
    if not row:
        return jsonify({'error': 'Carpeta no encontrada'}), 404
    carpeta_id = row['id']
    cur.execute("DELETE FROM habientes WHERE carpeta_id = ?", (carpeta_id,))
    for modelo, material, qty in data:
        cur.execute("INSERT INTO habientes (carpeta_id, modelo, material, qty) VALUES (?, ?, ?, ?)",
                    (carpeta_id, modelo, material, qty))
    conn.commit()
    conn.close()
    return jsonify({'mensaje': 'Habientes guardados'})

@app.route('/habientes/<carpeta>')
def obtener_habientes(carpeta):
    conn = conectar_db()
    cur = conn.cursor()
    cur.execute("SELECT id FROM carpetas WHERE nombre = ?", (carpeta,))
    row = cur.fetchone()
    if not row:
        return jsonify({'habientes': []})
    carpeta_id = row['id']
    habs = cur.execute("SELECT modelo, material, qty FROM habientes WHERE carpeta_id = ?", (carpeta_id,)).fetchall()
    conn.close()
    return jsonify({'habientes': [[h['modelo'], h['material'], h['qty']] for h in habs]})


@app.route('/actualizar_tabla/<carpeta>', methods=['POST'])
def actualizar_tabla(carpeta):
    data = request.get_json()
    conn = conectar_db()
    cur = conn.cursor()

    cur.execute("SELECT id FROM carpetas WHERE nombre = ?", (carpeta,))
    row = cur.fetchone()
    if not row:
        conn.close()
        return jsonify({'error': 'Carpeta no encontrada'}), 404

    carpeta_id = row['id']

    
    cur.execute("DELETE FROM productos WHERE carpeta_id = ?", (carpeta_id,))
    
    # Insertar nuevos productos
    for modelo, material, qty in data:
        if material != "TOTAL":
            cur.execute("INSERT INTO productos (carpeta_id, modelo, material, qty) VALUES (?, ?, ?, ?)",
                        (carpeta_id, modelo, material, qty))

    conn.commit()
    conn.close()
    return jsonify({'mensaje': 'Tabla principal actualizada'})


if __name__ == '__main__':
    import os
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port)

