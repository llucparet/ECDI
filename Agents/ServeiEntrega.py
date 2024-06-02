from multiprocessing import Queue, Process

from SPARQLWrapper import RDF, SPARQLWrapper, JSON
from flask import Flask, request
from pyparsing import Literal
from rdflib import Namespace, Literal, URIRef, XSD, Graph
from Utils.ACLMessages import *
from Utils.Agent import Agent
from Utils.Logger import config_logger
from Utils.OntoNamespaces import ONTO
from Utils.ACL import ACL
from geopy.geocoders import Nominatim
from geopy.distance import great_circle, geodesic


from Utils.ACLMessages import build_message, send_message, get_message_properties

logger = config_logger(level=1)

# Configuration stuff
hostname = "localhost"
port = 8000

agn = Namespace("http://www.agentes.org#")

# Contador de mensajes
mss_cnt = 0
endpoint_url = "http://localhost:3030/ONTO/query"

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
def asignar_port_centre_logistic(port):
    portcentrelogistic = port
    ServeiCentreLogistic = Agent('ServeiCentreLogistic',
                                 agn.ServeiCentreLogistic,
                                 'http://%s:%d/comm' % (hostname, portcentrelogistic),
                                 'http://%s:%d/Stop' % (hostname, portcentrelogistic))
    return ServeiCentreLogistic


# Global triplestore graph
dsgraph = Graph()

cola1 = Queue()

# Flask stuff
app = Flask(__name__)

def get_count():
    global mss_cnt
    mss_cnt += 1
    return mss_cnt


@app.route("/comm")
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
    global graph_compra
    global precio_total_compra, mss_cnt
    gr = Graph()

    if msgdic is None:
        # Si no es, respondemos que no hemos entendido el mensaje
        gr = build_message(Graph(), ACL['not-understood'], sender=AgentAssistent.uri, msgcnt=get_count())

    else:
        # Obtenemos la performativa
        if msgdic['performative'] != ACL.request:
            # Si no es un request, respondemos que no hemos entendido el mensaje
            gr = build_message(Graph(),
                               ACL['not-understood'],
                               sender=AgentAssistent.uri,
                               msgcnt=get_count())

        else:

            content = msgdic['content']

            accion = gm.value(subject=content, predicate=RDF.type)
            print(accion)
            count = get_count()
            # Accion de hacer pedido
            if accion == ONTO.InformarEnviament:

                print("Enviament informat")
                #aqui em retorna el dni de l'usuari i gurdo la comanda
                llista_porductes = []
                dni = ""
                comanda = ""
                data = ""
                transportista = ""
                gg = Graph()
                for s, p, o in gm:
                    if p == ONTO.DNI:
                        dni = o
                    elif p == ONTO.ComandaLot:
                        comanda = o
                    elif p == ONTO.ProducteLot:
                        llista_porductes.append(o)
                        gr.add((o, RDF.type, ONTO.Producte))
                        nom = gm.value(subject=o, predicate=ONTO.Nom)
                        gr.add((o, ONTO.Nom, nom))
                    elif p == ONTO.Data:
                        data = o
                        gr.add((accion, ONTO.Data, o))
                    elif p == ONTO.Transportista:
                        transportista = gm.value(subject=o, predicate=ONTO.Nom)
                        gr.add((accion, ONTO.Transportista, o))
                    elif p == ONTO.Preu:
                        gg.add((accion, ONTO.Preu, o))
                gr.add((accion, RDF.type, ONTO.InformarEnviament))
                msg = build_message(gr, ACL.request, ServeiEntrega.uri, AgentAssistent.uri, accion,
                                    get_count())
                resposta = send_message(msg, AgentAssistent.address)
                print("Enviament informat2")
                print(llista_porductes)
                print(comanda)
                print(data)
                print(transportista)
                print(dni)

                for producte in llista_porductes:
                    print("Enviament informat3")
                    # Construir les consultes SPARQL

                    sparql_query = f"""
                                        PREFIX rdf: <http://www.w3.org/1999/02/22-rdf-syntax-ns#>
                                        PREFIX ont: <http://www.semanticweb.org/nilde/ontologies/2024/4/>
                                        SELECT ?nom
                                        WHERE {{
                                            ?producte rdf:type ont:Producte .
                                            VALUES ?producte {{ <{producte}> }}
                                            ?producte ont:Nom ?nom .
                                          }}
                                      """

                    print(sparql_query)
                    # Crear el objeto SPARQLWrapper y establecer la consulta
                    sparql = SPARQLWrapper(endpoint_url)
                    sparql.setQuery(sparql_query)
                    sparql.setReturnFormat(JSON)
                    results = sparql.query().convert()
                    print(results["results"]["bindings"])
                    producte_result= results["results"]["bindings"][0]
                    nom_producte = producte_result["nom"]["value"]
                    print(nom_producte)

                    fuseki_url = 'http://localhost:3030/ONTO/update'


                    # Defineix la consulta SPARQL amb les variables
                    sparql_query = f"""
                    PREFIX ontologies: <http://www.semanticweb.org/nilde/ontologies/2024/4/>
                    PREFIX xsd: <http://www.w3.org/2001/XMLSchema#>

                    DELETE {{
                        ?producteComanda ontologies:Data ?oldData .
                        ?producteComanda ontologies:Pagat ?oldPagat .
                        ?producteComanda ontologies:TransportistaProducte ?oldTransportista .
                    }}
                    INSERT {{
                        ?producteComanda ontologies:Data "{data}"^^xsd:date .
                        ?producteComanda ontologies:Pagat true .
                        ?producteComanda ontologies:TransportistaProducte "{transportista}" .
                    }}
                    WHERE {{
                        <{comanda}> ontologies:ProductesComanda ?producteComanda .
                        ?producteComanda ontologies:Nom "{nom_producte}" .

                        OPTIONAL {{ ?producteComanda ontologies:Data ?oldData . }}
                        OPTIONAL {{ ?producteComanda ontologies:Pagat ?oldPagat . }}
                        OPTIONAL {{ ?producteComanda ontologies:TransportistaProducte ?oldTransportista . }}
                    }}
                    """

                    # Defineix els encapçalaments HTTP
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

                return gg.serialize(format="xml"),200

                """
                acction = ONTO["CobrarProductes_"+ str(count)]
                gm.add((accion, RDF.type, acction))
                msg = build_message(gr, ACL.request, ServeiEntrega.uri, AgentPagaments.uri, acction,
                                    get_count())
                resposta = send_message(msg, AgentPagaments.address)
                """
                #aqui guardo que ha fet el pagament






if __name__ == '__main__':
    # Ponemos en marcha el servidor
    app.run(host=hostname, port=port)