"""
Agente Asistente para el sistema ECSDI.
Utiliza Flask para la interacción web y RDFlib para la manipulación de grafos RDF.

/comm -> Método POST para recibir mensajes ACL de otros agentes.
/Stop -> Método GET para parar el agente.
"""
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

__author__ = 'Nil'

from Utils.ACLMessages import send_message

# Configuración de logging
logger = config_logger(level=1)

# Configuración del agente
hostname = socket.gethostname()
port = 9014

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

AgentTransportista = Agent('AgTransportista',
                        agn.Transportista,
                        'http://%s:9015/comm' % hostname,
                        'http://%s:9015/Stop' % hostname)

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


def get_count():
    global mss_cnt
    mss_cnt += 1
    return mss_cnt

@app.route("/comm", methods=['GET'])
def communication():
    """
    Entrypoint de comunicación del agente.
    """

    global centro
    message = request.args['content']
    gm = Graph()
    gm.parse(data=message)

    msgdic = get_message_properties(gm)

    gr = None
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
                accion = ONTO["EnviarCondicionsEnviament_" + str(count)]
                lot = ONTO["Lot_" + str(count)]
                graph = Graph()
                pes_total = 0
                graph.add((accion, RDF.type, ONTO.EnviarCondicionsEnviament))
                graph.add((lot, RDF.type, ONTO.Lot))

                compraSujeto = ""
                ciutat = ""
                idLot = ""
                preu_compra = 0
                productes = []
                for s, p, o in gm:
                    if p == ONTO.Ciutat:
                        graph.add((lot, ONTO.Ciutat, Literal(o, datatype=XSD.string)))
                        compraSujeto = s
                    if p == ONTO.ID:
                        idLot = o
                    elif p == ONTO.CiutatCL:
                        ciutat = o
                    elif p == ONTO.Prioritat:
                        graph.add((lot, ONTO.Prioritat, Literal(o, datatype=XSD.integer)))
                    elif p == ONTO.PreuTotal:
                        preu_compra = o.toPython()
                    elif p == ONTO.Pes:
                        pes_total += float(o)
                    elif p == ONTO.Producte:
                        productes.append(s)
                        graph.add((s, RDF.type, ONTO.Producte))
                        graph.add((s, ONTO.Nom, Literal(o, datatype=XSD.string)))
                        graph.add((lot, ONTO.ProductesLot, s))
                graph.add((lot, ONTO.Pes, Literal(pes_total, datatype=XSD.float)))

                # Accio per enviar les condicions de l'enviament
                graph.add((accion, ONTO.Lot, lot))
                logger.info("Pedimos los precios de envío a los transportistas del centro logístico de " + ciutat)
                gr = send_message(
                    build_message(graph, ACL.request, ServeiCentreLogistic.uri,
                                  AgentTransportista.uri, accion, count),
                    AgentTransportista.address
                )
                logger.info("Hemos recibido las ofertas iniciales")




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

                return gm.serialize(format='xml'), 200