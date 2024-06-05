import random
import string
from datetime import datetime, timedelta
import requests
from rdflib import Graph, Literal, RDF, URIRef, Namespace
from rdflib.namespace import XSD

# Crear un grafo RDF
g = Graph()

mss_cnt = 899

def get_count():
    global mss_cnt
    mss_cnt += 1
    return mss_cnt

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
                      "http://www.semanticweb.org/ecsdi/ontologies/2024/Valencia",
                      "http://www.semanticweb.org/ecsdi/ontologies/2024/Zaragoza"]

venedors_externs = {
    "Nike": "ESBN00909191",
    "IKEA": "ESBN0123442212",
    "Zara": "ESBN91120302102"
}

transportistas = ["Transportista1", "Transportista2", "Transportista3"]

# Función para generar un ID único
def generate_id():
    return f"P{random.randint(1000, 9999)}"

def random_name(prefix, size=6, chars=string.ascii_uppercase + string.digits):
    return prefix + '_' + ''.join(random.choice(chars) for _ in range(size))

def generar_productos_aleatorios(g, num_productos=60):
    productos = []
    for cat in categories:
        for _ in range(num_productos // len(categories)):
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
            g.add((product, NS.Empresa, Literal("ECDI", datatype=XSD.string)))
            productos.append({
                'ID': product_id,
                'Nom': name,
                'Preu': price,
                'Pes': weight,
                'Categoria': category,
                'Marca': brand,
                'Valoracio': valoracion,
                'Empresa': "ECDI"
            })

            ncentres = int(random.uniform(1, 5))
            numeros_disponibles = list(range(1, 5))
            numeros_aleatorios = random.sample(numeros_disponibles, ncentres)
            for num in numeros_aleatorios:
                centro_logistico = centros_logisticos[num]
                centro = URIRef(centro_logistico)
                g.add((product, NS.ProductesCentreLogistic, centro))

    return productos

def generar_comandas_aleatorias(g, productos, dni_cliente='41', num_comandas=5):
    for i in range(num_comandas):
        comanda_id = 'Comanda' + str(get_count())
        ciutat = random.choice(['Barcelona', 'Madrid', 'Valencia', 'Sevilla', 'Zaragoza'])
        preu_total = random.uniform(100, 1000)
        prioritat = random.choice([1, 2, 3])
        credit_card = ''.join(random.choices('0123456789', k=16))

        products = random.sample(productos, 4)

        comanda = URIRef(NS[comanda_id])
        g.add((comanda, RDF.type, NS.Comanda))
        g.add((comanda, NS.ID, Literal(comanda_id, datatype=XSD.string)))
        g.add((comanda, NS.Ciutat, Literal(ciutat, datatype=XSD.string)))
        g.add((comanda, NS.Client, URIRef(NS[dni_cliente])))
        g.add((comanda, NS.PreuTotal, Literal(preu_total, datatype=XSD.float)))
        g.add((comanda, NS.Prioritat, Literal(prioritat, datatype=XSD.integer)))
        g.add((comanda, NS.TargetaCredit, Literal(credit_card, datatype=XSD.string)))

        for producte in products:
            producte_comanda_id = f"{comanda_id}_ProducteComanda_{producte['ID']}"
            producte_comanda_uri = URIRef(NS[producte_comanda_id])

            transportista = random.choice(transportistas)
            fecha_transporte = (datetime.now() - timedelta(days=random.randint(0, 60))).date()

            g.add((producte_comanda_uri, RDF.type, NS.ProducteComanda))
            g.add((producte_comanda_uri, NS.Nom, Literal(producte['Nom'], datatype=XSD.string)))
            g.add((producte_comanda_uri, NS.Preu, Literal(producte['Preu'], datatype=XSD.float)))
            g.add((producte_comanda_uri, NS.Data, Literal(fecha_transporte, datatype=XSD.date)))
            g.add((producte_comanda_uri, NS.Pagat, Literal(random.choice([True, False]), datatype=XSD.boolean)))
            g.add((producte_comanda_uri, NS.Enviat, Literal(random.choice([True, False]), datatype=XSD.boolean)))
            g.add((producte_comanda_uri, NS.Retornat, Literal("Pendiente", datatype=XSD.string)))
            g.add((producte_comanda_uri, NS.TransportistaProducte, Literal(transportista, datatype=XSD.string)))
            g.add((producte_comanda_uri, NS.Empresa, Literal(producte['Empresa'], datatype=XSD.string)))
            g.add((producte_comanda_uri, NS.Valoracio, Literal('Pendiente')))
            g.add((producte_comanda_uri, NS.Pes, Literal(producte['Pes'], datatype=XSD.float)))
            g.add((producte_comanda_uri, NS.Categoria, Literal(producte['Categoria'], datatype=XSD.string)))
            g.add((producte_comanda_uri, NS.Marca, Literal(producte['Marca'], datatype=XSD.string)))
            g.add((comanda, NS.ProductesComanda, producte_comanda_uri))


if __name__ == '__main__':
    for venedor, compte in venedors_externs.items():
        venedor_uri = URIRef(NS[venedor])
        g.add((venedor_uri, RDF.type, NS.VenedorExtern))
        g.add((venedor_uri, NS.Nom, Literal(venedor, datatype=XSD.string)))
        g.add((venedor_uri, NS.CompteBancari, Literal(compte, datatype=XSD.string)))

    productos = generar_productos_aleatorios(g, num_productos=60)
    generar_comandas_aleatorias(g, productos, dni_cliente='41', num_comandas=10)

    g.serialize(destination="productos.rdf", format="xml")

    print("Se han generado instancias de productos aleatorios y se han guardado en 'productos.rdf'")

    rdf_xml_data = g.serialize(format='xml')

    fuseki_url = 'http://localhost:3030/ONTO/data'

    headers = {
        'Content-Type': 'application/rdf+xml'
    }

    response = requests.post(fuseki_url, data=rdf_xml_data, headers=headers)

    if response.status_code == 200:
        print('Datos subidos exitosamente a Fuseki')
    else:
        print(f'Error al subir los datos a Fuseki: {response.status_code} - {response.text}')
