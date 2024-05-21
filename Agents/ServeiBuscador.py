from flask import Flask, request, jsonify
from rdflib import Graph, Literal, URIRef, RDF, XSD, Namespace
from rdflib.namespace import FOAF, RDF
import logging
import requests

from Agents.AgentAssistent import ServeiBuscador
from Utils.ACL import ACL
from Utils.Agent import Agent
from Utils.Logger import config_logger
from Utils.OntoNamespaces import ONTO

from Utils.ACLMessages import build_message, get_message_properties
import random
import socket
import sys
from multiprocessing import Queue, Process
from flask import Flask, request
from pyparsing import Literal
from rdflib import XSD, Namespace, Literal, URIRef

FUSEKI_SERVER = "http://localhost:3030/ONTO/query"
DATASET_NAME = "myDataset"

logger = config_logger(level=1)

# Configuration stuff
hostname = socket.gethostname()
port = 9010

agn = Namespace("http://www.agentes.org#")

# Contador de mensajes
mss_cnt = 0

# Datos del Agente
AgBuscadorProductos = Agent('AgBuscadorProductos',
                            agn.AgenteSimple,
                            'http://%s:%d/comm' % (hostname, port),
                            'http://%s:%d/Stop' % (hostname, port))

# Global triplestore graph
dsgraph = Graph()

cola1 = Queue()

# Flask stuff
app = Flask(__name__)


def get_count():
    global mss_cnt
    mss_cnt += 1
    return mss_cnt


def process_action(gm, msgdic):
    """
    Procesa la acción requerida por el mensaje ACL recibido.
    """
    content = msgdic['content']
    action = gm.value(subject=content, predicate=RDF.type)
    if action == ONTO.BuscarProductes:
        return handle_search_products(gm, content)
    else:
        return build_message(Graph(), 'not-understood', ServeiBuscador.uri, ServeiBuscador.get_count())


def handle_search_products(gm, content):
    """
    Procesa la petición de búsqueda de productos aplicando las Restriccioes dadas.
    """
    restrictions = {}
    for restriction in gm.objects(content, ONTO.RestringidaPor):
        if gm.value(restriction, RDF.type) == ONTO.RestriccioMarca:
            restrictions['Marca'] = str(gm.value(restriction, ONTO.Marca))
        elif gm.value(restriction, RDF.type) == ONTO.RestriccioNom:
            restrictions['Nom'] = str(gm.value(restriction, ONTO.Nom))
        elif gm.value(restriction, RDF.type) == ONTO.RestriccioPreu:
            min_price = gm.value(restriction, ONTO.PreuMin)
            max_price = gm.value(restriction, ONTO.PreuMax)
            restrictions['PreuMin'] = float(min_price)
            restrictions['PreuMax'] = float(max_price)
        elif gm.value(restriction, RDF.type) == ONTO.RestriccioValoracio:
            restrictions['Valoracio'] = float(gm.value(restriction, ONTO.Valoracio))

    # Realiza la búsqueda de productos según las Restricciones procesadas
    results = search_products(restrictions)
    response_graph = build_response_graph(results)
    return response_graph


def search_products(restrictions):
    """
    Realiza la búsqueda de productos en la base de datos o triplestore según las Restriccioes.
    Aquí se debería implementar una consulta SPARQL o un acceso a base de datos.
    """
    """
        Realiza la búsqueda de productos en Apache Jena Fuseki según las Restriccioes dadas.
        """
    query = build_sparql_query(restrictions)
    url = f"{FUSEKI_SERVER}/{DATASET_NAME}/query"
    headers = {
        "Content-Type": "application/sparql-query",
        "Accept": "application/sparql-results+json"
    }
    response = requests.post(url, data=query, headers=headers)

    if response.status_code == 200:
        results = response.json()
        return parse_sparql_results(results)
    else:
        logger.error(f"Error en la consulta SPARQL: {response.status_code}")
        return []

    # Ejemplo de resultados, deberías reemplazar esto con una consulta real
    #return [{'uri': 'http://example.org/product/1', 'Nom': 'Producto 1', 'Preu': 100, 'Marca': 'Marca A','Valoracio': 5}]


def build_sparql_query(restrictions):
    """
    Construye una consulta SPARQL basada en las Restriccioes dadas.
    """
    base_query = """
    PREFIX ns: <http://www.owl-ontologies.com/OntologiaECSDI.owl#>
    SELECT ?producto ?Nom ?Preu ?Marca ?Valoracio WHERE {
        ?producto rdf:type ns:Producte.
        ?producto ns:Nom ?Nom.
        ?producto ns:Preu ?Preu.
        ?producto ns:Marca ?Marca.
        ?producto ns:Valoracio ?Valoracio.
    """
    filters = []

    if 'Marca' in restrictions:
        filters.append(f"?Marca = '{restrictions['Marca']}'")
    if 'Nom' in restrictions:
        filters.append(f"CONTAINS(LCASE(str(?Nom)), LCASE('{restrictions['Nom']}'))")
    if 'PreuMin' in restrictions and 'PreuMax' in restrictions:
        filters.append(f"?Preu >= {restrictions['PreuMin']} && ?Preu <= {restrictions['PreuMax']}")
    if 'Valoracio' in restrictions:
        filters.append(f"?Valoracio >= {restrictions['Valoracio']}")

    if filters:
        base_query += "FILTER (" + " && ".join(filters) + ")"

    base_query += "}"
    return base_query


def parse_sparql_results(results):
    """
    Parsea los resultados de una consulta SPARQL en formato JSON.
    """
    parsed_results = []
    for result in results['results']['bindings']:
        producto = {
            'uri': result['Producte']['value'],
            'Nom': result['Nom']['value'],
            'Preu': float(result['Preu']['value']),
            'Marca': result['Marca']['value'],
            'Categoria': result['Categoria']['value'],
            'Pes': float(result['Pes']['value']),
            'Valoracio': float(result['Valoracio']['value'])
        }
        parsed_results.append(producto)
    return parsed_results


def build_response_graph(results):
    """
    Construye un grafo RDF con los resultados de la búsqueda para enviar como respuesta.
    """
    g = Graph()
    for result in results:
        prod_uri = URIRef(result['uri'])
        g.add((prod_uri, RDF.type, ONTO.Producte))
        g.add((prod_uri, ONTO.Nom, Literal(result['Nom'])))
        g.add((prod_uri, ONTO.Preu, Literal(result['Preu'], datatype=XSD.decimal)))
        g.add((prod_uri, ONTO.Marca, Literal(result['Marca'])))
        g.add((prod_uri, ONTO.Categoria, Literal(result['Categoria'])))
        g.add((prod_uri, ONTO.Pes, Literal(result['Pes'], datatype=XSD.decimal)))
        g.add((prod_uri, ONTO.Valoracio, Literal(result['Valoracio'], datatype=XSD.decimal)))
    return g


@app.route("/comm", methods=['POST'])
def communication():
    try:
        data = request.data
        gm = Graph()
        gm.parse(data=data)
        msgdic = get_message_properties(gm)
        if not msgdic:
            raise ValueError("Mensaje no entendido")

        if msgdic['performative'] != ACL.request:
            raise ValueError("Performative no es request")

        # Procesa la acción según el contenido del mensaje
        content = msgdic['content']
        gr = process_action(gm, content)
        return gr.serialize(format='xml'), 200
    except Exception as e:
        logger.error(f"Error processing request: {str(e)}")
        return build_message(Graph(), ACL['not-understood'], sender=ServeiBuscador.uri).serialize(format='xml'), 400


@app.route("/Stop", methods=['GET'])
def stop():
    """
    Stop the agent and the server.
    """
    # Define o implementa esta función para cerrar el servidor correctamente
    logger.info("Shutting down the server.")
    return "Server is shutting down...", 200


if __name__ == '__main__':
    app.run(port=5000, debug=True)
