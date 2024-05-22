import socket
from multiprocessing import Queue, Process

from SPARQLWrapper import SPARQLWrapper, JSON
from flask import Flask, request
from pyparsing import Literal
from rdflib import Namespace, Literal, URIRef, XSD

from Agents.AgentTransportista import get_count
from Utils.ACLMessages import *
from Utils.Agent import Agent
from Utils.Logger import config_logger
from Utils.OntoNamespaces import ONTO
from geopy.geocoders import Nominatim
from geopy.distance import great_circle

logger = config_logger(level=1)

# Configuration stuff
hostname = socket.gethostname()
port = 9012
cola1 = Queue()
agn = Namespace("https://www.agentes.org#")

ServeiComandes = Agent('ServeiComandes',
                       agn.ServeiComandes,
                       'http://%s:%d/comm' % (hostname, port),
                       'http://%s:%d/Stop' % (hostname, port))
AgentAsistent = Agent('AgentAsistent',
                      agn.AgentAsistent,
                      'http://%s:9011/comm' % hostname,
                      'http://%s:9011/Stop' % hostname)
ServeiCentreLogistic = Agent('CentreLogistic',
                            agn.ServeiCentreLogistic,
                            'http://%s:9013/comm' % hostname,
                            'http://%s:9013/Stop' % hostname)
ServeiEntrega = Agent('ServeiEntrega',
                      agn.ServeiEntrega,
                      'http://%s:9014/comm' % hostname,
                      'http://%s:9014/Stop' % hostname)
AgentVenedorExtern = Agent('AgentVenedorExtern',
                           agn.AgentVenedorExtern,
                           'http://%s:9015/comm' % hostname,
                           'http://%s:9015/Stop' % hostname)
g = Graph()

app = Flask(__name__)

graph_compra = Graph()


@app.route("/comm")
def communication():
    """
    Communication Entrypoint

    message = request.args['content']
    graf = Graph()
    graf.parse(data=message)

    # Get the message properties
    msgdic = get_message_properties(graf)


    if msgdic is None:
        # Si no es, respondemos que no hemos entendido el mensaje
        gr = build_message(Graph(), ACL['not-understood'], sender=ServeiComandes.uri, msgcnt=get_count())

    else:
        # Obtenemos la performativa
        if msgdic['performative'] != ACL.request:
            # Si no es un request, respondemos que no hemos entendido el mensaje
            gr = build_message(Graph(),
                               ACL['not-understood'],
                               sender=ServeiComandes.uri,
                               msgcnt=get_count())
        else:
            # Obtenemos la acción
            content = msgdic['content']
            accion = graf.value(subject=content, predicate=RDF.type)

            if accion == ONTO.ComprarProductes:
                logger.info('Petición de compra recibida')
                graph_compra = graf
                sparql = SPARQLWrapper("http://localhost:3030/dataset/sparql")
                for s, p, o in graf:
                    if p == ONTO.Productes:
                        consulta_sparql =
                        SELECT ?centreLogistic
                        WHERE {
                            ?centreLogistic rdf:type ONTO:CentreLogistic .
                            ?centreLogistic ONTO:ProductesCentreLogistic onto:%s .
                        }
                         % o
                        sparql.setQuery(consulta_sparql)
                        sparql.setReturnFormat(JSON)
                        try:
                            resultats = sparql.query().convert()
                            centre_logistic_proper = None
                            for res in resultats['results']['bindings']:
                                centre_logistic = res['centreLogistic']['value']
                                logger.info('Centre logístic trobat: %s' % centre_logistic)
                                gr = build_message(Graph(),
                                                   ACL['request'],
                                                   sender=ServeiComandes.uri,
                                                   receiver=ServeiCentreLogistic.uri,
                                                   content=centre_logistic,
                                                   msgcnt=get_count())
                                return gr.serialize(format='xml')
                        except:
                            gr = build_message(Graph(),
                                               ACL['not-understood'],
                                               sender=ServeiComandes.uri,
                                               msgcnt=get_count())
                            return gr.serialize(format='xml')
            else:
                gr = build_message(Graph(),
                                   ACL['not-understood'],
                                   sender=ServeiComandes.uri,
                                   msgcnt=get_count())
    """
    global consulta_sparql
    msg_graph = Graph()

    # Definir las URI de los sujetos
    content_uri = URIRef("http://localhost:3030/dataset/sparql")

    # Añadir triples al grafo
    msg_graph.add((content_uri, RDF.type, ONTO.ComprarProductes))

    # Aquí añades la lista de productos, por ejemplo:
    productos = ["producto1", "producto2", "producto3"]
    for producto in productos:
        msg_graph.add((content_uri, ONTO.Producte, URIRef(ONTO + producto)))
    accion = msg_graph.value(predicate=RDF.type)

    if accion == ONTO.ComprarProductes:
        logger.info('Petición de compra recibida')
        graph_compra = msg_graph
        sparql = SPARQLWrapper("http://localhost:3030/dataset/sparql")
        for s, p, o in msg_graph:
            if p == ONTO.Productes:
                consulta_sparql = """
                SELECT ?centreLogistic
                WHERE
                {
                    ?centreLogistic rdf:type ontologies:CentreLogistic .
                    ?centreLogistic ontologies:Ciutat "Barcelona" .
                }
                """
            sparql.setQuery(consulta_sparql)
            sparql.setReturnFormat(JSON)
        try:
            resultats = sparql.query().convert()
            centre_logistic_proper = None
            for res in resultats['results']['bindings']:
                centre_logistic = res['centreLogistic']['value']
                print("Centre logístic trobat: %s" % centre_logistic)
                gr = build_message(Graph(),
                                   ACL.request,
                                   sender=ServeiComandes.uri,
                                   receiver=ServeiCentreLogistic.uri,
                                   content=centre_logistic,
                                   msgcnt=get_count())
                return gr.serialize(format='xml')
        except:
            gr = build_message(Graph(),
                               ACL.not_understood,
                               sender=ServeiComandes.uri,
                               msgcnt=get_count())
            return gr.serialize(format='xml')

def agentbehavior1(cola):
    """
    Un comportamiento del agente

    :return:
    """
    pass

if __name__ == '__main__':
    # Ponemos en marcha los behaviors
    ab1 = Process(target=agentbehavior1, args=(cola1,))
    ab1.start()

    # Ponemos en marcha el servidor
    app.run(host=hostname, port=port)

    # Esperamos a que acaben los behaviors
    ab1.join()

    print('The End')
