import socket
from flask import Flask, request
from rdflib import Namespace, Graph, RDF, Literal, URIRef, XSD
from SPARQLWrapper import SPARQLWrapper, JSON
from Utils.ACLMessages import build_message, send_message, get_message_properties
from Utils.Agent import Agent
from Utils.Logger import config_logger
from Utils.OntoNamespaces import ONTO
from Utils.ACL import ACL

import time

logger = config_logger(level=1)

hostname = socket.gethostname()
port = 8024

agn = Namespace("http://www.agentes.org#")

AgentValoraciones = Agent('AgentValoraciones',
                          agn.AgentValoraciones,
                          f'http://{hostname}:{port}/comm',
                          f'http://{hostname}:{port}/Stop')

app = Flask(__name__)

fuseki_url = 'http://localhost:3030/ONTO/update'
query_endpoint_url = 'http://localhost:3030/ONTO/query'

mss_cnt = 0

def get_count():
    global mss_cnt
    mss_cnt += 1
    return mss_cnt

@app.route("/comm", methods=['POST'])
def communication():
    """
    Communication entry point for the agent.
    """
    message = request.data
    gm = Graph()
    gm.parse(data=message, format='xml')
    msgdic = get_message_properties(gm)

    if not msgdic:
        gr = build_message(Graph(), ACL['not-understood'], sender=AgentValoraciones.uri, msgcnt=get_count())
    elif msgdic['performative'] != ACL.request:
        gr = build_message(Graph(), ACL['not-understood'], sender=AgentValoraciones.uri, msgcnt=get_count())
    else:
        content = msgdic['content']
        accion = gm.value(subject=content, predicate=RDF.type)

        if accion == ONTO.ValorarProducte:
            nombre_producto = str(gm.value(predicate=ONTO.Nom))
            nueva_valoracion = float(gm.value(predicate=ONTO.Valoracio))
            comanda_id = str(gm.value(predicate=ONTO.Comanda))
            update_product_rating(nombre_producto, nueva_valoracion, comanda_id)
            gr = build_message(Graph(), ACL['inform'], sender=AgentValoraciones.uri, msgcnt=get_count())

    return gr.serialize(format='xml')

def update_product_rating(nombre_producto, nueva_valoracion, comanda_id):
    sparql = SPARQLWrapper(query_endpoint_url)
    sparql.setQuery(f"""
        PREFIX ont: <http://www.semanticweb.org/nilde/ontologies/2024/4/>
        SELECT ?valoracion WHERE {{
            ?producto ont:Nom "{nombre_producto}" ;
                      ont:Valoracio ?valoracion .
        }}
    """)
    sparql.setReturnFormat(JSON)
    results = sparql.query().convert()

    total_valoraciones = nueva_valoracion
    count = 1  # Inicialmente contamos la nueva valoración

    for result in results["results"]["bindings"]:
        total_valoraciones += float(result["valoracion"]["value"])
        count += 1

    nuevo_promedio = total_valoraciones / count

    update_sparql = SPARQLWrapper(fuseki_url)
    update_sparql.setMethod('POST')
    update_sparql.setQuery(f"""
        PREFIX ont: <http://www.semanticweb.org/nilde/ontologies/2024/4/>
        DELETE WHERE {{
            ?producto ont:Nom "{nombre_producto}" ;
                      ont:Valoracio ?valoracion .
        }};
        INSERT {{
            ?producto ont:Valoracio "{nuevo_promedio}"^^xsd:float .
        }} WHERE {{
            ?producto ont:Nom "{nombre_producto}" .
        }}
    """)
    update_sparql.query()

    # Actualizar ProducteComanda
    update_producte_comanda_rating(comanda_id, nombre_producto, nueva_valoracion)

def update_producte_comanda_rating(comanda_id, nombre_producto, nueva_valoracion):
    update_sparql = SPARQLWrapper(fuseki_url)
    update_sparql.setMethod('POST')
    update_sparql.setQuery(f"""
        PREFIX ont: <http://www.semanticweb.org/nilde/ontologies/2024/4/>
        DELETE WHERE {{
            ?producte_comanda ont:Nom "{nombre_producto}" ;
                              ont:Valoracio ?valoracion .
        }};
        INSERT {{
            ?producte_comanda ont:Valoracio "{nueva_valoracion}"^^xsd:float .
        }} WHERE {{
            ?producte_comanda ont:Nom "{nombre_producto}" ;
                               ont:Comanda "{comanda_id}" .
        }}
    """)
    update_sparql.query()

    print(f"Valoración actualizada a {nueva_valoracion} para el producto {nombre_producto} en la comanda {comanda_id}")

if __name__ == '__main__':
    app.run(host=hostname, port=port)
