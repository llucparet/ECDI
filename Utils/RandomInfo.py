import random
import string

import requests
from rdflib import Graph, Literal, RDF, URIRef, Namespace
from rdflib.namespace import XSD

# Crear un grafo RDF
g = Graph()

# Definir la ontología y sus namespaces
NS = Namespace("http://www.semanticweb.org/nilde/ontologies/2024/4/")
g.bind("ns", NS)

# Definir categorías y marcas
categories = ["Phone", "Blender", "Computer"]
brands = ["Apple", "Samsung", "Xiaomi"]
brands2 = ["Bosch", "Philips", "Taurus"]
brands3 = ["Apple", "HP", "Lenovo"]

centros_logisticos = ["http://www.semanticweb.org/ecsdi/ontologies/2024/4/Banyoles",
                      "http://www.semanticweb.org/ecsdi/ontologies/2024/4/Barcelona",
                      "http://www.semanticweb.org/ecsdi/ontologies/2024/4/Tarragona",
                      "http://www.semanticweb.org/ecsdi/ontologies/2024/4/Valencia",
                      "http://www.semanticweb.org/ecsdi/ontologies/2024/4/Zaragoza"]

# Función para generar un ID único
def generate_id():
    return f"P{random.randint(1000, 9999)}"

def random_name(prefix, size=6, chars=string.ascii_uppercase + string.digits):
    """
    Genera un nombre aleatorio a partir de un prefijo, una longitud y una lista con los caracteres a usar
    en el nombre
    :param prefix:
    :param size:
    :param chars:
    :return:
    """
    return prefix + '_' + ''.join(random.choice(chars) for _ in range(size))
if __name__ == '__main__':
    # Crear instancias de productos aleatorios
    for cat in categories:
        for _ in range(20):
            product_id = generate_id()
            category = cat
            valoracion = round(random.uniform(1, 5), 2)
            if category == "Phone":
                brand = random.choice(brands)
                name = random_name(brand)
                weight = round(random.uniform(200, 400), 2)
                price = round(random.uniform(50, 600), 2)
            elif category == "Blender":
                brand = random.choice(brands2)
                name = random_name(brand)
                weight = round(random.uniform(25, 100), 2)
                price = round(random.uniform(500, 1000), 2)
            else:
                brand = random.choice(brands3)
                name = random_name(brand)
                weight = round(random.uniform(450, 3000), 2)
                price = round(random.uniform(1000, 2500), 2)


            product = URIRef(NS[product_id])

            g.add((product, RDF.type, NS.Producte))
            g.add((product, NS.ID, Literal(product_id, datatype=XSD.string)))
            g.add((product, NS.Categoria, Literal(category, datatype=XSD.string)))
            g.add((product, NS.Marca, Literal(brand, datatype=XSD.string)))
            g.add((product, NS.Nom, Literal(name, datatype=XSD.string)))
            g.add((product, NS.Pes, Literal(weight, datatype=XSD.float)))
            g.add((product, NS.Preu, Literal(price, datatype=XSD.float)))
            g.add((product, NS.Valoracio, Literal(valoracion, datatype=XSD.float)))

            # Añadir el producto a un centro logístico

            ncentres = int(random.uniform(1, 5))
            numeros_disponibles = list(range(1, 5))
            numeros_aleatorios = random.sample(numeros_disponibles, ncentres)
            for num in numeros_aleatorios:
                centro_logistico = centros_logisticos[num]
                centro = URIRef(centro_logistico)
                g.add((product, NS.ProductesCentreLogistic, centro))
    # Guardar el grafo en formato RDF/XML
    g.serialize(destination="productos.rdf", format="xml")
    
    print("Se han generado instancias de productos aleatorios y se han guardado en 'productos.rdf'")
    # Serializar el grafo a formato RDF/XML
    rdf_xml_data = g.serialize(format='xml')

    # URL del endpoint de Fuseki (cambia esto por la URL de tu instancia de Fuseki y el nombre de tu dataset)
    fuseki_url = 'http://localhost:3030/ONTO/data'  # Cambia 'dataset' por el nombre de tu dataset

    # Cabeceras para la solicitud
    headers = {
        'Content-Type': 'application/rdf+xml'  # Cambiado a 'application/rdf+xml'
    }

    # Enviamos los datos a Fuseki
    response = requests.post(fuseki_url, data=rdf_xml_data, headers=headers)

    # Verificamos la respuesta
    if response.status_code == 200:
        print('Datos subidos exitosamente a Fuseki')
    else:
        print(f'Error al subir los datos a Fuseki: {response.status_code} - {response.text}')