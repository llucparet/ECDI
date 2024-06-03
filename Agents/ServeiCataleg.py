import socket
from multiprocessing import Queue, Process

from SPARQLWrapper import SPARQLWrapper, POST, JSON, URLENCODED
from flask import Flask, request
from rdflib import Namespace, Graph, RDF, Literal
import requests
import random

from Utils.ACLMessages import *
from Utils.Agent import Agent
from Utils.Logger import config_logger
from Utils.OntoNamespaces import ONTO
from Utils.ACL import ACL
from Utils.FlaskServer import shutdown_server

logger = config_logger(level=1)

# Configuration stuff
hostname = '0.0.0.0'
port = 8005

agn = Namespace("http://www.agentes.org#")

# Contador de mensajes
mss_cnt = 0

# Datos del Agente
AgentVenedorExtern = Agent('AgentVenedorExtern',
                           agn.AgentVenedorExtern,
                           f'http://{hostname}:8004/comm',
                           f'http://{hostname}:8004/Stop')

ServeiCataleg = Agent('ServeiCataleg',
                      agn.ServeiCataleg,
                      f'http://{hostname}:{port}/comm',
                      f'http://{hostname}:{port}/Stop')

# Global triplestore graph
dsgraph = Graph()

cola1 = Queue()

# Flask stuff
app = Flask(__name__)

# Fuseki endpoint
fuseki_url = 'http://localhost:3030/ONTO/data'
update_endpoint_url = 'http://localhost:3030/ONTO/update'

def get_count():
    global mss_cnt
    mss_cnt += 1
    return mss_cnt


def get_existing_product_ids():
    query = """
    PREFIX ns: <http://www.semanticweb.org/nilde/ontologies/2024/4/>
    SELECT ?id
    WHERE {
        ?product a ns:Producte ;
                 ns:ID ?id .
    }
    """
    response = requests.post(fuseki_url.replace('/data', '/query'), data={'query': query},
                             headers={'Accept': 'application/sparql-results+json'})
    if response.status_code == 200:
        results = response.json()
        existing_ids = [result['id']['value'] for result in results['results']['bindings']]
        return existing_ids
    else:
        print(f"Error querying Fuseki: {response.status_code} - {response.text}")
        return []


def generate_unique_product_id(existing_ids):
    while True:
        new_id = f'P{random.randint(1000, 9999)}'
        if new_id not in existing_ids:
            return new_id

def delete_product_from_fuseki(product_id):
    query = f"""
    PREFIX ns: <http://www.semanticweb.org/nilde/ontologies/2024/4/>
    DELETE WHERE {{
        ?product ns:ID "{product_id}" ;
                 ?p ?o .
    }}
    """
    print(f"SPARQL Update Query: {query}")  # Registro de depuración

    sparql = SPARQLWrapper(update_endpoint_url)
    sparql.setMethod(POST)
    sparql.setQuery(query)
    sparql.setRequestMethod(URLENCODED)
    sparql.setReturnFormat(JSON)

    try:
        response = sparql.query()
        print("Product successfully deleted from Fuseki")
        return True
    except Exception as e:
        print(f"Error in SPARQL update: {e}")
        return False


@app.route("/comm", methods=['GET', 'POST'])
def communication():
    """
    Communication Entrypoint
    """
    if request.method == 'GET':
        message = request.args['content']
    elif request.method == 'POST':
        message = request.data
    gm = Graph()
    gm.parse(data=message, format='xml')

    msgdic = get_message_properties(gm)

    gr = None
    if msgdic is None:
        # Si no es, respondemos que no hemos entendido el mensaje
        gr = build_message(Graph(), ACL['not-understood'], sender=ServeiCataleg.uri, msgcnt=get_count())
    else:
        # Obtenemos la performativa
        if msgdic['performative'] != ACL.request:
            # Si no es un request, respondemos que no hemos entendido el mensaje
            gr = build_message(Graph(),
                               ACL['not-understood'],
                               sender=ServeiCataleg.uri,
                               msgcnt=get_count())
        else:
            # Extraemos el objeto del contenido que ha de ser una acción de la ontología
            content = msgdic['content']
            # Averiguamos el tipo de la acción
            accion = gm.value(subject=content, predicate=RDF.type)

            if accion == ONTO.AfegirProducteExtern:
                existing_ids = get_existing_product_ids()
                identificador = generate_unique_product_id(existing_ids)

                productSuj = ONTO[identificador]
                graphNewProduct = Graph()
                graphNewProduct.add((productSuj, RDF.type, ONTO.Producte))
                graphNewProduct.add((productSuj, ONTO.ID, Literal(identificador)))
                for s, p, o in gm:
                    if p == ONTO.Nom:
                        graphNewProduct.add((productSuj, ONTO.Nom, Literal(o)))
                    elif p == ONTO.NomEmpresa:
                        graphNewProduct.add((productSuj, ONTO.Empresa, Literal(o)))
                    elif p == ONTO.Marca:
                        graphNewProduct.add((productSuj, ONTO.Marca, Literal(o)))
                    elif p == ONTO.Preu:
                        graphNewProduct.add((productSuj, ONTO.Preu, Literal(o)))
                    elif p == ONTO.Pes:
                        graphNewProduct.add((productSuj, ONTO.Pes, Literal(o)))
                    elif p == ONTO.Categoria:
                        graphNewProduct.add((productSuj, ONTO.Categoria, Literal(o)))

                graphNewProduct.add((productSuj, ONTO.Valoracio, Literal(5)))
                graphNewProduct.add((productSuj, ONTO.QuantitatValoracions, Literal(1)))

                rdf_xml_data = graphNewProduct.serialize(format='xml')

                headers = {
                    'Content-Type': 'application/rdf+xml'
                }

                fuseki_response = requests.post(fuseki_url, data=rdf_xml_data, headers=headers)
                if fuseki_response.status_code == 200:
                    print('Producto añadido exitosamente a Fuseki')
                else:
                    print(
                        f'Error al añadir el producto a Fuseki: {fuseki_response.status_code} - {fuseki_response.text}')

                gr = Graph()
                return gr.serialize(format='xml'), 200

            elif accion == ONTO.EliminarProducteExtern:
                product_id = gm.value(subject=content, predicate=ONTO.ID)
                print(f"Received request to delete product with ID: {product_id}")  # Registro de depuración
                if product_id and delete_product_from_fuseki(str(product_id)):
                    print('Producto eliminado exitosamente de Fuseki')
                    gr = build_message(Graph(), ACL.inform, sender=ServeiCataleg.uri, msgcnt=get_count())
                else:
                    print('Error al eliminar el producto de Fuseki')
                    gr = build_message(Graph(), ACL.failure, sender=ServeiCataleg.uri, msgcnt=get_count())
                return gr.serialize(format='xml'), 200

            else:
                # No entendemos la acción
                gr = build_message(Graph(),
                                   ACL['not-understood'],
                                   sender=ServeiCataleg.uri,
                                   msgcnt=get_count())
                return gr.serialize(format='xml'), 200

    return "Aquest agent s'encarregarà d'afegir productes."

def agentbehavior1(queue):
    """
    Un comportament de l'agent
    :return:
    """
    pass


@app.route("/Stop")
def stop():
    """
    Entrypoint que para l'agent
    """
    tidyup()
    shutdown_server()
    return "Parant Servidor"


def tidyup():
    """
    Accions prèvies a parar l'agent
    """
    pass


if __name__ == '__main__':
    # Ponemos en marcha los behaviors
    ab1 = Process(target=agentbehavior1, args=(cola1,))
    ab1.start()
    compra = False
    # Ponemos en marcha el servidor
    app.run(host=hostname, port=port)

    # Esperamos a que acaben los behaviors
    ab1.join()

    print('The End')