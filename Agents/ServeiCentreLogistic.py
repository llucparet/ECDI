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

ServeiEntrega = Agent('ServeiEntrega',
                      agn.ServeiEntrega,
                      f'http://{hostname}:8000/comm',
                      f'http://{hostname}:8000/Stop')

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

                lot = ONTO["Lot_" + str(count)]
                print(lot)
                pes_total = 0
                preu_compra = 0
                gr.add((lot, RDF.type, ONTO.Lot))
                gr.add((action, ONTO.EnviaCondicions, lot))
                productes = []
                for s, p, o in gm:
                    if p == ONTO.Ciutat:
                        gr.add((lot, ONTO.Ciutat, Literal(o, datatype=XSD.string)))
                    elif p == ONTO.Prioritat:
                        gr.add((lot, ONTO.Prioritat, Literal(o, datatype=XSD.integer)))
                    elif p == ONTO.Pes:
                        pes_total += float(o)
                    elif p == RDF.type and o == ONTO.Producte:
                        productes.append(s)
                        gr.add((s, RDF.type, ONTO.Producte))

                        gr.add((lot, ONTO.ProductesLot, s))
                    elif o == ONTO.Comanda:
                        gr.add((lot, ONTO.ComandaLot, s))

                gr.add((lot, ONTO.Pes, Literal(pes_total, datatype=XSD.float)))

                AgentTransportista = asignar_port_agenttrasportista(port + 5)

                msg = build_message(gr, ACL.request, ServeiCentreLogistic.uri,
                                    AgentTransportista.uri, action, count)

                resposta = send_message(msg, AgentTransportista.address)

                preu_mes_barat = sys.maxsize
                data = "9999-12-31"
                nom_transportista = ""
                for s, p, o in resposta:
                    if p == ONTO.Oferta:
                        preu = float(resposta.value(subject=o, predicate=ONTO.Preu))
                        if preu < preu_mes_barat:
                            preu_mes_barat = preu
                            data = resposta.value(subject=o, predicate=ONTO.Data)
                            transportista = resposta.value(subject=o, predicate=ONTO.Transportista)
                            nom_transportista = resposta.value(subject=transportista, predicate=ONTO.Nom)
                #iniciar negociacio contraoferta
                acceptada = False
                reduccio = 0.80

                while not acceptada:
                    print("preu_mes_barat: ", preu_mes_barat)
                    print(ciutat)
                    count = get_count()
                    gO = Graph()
                    contraoferta_action = ONTO["EnviarContraoferta_" + str(count)]
                    gO.add((contraoferta_action, RDF.type, ONTO.EnviarContraoferta))
                    gO.add((contraoferta_action, ONTO.Preu,
                            Literal(preu_mes_barat * reduccio)))
                    gO.add((contraoferta_action, ONTO.UltimPreu, Literal(preu_mes_barat)))
                    gO.add((contraoferta_action, ONTO.Transportista, transportista))
                    gO.add((transportista, ONTO.Nom, Literal(nom_transportista, datatype=XSD.string)))
                    print(port)
                    AgentTransportista = asignar_port_agenttrasportista(port + 5)
                    msg = build_message(gO, ACL.request, ServeiCentreLogistic.uri,
                                        AgentTransportista.uri, contraoferta_action, count)

                    resposta_contraoferta = send_message(msg, AgentTransportista.address)

                    for s, p, o in resposta_contraoferta:
                        print(p)
                        if p == ONTO.AcceptarContraoferta:
                            preu_mes_barat = float(resposta_contraoferta.value(subject=s, predicate=ONTO.Preu))
                            acceptada = True
                        elif p == ONTO.RebutjarOferta:
                            reduccio += 0.05
                            nou_preu = float(resposta_contraoferta.value(subject=s, predicate=ONTO.Preu))
                            print("nou_preu: ", nou_preu)
                            if nou_preu < preu_mes_barat*reduccio:
                                acceptada = True
                                preu_mes_barat = nou_preu
                print("hola2")
                ab1 = Process(target=enviar_paquet,
                              args=(gr, transportista,nom_transportista))
                ab1.start()
                ab1.join()
                preu = reclamar_pagament(gr,transportista,nom_transportista, preu_mes_barat+preu_compra, data,productes)

                gresposta = Graph()
                accion = ONTO["InformarEnviament_" + str(count)]
                gresposta.add((accion, RDF.type, ONTO.InformarEnviament))
                gresposta.add((accion, ONTO.Preu, Literal(preu, datatype=XSD.float)))

                return gresposta.serialize(format="xml"), 200

def enviar_paquet(gr, transportista, nom_transportista):
    genvio = Graph()
    for s, p, o in gr:
        if p == ONTO.EnviaCondicions:
            lot = o
    count = get_count()
    accion = ONTO["AssignarTransportista_" + str(count)]
    genvio.add((accion, RDF.type, ONTO.AssignarTransportista))
    genvio.add((accion, ONTO.AssignarLot, lot))
    genvio.add((accion, ONTO.Transportista, transportista))
    genvio.add((transportista, ONTO.Nom, nom_transportista))
    AgentTransportista = asignar_port_agenttrasportista(port + 5)
    msg = build_message(genvio, ACL.request, ServeiCentreLogistic.uri,
                        AgentTransportista.uri, accion, count)

    resposta = send_message(msg, AgentTransportista.address)

    return resposta.serialize(format='xml'), 200

def reclamar_pagament(gr,transportista, nom_transportista, preu, data, productes):
    genvio = Graph()
    for s, p, o in gr:
        if p == ONTO.EnviaCondicions:
            lot = o
        if p == ONTO.ComandaLot:
            comanda = o
    print(lot)
    print(comanda)
    count = get_count()
    accion = ONTO["InformarEnviament_" + str(count)]
    genvio.add((accion, RDF.type, ONTO.InformarEnviament))
    genvio.add((accion, ONTO.InforamrLot, lot))
    genvio.add((lot,ONTO.ComandaLot,comanda))
    genvio.add((accion, ONTO.Data, Literal(data, datatype=XSD.string)))
    genvio.add((accion, ONTO.Transportista, transportista))
    genvio.add((transportista, ONTO.Nom, nom_transportista))
    genvio.add((accion, ONTO.Preu, Literal(preu, datatype=XSD.float)))
    print(productes)
    for p in productes:
        genvio.add((lot, ONTO.ProducteLot, p))

    msg = build_message(genvio, ACL.request, ServeiCentreLogistic.uri,
                        ServeiEntrega.uri, accion, count)

    resposta = send_message(msg, ServeiEntrega.address)

    for s, p, o in resposta:
        print(p)
        if p == ONTO.Preu:
            preu = o
    return preu


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