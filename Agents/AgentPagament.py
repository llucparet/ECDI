import argparse
import socket
from datetime import datetime
import sys
import os
sys.path.insert(0, os.path.abspath('../'))
from multiprocessing import Queue, Process

from SPARQLWrapper import RDF, SPARQLWrapper, JSON
from flask import Flask, request
from pyparsing import Literal
from rdflib import Namespace, Literal, URIRef, XSD, Graph
from Utils.ACLMessages import *
from Utils.Agent import Agent
from Utils.Logger import config_logger
from Utils.OntoNamespaces import ONTO
from Utils.ACL import ACL
from geopy.geocoders import Nominatim
from geopy.distance import great_circle, geodesic

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
    port = 8007
else:
    port = args.port

if args.open:
    hostname = '0.0.0.0'
    hostaddr = socket.gethostname()
else:
    hostaddr = hostname = socket.gethostname()

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

AgentPagament = Agent('AgentPagament',
                      agn.AgentPagament,
                      'http://%s:%d/comm' % (hostaddr, port),
                      'http://%s:%d/Stop' % (hostaddr, port))

# Directory agent address
DirectoryAgent = Agent('DirectoryAgent',
                       agn.Directory,
                       'http://%s:%d/Register' % (dhostname, dport),
                       'http://%s:%d/Stop' % (dhostname, dport))


# Global triplestore graph
dsgraph = Graph()

queue = Queue()

endpoint_url = f"http://{dhostname}:3030/ONTO/query"

fuseki_url = f'http://{dhostname}:3030/ONTO/update'




# Flask stuff
app = Flask(__name__)


def get_count():
    global mss_cnt
    mss_cnt += 1
    return mss_cnt
@app.route("/comm")
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
    global graph_compra
    global precio_total_compra, mss_cnt
    gr = Graph()

    if msgdic is None:
        # Si no es, respondemos que no hemos entendido el mensaje
        gr = build_message(Graph(), ACL['not-understood'], sender=AgentPagament.uri, msgcnt=get_count())

    else:
        # Obtenemos la performativa
        if msgdic['performative'] != ACL.request:
            # Si no es un request, respondemos que no hemos entendido el mensaje
            gr = build_message(Graph(),
                               ACL['not-understood'],
                               sender=AgentPagament.uri,
                               msgcnt=get_count())

        else:

            content = msgdic['content']

            accion = gm.value(subject=content, predicate=RDF.type)
            llista_productes = []
            print(accion)
            # Accion de hacer pedido
            if accion == ONTO.CobrarProductes:

                for s, p, o in gm:
                    if p == ONTO.Nom:
                        nom_producte = str(o)
                    elif p == ONTO.Comanda:
                        comanda = str(o)
                    elif p == ONTO.DNI:
                        dni = str(o)
                logger.info(f"L'usuari: {dni} ha pagat el producte:{nom_producte} de la comanda {comanda}")

                sparql_query = f"""
                                    PREFIX ontologies: <http://www.semanticweb.org/nilde/ontologies/2024/4/>
                                    PREFIX xsd: <http://www.w3.org/2001/XMLSchema#>

                                    DELETE {{
                                        ?producteComanda ontologies:Pagat ?oldPagat .
                                    }}
                                    INSERT {{
                                        ?producteComanda ontologies:Pagat true .
                                    }}
                                    WHERE {{
                                        <http://www.semanticweb.org/nilde/ontologies/2024/4/{comanda}> ontologies:ProductesComanda ?producteComanda .
                                        ?producteComanda ontologies:Nom "{nom_producte}" .

                                        OPTIONAL {{ ?producteComanda ontologies:Pagat ?oldPagat . }}
                                    }}
                                    """

                # Defineix els encapçalaments HTTP
                headers = {
                    'Content-Type': 'application/sparql-update'
                }

                # Envia la sol·licitud POST al servidor Fuseki
                response = requests.post(fuseki_url, data=sparql_query, headers=headers)

                # Mostra la resposta
                if response.status_code == 204:
                    print("Consulta SPARQL executada correctament.")
                else:
                    print(f"Error en executar la consulta SPARQL: {response.status_code}")
                    print(response.text)
                return gr.serialize(format='xml'), 200

            elif accion == ONTO.PagarVenedorExtern:
                logger.info ("Pagament a venedor extern")
                g = Graph()
                return g.serialize(format='xml'), 200

            elif accion == ONTO.PagarUsuari:
                print("Pagar Usuari")

                client = ""
                import_producte = ""
                producte_comanda = ""

                for s, p, o in gm:
                    if p == ONTO.Desti:
                        client = o
                    elif p == ONTO.Import:
                        import_producte = o
                    elif p == ONTO.ProducteComanda:
                        producte_comanda = o

                print(f"Client: {client}, Import: {import_producte}, ProducteComanda: {producte_comanda}")
                logger.info(f"Pagament a usuari: {client}, import: {import_producte}, producte: {producte_comanda}")

                return gr.serialize(format='xml'), 200


def PagamentBehavior(queue):

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

    gr = registerAgent(AgentPagament, DirectoryAgent, AgentPagament.uri, get_count(),port)
    return gr
if __name__ == '__main__':
    ab1 = Process(target=PagamentBehavior, args=(queue,))
    ab1.start()

    # Run server
    app.run(host=hostname, port=port, debug=False)

    # Wait behaviors
    ab1.join()
    print('The End')