"""
Agente Asistente para el sistema ECSDI.
Utiliza Flask para la interacción web y RDFlib para la manipulación de grafos RDF.

/comm -> Método POST para recibir mensajes ACL de otros agentes.
/Stop -> Método GET para parar el agente.
"""
import multiprocessing
import sys
from multiprocessing import Process, Queue
import socket
import flask
from SPARQLWrapper import SPARQLWrapper
from flask import Flask, request, render_template, redirect, url_for
from rdflib import Namespace, Graph, RDF, Literal, URIRef, XSD
from Utils.ACLMessages import build_message, get_message_properties
from Utils.FlaskServer import shutdown_server
from Utils.Agent import Agent
from Utils.templates import *
from Utils.OntoNamespaces import ONTO
from Utils.ACL import ACL
from Utils.Logger import config_logger


from Utils.ACLMessages import send_message

# Configuración de logging
logger = config_logger(level=1)

# Configuración del agente
hostname = "localhost"
port = None
ciutat = None
# Namespaces para RDF
agn = Namespace("http://www.agentes.org#")

# Instancia del Flask app
app = Flask(__name__, template_folder='../Utils/templates')

# Contador de mensajes
mss_cnt = 0

# Agentes del sistema
ServeiCentreLogistic = Agent('ServeiCentreLogistic',
                             agn.ServeiCentreLogistic,
                             f'http://{hostname}:{port}/comm',
                             f'http://{hostname}:{port}/Stop')

ServeiComandes = Agent('ServeiComandes',
                       agn.ServeiComandes,
                       f'http://{hostname}:9012/comm',
                       f'http://{hostname}:9012/Stop')

def asignar_port_agenttrasportista(port):
    AgentTransportista = Agent('AgTransportista',
                               agn.AgentTransportista,
                               f'http://{hostname}:{port}/comm',
                               f'http://{hostname}:{port}/Stop')
    return AgentTransportista

AgVendedorExterno = Agent('AgVendedorExterno',
                        agn.AgVendedorExterno,
                        'http://%s:9018/comm' % hostname,
                        'http://%s:9018/Stop' % hostname)


# Global triplestore graph
dsgraph = Graph()

# Configuración de Fuseki
fuseki_server = 'http://localhost:3030/ds'
sparql = SPARQLWrapper(fuseki_server)

cola1 = Queue()

lots_centre_logistic = []

def get_count():
    global mss_cnt
    mss_cnt += 1
    return mss_cnt

def run_agent(portx, city):
    @app.route('/')
    def index():
        return f"Agent running on port {portx} in city {city}"

    global port
    port = portx
    global ciutat
    ciutat = city
    app.run(host=hostname, port=portx)
@app.route("/comm", methods=['GET'])
def communication():
    """
    Entrypoint de comunicación del agente.
    """
    message = request.args['content']
    gm = Graph()
    gm.parse(data=message, format='xml')

    msgdic = get_message_properties(gm)

    gr = Graph()
    if msgdic is None:
        gr = build_message(Graph(), ACL['not-understood'],
                           sender=ServeiCentreLogistic.uri,
                           msgcnt=get_count())
    else:
        if msgdic['performative'] != ACL.request:
            gr = build_message(Graph(), ACL['not-understood'],
                               sender=ServeiCentreLogistic.uri,
                               msgcnt=get_count())
        else:
            content = msgdic['content']
            accion = gm.value(subject=content, predicate=RDF.type)

            if accion == ONTO.ProcessarEnviament:
                count = get_count()
                action = ONTO["EnviarCondicionsEnviament" + str(count)]
                gr.add((action, RDF.type, ONTO.EnviarCondicionsEnviament))

                lot = ONTO["Lot" + str(count)]
                pes_total = 0
                gr.add((lot, RDF.type, ONTO.Lot))
                gr.add((action, ONTO.EnviaCondicions, ONTO.Lot))
                preu_compra = 0
                productes = []
                for s, p, o in gm:
                    if p == ONTO.Ciutat:
                        gr.add((lot, ONTO.Ciutat, Literal(o, datatype=XSD.string)))
                    elif p == ONTO.Prioritat:
                        gr.add((lot, ONTO.Prioritat, Literal(o, datatype=XSD.integer)))
                    elif p == ONTO.Pes:
                        pes_total += float(o)
                    elif p == ONTO.Producte:
                        productes.append(o)
                        preu_compra += float(gm.value(subject=o, predicate=ONTO.Preu))
                        gr.add((o, RDF.type, ONTO.Producte))
                        gr.add((o, ONTO.Nom, Literal(o, datatype=XSD.string)))
                        gr.add((lot, ONTO.ProductesLot, o))
                gr.add((lot, ONTO.Pes, Literal(pes_total, datatype=XSD.float)))

                AgentTransportista = asignar_port_agenttrasportista(port + 5)

                msg = build_message(gr, ACL.request, ServeiCentreLogistic.uri,
                                    AgentTransportista.uri, action, count)

                resposta = send_message(msg, AgentTransportista.address)

                preu_mes_barat = sys.maxsize
                data = "9999-12-31"
                trasnportistax = ""
                for s, p, o in resposta:
                    if p == ONTO.Oferta:
                        preu = float(resposta.value(subject=o, predicate=ONTO.Preu))
                        if preu < preu_mes_barat:
                            preu_mes_barat = preu
                            data = resposta.value(subject=o, predicate=ONTO.Data)
                            transportistax = resposta.value(subject=o, predicate=ONTO.Transportista)

                gr = Graph()
                accion = ONTO["AssignarTransportista_" + str(count)]
                gr.add((accion, RDF.type, ONTO.AssignarTransportista))
                gr.add((accion, ONTO.Data, Literal(data)))
                gr.add((accion, ONTO.Preu, Literal(preu_mes_barat)))

                """ 
                               for s, p, o in resposta:
                    if p == ONTO.Preu:
                        lots_centre_logistic.append(o)
                        
                gc = Graph()
                accion = ONTO["EnviarContraoferta_" + str(count)]
                gc.add((accion, RDF.type, ONTO.EnviarContraoferta))
                gc.add((lot, RDF.type, ONTO.Lot))
                gc.add((accion, ONTO.EnviaContraoferta, lot))

                transportista = []
                for s, p, o in gr:
                    if p == ONTO.OfertaDe:
                        transportista.append(o)
                precio_min = sys.maxsize
                for t in transportista:
                    preu = gr.value(subject=t, predicate=ONTO.Preu)
                    if preu_min > preu:
                        preu_min = preu
                preu_contraoferta = preu_min * 0.9
                gc.add((accion, ONTO.PreuContraoferta, Literal(preu_contraoferta, datatype=XSD.float)))

                logger.info("Enviamos la contraoferta a los transportistas")
                gf = send_message(
                    build_message(gc, ACL.request, ServeiCentreLogistic.uri,
                                  AgentTransportista.uri, accion, count),
                    AgentTransportista.address
                )
                logger.info("Hemos recibido la confirmación de la contraoferta")

                preu_final_enviament = sys.maxsize
                id_transportista_final = ""
                nom_transportista_final = ""
                data_final = "9999-12-31"
                tansportista = []
                for s, p, o in gf:
                    if p == ONTO.OfertaDe:
                        transportista.append(o)
                for t in transportista:
                    preu = gf.value(subject=t, predicate=ONTO.Preu)
                    data = gf.value(subject=t, predicate=ONTO.Data)
                    if preu < preu_final_enviament or (preu == preu_final_enviament and data < data_final):
                        preu_final_enviament = preu
                        id_transportista_final = gf.value(subject=t, predicate=ONTO.ID)
                        nom_transportista_final = gf.value(subject=t, predicate=ONTO.Nom)
                        data_final = data

                preu_compra += preu_final_enviament
                transportista = ONTO[id_transportista_final]

                gconfirm = Graph()
                accion = ONTO["AssignarTransportista_" + str(count)]
                gconfirm.add((accion, RDF.type, ONTO.AssignarTransportista))
                gconfirm.add((accion, ONTO.ID, Literal(id_transportista_final, datatype=XSD.string)))
                gconfirm.add((accion, ONTO.Nom, Literal(nom_transportista_final, datatype=XSD.string)))
                gconfirm.add((accion, ONTO.AssignaLot, lot))

                logger.info("Enviamos la confirmación de la oferta al transportista" + nom_transportista_final)

                send_message(
                    build_message(gconfirm, ACL.request, ServeiCentreLogistic.uri,
                                  AgentTransportista.uri, accion, count),
                    AgentTransportista.address
                )

                logger.info("Hemos enviado la assignación al transportista")

                gcobrar = Graph()
                accion = ONTO["CobrarProductes_" + str(count)]
                gcobrar.add((accion, RDF.type, ONTO.CobrarProductes))
                gcobrar.add((accion, ONTO.CobraLot, Literal(idLot, datatype=XSD.string)))
                send_message(
                    build_message(gcobrar, ACL.request, ServeiCentreLogistic.uri,
                                  ServeiComandes.uri, accion, count),
                    ServeiComandes.address
                )

                logger.info("Hemos cobrado los productos")
                """
                return gr.serialize(format='xml'), 200
if __name__ == '__main__':
    ports_cities = {
        8014: 'Banyoles',
        8015: 'Barcelona',
        8016: 'Tarragona',
        8017: 'Valencia',
        8018: 'Zaragoza'
    }

    processes = []

    for port, city in ports_cities.items():
        p = multiprocessing.Process(target=run_agent, args=(port, city))
        processes.append(p)
        p.start()

    for p in processes:
        p.join()