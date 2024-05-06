from flask import Flask, request, jsonify
from rdflib import Graph, URIRef, Literal
from rdflib.namespace import RDF, FOAF

app = Flask(__name__)

@app.route('/')
def index():
    return '¡Hola, mundo! Esta es mi primera aplicación Flask.'

@app.route('/triples', methods=['POST'])
def add_triple():
    # Recuperar los datos del triple desde la solicitud HTTP
    subject = URIRef(request.json['subject'])
    predicate = URIRef(request.json['predicate'])
    obj = Literal(request.json['object'])

    # Conectar a la triplestore (en este caso, un archivo RDF)
    g = Graph()
    g.parse('data.rdf')  # Cambia 'data.rdf' al archivo RDF que estás utilizando

    # Agregar el triple al grafo RDF
    g.add((subject, predicate, obj))

    # Guardar el grafo RDF de vuelta en el archivo
    g.serialize('data.rdf', format='xml')

    return jsonify({'message': 'Triple added successfully'}), 201

# Ruta para consultar triples en el grafo RDF
@app.route('/triples', methods=['GET'])
def get_triples():
    # Conectar a la triplestore (en este caso, un archivo RDF)
    g = Graph()
    g.parse('data.rdf')  # Cambia 'data.rdf' al archivo RDF que estás utilizando

    # Consultar todos los triples en el grafo RDF
    results = []
    for s, p, o in g:
        results.append({'subject': s.n3(), 'predicate': p.n3(), 'object': o.n3()})

    return jsonify(results), 200
if __name__ == '__main__':
    app.run(debug=True)