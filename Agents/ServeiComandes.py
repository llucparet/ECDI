# -*- coding: utf-8 -*-
import socket
import time
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
port = 8012

agn = Namespace("http://www.agentes.org#")

# Contador de mensajes
mss_cnt = 0
endpoint_url = "http://localhost:3030/ONTO/query"

fuseki_url = 'http://localhost:3030/ONTO/data'

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

cola1 = Queue()

# Flask stuff
app = Flask(__name__)




productes_centre1 = []
productes_centre2 = []
productes_centre3 = []
productes_centre4 = []
productes_centre5 = []

def get_count():
    global mss_cnt
    mss_cnt += 1
    return mss_cnt


def obtener_coordenadas(ciudad, retries=3, delay=2):
    """
    Obtiene las coordenadas (latitud y longitud) de una ciudad utilizando el servicio Nominatim de OpenStreetMap.
    Reintenta la solicitud en caso de fallo hasta 'retries' veces con un retraso de 'delay' segundos entre intentos.
    """
    geolocator = Nominatim(user_agent="myapplication")
    attempt = 0

    while attempt < retries:
        try:
            location = geolocator.geocode(ciudad, timeout=10)
            if location:
                return (location.latitude, location.longitude)
            else:
                return None
        except Exception as e:
            print(f"Error obteniendo coordenadas de {ciudad}: {e}")
            attempt += 1
            time.sleep(delay)

    return None


def centro_logistico_mas_cercano(ciudades_centros, coordenadas_destino):
    """
    Encuentra el centro logístico más cercano a la ciudad de destino.
    """

    if not coordenadas_destino:
        print(f"No se pudieron obtener las coordenadas de la ciudad destino:")
        return None

    distancia_minima = float('inf')
    centro_mas_cercano = None

    for ciudad_centro in ciudades_centros:
        location_bany = (42.1167, 2.7667)
        location_bcn = (41.3825, 2.1769)
        location_ta = (41.1189, 1.2445)
        location_val = (39.4699, -0.3763)
        location_zar = (41.6488, -0.8891)
        if ciudad_centro == "Banyoles":
            coordenadas_centro = location_bany
        elif ciudad_centro == "Barcelona":
            coordenadas_centro = location_bcn
        elif ciudad_centro == "Tarragona":
            coordenadas_centro = location_ta
        elif ciudad_centro == "Valencia":
            coordenadas_centro = location_val
        elif ciudad_centro == "Zaragoza":
           coordenadas_centro = location_zar

        if coordenadas_centro:
            distancia = geodesic(coordenadas_destino, coordenadas_centro).kilometers
            if distancia < distancia_minima:
                distancia_minima = distancia
                centro_mas_cercano = ciudad_centro

    return centro_mas_cercano


def registrar_comanda(id, ciutat, client, preu_total, prioritat, credit_card, products):
    comanda = URIRef(ONTO[id])
    g_comanda = Graph()
    g_comanda.bind("ns", ONTO)

    g_comanda.add((comanda, RDF.type, ONTO.Comanda))
    g_comanda.add((comanda, ONTO.ID, Literal(id, datatype=XSD.string)))
    g_comanda.add((comanda, ONTO.Ciutat, Literal(ciutat, datatype=XSD.string)))
    g_comanda.add((comanda, ONTO.Client, URIRef(client)))
    g_comanda.add((comanda, ONTO.PreuTotal, Literal(preu_total, datatype=XSD.float)))
    g_comanda.add((comanda, ONTO.Prioritat, Literal(prioritat, datatype=XSD.integer)))
    g_comanda.add((comanda, ONTO.TargetaCredit, Literal(credit_card, datatype=XSD.string)))

    for producte in products:
        producte_comanda_id = f"{id}_ProducteComanda_{producte["ID"]}"
        producte_comanda_uri = URIRef(ONTO[producte_comanda_id])

        g_comanda.add((producte_comanda_uri, RDF.type, ONTO.ProducteComanda))
        g_comanda.add((producte_comanda_uri, ONTO.Nom, Literal(producte['Nom'], datatype=XSD.string)))
        g_comanda.add((producte_comanda_uri, ONTO.Preu, Literal(producte['Preu'], datatype=XSD.float)))
        g_comanda.add((producte_comanda_uri, ONTO.Data,
                       Literal(producte.get('Data', datetime(1970, 1, 1).date()), datatype=XSD.date)))
        g_comanda.add((producte_comanda_uri, ONTO.Pagat, Literal(producte.get('Pagat', False), datatype=XSD.boolean)))
        g_comanda.add((producte_comanda_uri, ONTO.Enviat, Literal(producte.get('Enviat', False), datatype=XSD.boolean)))
        g_comanda.add((producte_comanda_uri, ONTO.TransportistaProducte,
                       Literal(producte.get('Transportista', ""), datatype=XSD.string)))
        g_comanda.add((producte_comanda_uri, ONTO.Empresa, Literal(producte['Empresa'], datatype=XSD.string)))
        g_comanda.add((comanda, ONTO.ProductesComanda, producte_comanda_uri))

    # Serializar el grafo a formato RDF/XML
    rdf_xml_data_comanda = g_comanda.serialize(format='xml')
    fuseki_url = 'http://localhost:3030/ONTO/data'  # Asegúrate de tener la URL correcta

    # Cabeceras para la solicitud
    headers = {
        'Content-Type': 'application/rdf+xml'
    }

    # Enviamos los datos a Fuseki
    response = requests.post(fuseki_url, data=rdf_xml_data_comanda, headers=headers)

    # Verificamos la respuesta
    if response.status_code == 200:
        print('Comanda registrada exitosamente en Fuseki')
    else:
        print(f'Error al registrar la comanda en Fuseki: {response.status_code} - {response.text}')

    return g_comanda


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
            llista_productes_externs = []
            print(accion)
            # Accion de hacer pedido
            if accion == ONTO.ComprarProductes:
                preu_total = 0
                actionresposta = ONTO['EnviarRespostaTemptativa' + str(get_count())]
                gr.add((actionresposta, RDF.type, ONTO.EnviarRespostaTemptativa))
                comanda_id = 'Comanda' + str(get_count())
                comanda = ONTO[comanda_id]
                print(comanda)
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
                        empresa = str(gm.value(o, ONTO.Empresa))
                        if empresa == "ECDI":
                            llista_productes.append(o)
                        else:
                            producte_extern = {
                                'ID': o.split("/")[-1],
                                'Nom': str(gm.value(o, ONTO.Nom)),
                                'Preu': float(gm.value(o, ONTO.Preu)),
                                'DataEntrega': datetime(1970, 1, 1).date(),
                                'Pagat': False,
                                'Enviat': False,
                                'Transportista': "",
                                'Empresa': empresa
                            }
                            llista_productes_externs.append(producte_extern)

                        gr.add((comanda, ONTO.ProductesComanda, o))
                        preu = float(gm.value(o, ONTO.Preu))
                        preu_total += preu

                ab1 = Process(target=agentbehavior1,
                              args=(cola1, comanda_id, llista_productes, llista_productes_externs, ciutat, priority, creditcard, dni,comanda, gm,preu_total))
                ab1.start()
                print(preu_total)
                gr.add((comanda, ONTO.PreuTotal, Literal(preu_total, datatype=XSD.float)))
                return gr.serialize(format='xml'), 200


def agentbehavior1(cola, comanda_id, llista_productes,llista_productes_externs, ciutat, priority, creditcard, dni,comanda, gm,preu_total):
    products = []
    coordenadas_destino = obtener_coordenadas(ciutat)
    for producte in llista_productes:
        preu = float(gm.value(producte, ONTO.Preu))
        nom = str(gm.value(producte, ONTO.Nom))

        # Asignar valores por defecto ya que no se envían en gm
        pagat = False
        enviat = False
        transportista = ""
        # La fecha de entrega no se debe leer de los datos RDF, la inicializamos a una fecha por defecto
        data_entrega = datetime(1970, 1, 1).date()

        products.append({
            'ID': producte.split("/")[-1],
            'Nom': nom,
            'Preu': preu,
            'DataEntrega': data_entrega,
            'Pagat': pagat,
            'Enviat': enviat,
            'Transportista': transportista,
            'Empresa': 'ECDI'
        })

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
        city = centro_logistico_mas_cercano(centres_logistics, coordenadas_destino)
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

    products.extend(llista_productes_externs)

    registrar_comanda(comanda_id, ciutat, client, preu_total, priority, creditcard, products)

    comandos = []
    if len(productes_centre1) > 0:
        comandos.append((productes_centre1, 8014))
    if len(productes_centre2) > 0:
        comandos.append((productes_centre2, 8015))
    if len(productes_centre3) > 0:
        comandos.append((productes_centre3, 8016))
    if len(productes_centre4) > 0:
        comandos.append((productes_centre4, 8017))
    if len(productes_centre5) > 0:
        comandos.append((productes_centre5, 8018))

    queue = Queue()
    processes = []

    for productes, centre_id in comandos:
        p = Process(target=enviar_comanda,
                    args=(productes, centre_id, ciutat, priority, creditcard, client, comanda, gm, queue))
        processes.append(p)
        p.start()

    for p in processes:
        p.join()

    while not queue.empty():
        print(queue.get())

    productes_centre1.clear()
    productes_centre2.clear()
    productes_centre3.clear()
    productes_centre4.clear()
    productes_centre5.clear()

def enviar_comanda(productes, centre_id, ciutat, priority, creditcard, client, comanda, gm, queue):
    pr = comanda_a_centre_logistic(productes, centre_id, ciutat, priority, creditcard, client, comanda, gm)
    queue.put(pr)
def comanda_a_centre_logistic(productes, portcentrelogistic,ciutat,priority, creditcard, client,comanda,gm):
    """
    Envia una comanda a un centre logístico.
    """

    gr = Graph()
    acction = ONTO['ProcessarEnviament' + str(get_count())]
    gr.add((acction, RDF.type, ONTO.ProcessarEnviament))
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
    logger.info("Enviament processat")
    return preu


# AgServicioPago ens avisa que ja ha realitzat el cobro i aixi podem realitzar la valoracio


if __name__ == '__main__':
    # Ponemos en marcha el servidor
    app.run(host=hostname, port=port)
