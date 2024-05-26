from SPARQLWrapper import JSON, SPARQLWrapper
from flask import Flask, request
from rdflib import Graph, RDF, Namespace, Literal, XSD, URIRef
from multiprocessing import Queue, Process

from Agents.AgentAssistent import cola1
from Utils.ACL import ACL
from Utils.ACLMessages import build_message, get_message_properties
from Utils.Agent import Agent
from Utils.FlaskServer import shutdown_server
from Utils.Logger import config_logger
from Utils.OntoNamespaces import ONTO
import socket
import sys

# Configuración de logging
logger = config_logger(level=1)

# Configuración del agente
hostname = "localhost"
port = 9010

# Namespaces para RDF
agn = Namespace("http://www.agentes.org#")

# Datos del Agente
ServeiBuscador = Agent('ServeiBuscador',
                       agn.ServeiBuscador,
                       f'http://{hostname}:{port}/comm',
                       f'http://{hostname}:{port}/Stop')

# Global triplestore graph
dsgraph = Graph()

# Flask stuff
app = Flask(__name__)

# Contador de mensajes
mss_cnt = 0


def get_count():
    global mss_cnt
    mss_cnt += 1
    return mss_cnt


@app.route("/comm", methods=['GET', 'POST'])
def communication():
    logger.info('Petición de información recibida')

    if request.method == 'GET':
        message = request.args['content']
    elif request.method == 'POST':
        message = request.data

    gm = Graph()
    gm.parse(data=message, format='xml')
    msgdic = get_message_properties(gm)
    gr = None

    if msgdic is None:
        # Si no es, respondemos que no hemos entendido el mensaje
        gr = build_message(Graph(), ACL['not-understood'], sender=ServeiBuscador.uri, msgcnt=get_count())
    else:
        # Obtenemos la performativa
        if msgdic['performative'] != ACL.request:
            # Si no es un request, respondemos que no hemos entendido el mensaje
            gr = build_message(Graph(),
                               ACL['not-understood'],
                               sender=ServeiBuscador.uri,
                               msgcnt=get_count())
        else:
            # Extraemos el objeto del contenido que ha de ser una acción de la ontología
            content = msgdic['content']
            # Averiguamos el tipo de la acción
            accion = gm.value(subject=content, predicate=RDF.type)

            # Acción de buscar productos
            if accion == ONTO.BuscarProductes:
                restriccions = gm.objects(content, ONTO.Restriccions)
                restriccions_dict = {}
                for restriccio in restriccions:
                    if gm.value(subject=restriccio, predicate=RDF.type) == ONTO.RestriccioMarca:
                        marca = gm.value(subject=restriccio, predicate=ONTO.Marca)
                        logger.info('BÚSQUEDA->Restriccion de Marca: ' + str(marca))
                        restriccions_dict['marca'] = str(marca)

                    elif gm.value(subject=restriccio, predicate=RDF.type) == ONTO.RestriccioPreu:
                        preciomax = gm.value(subject=restriccio, predicate=ONTO.PreuMax)
                        preciomin = gm.value(subject=restriccio, predicate=ONTO.PreuMin)
                        if preciomin:
                            logger.info('BÚSQUEDA->Restriccion de precio mínimo: ' + str(preciomin))
                            restriccions_dict['preciomin'] = float(preciomin)
                        if preciomax:
                            logger.info('BÚSQUEDA->Restriccion de precio máximo: ' + str(preciomax))
                            restriccions_dict['preciomax'] = float(preciomax)

                    elif gm.value(subject=restriccio, predicate=RDF.type) == ONTO.RestriccioNom:
                        nombre = gm.value(subject=restriccio, predicate=ONTO.Nom)
                        logger.info('BÚSQUEDA->Restriccion de Nombre: ' + str(nombre))
                        restriccions_dict['nombre'] = str(nombre)

                    elif gm.value(subject=restriccio, predicate=RDF.type) == ONTO.RestriccioValoracio:
                        valoracio = gm.value(subject=restriccio, predicate=ONTO.Valoracio)
                        logger.info('BÚSQUEDA->Restriccion de Valoración: ' + str(valoracio))
                        restriccions_dict['valoracio'] = float(valoracio)
                        """""
                    elif gm.value(subject=restriccio, predicate=RDF.type) == ONTO.RestriccioCategoria:
                        categoria = gm.value(subject=restriccio, predicate=ONTO.Categoria)
                        logger.info('BÚSQUEDA->Restriccion de Categoria: ' + str(categoria))
                        restriccions_dict['categoria'] = str(categoria)
                        """""

                gr = buscar_productos(**restriccions_dict)

    return gr.serialize(format='xml'), 200


@app.route("/Stop")
def stop():
    """
    Entrypoint que para el agente

    :return:
    """
    tidyup()
    shutdown_server()
    return "Parando Servidor"


def tidyup():
    """
    Acciones previas a parar el agente

    """
    pass


def agentbehavior1(cola):
    """
    Un comportamiento del agente

    :return:
    """
    pass


def buscar_productos(valoracio=0.0, marca=None, preciomin=0.0, preciomax=sys.float_info.max, nombre=None):
    graph = Graph()
    endpoint_url = "http://localhost:3030/ONTO/query"

    query = f"""
        PREFIX rdf: <http://www.w3.org/1999/02/22-rdf-syntax-ns#>
        PREFIX ex: <http://www.semanticweb.org/nilde/ontologies/2024/4/>

        SELECT ?producte ?categoria ?nom ?pes ?preu ?marca ?valoracio
        WHERE {{
            ?producte rdf:type ex:Producte .
            OPTIONAL {{ ?producte ex:Categoria ?categoria . }}
            OPTIONAL {{ ?producte ex:Nom ?nom . }}
            OPTIONAL {{ ?producte ex:Pes ?pes . }}
            OPTIONAL {{ ?producte ex:Preu ?preu . }}
            OPTIONAL {{ ?producte ex:Marca ?marca . }}
            OPTIONAL {{ ?producte ex:Valoracio ?valoracio . }}
        }}
    """

    print(query)


    # Crear el objeto SPARQLWrapper y establecer la consulta
    sparql = SPARQLWrapper(endpoint_url)
    sparql.setQuery(query)
    sparql.setReturnFormat(JSON)

    # Ejecutar la consulta y obtener los resultados
    try:
        results = sparql.query().convert()

        # Añadir los resultados JSON al gráfico RDF
        for result in results["results"]["bindings"]:
            producte = URIRef(result["producte"]["value"])
            graph.add((producte, RDF.type, ONTO.Producte))

            if "categoria" in result:
                graph.add((producte, ONTO.Categoria, Literal(result["categoria"]["value"])))
            if "nom" in result:
                graph.add((producte, ONTO.Nom, Literal(result["nom"]["value"])))
            if "pes" in result:
                graph.add((producte, ONTO.Pes, Literal(result["pes"]["value"])))
            if "preu" in result:
                graph.add((producte, ONTO.Preu, Literal(result["preu"]["value"])))
            if "marca" in result:
                graph.add((producte, ONTO.Marca, Literal(result["marca"]["value"])))
            if "valoracio" in result:
                graph.add((producte, ONTO.Valoracio, Literal(result["valoracio"]["value"])))

        return graph
    except Exception as e:
        print(f"Error al ejecutar la consulta: {e}")
    return "Error en la consulta SPARQL", 500
    # Si no es la acción esperada o hay algún otro problema, devolver un mensaje adecuado





if __name__ == '__main__':
    # Ponemos en marcha los behaviors
    ab1 = Process(target=agentbehavior1, args=(cola1,))
    ab1.start()

    # Ponemos en marcha el servidor
    app.run(host=hostname, port=port)

    # Esperamos a que acaben los behaviors
    ab1.join()
    print('The End')
