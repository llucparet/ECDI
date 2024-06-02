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
port = 8000

agn = Namespace("http://www.agentes.org#")

# Contador de mensajes
mss_cnt = 0
endpoint_url = "http://localhost:3030/ONTO/query"

ServeiEntrega = Agent('ServeiEntrega',
                      agn.ServeiEntrega,
                      'http://%s:%d/comm' % (hostname, port),
                      'http://%s:%d/Stop' % (hostname, port))

AgentAssistent = Agent('AgentAssistent',
                       agn.AgentAssistent,
                       'http://%s:9011/comm' % hostname,
                       'http://%s:9011/Stop' % hostname)
AgentPagaments = Agent('AgentPagaments',
                       agn.AgentPagaments,
                       'http://%s:8001/comm' % hostname,
                       'http://%s:8001/Stop' % hostname)
def asignar_port_centre_logistic(port):
    portcentrelogistic = port
    ServeiCentreLogistic = Agent('ServeiCentreLogistic',
                                 agn.ServeiCentreLogistic,
                                 'http://%s:%d/comm' % (hostname, portcentrelogistic),
                                 'http://%s:%d/Stop' % (hostname, portcentrelogistic))
    return ServeiCentreLogistic


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
            print(accion)
            count = get_count()
            # Accion de hacer pedido
            if accion == ONTO.InformarEnviament:
                msg = build_message(gr, ACL.request, ServeiEntrega.uri, AgentAssistent.uri, accion,
                                    get_count())
                resposta = send_message(msg, AgentAssistent.address)
                #aqui em retorna el dni de l'usuari i gurdo la comanda
                llista_porductes = []
                for s, p, o in resposta:
                    if p == ONTO.DNI:
                        dni = o
                    elif p == ONTO.ComandaLot:
                        comanda = o
                    elif p == ONTO.Producte:
                        llista_porductes.append(o)

                for producte in llista_porductes:

                    # Construir les consultes SPARQL
                    delete_query = f"""
                    PREFIX ONTO: <http://example.org/ontology#>
                    SELECT ?produte 
                    WHERE {{
                        <{comanda}> ONTO:ProductesComanda "{producte}" .
                        <{}>
                    }}
                    """

                    insert_query = f"""
                    PREFIX ONTO: <http://example.org/ontology#>
                    INSERT DATA {{
                      <{comanda}> ONTO:Data "{nou_valor}" .
                    }}
                    """

                    # URL del endpoint de Fuseki
                    fuseki_url_update = 'http://localhost:3030/ONTO/update'

                    # Executar la consulta DELETE
                    response_delete = requests.post(fuseki_url_update, data={'update': delete_query},
                                                    headers={'Content-Type': 'application/x-www-form-urlencoded'})
                    if response_delete.status_code == 200:
                        print("DELETE query successful")
                    else:
                        print(f"DELETE query failed: {response_delete.text}")

                    # Executar la consulta INSERT
                    response_insert = requests.post(fuseki_url_update, data={'update': insert_query},
                                                    headers={'Content-Type': 'application/x-www-form-urlencoded'})
                    if response_insert.status_code == 200:
                        print("INSERT query successful")
                    else:
                        print(f"INSERT query failed: {response_insert.text}")

                acction = ONTO["CobrarProductes_"+ str(count)]
                gm.add((accion, RDF.type, acction))
                msg = build_message(gr, ACL.request, ServeiEntrega.uri, AgentPagaments.uri, acction,
                                    get_count())
                resposta = send_message(msg, AgentPagaments.address)
                #aqui guardo que ha fet el pagament






if __name__ == '__main__':
    # Ponemos en marcha el servidor
    app.run(host=hostname, port=port)