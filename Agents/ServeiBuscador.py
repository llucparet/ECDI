import os

import argparse
import sys
sys.path.insert(0, os.path.abspath('../'))
from SPARQLWrapper import JSON, SPARQLWrapper
from flask import Flask, request
from rdflib import Graph, RDF, Namespace, Literal, URIRef
from multiprocessing import Queue, Process

from Utils.ACL import ACL
from Utils.ACLMessages import build_message, get_message_properties, registerAgent
from Utils.Agent import Agent
from Utils.FlaskServer import shutdown_server
from Utils.Logger import config_logger
from Utils.OntoNamespaces import ONTO
import socket

# Definimos los parametros de la linea de comandos
parser = argparse.ArgumentParser()
parser.add_argument('--open', help="Define si el servidor est abierto al exterior o no", action='store_true',
                    default=False)
parser.add_argument('--port', type=int, help="Puerto de comunicacion del agente")
parser.add_argument('--dhost', default=socket.gethostname(), help="Host del agente de directorio")
parser.add_argument('--dport', type=int, help="Puerto de comunicacion del agente de directorio")

# Logging
logger = config_logger(level=1)

# parsing de los parametros de la linea de comandos
args = parser.parse_args()

# Configuration stuff
if args.port is None:
    port = 9003
else:
    port = args.port

if args.open is None:
    hostname = '0.0.0.0'
else:
    hostname = socket.gethostname()

if args.dport is None:
    dport = 9000
else:
    dport = args.dport

if args.dhost is None:
    dhostname = socket.gethostname()
else:
    dhostname = args.dhost

# AGENT ATTRIBUTES ----------------------------------------------------------------------------------------

# Agent Namespace
agn = Namespace("http://www.agentes.org#")

# Message Count
mss_cnt = 0

# Data Agent

ServeiBuscador = Agent('ServeiBuscador',
                       agn.ServeiBuscador,
                       f'http://{hostname}:{port}/comm',
                       f'http://{hostname}:{port}/Stop')
# Directory agent address
DirectoryAgent = Agent('DirectoryAgent',
                       agn.Directory,
                       'http://%s:%d/Register' % (dhostname, dport),
                       'http://%s:%d/Stop' % (dhostname, dport))

# Global triplestore graph
dsGraph = Graph()

# Queue
queue = Queue()

# Flask app
app = Flask(__name__)


def get_count():
    global mss_cnt
    mss_cnt += 1
    return mss_cnt

@app.route("/comm", methods=['GET', 'POST'])
def communication():
    if request.method == 'POST':
        message = request.data
    elif request.method == 'GET':
        message = request.args['content']

    gm = Graph()
    gm.parse(data=message, format='xml')
    msgdic = get_message_properties(gm)

    if msgdic and msgdic['performative'] == ACL.request:
        content = msgdic['content']
        accion = gm.value(subject=content, predicate=RDF.type)
        if accion == ONTO.BuscarProductes:
            return handle_search_request(gm, content)

    # Default response if message is not understood or there is no action to perform
    gr = build_message(Graph(), ACL['not-understood'], sender=ServeiBuscador.uri, msgcnt=get_count())
    return gr.serialize(format='xml'), 200

def handle_search_request(gm, content):
    # Extrae las restricciones de búsqueda
    filters = {}
    for restriccio in gm.objects(content, ONTO.Restriccions):
        tipo_restriccion = gm.value(subject=restriccio, predicate=RDF.type)
        for p in ['Marca', 'Nom', 'Valoracio', 'Categoria']:
            if tipo_restriccion == ONTO['Restriccio' + p]:
                filters[p] = gm.value(subject=restriccio, predicate=ONTO[p])

        # Trata las restricciones de precio como un caso especial
        if tipo_restriccion == ONTO.RestriccioPreu:
            filters['PreuMin'] = gm.value(subject=restriccio, predicate=ONTO.PreuMin, default=0.0)
            filters['PreuMax'] = gm.value(subject=restriccio, predicate=ONTO.PreuMax, default=sys.float_info.max)

    logger.info(f'Applying filters: {filters}')
    gr = buscar_productos(**filters)
    return gr.serialize(format='xml'), 200



def buscar_productos(**filters):
    endpoint_url = f"http://{dhostname}:3030/ONTO/query"
    graph = Graph()
    conditions = []

    if 'Marca' in filters:
        conditions.append(f"?marca = \"{filters['Marca']}\"")
    if 'Nom' in filters:
        conditions.append(f"regex(?nom, \"{filters['Nom']}\", \"i\")")
    if 'Categoria' in filters:
        conditions.append(f"regex(?categoria, \"{filters['Categoria']}\", \"i\")")
    if 'Valoracio' in filters:
        conditions.append(f"?valoracio >= {float(filters['Valoracio'])}")
    if 'PreuMin' in filters or 'PreuMax' in filters:
        preuMin = float(filters.get('PreuMin', 0))
        preuMax = float(filters.get('PreuMax', sys.float_info.max))
        conditions.append(f"?preu >= {preuMin} && ?preu <= {preuMax}")

    where_clause = " && ".join(conditions)
    if not where_clause:
        where_clause = "1=1"

    query = f"""
        PREFIX rdf: <http://www.w3.org/1999/02/22-rdf-syntax-ns#>
        PREFIX ex: <http://www.semanticweb.org/nilde/ontologies/2024/4/>

        SELECT ?producte ?nom ?pes ?preu ?marca ?valoracio ?categoria ?empresa
        WHERE {{
            ?producte rdf:type ex:Producte .
            OPTIONAL {{ ?producte ex:Nom ?nom . }}
            OPTIONAL {{ ?producte ex:Pes ?pes . }}
            OPTIONAL {{ ?producte ex:Preu ?preu . }}
            OPTIONAL {{ ?producte ex:Marca ?marca . }}
            OPTIONAL {{ ?producte ex:Valoracio ?valoracio . }}
            OPTIONAL {{ ?producte ex:Categoria ?categoria . }}
            OPTIONAL {{ ?producte ex:Empresa ?empresa . }}
            FILTER ({where_clause})
        }}
    """

    sparql = SPARQLWrapper(endpoint_url)
    sparql.setQuery(query)
    sparql.setReturnFormat(JSON)
    try:
        results = sparql.query().convert()
        for result in results["results"]["bindings"]:
            producte = URIRef(result["producte"]["value"])
            graph.add((producte, RDF.type, ONTO.Producte))
            for attr in ['nom', 'pes', 'preu', 'marca', 'valoracio', 'categoria', 'empresa']:
                if attr in result:
                    graph.add((producte, ONTO[attr.capitalize()], Literal(result[attr]["value"])))
        return graph
    except Exception as e:
        logger.error(f"Error executing SPARQL query: {e}")
        return Graph()  # Return an empty graph on error


@app.route("/Stop")
def stop():
    shutdown_server()
    return "Stopping server"

def buscadorBehavior(queue):

    """
    Agent Behaviour in a concurrent thread.
    :param queue: the queue
    :return: something
    """
    gr = register_message()
def register_message():
    """
    Envia un mensaje de registro al servicio de registro
    usando una performativa Request y una accion Register del
    servicio de directorio

    :param gmess:
    :return:
    """

    logger.info('Nos registramos')

    gr = registerAgent(ServeiBuscador, DirectoryAgent, ServeiBuscador.uri, get_count(),port)
    return gr
if __name__ == '__main__':
    ab1 = Process(target=buscadorBehavior, args=(queue,))
    ab1.start()

    # Run server
    app.run(host=hostname, port=port, debug=False)

    # Wait behaviors
    ab1.join()
    print('The End')
