# -*- coding: utf-8 -*-
"""
Agente Gestor de Compra.
Tiene una funcion AgentBehavior1 que se lanza como un thread concurrente

Esqueleto de agente usando los servicios web de Flask

/comm es la entrada para la recepcion de mensajes del agente
/Stop es la entrada que para el agente

@author: pau-laia-anna
"""

import socket
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
port = 8012

agn = Namespace("http://www.agentes.org#")

# Contador de mensajes
mss_cnt = 0
endpoint_url = "http://localhost:3030/ONTO/query"

ServeiComanda = Agent('ServeiComanda',
                      agn.ServeiComanda,
                      'http://%s:%d/comm' % (hostname, port),
                      'http://%s:%d/Stop' % (hostname, port))

AgentAssistent = Agent('AgentAssistent',
                       agn.AgentAssistent,
                       'http://%s:9011/comm' % hostname,
                       'http://%s:9011/Stop' % hostname)

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

graph_compra = Graph()
precio_total_compra = 0.0
ultima_compra = Graph()

productes_centre1 = []
productes_centre2 = []
productes_centre3 = []
productes_centre4 = []
productes_centre5 = []


def get_count():
    global mss_cnt
    mss_cnt += 1
    return mss_cnt


def obtener_coordenadas(ciudad):
    """
    Obtiene las coordenadas (latitud y longitud) de una ciudad utilizando el servicio Nominatim de OpenStreetMap.
    """
    geolocator = Nominatim(user_agent="myapplication")
    location = geolocator.geocode(ciudad)
    if location:
        return (location.latitude, location.longitude)
    else:
        return None


def centro_logistico_mas_cercano(ciudades_centros, ciudad_destino):
    """
    Encuentra el centro logístico más cercano a la ciudad de destino.
    """
    coordenadas_destino = obtener_coordenadas(ciudad_destino)

    if not coordenadas_destino:
        print(f"No se pudieron obtener las coordenadas de la ciudad destino: {ciudad_destino}")
        return None

    distancia_minima = float('inf')
    centro_mas_cercano = None

    for ciudad_centro in ciudades_centros:
        coordenadas_centro = obtener_coordenadas(ciudad_centro)
        if coordenadas_centro:
            distancia = geodesic(coordenadas_destino, coordenadas_centro).kilometers
            if distancia < distancia_minima:
                distancia_minima = distancia
                centro_mas_cercano = ciudad_centro

    return centro_mas_cercano

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
            if accion == ONTO.ComprarProductes:
                preu_total = 0
                actionresposta = ONTO['EnviarRespostaTemptativa' + str(get_count())]
                gr.add((actionresposta, RDF.type, ONTO.EnviarRespostaTemptativa))
                comanda = ONTO['Comanda' + str(get_count())]
                gr.add((comanda, RDF.type, ONTO.Comanda))
                gr.add((actionresposta, ONTO.ComandaRespostaTemptativa, comanda))
                ciutat = ""
                priority = 0
                creditcard = ""
                dni = ""
                i = 0
                for s, p, o in gm:
                    if p == ONTO.Prioritat:
                        gr.add((comanda, ONTO.Prioritat, Literal(o)))
                        priority = o
                    if p == ONTO.Ciutat:
                        gr.add((actionresposta, ONTO.Ciutat, Literal(o)))
                        ciutat = o
                    if p == ONTO.TargetaCredit:
                        gr.add((comanda, ONTO.TargetaCredit, Literal(o)))
                        creditcard = o
                        print(o)
                    if p == ONTO.DNI:
                        gr.add((comanda, ONTO.DNI, Literal(o)))
                        dni = o
                    if p == ONTO.Compra:
                        llista_productes.append(o)
                        gr.add((comanda, ONTO.ProductesComanda, o))
                        preu = float(gm.value(o, ONTO.Preu))
                        preu_total += preu

                ab1 = Process(target=agentbehavior1, args=(cola1, llista_productes, ciutat, priority, creditcard,dni,gm))
                ab1.start()
                print(preu_total)
                gr.add((comanda, ONTO.PreuTotal, Literal(preu_total, datatype=XSD.float)))
                return gr.serialize(format='xml'), 200


def agentbehavior1(cola, llista_productes, ciutat, priority, creditcard, dni,gm):

    for producte in llista_productes:
        value = "".join(f"<{producte}> ")
        # Consulta SPARQL
        sparql_query = f"""
           PREFIX rdf: <http://www.w3.org/1999/02/22-rdf-syntax-ns#>
           PREFIX ont: <http://www.semanticweb.org/nilde/ontologies/2024/4/>
           SELECT ?ciutat 
           WHERE {{
                ?producte rdf:type ont:Producte .
                 ?producte ont:ProductesCentreLogistic ?centreLogistic .
                 ?centreLogistic ont:Ciutat ?ciutat .
                 VALUES ?producte {{{value}}}
           }}
          """

        print(producte)
        print(sparql_query)
        # Crear el objeto SPARQLWrapper y establecer la consulta
        sparql = SPARQLWrapper(endpoint_url)
        sparql.setQuery(sparql_query)
        sparql.setReturnFormat(JSON)
        results = sparql.query().convert()
        centres_logistics = []
        for result in results["results"]["bindings"]:
            centres_logistics.append(result["ciutat"]["value"])
        city = centro_logistico_mas_cercano(centres_logistics, ciutat)
        if city == "Banyoles":
            productes_centre1.append(producte)
        elif city == "Barcelona":
            productes_centre2.append(producte)
        elif city == "Tarragona":
            productes_centre3.append(producte)
        elif city == "Valencia":
            productes_centre4.append(producte)
        elif city == "Zaragoza":
            productes_centre5.append(producte)
        print(productes_centre1)
        print(productes_centre2)
        print(productes_centre3)
        print(productes_centre4)
        print(productes_centre5)
        print(dni)
    sparql_query = f"""
                    PREFIX rdf: <http://www.w3.org/1999/02/22-rdf-syntax-ns#>
                    PREFIX ont: <http://www.semanticweb.org/nilde/ontologies/2024/4/>
                    SELECT ?client
                    WHERE {{
                        ?client rdf:type ont:Client .
                        ?client ont:DNI "{dni}" .
                      }}
                  """

    print(sparql_query)
    # Crear el objeto SPARQLWrapper y establecer la consulta
    sparql = SPARQLWrapper(endpoint_url)
    sparql.setQuery(sparql_query)
    sparql.setReturnFormat(JSON)
    results = sparql.query().convert()
    print(results["results"]["bindings"])
    client_result = results["results"]["bindings"][0]
    client = client_result["client"]["value"]
    print(client)
    if len(productes_centre1) > 0:
        comanda_a_centre_logistic(productes_centre1,8014,ciutat,priority, creditcard, client,gm)
        print("hola")
    if len(productes_centre2) > 0:
        comanda_a_centre_logistic(productes_centre2, 8015,ciutat,priority, creditcard, client,gm)
        print("hola")
    if len(productes_centre3) > 0:
        comanda_a_centre_logistic(productes_centre3, 8016,ciutat,priority, creditcard, client,gm)
        print("hola")
    if len(productes_centre4) > 0:
        comanda_a_centre_logistic(productes_centre4, 8017,ciutat,priority, creditcard, client,gm)
        print("hola")
    if len(productes_centre5) > 0:
        comanda_a_centre_logistic(productes_centre5, 8018,ciutat,priority, creditcard, client,gm)
        print("hola")

    productes_centre1.clear()
    productes_centre2.clear()
    productes_centre3.clear()
    productes_centre4.clear()
    productes_centre5.clear()


def comanda_a_centre_logistic(productes, portcentrelogistic,ciutat,priority, creditcard, client,gm):
    """
    Envia una comanda a un centre logístico.
    """

    gr = Graph()
    acction = ONTO['ProcessarEnviament' + str(get_count())]
    gr.add((acction, RDF.type, ONTO.ProcessarEnviament))
    comanda = ONTO['Comanda' + str(get_count())]
    gr.add((comanda, RDF.type, ONTO.Comanda))
    gr.add((comanda, ONTO.Ciutat, Literal(ciutat)))
    gr.add((comanda, ONTO.Prioritat, Literal(priority)))
    gr.add((comanda, ONTO.TargetaCredit, Literal(creditcard)))
    for producte in productes:
        nom = gm.value(producte, ONTO.Nom)
        preu = gm.value(producte, ONTO.Preu)
        pes = gm.value(producte, ONTO.Pes)
        gr.add((producte, RDF.type, ONTO.Producte))
        gr.add((producte, ONTO.Nom, Literal(nom)))
        gr.add((producte, ONTO.Preu, Literal(preu)))
        gr.add((producte, ONTO.Pes, Literal(pes)))
        gr.add((comanda, ONTO.ProductesComanda, producte))
    gr.add((comanda, ONTO.ClientComanda, URIRef(client)))

    gr.add((acction, ONTO.Processa, comanda))
    ServeiCentreLogistic = asignar_port_centre_logistic(portcentrelogistic)

    msg = build_message(gr, ACL.request, ServeiCentreLogistic.uri, ServeiCentreLogistic.uri, acction, get_count())
    resposta = send_message(msg, ServeiCentreLogistic.address)
    preu = 0
    for s, p, o in resposta:
        if p == ONTO.Preu:
            preu = o
    print(preu)


# AgServicioPago ens avisa que ja ha realitzat el cobro i aixi podem realitzar la valoracio


if __name__ == '__main__':
    # Ponemos en marcha el servidor
    app.run(host=hostname, port=port)
