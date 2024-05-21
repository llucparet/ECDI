"""
Agente Transportista

Esqueleto de agente usando los servicios web de Flask

/comm es la entrada para la recepcion de mensajes del agente
/Stop es la entrada que para el agente

Tiene una funcion AgentBehavior1 que se lanza como un thread concurrente


@author: pau-laia-anna
"""

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
from Utils.OntoNamespaces import ONTO, FONTO
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
hostname = socket.gethostname()
port = 9015

agn = Namespace("http://www.agentes.org#")

# Contador de mensajes
mss_cnt = 0

# Datos del Agente

AgTransportista = Agent('AgentTransportista',
                        agn.AgTransportista,
                        'http://%s:%d/comm' % (hostname, port),
                        'http://%s:%d/Stop' % (hostname, port))

AgCentroLogistico = Agent('ServeiAssignadorTransportista',
                          agn.Directory,
                          'http://%s:9014/comm' % hostname,
                          'http://%s:9014/Stop' % hostname)

location_ny = (Nominatim(user_agent='myapplication').geocode("New York").latitude,
               Nominatim(user_agent='myapplication').geocode("New York").longitude)
location_bcn = (Nominatim(user_agent='myapplication').geocode("Barcelona").latitude,
                Nominatim(user_agent='myapplication').geocode("Barcelona").longitude)
location_pk = (Nominatim(user_agent='myapplication').geocode("Pekín").latitude,
               Nominatim(user_agent='myapplication').geocode("Pekín").longitude)

# identificador transportista, nombre transportista, €/kg, €/km
ny = [
    ["Transportista_NACEX", "NACEX", 1, 0.012],
    ["Transportista_SEUR", "SEUR", 1.08, 0.008],
    ["Transportista_DHL", "DHL", 1, 0.009],
    ["Transportista_FedEx", "FedEx", 0.9, 0.007]
]

bcn = [
    ["Transportista_SEUR", "SEUR", 1.03, 0.01],
    ["Transportista_DHL", "DHL", 0.95, 0.008]
]

pk = [
    ["Transportista_SEUR", "SEUR", 0.93, 0.009],
    ["Transportista_DHL", "DHL", 1.15, 0.01],
    ["Transportista_FedEx", "FedEx", 1.02, 0.007]
]

gFirstOffers = Graph()

# Global triplestore graph
dsgraph = Graph()

cola1 = Queue()
global obj
obj = ""
# Flask stuff
app = Flask(__name__)


def get_count():
    global mss_cnt
    mss_cnt += 1
    return mss_cnt


def calcular_fecha(priority):
    if priority == 1:
        return str(datetime.datetime.now() + datetime.timedelta(days=1))
    elif priority == 2:
        return str(datetime.datetime.now() + datetime.timedelta(days=random.randint(3, 5)))
    return str(datetime.datetime.now() + datetime.timedelta(days=random.randint(5, 10)))


def calcular_distancia(centro, city):
    geolocator = Nominatim(user_agent='myapplication')
    location = geolocator.geocode(city)
    location = (location.latitude, location.longitude)
    if centro == "Barcelona":
        return great_circle(location_bcn, location).km
    elif centro == "New York":
        return great_circle(location_ny, location).km
    else:
        return great_circle(location_pk, location).km


obj = ""


@app.route("/comm")
def communication():
    """
    Communication Entrypoint
    """
    message = request.args['content']
    gm = Graph()
    gm.parse(data=message)

    msgdic = get_message_properties(gm)
    global gFirstOffers

    gr = None
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
            centro = ""

            if accion == FONTO.EnviarCondicionsEnviament:
                for s, p, o in gm:
                    if p == FONTO.Pes:
                        peso_total = float(o)
                    elif p == FONTO.Ciutat:
                        city = str(o)

                logger.info("Hemos recibido un lote del centro logístico de " + city + " para ser entregado")
                logger.info("Calculamos el precio que cada transportista pide por el envío de este lote")

                # id transoprtista, nombre, fecha prevista y precio
                action = ONTO["PedirPreciosEnvio_" + str(get_count())]
                gOfertas = Graph()
                gOfertas.add((action, RDF.type, ONTO.PedirPreciosEnvio))
                cl = []
                if centro == "Barcelona":
                    global bcn
                    cl = bcn
                elif centro == "New York":
                    global ny
                    cl = ny
                elif centro == "Pekin":
                    global pk
                    cl = pk
                gFirstOffers = Graph()
                for tr in cl:
                    trSuj = ONTO[tr[0]]
                    gOfertas.add((action, ONTO.OfertaDe, trSuj))
                    gOfertas.add((trSuj, RDF.type, ONTO.Transportista))
                    gOfertas.add((trSuj, ONTO.Identificador, Literal(tr[0])))
                    gOfertas.add((trSuj, ONTO.Nombre, Literal(tr[1])))
                    fecha = calcular_fecha(priority)
                    gOfertas.add((trSuj, ONTO.Fecha, Literal(fecha)))
                    dist_fromcentro = calcular_distancia(centro, city)
                    precio_envio = peso_total * tr[2] + dist_fromcentro * tr[3]
                    gOfertas.add((trSuj, ONTO.PrecioTransporte, Literal(precio_envio)))
                    logger.info(
                        "Transportista: " + tr[0] + " / Fecha: " + str(fecha) + " / Precio_envio: " + str(precio_envio))
                gFirstOffers = gOfertas

                for s, p, o in gOfertas:
                    if p == ONTO.Nombre:
                        for s2, p2, o2 in gOfertas:
                            if s == s2 and p == ONTO.PrecioTransporte:
                                logger.info("El transportista " + o + " ofrece un precio de " + str(o2.toPython()))

                return gOfertas.serialize(format="xml"), 200

            elif accion == FONTO.PedirContraofertasPreciosEnvio:
                gFinal = gFirstOffers
                action = FONTO["PedirContraofertasPreciosEnvio_" + str(get_count())]
                gFinal.add((action, RDF.type, ONTO.PedirContraofertasPreciosEnvio))

                for s, p, o in gm:
                    if p == ONTO.PrecioTransporte:
                        contraoferta = o

                logger.info("Hemos recibido una contraoferta del centro logístico")

                transportistas = []
                for s, p, o in gFinal:
                    if p == ONTO.OfertaDe:
                        transportistas.append(o)
                for t in transportistas:
                    offer = gFinal.value(subject=t, predicate=ONTO.PrecioTransporte)
                    if contraoferta.toPython() < 0.75 * offer.toPython():
                        logger.info("El transportista " + t[63:] + " rechaza la contraoferta")
                        gFinal.remove((t, None, None))
                        gFinal.remove((None, None, t))
                    else:
                        segunda_oferta = offer.toPython() * random.uniform(0.80, 0.97)
                        logger.info("El transportista " + t[
                                                          63:] + " acepta la contraoferta y ofrece un segundo precio de envío de " + str(
                            segunda_oferta) + "€")
                        gFinal.set((t, ONTO.PrecioTransporte, Literal(segunda_oferta)))
                return gFinal.serialize(format="xml"), 200

            elif accion == ONTO.EnviarPaquete:
                for s, p, o in gm:
                    if p == ONTO.LoteFinal:
                        obj = str(o)
                proceso = Process(target=entregar_producto, args=())
                proceso.start()
                obj = str(obj)

                logger.info("Pedido entregado")
                g = Graph()
                action = ONTO["CobrarCompra_" + str(get_count())]

                g.add((action, RDF.type, ONTO.CobrarCompra))
                g.add((action, ONTO.LoteEntregado, Literal(obj)))
                p = Process(target=avisar_entrega, args=(g, action))
                p.start()
                return g.serialize(format='xml'), 200

            else:  # CAL??
                grr = Graph()
                return grr.serialize(format="xml"), 200


def avisar_entrega(g=Graph(), action=""):
    time.sleep(3)
    send_message(
        build_message(g, ACL.request, AgTransportista.uri, AgCentroLogistico.uri, action, get_count()),
        AgCentroLogistico.address)


def entregar_producto():
    grr = Graph()
    return grr.serialize(format="xml"), 200


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
    # Ponemos en marcha los behaviors
    ab1 = Process(target=agentbehavior1, args=(cola1,))
    ab1.start()

    # Ponemos en marcha el servidor
    app.run(host=hostname, port=port)

    # Esperamos a que acaben los behaviors
    ab1.join()

    print('The End')
