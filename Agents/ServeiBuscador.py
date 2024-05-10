from flask import Flask, request, jsonify
from rdflib import Graph, Literal, URIRef, RDF, XSD, Namespace
from rdflib.namespace import FOAF, RDF
import logging
import requests

FUSEKI_SERVER = "http://localhost:3030"  # Cambia esto por la URL de tu servidor Fuseki
DATASET_NAME = "myDataset"  # Cambia esto por el Nom de tu dataset en Fuseki

# Configuración del logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger('ServeiBuscador')


# Configuración inicial del agente
class Agent:
    def __init__(self, name, uri, address, stop):
        self.name = name
        self.uri = uri
        self.address = address
        self.stop = stop
        self.message_count = 0

    def get_count(self):
        self.message_count += 1
        return self.message_count


# Creación del agente
ServeiBuscador = Agent(
    'ServeiBuscador',
    'http://www.agentes.org#ServeiBuscador',
    'http://localhost:5000/comm',
    'http://localhost:5000/Stop'
)

app = Flask(__name__)

# Namespace para la ontología utilizada (ajustar según sea necesario)
ONT = Namespace("http://www.owl-ontologies.com/OntologiaECSDI.owl#")


def process_action(gm, msgdic):
    """
    Procesa la acción requerida por el mensaje ACL recibido.
    """
    content = msgdic['content']
    action = gm.value(subject=content, predicate=RDF.type)
    if action == ONT.BuscarProductes:
        return handle_search_products(gm, content)
    else:
        return build_message(Graph(), 'not-understood', ServeiBuscador.uri, ServeiBuscador.get_count())


def handle_search_products(gm, content):
    """
    Procesa la petición de búsqueda de productos aplicando las Restriccioes dadas.
    """
    restrictions = {}
    for restriction in gm.objects(content, ONT.RestringidaPor):
        if gm.value(restriction, RDF.type) == ONT.RestriccioMarca:
            restrictions['Marca'] = str(gm.value(restriction, ONT.Marca))
        elif gm.value(restriction, RDF.type) == ONT.RestriccioNom:
            restrictions['Nom'] = str(gm.value(restriction, ONT.Nom))
        elif gm.value(restriction, RDF.type) == ONT.RestriccioPreu:
            min_price = gm.value(restriction, ONT.PreuMin)
            max_price = gm.value(restriction, ONT.PreuMax)
            restrictions['PreuMin'] = float(min_price)
            restrictions['PreuMax'] = float(max_price)
        elif gm.value(restriction, RDF.type) == ONT.RestriccioValoracio:
            restrictions['Valoracio'] = float(gm.value(restriction, ONT.Valoracio))

    # Realiza la búsqueda de productos según las Restricciones procesadas
    results = search_products(restrictions)
    response_graph = build_response_graph(results)
    return response_graph


def search_products(restrictions):
    """
    Realiza la búsqueda de productos en la base de datos o triplestore según las Restriccioes.
    Aquí se debería implementar una consulta SPARQL o un acceso a base de datos.
    """
    """
        Realiza la búsqueda de productos en Apache Jena Fuseki según las Restriccioes dadas.
        """
    query = build_sparql_query(restrictions)
    url = f"{FUSEKI_SERVER}/{DATASET_NAME}/query"
    headers = {
        "Content-Type": "application/sparql-query",
        "Accept": "application/sparql-results+json"
    }
    response = requests.post(url, data=query, headers=headers)

    if response.status_code == 200:
        results = response.json()
        return parse_sparql_results(results)
    else:
        logger.error(f"Error en la consulta SPARQL: {response.status_code}")
        return []

    # Ejemplo de resultados, deberías reemplazar esto con una consulta real
    #return [{'uri': 'http://example.org/product/1', 'Nom': 'Producto 1', 'Preu': 100, 'Marca': 'Marca A','Valoracio': 5}]


def build_sparql_query(restrictions):
    """
    Construye una consulta SPARQL basada en las Restriccioes dadas.
    """
    base_query = """
    PREFIX ns: <http://www.owl-ontologies.com/OntologiaECSDI.owl#>
    SELECT ?producto ?Nom ?Preu ?Marca ?Valoracio WHERE {
        ?producto rdf:type ns:Producto.
        ?producto ns:Nom ?Nom.
        ?producto ns:Preu ?Preu.
        ?producto ns:Marca ?Marca.
        ?producto ns:Valoracio ?Valoracio.
    """
    filters = []

    if 'Marca' in restrictions:
        filters.append(f"?Marca = '{restrictions['Marca']}'")
    if 'Nom' in restrictions:
        filters.append(f"CONTAINS(LCASE(str(?Nom)), LCASE('{restrictions['Nom']}'))")
    if 'PreuMin' in restrictions and 'PreuMax' in restrictions:
        filters.append(f"?Preu >= {restrictions['PreuMin']} && ?Preu <= {restrictions['PreuMax']}")
    if 'Valoracio' in restrictions:
        filters.append(f"?Valoracio >= {restrictions['Valoracio']}")

    if filters:
        base_query += "FILTER (" + " && ".join(filters) + ")"

    base_query += "}"
    return base_query


def parse_sparql_results(results):
    """
    Parsea los resultados de una consulta SPARQL en formato JSON.
    """
    parsed_results = []
    for result in results['results']['bindings']:
        producto = {
            'uri': result['Producte']['value'],
            'Nom': result['Nom']['value'],
            'Preu': float(result['Preu']['value']),
            'Marca': result['Marca']['value'],
            'Categoria': result['Categoria']['value'],
            'Pes': float(result['Pes']['value']),
            'Valoracio': float(result['Valoracio']['value'])
        }
        parsed_results.append(producto)
    return parsed_results

def build_response_graph(results):
    """
    Construye un grafo RDF con los resultados de la búsqueda para enviar como respuesta.
    """
    g = Graph()
    for result in results:
        prod_uri = URIRef(result['uri'])
        g.add((prod_uri, RDF.type, ONT.Producte))
        g.add((prod_uri, ONT.Nom, Literal(result['Nom'])))
        g.add((prod_uri, ONT.Preu, Literal(result['Preu'], datatype=XSD.decimal)))
        g.add((prod_uri, ONT.Marca, Literal(result['Marca'])))
        g.add((prod_uri, ONT.Categoria, Literal(result['Categoria'])))
        g.add((prod_uri, ONT.Pes, Literal(result['Pes'], datatype=XSD.decimal)))
        g.add((prod_uri, ONT.Valoracio, Literal(result['Valoracio'], datatype=XSD.decimal)))
    return g


@app.route("/comm", methods=['POST'])
def communication():
    """
    Communication entry point for the agent.
    """
    logger.info('Request received at /comm')
    data = request.data
    gm = Graph()
    gm.parse(data=data)

    msgdic = {}  # Suponemos que esta función extrae las propiedades del mensaje correctamente
    gr = process_action(gm, msgdic)
    return gr.serialize(format='xml'), 200


@app.route("/Stop", methods=['GET'])
def stop():
    """
    Stop the agent and the server.
    """
    # Define o implementa esta función para cerrar el servidor correctamente
    logger.info("Shutting down the server.")
    return "Server is shutting down...", 200


if __name__ == '__main__':
    app.run(port=5000, debug=True)
