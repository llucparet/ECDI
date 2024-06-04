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
import os
sys.path.insert(0, os.path.abspath('../'))
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
from Utils.ACLMessages import build_message

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

if args.open:
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
port = None
ciutat = None
# Agent Namespace
agn = Namespace("http://www.agentes.org#")

# Message Count
mss_cnt = 0

# Data Agent

# Directory agent address
DirectoryAgent = Agent('DirectoryAgent',
                       agn.Directory,
                       'http://%s:%d/Register' % (dhostname, dport),
                       'http://%s:%d/Stop' % (dhostname, dport))

AgentTransportista = Agent('AgentTransportista',
                        agn.AgentTransportista,
                        None,
                        None)


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

# Global triplestore graph
dsgraph = Graph()

queue = Queue()
global obj
# Flask stuff
app = Flask(__name__)

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


def obtener_coordenadas(city, retries=3, delay=2):
    """
    Obtiene las coordenadas (latitud y longitud) de una ciudad utilizando el servicio Nominatim de OpenStreetMap.
    Reintenta la solicitud en caso de fallo hasta 'retries' veces con un retraso de 'delay' segundos entre intentos.
    """
    geolocator = Nominatim(user_agent="myapplication")
    attempt = 0

    while attempt < retries:
        try:
            location = geolocator.geocode(city, timeout=10)
            if location:
                return (location.latitude, location.longitude)
            else:
                return None
        except Exception as e:
            print(f"Error obteniendo coordenadas de {city}: {e}")
            attempt += 1
            time.sleep(delay)

    return None


def calcular_distancia(city):
    """
    Calcula la distancia desde una ciudad dada a diferentes ubicaciones predefinidas.
    """
    coordenadas_ciudad = obtener_coordenadas(city)
    time.sleep(1)  # Retraso para cumplir con la restricción de 1 solicitud por segundo

    if not coordenadas_ciudad:
        print(f"No se pudieron obtener las coordenadas de la ciudad: {city}")
        coordenadas_ciudad = (41.3825, 2.1769)

    location_bany = (42.1167, 2.7667)
    location_bcn = (41.3825, 2.1769)
    location_ta = (41.1189, 1.2445)
    location_val = (39.4699, -0.3763)
    location_zar = (41.6488, -0.8891)

    if ciutat == "Banyoles":
        return great_circle(location_bany, coordenadas_ciudad).km
    elif ciutat == "Barcelona":
        return great_circle(location_bcn, coordenadas_ciudad).km
    elif ciutat == "Tarragona":
        return great_circle(location_ta, coordenadas_ciudad).km
    elif ciutat == "Valencia":
        return great_circle(location_val, coordenadas_ciudad).km
    elif ciutat == "Zaragoza":
        return great_circle(location_zar, coordenadas_ciudad).km
    else:
        print("Ciudad no reconocida.")
        return None

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
        gr = build_message(Graph(), ACL['not-understood'], sender=AgentTransportista.uri, msgcnt=get_count())
    else:
        # Obtenemos la performativa
        if msgdic['performative'] != ACL.request:
            # Si no es un request, respondemos que no hemos entendido el mensaje
            gr = build_message(Graph(),
                               ACL['not-understood'],
                               sender=AgentTransportista.uri,
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

            elif accion == ONTO.AssignarTransportista:
                lot = ""
                for s, p, o in gm:
                    if p == ONTO.Lot:
                        lot = str(o)
                    elif p == ONTO.Nom:
                        nom = str(o)
                logger.info(f"El transportista {nom} " + " ha recogido el lot amb id " + lot)
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


def TransportistaBehavior(queue):

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
    global port

    logger.info('Nos registramos')

    gr = registerAgent(AgentTransportista, DirectoryAgent, AgentTransportista.uri, get_count(),port)
    return gr

def run_agent(portx, city):
    @app.route('/')
    def index():
        return f"Agent running on port {portx} in city {city}"

    global port
    port = portx
    global ciutat
    ciutat = city

    AgentTransportista.address = 'http://%s:%d/comm' % (hostname, portx)
    AgentTransportista.uri = 'http://%s:%d/comm' % (hostname, portx)

    ab1 = Process(target=TransportistaBehavior, args=(queue,))
    ab1.start()

    app.run(host=hostname, port=portx)
    ab1.join()

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
