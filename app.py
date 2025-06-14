from flask import Flask, request, jsonify, render_template
from flask_sqlalchemy import SQLAlchemy
from werkzeug.utils import secure_filename
import os, pdfplumber
from collections import defaultdict
import re

app = Flask(__name__)

# Configuración para Neon PostgreSQL
app.config['SQLALCHEMY_DATABASE_URI'] = 'postgresql://neondb_owner:npg_uceM7HVZ0Fvx@ep-billowing-cell-a4g5lpzg-pooler.us-east-1.aws.neon.tech/neondb?sslmode=require'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

db = SQLAlchemy(app)

UPLOAD_FOLDER = 'uploads'
os.makedirs(UPLOAD_FOLDER, exist_ok=True)

class Carpeta(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    nombre = db.Column(db.String, unique=True, nullable=False)

class Archivo(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    carpeta_id = db.Column(db.Integer, db.ForeignKey('carpeta.id'), nullable=False)
    nombre = db.Column(db.String, nullable=False)

class Producto(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    carpeta_id = db.Column(db.Integer, db.ForeignKey('carpeta.id'), nullable=False)
    modelo = db.Column(db.String, nullable=False)
    material = db.Column(db.String, nullable=False)
    qty = db.Column(db.Integer, nullable=False)

class Habiente(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    carpeta_id = db.Column(db.Integer, db.ForeignKey('carpeta.id'), nullable=False)
    modelo = db.Column(db.String, nullable=False)
    material = db.Column(db.String, nullable=False)
    qty = db.Column(db.Integer, nullable=False)

with app.app_context():
    db.create_all()

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/crear_carpeta', methods=['POST'])
def crear_carpeta():
    data = request.get_json()
    nombre = data.get('nombre')
    if not nombre:
        return jsonify({'error': 'Nombre requerido'}), 400
    if not Carpeta.query.filter_by(nombre=nombre).first():
        db.session.add(Carpeta(nombre=nombre))
        db.session.commit()
    return jsonify({'mensaje': f'Carpeta "{nombre}" creada'})

@app.route('/eliminar_carpeta/<nombre>', methods=['DELETE'])
def eliminar_carpeta(nombre):
    carpeta = Carpeta.query.filter_by(nombre=nombre).first()
    if carpeta:
        Archivo.query.filter_by(carpeta_id=carpeta.id).delete()
        Producto.query.filter_by(carpeta_id=carpeta.id).delete()
        Habiente.query.filter_by(carpeta_id=carpeta.id).delete()
        db.session.delete(carpeta)
        db.session.commit()
        return jsonify({'mensaje': f'Carpeta "{nombre}" eliminada'})
    return jsonify({'error': 'Carpeta no encontrada'}), 404

@app.route('/carpetas')
def listar_carpetas():
    carpetas = Carpeta.query.all()
    return jsonify({'carpetas': [c.nombre for c in carpetas]})

def extraer_productos_pdf(path):
    productos = []
    with pdfplumber.open(path) as pdf:
        for page_index, page in enumerate(pdf.pages):
            tabla = page.extract_table()
            if not tabla:
                continue

            filas = tabla
            # Saltar encabezado solo en la primera página
            if page_index == 0 and len(filas) > 1:
                filas = filas[1:]

            for fila in filas:
                if not fila or len(fila) < 4:
                    continue

                material_raw = fila[2]  # Columna MATERIAL
                modelo_raw = fila[3]    # Columna MODEL o COLOR

                if not material_raw or not modelo_raw:
                    continue

                material = material_raw.strip().title()
                modelo = modelo_raw.strip().title()
                productos.append((modelo, material))

    return productos



def contar_productos(productos):
    conteo = defaultdict(int)
    for modelo, material in productos:
        conteo[(modelo.strip().title(), material.strip().title())] += 1
    return [{'modelo': modelo, 'material': material, 'qty': qty} for (modelo, material), qty in conteo.items()]

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

    carpeta_obj = Carpeta.query.filter_by(nombre=carpeta).first()
    if not carpeta_obj:
        return jsonify({'error': 'Carpeta no encontrada'}), 404

    db.session.add(Archivo(carpeta_id=carpeta_obj.id, nombre=nombre_seguro))
    Producto.query.filter_by(carpeta_id=carpeta_obj.id).delete()

    productos_raw = extraer_productos_pdf(ruta_archivo)
    productos_contados = contar_productos(productos_raw)

    for p in productos_contados:
        db.session.add(Producto(
            carpeta_id=carpeta_obj.id,
            modelo=p['modelo'],
            material=p['material'],
            qty=p['qty']
        ))

    db.session.commit()
    return jsonify({'mensaje': 'Archivo subido y productos guardados'})

@app.route('/productos/<carpeta>')
def obtener_productos(carpeta):
    carpeta_obj = Carpeta.query.filter_by(nombre=carpeta).first()
    if not carpeta_obj:
        return jsonify({'tabla': []})
    productos = Producto.query.filter_by(carpeta_id=carpeta_obj.id).all()
    resultado = [[p.modelo, p.material, p.qty] for p in productos]
    total = sum(p.qty for p in productos)
    resultado.append(["", "TOTAL", total])
    return jsonify({'tabla': resultado})

@app.route('/guardar_habientes/<carpeta>', methods=['POST'])
def guardar_habientes(carpeta):
    data = request.get_json()
    carpeta_obj = Carpeta.query.filter_by(nombre=carpeta).first()
    if not carpeta_obj:
        return jsonify({'error': 'Carpeta no encontrada'}), 404
    Habiente.query.filter_by(carpeta_id=carpeta_obj.id).delete()
    for modelo, material, qty in data:
        db.session.add(Habiente(carpeta_id=carpeta_obj.id, modelo=modelo, material=material, qty=qty))
    db.session.commit()
    return jsonify({'mensaje': 'Habientes guardados'})

@app.route('/habientes/<carpeta>')
def obtener_habientes(carpeta):
    carpeta_obj = Carpeta.query.filter_by(nombre=carpeta).first()
    if not carpeta_obj:
        return jsonify({'habientes': []})
    habs = Habiente.query.filter_by(carpeta_id=carpeta_obj.id).all()
    return jsonify({'habientes': [[h.modelo, h.material, h.qty] for h in habs]})

@app.route('/actualizar_tabla/<carpeta>', methods=['POST'])
def actualizar_tabla(carpeta):
    data = request.get_json()
    carpeta_obj = Carpeta.query.filter_by(nombre=carpeta).first()
    if not carpeta_obj:
        return jsonify({'error': 'Carpeta no encontrada'}), 404
    Producto.query.filter_by(carpeta_id=carpeta_obj.id).delete()
    for modelo, material, qty in data:
        if material != "TOTAL":
            db.session.add(Producto(carpeta_id=carpeta_obj.id, modelo=modelo, material=material, qty=qty))
    db.session.commit()
    return jsonify({'mensaje': 'Tabla principal actualizada'})

if __name__ == '__main__':
    import os
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port)
