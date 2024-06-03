from multiprocessing import Queue, Process
from flask import Flask, request
from rdflib import Graph, Namespace, Literal, RDF, URIRef
from Utils.ACLMessages import build_message, send_message, get_message_properties
from Utils.Agent import Agent
from Utils.FlaskServer import shutdown_server
from Utils.Logger import config_logger
from Utils.OntoNamespaces import ONTO
from Utils.ACL import ACL
from rdflib.term import URIRef
import datetime

logger = config_logger(level=1)

# Configuration stuff
hostname = "localhost"
port = 8030

agn = Namespace("http://www.agentes.org#")

# Contador de mensajes
mss_cnt = 0

ServeiEntrega = Agent('ServeiEntrega',
                      agn.ServeiEntrega,
                      'http://%s:%d/comm' % (hostname, port),
                      'http://%s:%d/Stop' % (hostname, port))

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

                if dias_pasados <= 14 and len(str(motiu)) > 50:
                    # Devolución válida
                    gr.add((content, RDF.type, ONTO.RetornarProducte))
                    gr.add((content, ONTO.Resolucio, Literal("Retornat")))
                    gr.add((content, ONTO.ProducteComanda, producte_comanda))
                    print("Devolución válida")

                    # Informar al ServeiEntrega para realizar el pago
                    g_pago = Graph()
                    accion_pago = ONTO["PagarUsuari_" + str(get_count())]
                    g_pago.add((accion_pago, RDF.type, ONTO.PagarUsuari))
                    g_pago.add((accion_pago, ONTO.Desti, client))
                    g_pago.add((accion_pago, ONTO.Import, import_producte))
                    g_pago.add((accion_pago, ONTO.ProducteComanda, producte_comanda))

                    msg_pago = build_message(g_pago, ACL.request, ServeiEntrega.uri, AgentPagaments.uri, accion_pago,
                                             get_count())
                    send_message(msg_pago, AgentPagaments.address)
                else:
                    # Devolución no válida
                    gr.add((content, RDF.type, ONTO.RetornarProducte))
                    gr.add((content, ONTO.Resolucio, Literal("Rebutjat")))
                    gr.add((content, ONTO.ProducteComanda, producte_comanda))
                    gr.add((content, ONTO.Motiu, motiu))
                    print("Devolución no válida")
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