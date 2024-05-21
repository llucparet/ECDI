from flask import Flask, request
from rdflib import Graph, URIRef, Namespace, RDF
from SPARQLWrapper import SPARQLWrapper, JSON
import logging

from Utils.OntoNamespaces import ONTO

# Inicializar la aplicación Flask
app = Flask(__name__)

# Configurar el registro (logging)
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Definir los prefijos RDF
RDF_TYPE = RDF.type

@app.route("/comm")
def communication():
    # URL de tu servidor Fuseki
    global centre_logistic
    endpoint_url = "http://localhost:3030/ONTO/query"

    # Consulta SPARQL
    sparql_query = """
    PREFIX rdf: <http://www.w3.org/1999/02/22-rdf-syntax-ns#>
    PREFIX ont: <http://www.semanticweb.org/nilde/ontologies/2024/4/>
    SELECT ?ciudad
    WHERE {
      ?centroLogistico rdf:type ont:CentreLogistic .
      ?centroLogistico ont:Ciutat ?ciudad .
    }
   """

    # Crear el objeto SPARQLWrapper y establecer la consulta
    sparql = SPARQLWrapper(endpoint_url)
    sparql.setQuery(sparql_query)
    sparql.setReturnFormat(JSON)

    # Ejecutar la consulta y obtener los resultados
    try:
        try:
            results = sparql.query().convert()
            centre_logistic = None
            """
            for result in results["results"]["bindings"]:
                centre_logistic = result["ciudad"]["value"]
            return centre_logistic, 200
            """
            return results, 200
        except Exception as e:
            print(f"Error al ejecutar la consulta: {e}")
        return "Error en la consulta SPARQL", 500
    # Si no es la acción esperada o hay algún otro problema, devolver un mensaje adecuado
    except:
        return "Petición no entendida", 400

if __name__ == "__main__":
    app.run(debug=True)
