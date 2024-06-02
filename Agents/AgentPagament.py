import socket
from datetime import datetime
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

from Utils.ACLMessages import build_message, send_message, get_message_properties

logger = config_logger(level=1)

# Configuration stuff
hostname = "localhost"
port = 8007

agn = Namespace("http://www.agentes.org#")

# Contador de mensajes
mss_cnt = 0
endpoint_url = "http://localhost:3030/ONTO/query"

fuseki_url = 'http://localhost:3030/ONTO/data'

AgentPagament = Agent('AgentPagament',
                      agn.AgentPagament,
                      'http://%s:%d/comm' % (hostname, port),
                      'http://%s:%d/Stop' % (hostname, port))

AgentAssistent = Agent('AgentAssistent',
                       agn.AgentAssistent,
                       'http://%s:9011/comm' % hostname,
                       'http://%s:9011/Stop' % hostname)


# Global triplestore graph
dsgraph = Graph()

cola1 = Queue()

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
        gr = build_message(Graph(), ACL['not-understood'], sender=AgentAssistent.uri, msgcnt=get_count())

    else:
        # Obtenemos la performativa
        if msgdic['performative'] != ACL.request:
            # Si no es un request, respondemos que no hemos entendido el mensaje
            gr = build_message(Graph(),
                               ACL['not-understood'],
                               sender=AgentAssistent.uri,
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

if __name__ == '__main__':
    # Ponemos en marcha el servidor
    app.run(host=hostname, port=port)