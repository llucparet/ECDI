import argparse
import socket
import sys
import os
sys.path.insert(0, os.path.abspath('../'))
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
import requests

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

# Configuration stuff
if args.port is None:
    port = 8000
else:
    port = args.port

if args.open is None:
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

# Agent Namespace
agn = Namespace("http://www.agentes.org#")

# Message Count
mss_cnt = 0

# Data Agent

ServeiEntrega = Agent('ServeiEntrega',
                      agn.ServeiEntrega,
                      'http://%s:%d/comm' % (hostname, port),
                      'http://%s:%d/Stop' % (hostname, port))


# Directory agent address
DirectoryAgent = Agent('DirectoryAgent',
                       agn.Directory,
                       'http://%s:%d/Register' % (dhostname, dport),
                       'http://%s:%d/Stop' % (dhostname, dport))
endpoint_url = f"http://{dhostname}:3030/ONTO/query"


# Global triplestore graph
dsgraph = Graph()

queue = Queue()

# Flask stuff
app = Flask(__name__)

def get_count():
    global mss_cnt
    mss_cnt += 1
    return mss_cnt

def registrar_transaccio(pagador, cobrador, producte, preu):
    g = Graph()
    accio = ONTO['Transaccio_' + str(get_count())]
    g.add((accio, RDF.type, ONTO.Transaccio))
    g.add((accio, ONTO.Pagador, Literal(pagador)))
    g.add((accio, ONTO.Cobrador, Literal(cobrador)))
    g.add((accio, ONTO.Producte, Literal(producte)))
    g.add((accio, ONTO.Preu, Literal(preu)))

    # Serializar el grafo a formato RDF/XML
    rdf_xml_data_comanda = g.serialize(format='xml')
    fuseki_url = f'http://{dhostname}:3030/ONTO/data'  # Asegúrate de tener la URL correcta

    # Cabeceras para la solicitud
    headers = {
        'Content-Type': 'application/rdf+xml'
    }

    # Enviamos los datos a Fuseki
    response = requests.post(fuseki_url, data=rdf_xml_data_comanda, headers=headers)

    # Verificamos la respuesta
    if response.status_code == 200:
        print('transaccio registrada exitosamente en Fuseki')
    else:
        print(f'Error al registrar la transaccio en Fuseki: {response.status_code} - {response.text}')


@app.route("/comm", methods=['GET', 'POST'])
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
        gr = build_message(Graph(), ACL['not-understood'], sender=ServeiEntrega.uri, msgcnt=get_count())

    else:
        # Obtenemos la performativa
        if msgdic['performative'] != ACL.request:
            # Si no es un request, respondemos que no hemos entendido el mensaje
            gr = build_message(Graph(),
                               ACL['not-understood'],
                               sender=ServeiEntrega.uri,
                               msgcnt=get_count())

        else:

            content = msgdic['content']

            accion = gm.value(subject=content, predicate=RDF.type)
            print(accion)
            count = get_count()

            # Acción de pagar usuario
            if accion == ONTO.PagarUsuari:
                print("Pagar Usuari")

                client = ""
                import_producte = ""
                producte_comanda = ""

                for s, p, o in gm:
                    if p == ONTO.Desti:
                        client = o
                    elif p == ONTO.Import:
                        import_producte = o
                    elif p == ONTO.ProducteComanda:
                        producte_comanda = o

                print(f"Client: {client}, Import: {import_producte}, ProducteComanda: {producte_comanda}")

                # Registrar transacción de devolución
                registrar_transaccio("ECDI", client, f"Devolució producte {producte_comanda}", import_producte)

                # Enviar la acción PagarUsuari al AgentPagament
                g_pago = Graph()
                accion_pago = ONTO["PagarUsuari_" + str(get_count())]
                g_pago.add((accion_pago, RDF.type, ONTO.PagarUsuari))
                g_pago.add((accion_pago, ONTO.Desti, client))
                g_pago.add((accion_pago, ONTO.Import, import_producte))
                g_pago.add((accion_pago, ONTO.ProducteComanda, producte_comanda))

                agent_pagaent = getAgentInfo(agn.AgentPagament, DirectoryAgent, ServeiEntrega, get_count())
                msg_pago = build_message(g_pago, ACL.request, ServeiEntrega.uri, agent_pagaent.uri, accion_pago,
                                         get_count())
                send_message(msg_pago, agent_pagaent.address)

                # Responder con éxito
                gr = build_message(gr, ACL.inform, sender=ServeiEntrega.uri, msgcnt=get_count())
                return gr.serialize(format='xml'), 200

            # Accion de hacer pedido
            elif accion == ONTO.InformarEnviament:

                print("Enviament informat")
                #aqui em retorna el dni de l'usuari i gurdo la comanda
                llista_porductes = []

                dni = ""
                comanda = ""
                data = ""
                transportista = ""
                gg = Graph()
                for s, p, o in gm:
                    if p == ONTO.DNI:
                        dni = o
                    elif p == ONTO.ComandaLot:
                        comanda = o
                    elif p == ONTO.ProducteLot:
                        llista_porductes.append(o)
                    elif p == ONTO.Data:
                        data = o
                        gr.add((accion, ONTO.Data, o))
                    elif p == ONTO.Transportista:
                        transportista = gm.value(subject=o, predicate=ONTO.Nom)
                        gr.add((accion, ONTO.Transportista, o))
                    elif p == ONTO.Preu:
                        gg.add((accion, ONTO.Preu, o))
                gr.add((accion, RDF.type, ONTO.InformarEnviament))

                print("Enviament informat2")
                print(llista_porductes)
                print(comanda)
                print(data)
                print(transportista)
                print(dni)

                for producte in llista_porductes:
                    print("Enviament informat3")
                    # Construir les consultes SPARQL

                    sparql_query = f"""
                                        PREFIX rdf: <http://www.w3.org/1999/02/22-rdf-syntax-ns#>
                                        PREFIX ont: <http://www.semanticweb.org/nilde/ontologies/2024/4/>
                                        SELECT ?nom
                                        WHERE {{
                                            ?producte rdf:type ont:Producte .
                                            VALUES ?producte {{ <{producte}> }}
                                            ?producte ont:Nom ?nom .
                                          }}
                                      """

                    print(sparql_query)
                    # Crear el objeto SPARQLWrapper y establecer la consulta
                    sparql = SPARQLWrapper(endpoint_url)
                    sparql.setQuery(sparql_query)
                    sparql.setReturnFormat(JSON)
                    results = sparql.query().convert()
                    print(results["results"]["bindings"])
                    producte_result= results["results"]["bindings"][0]
                    nom_producte = producte_result["nom"]["value"]
                    print(nom_producte)
                    gr.add((producte, ONTO.Nom, Literal(nom_producte)))

                    fuseki_url = f'http://{dhostname}:3030/ONTO/update'


                    # Defineix la consulta SPARQL amb les variables
                    sparql_query = f"""
                    PREFIX ontologies: <http://www.semanticweb.org/nilde/ontologies/2024/4/>
                    PREFIX xsd: <http://www.w3.org/2001/XMLSchema#>

                    DELETE {{
                        ?producteComanda ontologies:Data ?oldData .
                        ?producteComanda ontologies:Enviat ?oldPagat .
                        ?producteComanda ontologies:TransportistaProducte ?oldTransportista .
                    }}
                    INSERT {{
                        ?producteComanda ontologies:Data "{data}"^^xsd:date .
                        ?producteComanda ontologies:Enviat true .
                        ?producteComanda ontologies:TransportistaProducte "{transportista}" .
                    }}
                    WHERE {{
                        <{comanda}> ontologies:ProductesComanda ?producteComanda .
                        ?producteComanda ontologies:Nom "{nom_producte}" .

                        OPTIONAL {{ ?producteComanda ontologies:Data ?oldData . }}
                        OPTIONAL {{ ?producteComanda ontologies:Enviat ?oldPagat . }}
                        OPTIONAL {{ ?producteComanda ontologies:TransportistaProducte ?oldTransportista . }}
                    }}
                    """

                    # Defineix els encapçalaments HTTP
                    headers = {
                        'Content-Type': 'application/sparql-update'
                    }

                    # Envia la sol·licitud POST al servidor Fuseki
                    response = requests.post(fuseki_url, data=sparql_query, headers=headers)

                    # Mostra la resposta
                    if response.status_code == 204:
                        print("Consulta SPARQL executada correctament.")
                    else:
                        print(f"Error en executar la consulta SPARQL: {response.status_code}")
                        print(response.text)

                agent_assistent = getAgentInfo(agn.AgentAssistent, DirectoryAgent, ServeiEntrega, get_count())
                msg = build_message(gr, ACL.request, ServeiEntrega.uri, agent_assistent.uri, accion,
                                    get_count())
                resposta = send_message(msg, agent_assistent.address)
                return gg.serialize(format="xml"), 200

            elif accion == ONTO.CobrarProductes:
                print("Cobrar productes")
                dni = ""
                comanda = ""
                nom_producte = ""
                preu = ""
                empresa = ""
                g = Graph()
                action = ONTO['CobrarProductes_' + str(get_count())]
                g.add((action, RDF.type, ONTO.CobrarProductes))

                for s, p, o in gm:
                    if p == ONTO.DNI:
                        dni = o
                        g.add((action, ONTO.DNI, o))
                    elif p == ONTO.Comanda:
                        comanda = o
                        g.add((action, ONTO.Comanda, o))
                    elif p == ONTO.Nom:
                        nom_producte = o
                        g.add((action, ONTO.Nom, o))
                    elif p == ONTO.Preu:
                        preu = o
                        g.add((action, ONTO.Preu, o))
                    elif p == ONTO.Empresa:
                        empresa = o
                        g.add((action, ONTO.Empresa, o))
                print(dni)
                print(comanda)
                print(nom_producte)
                print(preu)
                registrar_transaccio(dni,empresa, nom_producte, preu)
                agent_pagament = getAgentInfo(agn.AgentPagament, DirectoryAgent, ServeiEntrega, get_count())
                msg = build_message(g, ACL.request, ServeiEntrega.uri, agent_pagament.uri, action, get_count())

                gresposta = send_message(msg, agent_pagament.address)

                if empresa != "ECDI":
                    g = Graph()
                    action = ONTO['PagarVenedorExtern' + str(get_count())]
                    g.add((action, RDF.type, ONTO.PagarVenedorExtern))
                    agent_pagament = getAgentInfo(agn.AgentPagament, DirectoryAgent, ServeiEntrega, get_count())
                    msg = build_message(g, ACL.request, ServeiEntrega.uri, agent_pagament.uri, action, get_count())
                    gresposta = send_message(msg, agent_pagament.address)

                return gresposta.serialize(format="xml"), 200
            elif accion == ONTO.CobrarProductesVenedorExtern:
                gr.add((accion, RDF.type, ONTO.CobrarProductesVenedorExtern))
                for s, p, o in gm:
                    if p == ONTO.DNI:
                        dni = o
                    elif p == ONTO.Comanda:
                        comanda = o
                    elif p == ONTO.Nom:
                        nom_producte = o
                        gr.add((accion, ONTO.Nom, o))
                    elif p == ONTO.Preu:
                        preu = o
                    elif p == ONTO.Empresa:
                        empresa = o
                        gr.add((accion, ONTO.Empresa, o))

                agent_assistent = getAgentInfo(agn.AgentAssistent, DirectoryAgent, ServeiEntrega, get_count())
                msg = build_message(gr, ACL.request, ServeiEntrega.uri, agent_assistent.uri, accion,
                                    get_count())
                resposta = send_message(msg, agent_assistent.address)

                return resposta.serialize(format="xml"), 200


def EntregaBehavior(queue):

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

    logger.info('Nos registramos')

    gr = registerAgent(ServeiEntrega, DirectoryAgent, ServeiEntrega.uri, get_count(),port)
    return gr
if __name__ == '__main__':
    ab1 = Process(target=EntregaBehavior, args=(queue,))
    ab1.start()

    # Run server
    app.run(host=hostname, port=port, debug=False)

    # Wait behaviors
    ab1.join()
    print('The End')
