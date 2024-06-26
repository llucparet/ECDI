import socket
import time
from multiprocessing import Process

import requests
from flask import Flask, request
from rdflib import Namespace, Graph, RDF, Literal, URIRef, XSD
from SPARQLWrapper import SPARQLWrapper, JSON
from Utils.ACLMessages import build_message, get_message_properties, send_message
from Utils.Agent import Agent
from Utils.Logger import config_logger
from Utils.OntoNamespaces import ONTO
from Utils.ACL import ACL

logger = config_logger(level=1)

hostname = '0.0.0.0'
port = 8024

agn = Namespace("http://www.agentes.org#")

ServeiClients = Agent('ServeiClients',
                      agn.ServeiClients,
                      f'http://{hostname}:{port}/comm',
                      f'http://{hostname}:{port}/Stop')

AgentAssistent = Agent('AgentAssistent',
                       agn.AgentAssistent,
                       'http://%s:9011/comm' % hostname,
                       'http://%s:9011/Stop' % hostname)

app = Flask(__name__)

fuseki_url = 'http://localhost:3030/ONTO/update'
query_endpoint_url = 'http://localhost:3030/ONTO/query'
endpoint_url = "http://localhost:3030/ONTO/query"
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
    sparql_query = f"""
        PREFIX ont: <http://www.semanticweb.org/nilde/ontologies/2024/4/>
        PREFIX xsd: <http://www.w3.org/2001/XMLSchema#>
        PREFIX rdf: <http://www.w3.org/1999/02/22-rdf-syntax-ns#>
        SELECT ?valoracion WHERE {{
    		?producto rdf:type ont:Producte .
            ?producto ont:Nom "{nombre_producto}" .
            ?producto ont:Valoracio ?valoracion .
        }}
    """
    sparql = SPARQLWrapper(query_endpoint_url)
    sparql.setQuery(sparql_query)
    sparql.setReturnFormat(JSON)
    results = sparql.query().convert()

    total_valoraciones = nueva_valoracion
    print(total_valoraciones)


    for result in results["results"]["bindings"]:
        total_valoraciones += float(result["valoracion"]["value"])


    nuevo_promedio = total_valoraciones / 2

    sparql_query = f"""
        PREFIX ont: <http://www.semanticweb.org/nilde/ontologies/2024/4/>
        PREFIX xsd: <http://www.w3.org/2001/XMLSchema#>
        PREFIX rdf: <http://www.w3.org/1999/02/22-rdf-syntax-ns#>
        DELETE {{
            ?producto ont:Valoracio ?old_valoracion .
        }}
        INSERT {{
            ?producto ont:Valoracio "{nuevo_promedio}"^^xsd:float .
        }} WHERE {{
    		?producto rdf:type ont:Producte .
            ?producto ont:Nom "{nombre_producto}" .
            OPTIONAL {{ ?producte ont:Valoracio ?old_valoracion . }}          
        }}
    """
    headers = {
        'Content-Type': 'application/sparql-update'
    }

    # Envia la sol·licitud POST al servidor Fuseki
    response = requests.post(fuseki_url, data=sparql_query, headers=headers)

    # Mostra la resposta
    if response.status_code == 204:
        print("update_product_rating: Valoración actualizada correctamente")
    else:
        print(f"Error en executar la consulta SPARQL: {response.status_code}")
        print(response.text)

    # Actualizar ProducteComanda
    update_producte_comanda_rating(comanda_id, nombre_producto, nueva_valoracion)


def update_producte_comanda_rating(comanda_id, nom_producte, nueva_valoracion):
    comanda = f"http://www.semanticweb.org/nilde/ontologies/2024/4/{comanda_id}"
    print(comanda)
    print(nom_producte)
    sparql_query = f"""
        PREFIX ont: <http://www.semanticweb.org/nilde/ontologies/2024/4/>
        PREFIX xsd: <http://www.w3.org/2001/XMLSchema#>
        PREFIX rdf: <http://www.w3.org/1999/02/22-rdf-syntax-ns#>
        DELETE {{
            ?producteComanda ont:Valoracio ?oldValoracio .
        }}
        INSERT {{
            ?producteComanda ont:Valoracio "{nueva_valoracion}"^^xsd:float .
        }}
        WHERE {{
            <{comanda}> ont:ProductesComanda ?producteComanda .
            ?producteComanda ont:Nom "{nom_producte}" .

            OPTIONAL {{ ?producteComanda ont:Valoracio ?oldValoracio . }}
        
        }}
    """
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

    print(f"Valoración actualizada a {nueva_valoracion} para el producto {nom_producte} en la comanda {comanda_id}")


def recomenar_productes():
    """
    Recomana productes als clients segons les valoracions que hagin fet.
    """
    while True:

        sparql_query = f"""
                                PREFIX rdf: <http://www.w3.org/1999/02/22-rdf-syntax-ns#>
                                PREFIX ont: <http://www.semanticweb.org/nilde/ontologies/2024/4/>
                                SELECT ?client
                                WHERE {{
                                    ?client rdf:type ont:Client .
                                  }}
                              """

        print(sparql_query)
        # Crear el objeto SPARQLWrapper y establecer la consulta
        sparql = SPARQLWrapper(endpoint_url)
        sparql.setQuery(sparql_query)
        sparql.setReturnFormat(JSON)
        results = sparql.query().convert()
        print(results["results"]["bindings"])
        usuaris = []
        for client_result in results["results"]["bindings"]:
            client = client_result["client"]["value"]
            print(client)
            usuaris.append(client)

        for u in usuaris:
            g = Graph()
            accio = ONTO['RecomanarProductes' + str(get_count())]
            g.add((accio, RDF.type, ONTO.RecomanarProductes))
            sparql_query = f"""
                PREFIX rdf: <http://www.w3.org/1999/02/22-rdf-syntax-ns#>
                PREFIX ont: <http://www.semanticweb.org/nilde/ontologies/2024/4/>
                
                SELECT ?producte_comanda ?nom ?valoracio
                WHERE {{
                    ?comanda rdf:type ont:Comanda .
                    ?comanda ont:Client ?client .
                    ?comanda ont:ProductesComanda ?producte_comanda .
                    ?producte_comanda rdf:type ont:ProducteComanda .
                    ?producte_comanda ont:Nom ?nom .
                    ?producte_comanda ont:Valoracio ?valoracio .
                    VALUES ?client {{ <{u}> }}
                
                  }}
            """
            print(sparql_query)
            # Crear el objeto SPARQLWrapper y establecer la consulta
            sparql = SPARQLWrapper(endpoint_url)
            sparql.setQuery(sparql_query)
            sparql.setReturnFormat(JSON)
            results = sparql.query().convert()
            categorias = []
            marques = []
            for producte_comanda_result in results["results"]["bindings"]:
                producte_comanda = producte_comanda_result["producte_comanda"]["value"]
                nom = producte_comanda_result["nom"]["value"]
                valoracio = producte_comanda_result["valoracio"]["value"]
                if str(valoracio) != 'Pendiente':
                    if float(valoracio) > 3:
                        sparql_query = f"""
                                            PREFIX rdf: <http://www.w3.org/1999/02/22-rdf-syntax-ns#>
                                            PREFIX ont: <http://www.semanticweb.org/nilde/ontologies/2024/4/>
            
                                            SELECT ?categoria ?marca
                                            WHERE {{
                                                ?producte rdf:type ont:Producte .
                                                ?producte ont:Nom "{nom}" .
                                                ?producte ont:Categoria ?categoria .
                                                ?producte ont:Marca ?marca .
                                              }}
                                        """
                        print(sparql_query)
                        # Crear el objeto SPARQLWrapper y establecer la consulta
                        sparql = SPARQLWrapper(endpoint_url)
                        sparql.setQuery(sparql_query)
                        sparql.setReturnFormat(JSON)
                        results = sparql.query().convert()
                        result_info_producte = results["results"]["bindings"][0]
                        categoria = result_info_producte["categoria"]["value"]
                        marca = result_info_producte["marca"]["value"]

                        if categoria not in categorias:
                            categorias.append(categoria)
                        if marca not in marques:
                            marques.append(marca)
            if categorias and marques:
                categories_filter = ' || '.join([f'?categoria = "{categoria}"' for categoria in categorias])
                # Generar la part del filtre per les marques
                marques_filter = ' || '.join([f'?marca = "{marca}"' for marca in marques])

                # Unir les parts del filtre amb un operador OR
                filtre = ''
                if categories_filter and marques_filter:
                    filtre = f'FILTER ({categories_filter} || {marques_filter})'
                elif categories_filter:
                    filtre = f'FILTER ({categories_filter})'
                elif marques_filter:
                    filtre = f'FILTER ({marques_filter})'
                sparql_query = f"""
                    PREFIX rdf: <http://www.w3.org/1999/02/22-rdf-syntax-ns#>
                    PREFIX ont: <http://www.semanticweb.org/nilde/ontologies/2024/4/>
            
                    SELECT ?nom ?categoria ?marca ?preu
                    WHERE {{
                        ?producte rdf:type ont:Producte .
                        ?producte ont:Nom ?nom .
                        ?producte ont:Categoria ?categoria .
                        ?producte ont:Marca ?marca .
                        ?producte ont:Preu ?preu .
                        {filtre}
                      }}
                      LIMIT 5
                """
                print(sparql_query)
                # Crear el objeto SPARQLWrapper y establecer la consulta
                sparql = SPARQLWrapper(endpoint_url)
                sparql.setQuery(sparql_query)
                sparql.setReturnFormat(JSON)
                results = sparql.query().convert()
                for producte in results["results"]["bindings"]:
                    nom = producte["nom"]["value"]
                    categoria = producte["categoria"]["value"]
                    marca = producte["marca"]["value"]
                    preu = producte["preu"]["value"]
                    producte = ONTO[nom]
                    g.add((producte, RDF.type, ONTO.Producte))
                    g.add((producte, ONTO.Nom, Literal(nom, datatype=XSD.string)))
                    g.add((producte, ONTO.Categoria, Literal(categoria, datatype=XSD.string)))
                    g.add((producte, ONTO.Marca, Literal(marca, datatype=XSD.string)))
                    g.add((producte, ONTO.Preu, Literal(preu, datatype=XSD.float)))

                msg = build_message(g, ACL.request, ServeiClients.uri, AgentAssistent.uri, accio, get_count())
                send_message(msg, AgentAssistent.address)
        time.sleep(5)


if __name__ == '__main__':
    recomanacio_automatica = Process(target=recomenar_productes, args=())
    recomanacio_automatica.start()
    app.run(host=hostname, port=port)
