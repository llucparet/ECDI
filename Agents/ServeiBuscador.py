import sys

from SPARQLWrapper import JSON, SPARQLWrapper
from flask import Flask, request
from rdflib import Graph, RDF, Namespace, Literal, URIRef
from multiprocessing import Queue, Process

from Agents.AgentAssistent import agentbehavior1, cola1
from Utils.ACL import ACL
from Utils.ACLMessages import build_message, get_message_properties
from Utils.Agent import Agent
from Utils.FlaskServer import shutdown_server
from Utils.Logger import config_logger
from Utils.OntoNamespaces import ONTO
import socket

# Configuración de logging
logger = config_logger(level=1)

# Configuración del agente
hostname = "localhost"
port = 8003
agn = Namespace("http://www.agentes.org#")
ServeiBuscador = Agent('ServeiBuscador', agn.ServeiBuscador, f'http://{hostname}:{port}/comm', f'http://{hostname}:{port}/Stop')

app = Flask(__name__)
mss_cnt = 0

def get_count():
    global mss_cnt
    mss_cnt += 1
    return mss_cnt

@app.route("/comm", methods=['GET', 'POST'])
def communication():
    if request.method == 'POST':
        message = request.data
    elif request.method == 'GET':
        message = request.args['content']

    gm = Graph()
    gm.parse(data=message, format='xml')
    msgdic = get_message_properties(gm)

    if msgdic and msgdic['performative'] == ACL.request:
        content = msgdic['content']
        accion = gm.value(subject=content, predicate=RDF.type)
        if accion == ONTO.BuscarProductes:
            return handle_search_request(gm, content)

    # Default response if message is not understood or there is no action to perform
    gr = build_message(Graph(), ACL['not-understood'], sender=ServeiBuscador.uri, msgcnt=get_count())
    return gr.serialize(format='xml'), 200

def handle_search_request(gm, content):
    filters = {p: gm.value(subject=restriccio, predicate=ONTO[p])
               for restriccio in gm.objects(content, ONTO.Restriccions)
               for p in ['Marca', 'PreuMax', 'PreuMin', 'Nom', 'Valoracio', 'Categoria']
               if gm.value(subject=restriccio, predicate=RDF.type) == ONTO['Restriccio' + p]}

    logger.info(f'Applying filters: {filters}')
    gr = buscar_productos(**filters)
    return gr.serialize(format='xml'), 200

def buscar_productos(**filters):
    endpoint_url = "http://localhost:3030/ONTO/query"
    graph = Graph()
    conditions = []

    if 'Marca' in filters:
        conditions.append(f"?marca = \"{filters['Marca']}\"")
    if 'Nom' in filters:
        conditions.append(f"regex(?nom, \"{filters['Nom']}\", \"i\")")
    if 'Categoria' in filters:
        conditions.append(f"regex(?categoria, \"{filters['Categoria']}\", \"i\")")
    if 'Valoracio' in filters:
        conditions.append(f"?valoracio >= {float(filters['Valoracio'])}")
    if 'PreuMin' in filters or 'PreuMax' in filters:
        preuMin = float(filters.get('PreuMin', 0))
        preuMax = float(filters.get('PreuMax', sys.float_info.max))
        conditions.append(f"?preu >= {preuMin} && ?preu <= {preuMax}")

    where_clause = " && ".join(conditions)
    query = f"""
        PREFIX rdf: <http://www.w3.org/1999/02/22-rdf-syntax-ns#>
        PREFIX ex: <http://www.semanticweb.org/nilde/ontologies/2024/4/>

        SELECT ?producte ?nom ?pes ?preu ?marca ?valoracio ?categoria
        WHERE {{
            ?producte rdf:type ex:Producte .
            OPTIONAL {{ ?producte ex:Nom ?nom . }}
            OPTIONAL {{ ?producte ex:Pes ?pes . }}
            OPTIONAL {{ ?producte ex:Preu ?preu . }}
            OPTIONAL {{ ?producte ex:Marca ?marca . }}
            OPTIONAL {{ ?producte ex:Valoracio ?valoracio . }}
            OPTIONAL {{ ?producte ex:Categoria ?categoria . }}
            FILTER ({where_clause})
        }}
    """

    sparql = SPARQLWrapper(endpoint_url)
    sparql.setQuery(query)
    sparql.setReturnFormat(JSON)
    try:
        results = sparql.query().convert()
        for result in results["results"]["bindings"]:
            producte = URIRef(result["producte"]["value"])
            graph.add((producte, RDF.type, ONTO.Producte))
            for attr in ['nom', 'pes', 'preu', 'marca', 'valoracio', 'categoria']:
                if attr in result:
                    graph.add((producte, ONTO[attr.capitalize()], Literal(result[attr]["value"])))
        return graph
    except Exception as e:
        logger.error(f"Error executing SPARQL query: {e}")
        return Graph()  # Return an empty graph on error

@app.route("/Stop")
def stop():
    tidyup()
    shutdown_server()
    return "Stopping server"

def tidyup():
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
