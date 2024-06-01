"""
Agente Transportista

Esqueleto de agente usando los servicios web de Flask

/comm es la entrada para la recepcion de mensajes del agente
/Stop es la entrada que para el agente

Tiene una funcion AgentBehavior1 que se lanza como un thread concurrente


@author: pau-laia-anna
"""
import multiprocessing
import time, random
import argparse
import socket
import sys
import requests
from multiprocessing import Queue, Process
from flask import Flask, request
from pyparsing import Literal
from rdflib import URIRef, XSD, Namespace, Graph, Literal
from Utils.ACLMessages import *
from Utils.Agent import Agent
from Utils.FlaskServer import shutdown_server
from Utils.Logger import config_logger
from Utils.OntoNamespaces import ONTO
#from opencage.geocoder import OpenCageGeocode
from geopy.geocoders import Nominatim
from geopy.distance import geodesic, great_circle
from geopy import geocoders
import datetime
import time

from Utils.ACL import ACL
from Utils.ACLMessages import send_message, build_message

logger = config_logger(level=1)

# Configuration stuff
hostname = "localhost"
port = None
ciutat = None

agn = Namespace("http://www.agentes.org#")

# Contador de mensajes
mss_cnt = 0

# Datos del Agente

AgTransportista = None

def assignar_port_transportista():
    return Agent('AgentTransportista',
                        agn.AgTransportista,
                        'http://%s:%d/comm' % (hostname, port),
                        'http://%s:%d/Stop' % (hostname, port))

ServeiCentreLogistic = None

# identificador transportista, nombre transportista, €/kg, €/km
banyoles = [
    ["Transportista_NACEX", "NACEX", 1.50, 0.010, 0.10],
    ["Transportista_SEUR", "SEUR", 1.75, 0.012, 0.15],
    ["Transportista_Correos", "Correos", 1.40, 0.009, 0.05]
]

barcelona = [
    ["Transportista_SEUR", "SEUR", 1.75, 0.012, 0.15],
    ["Transportista_DHL", "DHL", 1.90, 0.015, 0.20],
    ["Transportista_FedEx", "FedEx", 2.00, 0.014, 0.18],
    ["Transportista_UPS", "UPS", 1.85, 0.013, 0.17]
]

tarragona = [
    ["Transportista_NACEX", "NACEX", 1.55, 0.011, 0.12],
    ["Transportista_DHL", "DHL", 1.95, 0.016, 0.22],
    ["Transportista_FedEx", "FedEx", 2.05, 0.014, 0.19],
    ["Transportista_Correos", "Correos", 1.45, 0.010, 0.07]
]

valencia = [
    ["Transportista_NACEX", "NACEX", 1.60, 0.012, 0.13],
    ["Transportista_SEUR", "SEUR", 1.80, 0.011, 0.14],
    ["Transportista_UPS", "UPS", 1.90, 0.013, 0.16],
    ["Transportista_Correos", "Correos", 1.50, 0.009, 0.08]
]

zaragoza = [
    ["Transportista_DHL", "DHL", 1.85, 0.015, 0.20],
    ["Transportista_FedEx", "FedEx", 2.10, 0.014, 0.21],
    ["Transportista_Correos", "Correos", 1.55, 0.010, 0.09],
    ["Transportista_UPS", "UPS", 1.95, 0.012, 0.18]
]

llista_transportistas = {
    "Banyoles": banyoles,
    "Barcelona": barcelona,
    "Tarragona": tarragona,
    "Valencia": valencia,
    "Zaragoza": zaragoza
}

gFirstOffers = Graph()

# Global triplestore graph
dsgraph = Graph()

cola1 = Queue()
global obj
# Flask stuff
app = Flask(__name__)

def run_agent(portx, city):
    @app.route('/')
    def index():
        return f"Agent running on port {portx} in city {city}"

    global port
    port = portx
    global ciutat
    ciutat = city
    global ServeiCentreLogistic
    ServeiCentreLogistic = asignar_port_CentreLogistic(port - 5)
    assignar_port_transportista()
    app.run(host=hostname, port=portx)

def asignar_port_CentreLogistic(port):
    return  Agent('ServeiCentreLogistic',
                               agn.ServeiCentreLogistic,
                               f'http://{hostname}:{port}/comm',
                               f'http://{hostname}:{port}/Stop')

def get_count():
    global mss_cnt
    mss_cnt += 1
    return mss_cnt

def calcular_data(priority):
    if priority == 1:
        return str(datetime.datetime.now() + datetime.timedelta(days=1))
    elif priority == 2:
        return str(datetime.datetime.now() + datetime.timedelta(days=random.randint(3, 5)))
    return str(datetime.datetime.now() + datetime.timedelta(days=random.randint(5, 10)))


def calcular_distancia( city):
    geolocator = Nominatim(user_agent='myapplication')
    location = geolocator.geocode(city)
    location = (location.latitude, location.longitude)
    location_bany = (42.1167, 2.7667)
    location_bcn = (41.3825, 2.1769)
    location_ta = (41.1189, 1.2445)
    location_val = (39.4699, -0.3763)
    location_zar = (41.6488, -0.8891)
    if ciutat == "Banyoles":
        return great_circle(location_bany, location).km
    elif ciutat == "Barcelona":
        return great_circle(location_bcn, location).km
    elif ciutat == "Tarragona":
        return great_circle(location_ta, location).km
    elif ciutat == "Valencia":
        return great_circle(location_val, location).km
    elif ciutat == "Zaragoza":
        return great_circle(location_zar, location).km

@app.route("/comm")
def communication():
    """
    Communication Entrypoint
    """
    message = request.args['content']
    gm = Graph()
    gm.parse(data=message, format='xml')

    msgdic = get_message_properties(gm)
    global gFirstOffers

    gr = Graph()
    if msgdic is None:
        # Si no es, respondemos que no hemos entendido el mensaje
        gr = build_message(Graph(), ACL['not-understood'], sender=AgTransportista.uri, msgcnt=get_count())
    else:
        # Obtenemos la performativa
        if msgdic['performative'] != ACL.request:
            # Si no es un request, respondemos que no hemos entendido el mensaje
            gr = build_message(Graph(),
                               ACL['not-understood'],
                               sender=AgTransportista.uri,
                               msgcnt=get_count())
        else:
            content = msgdic['content']
            # Averiguamos el tipo de la accion
            accion = gm.value(subject=content, predicate=RDF.type)
            peso_total = 0
            city = ""
            priority = 0.0

            if accion == ONTO.EnviarCondicionsEnviament:
                for s, p, o in gm:
                    if p == ONTO.Pes:
                        peso_total = float(o)
                    elif p == ONTO.Ciutat:
                        city = str(o)
                    elif p == ONTO.Prioritat:
                        priority = int(o)


                transportistes = llista_transportistas[ciutat]

                action = ONTO["EnviarCondicionsEnviament_" + str(get_count())]
                gr.add((accion, RDF.type, ONTO.EnviarCondicionsEnviament))
                for t in transportistes:

                    oferta = ONTO["Oferta_" + str(get_count())]
                    gr.add((action, ONTO.Oferta, oferta))
                    gr.add((oferta, RDF.type, ONTO.Oferta))
                    transportista = ONTO[t[0]]
                    gr.add((oferta, ONTO.Transportista, transportista))
                    gr.add((transportista, ONTO.Nom, Literal(t[1])))
                    distancia = calcular_distancia(city)
                    preu_transport = (t[2] * (peso_total/1000) + distancia * t[3]) * random.uniform(0.8,1.2)
                    logger.info("Transportista " + t[1] + " ofrece un precio de " + str(preu_transport) + "€")
                    gr.add((oferta, ONTO.Preu, Literal(preu_transport)))
                    data = calcular_data(priority)
                    gr.add((oferta, ONTO.Data, Literal(data)))

                return gr.serialize(format="xml"), 200

            elif accion == ONTO.EnviarContraoferta:
                print("Entra en enviar contraoferta")
                action = ONTO["EnviarContraoferta_" + str(get_count())]
                gr.add((action, RDF.type, ONTO.EnviarContraoferta))

                preu_contraoferta = 0
                transportista = ""
                preu_ultim = 0
                for s, p, o in gm:
                    if p == ONTO.Preu:
                        preu_contraoferta = float(o)
                    elif p == ONTO.Transportista:
                        transportista = str(gm.value(subject=o, predicate=ONTO.Nom))
                    elif p == ONTO.UltimPreu:
                        preu_ultim = float(o)
                trobat = False
                print(preu_contraoferta)
                print(preu_ultim)
                for t in llista_transportistas[ciutat]:
                    if t[1] == transportista:
                        trobat = True
                        marge = t[4]
                        print(marge)
                        if preu_contraoferta <= preu_ultim * (1-marge):
                            nou_marge = marge * random.uniform(0.8, 1.2)
                            print("nou marge: " + str(nou_marge))
                            nou_preu = preu_ultim * (1 - (nou_marge))
                            gr.add((action, ONTO.RebutjarOferta, Literal(True)))
                            gr.add((action, ONTO.Preu, Literal(nou_preu)))

                        else:
                            gr.add((action, ONTO.AcceptarContraoferta, Literal(True)))
                            gr.add((action, ONTO.Preu, Literal(preu_contraoferta)))
                print(trobat)
                return gr.serialize(format="xml"), 200

            elif accion == ONTO.EnviarPaquet:
                c = ""
                obj = ""
                for s, p, o in gm:
                    if p == ONTO.Lot:
                        obj = str(o)
                    elif p == ONTO.Ciutat:
                        c = str(o)
                logger.info("El transportista " + " ha recogido el paquete " + obj)
                g = Graph()
                return g.serialize(format='xml'), 200



@app.route("/Stop")
def stop():
    """
    Entrypoint que para el agente

    :return:
    """
    tidyup()
    shutdown_server()
    return "Parando Servidor"


def tidyup():
    """
    Acciones previas a parar el agente

    """
    pass


def agentbehavior1(cola):
    """
    Un comportamiento del agente

    :return:
    """
    pass


if __name__ == '__main__':
    ports_cities = {
        8019: 'Banyoles',
        8020: 'Barcelona',
        8021: 'Tarragona',
        8022: 'Valencia',
        8023: 'Zaragoza'
    }

    processes = []

    for port, city in ports_cities.items():
        p = multiprocessing.Process(target=run_agent, args=(port, city))
        processes.append(p)
        p.start()

    for p in processes:
        p.join()
