import socket
from flask import Flask, request
from rdflib import Namespace, Graph, RDF, Literal, URIRef, XSD
from SPARQLWrapper import SPARQLWrapper, JSON
from Utils.ACLMessages import build_message, get_message_properties
from Utils.Agent import Agent
from Utils.Logger import config_logger
from Utils.OntoNamespaces import ONTO
from Utils.ACL import ACL

logger = config_logger(level=1)

hostname = "localhost"
port = 8024

agn = Namespace("http://www.agentes.org#")

ServeiClients = Agent('ServeiClients',
                      agn.ServeiClients,
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


@app.route("/comm", methods=['GET'])
def communication():
    """
    Communication entry point for the agent.
    """
    message = request.args.get('content')
    gm = Graph()
    gm.parse(data=message, format='xml')
    msgdic = get_message_properties(gm)

    if not msgdic:
        gr = build_message(Graph(), ACL['not-understood'], sender=ServeiClients.uri, msgcnt=get_count())
    elif msgdic['performative'] != ACL.request:
        gr = build_message(Graph(), ACL['not-understood'], sender=ServeiClients.uri, msgcnt=get_count())
    else:
        content = msgdic['content']
        accion = gm.value(subject=content, predicate=RDF.type)

        if accion == ONTO.ValorarProducte:
            nombre_producto = str(gm.value(subject=content, predicate=ONTO.Nom))
            nueva_valoracion = float(gm.value(subject=content, predicate=ONTO.Valoracio))
            comanda_id = str(gm.value(subject=content, predicate=ONTO.Comanda))
            update_product_rating(nombre_producto, nueva_valoracion, comanda_id)
            gr = build_message(Graph(), ACL['inform'], sender=ServeiClients.uri, msgcnt=get_count())

    return gr.serialize(format='xml')


def update_product_rating(nombre_producto, nueva_valoracion, comanda_id):
    sparql = SPARQLWrapper(query_endpoint_url)
    sparql.setQuery(f"""
        PREFIX ont: <http://www.semanticweb.org/nilde/ontologies/2024/4/>
        PREFIX xsd: <http://www.w3.org/2001/XMLSchema#>
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
        PREFIX xsd: <http://www.w3.org/2001/XMLSchema#>
        DELETE {{
            ?producto ont:Valoracio ?old_valoracion .
        }}
        INSERT {{
            ?producto ont:Valoracio "{nuevo_promedio}"^^xsd:float .
        }} WHERE {{
            ?producto ont:Nom "{nombre_producto}" ;
                      ont:Valoracio ?old_valoracion .
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
        PREFIX xsd: <http://www.w3.org/2001/XMLSchema#>
        DELETE {{
            ?producte_comanda ont:Valoracio ?old_valoracion .
        }}
        INSERT {{
            ?producte_comanda ont:Valoracio "{nueva_valoracion}"^^xsd:float .
        }} WHERE {{
            ?producte_comanda ont:Nom "{nombre_producto}" ;
                               ont:Comanda "{comanda_id}" ;
                               ont:Valoracio ?old_valoracion .
        }}
    """)
    update_sparql.query()

    print(f"Valoración actualizada a {nueva_valoracion} para el producto {nombre_producto} en la comanda {comanda_id}")



if __name__ == '__main__':
    app.run(host=hostname, port=port)
