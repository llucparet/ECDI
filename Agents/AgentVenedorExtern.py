import argparse
import sys
import os
sys.path.insert(0, os.path.abspath('../'))
from rdflib import Graph, Namespace, Literal, RDF, URIRef, XSD
from flask import Flask, request, render_template
from Utils.ACLMessages import *
from Utils.Agent import Agent
from Utils.Logger import config_logger
from Utils.OntoNamespaces import ONTO
from Utils.ACL import ACL
from Utils.FlaskServer import shutdown_server
from datetime import datetime
import time
import socket
from multiprocessing import Process, Queue

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
    port = 8080
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

AgentVenedorExtern = Agent('AgentVenedorExtern',
                          agn.AgentVenedorExtern,
                          f'http://{hostaddr}:{port}/comm',
                          f'http://{hostaddr}:{port}/Stop')
# Directory agent address
DirectoryAgent = Agent('DirectoryAgent',
                       agn.Directory,
                       'http://%s:%d/Register' % (dhostname, dport),
                       'http://%s:%d/Stop' % (dhostname, dport))

# Global triplestore graph
dsGraph = Graph()

# Queue
queue = Queue()

# Fuseki endpoint
fuseki_url = f'http://{dhostname}:3030/ONTO/query'

# Flask stuff

template_dir = os.path.abspath('../Utils/templates')
app = Flask(__name__, template_folder=template_dir, static_folder='../static')


def get_count():
    global mss_cnt
    mss_cnt += 1
    return mss_cnt


def get_vendors():
    query = """
    PREFIX ns: <http://www.semanticweb.org/nilde/ontologies/2024/4/>
    SELECT ?nom ?compteBancari
    WHERE {
        ?vendedor a ns:VenedorExtern ;
                  ns:Nom ?nom ;
                  ns:CompteBancari ?compteBancari .
    }
    """
    response = requests.post(fuseki_url, data={'query': query}, headers={'Accept': 'application/sparql-results+json'})
    if response.status_code == 200:
        results = response.json()
        vendors = {result['nom']['value']: result['compteBancari']['value'] for result in results['results']['bindings']}
        return vendors
    else:
        print(f"Error querying Fuseki: {response.status_code} - {response.text}")
        return {}


def get_products_by_company(company):
    query = f"""
    PREFIX ns: <http://www.semanticweb.org/nilde/ontologies/2024/4/>
    SELECT ?id ?nom ?marca ?empresa ?preu ?pes ?categoria ?valoracio
    WHERE {{
        ?product a ns:Producte ;
                 ns:ID ?id ;
                 ns:Nom ?nom ;
                 ns:Marca ?marca ;
                 ns:Empresa ?empresa ;
                 ns:Preu ?preu ;
                 ns:Pes ?pes ;
                 ns:Categoria ?categoria ;
                 ns:Valoracio ?valoracio .
        FILTER (STR(?empresa) = "{company}")
    }}
    """
    response = requests.post(fuseki_url, data={'query': query}, headers={'Accept': 'application/sparql-results+json'})
    if response.status_code == 200:
        results = response.json()
        products = [{
            'id': result['id']['value'],
            'name': result['nom']['value'],
            'brand': result['marca']['value'],
            'company': result['empresa']['value'],
            'price': result['preu']['value'],
            'weight': result['pes']['value'],
            'category': result['categoria']['value'],
            'rating': result['valoracio']['value']
        } for result in results['results']['bindings']]
        return products
    else:
        print(f"Error querying Fuseki: {response.status_code} - {response.text}")
        return []

@app.route("/register", methods=['GET', 'POST'])
def register():
    vendors = get_vendors()
    if request.method == 'GET':
        return render_template('register_venedor_extern.html', vendors=vendors)
    else:
        selected_vendor = request.form['vendor']
        # Guardar la empresa registrada en una variable global o en sesión
        global registered_vendor
        registered_vendor = selected_vendor
        return render_template('home_venedor_extern.html', registered_vendor=registered_vendor)

@app.route("/", methods=['GET'])
def home():
    if 'registered_vendor' in globals():
        return render_template('home_venedor_extern.html', registered_vendor=registered_vendor)
    else:
        return render_template('register_venedor_extern.html', vendors=get_vendors())


@app.route("/new_product", methods=['GET', 'POST'])
def add_product():
    if 'registered_vendor' not in globals():
        return render_template('register_venedor_extern.html', vendors=get_vendors())

    if request.method == 'GET':
        return render_template('nou_producte.html', start=True)
    else:
        if request.form['submit'] == 'Afegir':
            nomProducte = request.form['productName']
            preu = request.form['price']
            marca = request.form['brand']
            categoria = request.form['category']
            pes = request.form['weight']
            error, error_message = add_new_product(registered_vendor, nomProducte, preu, marca, categoria, pes)
            if error:
                return render_template('nou_producte.html', start=True, error=True, error_message=error_message)
            else:
                return render_template('nou_producte.html', start=False, success=True)
        if request.form['submit'] == 'Tornar':
            return render_template('home_venedor_extern.html', registered_vendor=registered_vendor)


@app.route("/list_products", methods=['GET'])
def list_products():
    if 'registered_vendor' not in globals():
        return render_template('register_venedor_extern.html', vendors=get_vendors())
    products = get_products_by_company(registered_vendor)
    return render_template('list_products_venedor_extern.html', products=products)

@app.route("/delete_product", methods=['POST'])
def delete_product():
    product_id = request.form['product_id']
    error = delete_product_by_id(product_id)
    if error:
        print(f"Error deleting product: {error}")
    return list_products()


def delete_product_by_id(product_id):
    global mss_cnt
    g = Graph()
    cnt = get_count()

    if not product_id:
        return "El ID del producto no puede estar vacío."

    print(f"Deleting product with ID: {product_id}")  # Registro de depuración

    action = ONTO['EliminarProducteExtern_' + str(cnt)]
    g.add((action, RDF.type, ONTO.EliminarProducteExtern))
    g.add((action, ONTO.ID, Literal(product_id)))

    servei_cataleg = getAgentInfo(agn.ServeiCataleg, DirectoryAgent, AgentVenedorExtern, get_count())
    msg = build_message(g, ACL.request, AgentVenedorExtern.uri, servei_cataleg.uri, action, get_count())
    send_message(msg, servei_cataleg.address)

def add_new_product(nomEmpresa, nomProducte, preu, marca, categoria, pes):
    global mss_cnt
    g = Graph()
    cnt = get_count()

    if not nomEmpresa or not nomProducte or not preu or not marca or not categoria or not pes:
        return True, "No puedes dejar ningún campo vacío. Tienes que rellenarlos todos."

    vendors = get_vendors()
    if nomEmpresa not in vendors:
        return True, "Esta tienda sólo acepta productos de Ikea, Nike o Apple."
    if not preu.replace('.', '', 1).isdigit():
        return True, "Introduce un precio válido. Recuerda que son euros."
    if not pes.replace('.', '', 1).isdigit():
        return True, "Introduce un peso válido. Recuerda que son kilogramos."

    action = ONTO['AfegirProducteExtern_' + str(cnt)]
    g.add((action, RDF.type, ONTO.AfegirProducteExtern))
    g.add((action, ONTO.NomEmpresa, Literal(nomEmpresa)))
    g.add((action, ONTO.Nom, Literal(nomProducte)))
    g.add((action, ONTO.Preu, Literal(preu)))
    g.add((action, ONTO.Marca, Literal(marca)))
    g.add((action, ONTO.Pes, Literal(pes)))
    g.add((action, ONTO.Categoria, Literal(categoria)))

    servei_cataleg = getAgentInfo(agn.ServeiCataleg, DirectoryAgent, AgentVenedorExtern, get_count())
    print(servei_cataleg.uri)
    print(servei_cataleg.address)
    msg = build_message(g, ACL.request, AgentVenedorExtern.uri, servei_cataleg.uri, action, get_count())
    send_message(msg, servei_cataleg.address)
    return False, None


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
    vendors = get_vendors()

    gr = None
    if msgdic is None:
        # Si no es, respondemos que no hemos entendido el mensaje
        gr = build_message(Graph(), ACL['not-understood'], sender=AgentVenedorExtern.uri, msgcnt=get_count())
    else:
        # Obtenemos la performativa
        if msgdic['performative'] != ACL.request:
            # Si no es un request, respondemos que no hemos entendido el mensaje
            gr = build_message(Graph(),
                               ACL['not-understood'],
                               sender=AgentVenedorExtern.uri,
                               msgcnt=get_count())
        else:
            # Extraemos el objeto del contenido que ha de ser una accion de la ontologia
            content = msgdic['content']
            # Averiguamos el tipo de la accion
            accion = gm.value(subject=content, predicate=RDF.type)
            nomEmpresa = ""

            if accion == ONTO.PagarVenedorExtern:
                for s, p, o in gm:
                    if p == ONTO.Nom:
                        nomEmpresa = str(o)
                        break
                graphrespuesta = Graph()
                accion = ONTO["PagarVenedorExtern"]
                graphrespuesta.add((accion, RDF.type, ONTO.PagarVenedorExtern))
                if nomEmpresa not in vendors:
                    return graphrespuesta.serialize(format='xml'), 200
                else:
                    graphrespuesta.add((accion, ONTO.CompteBancari, Literal(vendors[nomEmpresa])))
                    return graphrespuesta.serialize(format='xml'), 200

            if accion == ONTO.AvisarEnviament:
                g = Graph()
                action = ONTO["AvisarEnviament_" + str(get_count())]
                g.add((action, RDF.type, ONTO.AvisarEnviament))
                return g.serialize(format="xml"), 200

            if accion == ONTO.CobrarVenedorExtern:
                empresa = gm.value(subject=content, predicate=ONTO.Nom)
                ginfo = Graph()
                accion = ONTO["CobrarVenedorExtern_" + str(get_count())]
                ginfo.add((accion, RDF.type, ONTO.CobrarVenedorExtern))
                ginfo.add((accion, ONTO.CompteBancari, Literal(vendors[str(empresa)])))

                return ginfo.serialize(format="xml"), 200
    return "Aquest agent s'encarregarà d'afegir productes."


@app.route("/Stop")
def stop():
    """
    Entrypoint que para el agent
    """
    tidyup()
    shutdown_server()
    return "Parant Servidor"


def tidyup():
    """
    Accions prèvies a parar l'agent
    """
    pass


def VenedorExternBehavior(queue):

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

    gr = registerAgent(AgentVenedorExtern, DirectoryAgent, AgentVenedorExtern.uri, get_count(),port)
    return gr
if __name__ == '__main__':
    ab1 = Process(target=VenedorExternBehavior, args=(queue,))
    ab1.start()

    # Run server
    app.run(host=hostname, port=port, debug=False)

    # Wait behaviors
    ab1.join()
    print('The End')

