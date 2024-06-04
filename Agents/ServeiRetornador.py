import argparse
import socket
import os
import sys
sys.path.insert(0, os.path.abspath('../'))
from multiprocessing import Queue, Process
from SPARQLWrapper import SPARQLWrapper, JSON
from flask import Flask, request
from rdflib import Graph, Namespace, Literal, RDF, URIRef, XSD
from Utils.ACLMessages import build_message, send_message, get_message_properties, registerAgent, getAgentInfo
from Utils.Agent import Agent
from Utils.FlaskServer import shutdown_server
from Utils.Logger import config_logger
from Utils.OntoNamespaces import ONTO
from Utils.ACL import ACL
import datetime

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
    port = 8030
else:
    port = args.port

if args.open:
        hostname = '0.0.0.0'
        hostaddr = socket.gethostname()
else:
    hostaddr = hostname = socket.gethostname()

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

ServeiRetornador = Agent('ServeiRetornador',
                      agn.ServeiRetornador,
                      f'http://{hostaddr}:{port}/comm',
                      f'http://{hostaddr}:{port}/Stop')

# Directory agent address
DirectoryAgent = Agent('DirectoryAgent',
                       agn.Directory,
                       'http://%s:%d/Register' % (dhostname, dport),
                       'http://%s:%d/Stop' % (dhostname, dport))


# Global triplestore graph
dsgraph = Graph()

queue = Queue()

# Flask stuff
app = Flask(__name__)


def get_count():
    global mss_cnt
    mss_cnt += 1
    return mss_cnt


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
    try:
        gm.parse(data=message, format='xml')
    except Exception as e:
        logger.error(f"Error parsing message: {e}")
        gr = build_message(Graph(), ACL['not-understood'], sender=ServeiRetornador.uri, msgcnt=get_count())
        return gr.serialize(format="xml"), 500

    msgdic = get_message_properties(gm)
    gr = Graph()

    if msgdic is None:
        gr = build_message(Graph(), ACL['not-understood'], sender=ServeiRetornador.uri, msgcnt=get_count())
        print("Message properties not found")
    else:
        performative_uri = URIRef(msgdic['performative'])
        expected_uri = ACL.request
        print(f"Message performative: {performative_uri}")
        print(f"Expected performative: {expected_uri}")

        if performative_uri != expected_uri:
            gr = build_message(Graph(), ACL['not-understood'], sender=ServeiRetornador.uri, msgcnt=get_count())
            print("Message performative not understood")
        else:
            content = msgdic['content']
            accion = gm.value(subject=content, predicate=RDF.type)

            if accion == ONTO.RetornarProducte:
                producte_comanda = gm.value(subject=content, predicate=ONTO.ProducteComanda)
                data_compra = gm.value(subject=content, predicate=ONTO.Data)
                client = gm.value(subject=content, predicate=ONTO.Usuari)
                import_producte = gm.value(subject=content, predicate=ONTO.Preu)
                motiu = gm.value(subject=content, predicate=ONTO.Motiu)

                # Debug prints
                print(f"ProducteComanda: {producte_comanda}")
                print(f"DataCompra: {data_compra}")
                print(f"Client: {client}")
                print(f"ImportProducte: {import_producte}")
                print(f"Motiu: {motiu}")

                if not all([producte_comanda, data_compra, client, import_producte, motiu]):
                    logger.error("Missing data in the message.")
                    gr = build_message(Graph(), ACL['not-understood'], sender=ServeiRetornador.uri, msgcnt=get_count())
                    return gr.serialize(format="xml"), 400

                # Verificar si la devolución es válida
                fecha_compra = datetime.datetime.strptime(str(data_compra), '%Y-%m-%d')
                dias_pasados = (datetime.datetime.now() - fecha_compra).days
                print(f"Días pasados desde la compra: {dias_pasados}")

                # Convertir el valor de motiu a string y eliminar espacios adicionales
                motiuN = str(motiu).strip()
                print(f"Motiu (trimmed): {motiuN}")

                # Considerar cualquier valor negativo como menor que 15 o 30
                if (motiuN == "No se satisfan les expectatives del producte" and dias_pasados <= 15) or \
                   (motiuN in ["El producte és defectuós", "El producte és erroni"] and dias_pasados <= 30):
                    resolucio = "Retornat"
                    print("Devolución válida")

                    # Agregar detalles del transportista y fecha de recogida
                    transportista = "Devolvedor"
                    fecha_recogida = datetime.datetime.now() + datetime.timedelta(days=5)
                    fecha_recogida_str = fecha_recogida.strftime('%Y-%m-%d')

                    gr.add((content, ONTO.Transportista, Literal(transportista)))
                    gr.add((content, ONTO.DataRecogida, Literal(fecha_recogida_str, datatype=XSD.date)))

                    # Informar al ServeiEntrega para realizar el pago
                    g_pago = Graph()
                    accion_pago = ONTO["PagarUsuari_" + str(get_count())]
                    g_pago.add((accion_pago, RDF.type, ONTO.PagarUsuari))
                    g_pago.add((accion_pago, ONTO.Desti, client))
                    g_pago.add((accion_pago, ONTO.Import, import_producte))
                    g_pago.add((accion_pago, ONTO.ProducteComanda, producte_comanda))

                    servei_entrega = getAgentInfo(agn.ServeiEntrega, DirectoryAgent, ServeiRetornador, get_count())
                    msg_pago = build_message(g_pago, ACL.request, ServeiRetornador.uri, servei_entrega.uri, accion_pago,
                                             get_count())
                    send_message(msg_pago, servei_entrega.address)

                else:
                    resolucio = "Rebutjat"
                    print("Devolución no válida")

                # Crear respuesta
                gr.add((content, RDF.type, ONTO.RetornarProducte))
                gr.add((content, ONTO.Resolucio, Literal(resolucio)))
                gr.add((content, ONTO.ProducteComanda, producte_comanda))
                gr.add((content, ONTO.Motiu, motiu))

                # Actualizar el estado de Retornat en Fuseki
                update_sparql = f"""
                PREFIX rdf: <http://www.w3.org/1999/02/22-rdf-syntax-ns#>
                PREFIX ont: <http://www.semanticweb.org/nilde/ontologies/2024/4/>

                DELETE {{
                    <{producte_comanda}> ont:Retornat ?oldState .
                }}
                INSERT {{
                    <{producte_comanda}> ont:Retornat "{resolucio}" .
                }}
                WHERE {{
                    <{producte_comanda}> ont:Retornat ?oldState .
                }}
                """

                print(f"SPARQL Update Query:\n{update_sparql}")

                sparql_update = SPARQLWrapper(f"http://{dhostname}:3030/ONTO/update")
                sparql_update.setQuery(update_sparql)
                sparql_update.method = 'POST'
                sparql_update.setReturnFormat(JSON)
                try:
                    response = sparql_update.query()
                    print(f"SPARQL Update Response: {response}")
                except Exception as e:
                    print(f"Error executing SPARQL update: {e}")
            else:
                print("Action not recognized")

    return gr.serialize(format="xml"), 200


@app.route("/Stop")
def stop():
    shutdown_server()
    return "Parando Servidor"


def RetornadorBehavior(queue):

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

    gr = registerAgent(ServeiRetornador, DirectoryAgent, ServeiRetornador.uri, get_count(),port)
    return gr
if __name__ == '__main__':
    ab1 = Process(target=RetornadorBehavior, args=(queue,))
    ab1.start()

    # Run server
    app.run(host=hostname, port=port, debug=False)

    # Wait behaviors
    ab1.join()
    print('The End')
