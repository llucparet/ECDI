import requests
from Utils.templates import *
import os
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

logger = config_logger(level=1)

# Configuration stuff
hostname = "localhost"
port = 8004

agn = Namespace("http://www.agentes.org#")

mss_cnt = 0

AgentVenedorExtern = Agent('AgentVenedorExtern',
                          agn.AgentVenedorExtern,
                          f'http://{hostname}:{port}/comm',
                          f'http://{hostname}:{port}/Stop')

ServeiCataleg = Agent('ServeiCataleg',
                          agn.AgGestorProductes,
                          f'http://{hostname}:8005/comm',
                          f'http://{hostname}:8005/Stop')

# Global triplestore graph
dsgraph = Graph()

cola1 = Queue()

# Fuseki endpoint
fuseki_url = 'http://localhost:3030/ONTO/query'

# Flask stuff
app = Flask(__name__)

template_dir = os.path.abspath('../Utils/templates')
app = Flask(__name__, template_folder=template_dir)


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


def get_products_by_company():
    query = """
    PREFIX ns: <http://www.semanticweb.org/nilde/ontologies/2024/4/>
    SELECT ?id ?nom ?marca ?empresa ?preu ?pes ?categoria ?valoracio
    WHERE {
        ?product a ns:Producte ;
                 ns:ID ?id ;
                 ns:Nom ?nom ;
                 ns:Marca ?marca ;
                 ns:Empresa ?empresa ;
                 ns:Preu ?preu ;
                 ns:Pes ?pes ;
                 ns:Categoria ?categoria ;
                 ns:Valoracio ?valoracio .
        FILTER (STRLEN(STR(?empresa)) > 0)
    }
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


@app.route("/", methods=['GET'])
def home():
    return render_template('home_venedor_extern.html')


@app.route("/new_product", methods=['GET', 'POST'])
def add_product():
    vendors = get_vendors()
    if request.method == 'GET':
        return render_template('nou_producte.html', vendors=vendors, start=True)
    else:
        if request.form['submit'] == 'Afegir':
            nomEmpresa = request.form['companyName']
            nomProducte = request.form['productName']
            preu = request.form['price']
            marca = request.form['brand']
            categoria = request.form['category']
            pes = request.form['weight']
            error, error_message = add_new_product(nomEmpresa, nomProducte, preu, marca, categoria, pes)
            if error:
                return render_template('nou_producte.html', start=True, vendors=vendors, error=True, error_message=error_message)
            else:
                return render_template('nou_producte.html', start=False)
        if request.form['submit'] == 'Tornar':
            return render_template('nou_producte.html', start=True, vendors=vendors)


@app.route("/list_products", methods=['GET'])
def list_products():
    products = get_products_by_company()
    return render_template('list_products_venedor_extern.html', products=products)


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

    msg = build_message(g, ACL.request, AgentVenedorExtern.uri, ServeiCataleg.uri, action, get_count())
    send_message(msg, ServeiCataleg.address)
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


def agentbehavior1(queue):
    """
    Un comportament de l'agent
    :return:
    """
    pass


if __name__ == '__main__':
    """
    # Ponemos en marcha los behaviors
    ab1 = Process(target=agentbehavior1, args=(cola1,))
    ab1.start()
    # Ponemos en marcha el servidor
    app.run(host=hostname, port=port)

    # Esperamos a que acaben los behaviors
    ab1.join()

    print('The End')
    """
    app.run(host=hostname, port=port)
