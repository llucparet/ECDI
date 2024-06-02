from multiprocessing import Queue, Process
from flask import Flask, request
from rdflib import Graph, Namespace, Literal, RDF, URIRef
from Utils.ACLMessages import build_message, send_message, get_message_properties
from Utils.Agent import Agent
from Utils.FlaskServer import shutdown_server
from Utils.Logger import config_logger
from Utils.OntoNamespaces import ONTO, ACL
import datetime

logger = config_logger(level=1)

# Configuration stuff
hostname = "localhost"
port = 8000

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
    gm.parse(data=message, format='xml')
    msgdic = get_message_properties(gm)

    gr = Graph()

    if msgdic is None:
        gr = build_message(Graph(), ACL['not-understood'], sender=AgentAssistent.uri, msgcnt=get_count())
    else:
        if msgdic['performative'] != ACL.request:
            gr = build_message(Graph(), ACL['not-understood'], sender=AgentAssistent.uri, msgcnt=get_count())
        else:
            content = msgdic['content']
            accion = gm.value(subject=content, predicate=RDF.type)

            if accion == ONTO.RetornarProducte:
                producte_comanda = gm.value(subject=content, predicate=ONTO.ProducteComanda)
                data_compra = gm.value(subject=producte_comanda, predicate=ONTO.Data)
                client = gm.value(subject=content, predicate=ONTO.Usuari)
                import_producte = gm.value(subject=producte_comanda, predicate=ONTO.Preu)

                # Verificar si la devolución es válida
                fecha_compra = datetime.datetime.strptime(str(data_compra), '%Y-%m-%d')
                dias_pasados = (datetime.datetime.now() - fecha_compra).days

                if dias_pasados <= 14:
                    # Devolución válida
                    gr.add((content, RDF.type, ONTO.RetornarProducte))
                    gr.add((content, ONTO.Resolucio, Literal("Acceptada")))

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
                    gr.add((content, ONTO.Resolucio, Literal("Rebutjada")))

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
