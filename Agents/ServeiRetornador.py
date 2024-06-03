from multiprocessing import Queue, Process
from SPARQLWrapper import SPARQLWrapper, JSON
from flask import Flask, request
from rdflib import Graph, Namespace, Literal, RDF, URIRef, XSD
from Utils.ACLMessages import build_message, send_message, get_message_properties
from Utils.Agent import Agent
from Utils.FlaskServer import shutdown_server
from Utils.Logger import config_logger
from Utils.OntoNamespaces import ONTO
from Utils.ACL import ACL
import datetime

logger = config_logger(level=1)

# Configuration stuff
hostname = "localhost"
port = 8030

agn = Namespace("http://www.agentes.org#")

# Contador de mensajes
mss_cnt = 0

ServeiEntrega = Agent('ServeiEntrega', agn.ServeiEntrega, f'http://{hostname}:8000/comm',
                         f'http://{hostname}:8000/Stop')

AgentAssistent = Agent('AgentAssistent',
                       agn.AgentAssistent,
                       'http://%s:9011/comm' % hostname,
                       'http://%s:9011/Stop' % hostname)

AgentPagaments = Agent('AgentPagaments',
                       agn.AgentPagaments,
                       'http://%s:8001/comm' % hostname,
                       'http://%s:8001/Stop' % hostname)

ServeiRetornador = Agent('ServeiRetornador', agn.ServeiRetornador, f'http://{hostname}:8030/comm',
                         f'http://{hostname}:8030/Stop')

# Global triplestore graph
dsgraph = Graph()

cola1 = Queue()

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

                # Considerar cualquier valor negativo como menor que 15 o 30
                if dias_pasados < 0 or \
                   (motiu == "No se satisfan les expectatives del producte" and dias_pasados <= 15) or \
                   (motiu in ["El producte és defectuós", "El producte és erroni"] and dias_pasados <= 30):
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

                    print(f"Sending payment message to {ServeiEntrega.uri}")
                    msg_pago = build_message(g_pago, ACL.request, ServeiRetornador.uri, ServeiEntrega.uri, accion_pago,
                                             get_count())
                    send_message(msg_pago, ServeiEntrega.address)

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

                sparql_update = SPARQLWrapper("http://localhost:3030/ONTO/update")
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
    tidyup()
    shutdown_server()
    return "Parando Servidor"


def tidyup():
    pass


def agentbehavior1(cola):
    pass


if __name__ == '__main__':
    ab1 = Process(target=agentbehavior1, args=(cola1,))
    ab1.start()

    app.run(host=hostname, port=port)

    ab1.join()
    print('The End')
