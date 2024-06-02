import random

import flask
import requests
from SPARQLWrapper import SPARQLWrapper, JSON
from flask import Flask, request, render_template, redirect, url_for
from rdflib import Namespace, Graph, RDF, Literal, URIRef

from Utils.ACL import ACL
from Utils.ACLMessages import build_message, get_message_properties, send_message
from Utils.Agent import Agent
from Utils.Logger import config_logger
from Utils.OntoNamespaces import ONTO
import socket
from multiprocessing import Queue, Process


# Configuración de logging
logger = config_logger(level=1)

# Configuración del agente
hostname = "localhost"
port = 9011

# Namespaces para RDF
agn = Namespace("http://www.agentes.org#")

# Instancia del Flask app
app = Flask(__name__, template_folder='../Utils/templates')

# Agentes del sistema
AgentAssistent = Agent('AgentAssistent', agn.AgentAssistent, f'http://{hostname}:{port}/comm', f'http://{hostname}:{port}/Stop')
ServeiBuscador = Agent('ServeiBuscador', agn.ServeiBuscador, f'http://{hostname}:8003/comm', f'http://{hostname}:8003/Stop')
ServeiComandes = Agent('ServeiComandes', agn.ServeiComandes, f'http://{hostname}:8012/comm', f'http://{hostname}:9012/Stop')

cola1 = Queue()

# Variables globales
mss_cnt = 0
productos_recomendados = []
products_list = []
DNIusuari = ""
usuari= ""
completo = False


productes_enviats = []

@app.route("/", methods=['GET', 'POST'])
def initialize():
    global DNIusuari, productos_recomendados, products_list, completo, info_bill, productes_enviats
    if request.method == 'GET':
        if DNIusuari:
            if productes_enviats:
                aux = productes_enviats
                productes_enviats = []
                return render_template('home.html', products=aux, usuario=DNIusuari, recomendacion=False,notificacio=True)
            elif not productos_recomendados:
                return render_template('home.html', products=None, usuario=DNIusuari, recomendacion=False,notificacio=False)
            else:
                return render_template('home.html', products=productos_recomendados, usuario=DNIusuari, recomendacion=True,notificacio=False)
        else:
            return render_template('usuari.html')
    elif request.method == 'POST':
        if 'submit' in request.form and request.form['submit'] == 'registro_usuario':
            DNIusuari = request.form['DNI']

            g = Graph()
            g.bind('ns', ONTO)
            client = URIRef(ONTO[DNIusuari])
            g.add((client, RDF.type, ONTO.Client))
            g.add((client, ONTO.DNI, Literal(DNIusuari)))
            rdf_xml_data = g.serialize(format='xml')
            fuseki_url = 'http://localhost:3030/ONTO/data'  # Cambia 'dataset' por el nombre de tu dataset

            # Cabeceras para la solicitud
            headers = {
                'Content-Type': 'application/rdf+xml'  # Cambiado a 'application/rdf+xml'
            }

            # Enviamos los datos a Fuseki
            response = requests.post(fuseki_url, data=rdf_xml_data, headers=headers)
            print (response)
            return render_template('home.html', products=None, usuario=DNIusuari)
        elif 'submit' in request.form and request.form['submit'] == 'search_products':
            return flask.redirect("http://%s:%d/search_products" % (hostname, port))

@app.route("/comm")
def comunicacion():
    """
    Entrypoint de comunicacion
    """
    message = request.args['content']
    gm = Graph()
    gm.parse(data=message, format='xml')

    msgdic = get_message_properties(gm)

    gr = Graph()
    global mss_cnt
    if msgdic is None:
        mss_cnt+=1
        # Si no es, respondemos que no hemos entendido el mensaje
        gr = build_message(Graph(), ACL['not-understood'], sender=AgentAssistent.uri, msgcnt=str(mss_cnt))
    else:
        # Obtenemos la performativa
        if msgdic['performative'] != ACL.request:
            # Si no es un request, respondemos que no hemos entendido el mensaje
            gr = build_message(Graph(),
                               ACL['not-understood'],
                               sender=AgentAssistent.uri,
                               msgcnt=str(mss_cnt))
        else:
            # Extraemos el objeto del contenido que ha de ser una accion de la ontologia
            # de registro
            content = msgdic['content']
            # Averiguamos el tipo de la accion
            accion = gm.value(subject=content, predicate=RDF.type)
            print(accion)
            if accion == ONTO.InformarEnviament:
                logger.info("enviament començat")
                for s,p,o in gm:
                    if p == ONTO.Nom:
                        productes_enviats.append(str(o))

                print(productes_enviats)
                gr.add((accion, RDF.type, ONTO.InformarEnviament))
                gr.add((accion, ONTO.DNI, Literal(DNIusuari)))
                return gr.serialize(format="xml"),200
            """
            if accion == ONTO.ProcesarEnvio:
                global grafo_respuesta
                grafo_respuesta = gm
                global completo
                completo = True
                gr = Graph()
                return gr.serialize(format="xml"),200

            # Accion de valorar
            elif accion == ONTO.ValorarProducto:
                gr =Graph()
                return gr.serialize(format="xml"),200

            elif accion == ONTO.ConfirmarValoracion:
                global productos_valorar_no_permitido
                for s,p,o in gm:
                    if p == ONTO.Nombre:
                        if str(o) in productos_valorar_no_permitido:
                            productos_valorar_no_permitido.remove(str(o))
                gr = Graph()
                return gr.serialize(format="xml"),200
            elif accion == ONTO.RecomendarProducto:
                subjects_productos_usuari = []
                for s,p,o in gm:
                    if p == ONTO.DNI and str(o) == nombreusuario:
                        subjects_productos_usuari.append(str(s))
                global productos_recomendados
                productos_recomendados = []
                for s,p,o in gm:
                    if str(s) in subjects_productos_usuari:
                        if p == ONTO.Nombre:
                            productos_recomendados.append(str(o))
                gr = Graph()
                return gr.serialize(format="xml"),200
"""
@app.route("/hacer_pedido", methods=['GET', 'POST'])
def hacer_pedido():
    global products_list, completo, info_bill
    if request.method == 'GET':
        # Mostrar los productos seleccionados para confirmar la compra
        return render_template('novaComanda.html', products=products_list, bill=None, intento=False, completo=False,
                               campos_error=False)
    else:
        if request.form['submit'] == 'Comprar':
            city = request.form['city']
            priority = request.form['priority']
            creditCard = request.form['creditCard']
            # Validar la entrada del formulario
            if city == "" or priority == "" or creditCard == "" or priority not in ["1", "2", "3"]:
                return render_template('novaComanda.html', products=products_list, bill=None, intento=False,
                                       completo=False, campos_error=True)

            products_to_buy = [products_list[int(p)] for p in request.form.getlist("checkbox") if
                               p.isdigit() and int(p) < len(products_list)]
            if not products_to_buy:
                # Si no se seleccionaron productos, también muestra un mensaje de error
                return render_template('novaComanda.html', products=products_list, bill=None, intento=False,
                                       completo=False, campos_error=True)

            # Procesa la compra y genera una "factura"
            comanda = realizar_compra(products_to_buy, city, priority, creditCard)
            completo = True  # Indica que la compra se ha completado
            return render_template('novaComanda.html', products=None, comanda=comanda, intento=False, completo=completo)
        elif request.form['submit'] == "Volver a buscar":
            return redirect(url_for('search_products'))


def realizar_compra(products_to_buy, city, priority, creditCard):
    global mss_cnt
    g = Graph()
    action = ONTO['ComprarProductes_' + str(mss_cnt)]
    g.add((action, RDF.type, ONTO.ComprarProductes))
    g.add((action, ONTO.Ciutat, Literal(city)))
    g.add((action, ONTO.Prioritat, Literal(priority)))
    g.add((action, ONTO.TargetaCredit, Literal(creditCard)))
    g.add((action, ONTO.DNI, Literal(DNIusuari)))

    for p in products_to_buy:
        producte = URIRef(p['Producte'])
        g.add((producte, RDF.type, ONTO.Producte))# Asumiendo que 'url' es una URI válida para el producto
        g.add((producte, ONTO.Nom, Literal(p['Nom'])))
        g.add((producte, ONTO.Preu, Literal(p['Preu'])))
        g.add((producte, ONTO.Pes, Literal(p['Pes'])))
        g.add((action, ONTO.Compra, producte))
    # Send the GET request with a timeout
    msg = build_message(g, ACL.request, AgentAssistent.uri, ServeiComandes.uri, action, mss_cnt)
    mss_cnt += 1
    resposta = send_message(msg, ServeiComandes.address)
    comanda_info = {}
    products = []
    for s, p, o in resposta:
        if p == ONTO.Ciutat:
            comanda_info['city'] = o
        if p == ONTO.Prioritat:
            comanda_info['priority'] = o
        if p == ONTO.TargetaCredit:
            comanda_info['creditCard'] = o
        if p == ONTO.Data:
            comanda_info['date'] = o
        if p == ONTO.PreuTotal:
            comanda_info['total'] = o
        if p == ONTO.ProductesComanda:
            #productos_valorar_no_permitido.append(str(o))
            values = "".join(f"<{o}> ")
            endpoint_url = "http://localhost:3030/ONTO/query"
            sparql_query = f"""
                               PREFIX rdf: <http://www.w3.org/1999/02/22-rdf-syntax-ns#>
                               PREFIX ont: <http://www.semanticweb.org/nilde/ontologies/2024/4/>
                               SELECT ?nom ?preu
                               WHERE {{
                                    ?producte rdf:type ont:Producte .
                                     ?producte ont:Nom ?nom .
                                        ?producte ont:Preu ?preu .
                                     VALUES ?producte {{{values}}}
                               }}
                              """
            sparql = SPARQLWrapper(endpoint_url)
            sparql.setQuery(sparql_query)
            sparql.setReturnFormat(JSON)
            results = sparql.query().convert()
            product = {"Nom": results['results']['bindings'][0]['nom']['value'],"Preu": results['results']['bindings'][0]['preu']['value']}
            products.append(product)
    comanda_info['Products'] = products
    return comanda_info


@app.route("/search_products", methods=['GET', 'POST'])
def search_products():
    global DNIusuari
    if request.method == 'GET':
        return render_template('busquedaProductes.html', products=None, usuario=DNIusuari, busquedafallida=False, errorvaloracio=False)
    else:
        if request.form['submit'] == 'Buscar':
            global products_list
            Nom = request.form['Nom']
            PreuMin = request.form['PreuMin']
            PreuMax = request.form['PreuMax']
            Marca = request.form['Marca']
            Valoracio = request.form['Valoracio']
            Categoria = request.form.get('Categoria')
            products_list = buscar_productos(Nom, PreuMin, PreuMax, Marca, Valoracio, Categoria)
            if len(products_list) == 0:
                return render_template('busquedaProductes.html', products=None, usuario=DNIusuari, busquedafallida=True, errorvaloracio=False)
            elif Valoracio != "":
                if str(Valoracio) < str(0) or str(Valoracio) > str(5):
                    return render_template('busquedaProductes.html', products=None, usuario=DNIusuari, busquedafallida=False, errorvaloracio=True)
                else:
                    return flask.redirect("http://%s:%d/hacer_pedido" % (hostname, port))
            else:
                return flask.redirect("http://%s:%d/hacer_pedido" % (hostname, port))


def buscar_productos(Nom=None, PreuMin=0.0, PreuMax=10000.0, Marca=None, Valoracio=0.0, Categoria=None):
    global mss_cnt, products_list
    g = Graph()

    action = ONTO['BuscarProductes' + str(mss_cnt)]
    g.add((action, RDF.type, ONTO.BuscarProductes))

    if Nom:
        nameRestriction = ONTO['RestriccioNom' + str(mss_cnt)]
        g.add((nameRestriction, RDF.type, ONTO.RestriccioNom))
        g.add((nameRestriction, ONTO.Nom, Literal(Nom)))
        g.add((action, ONTO.Restriccions, URIRef(nameRestriction)))

    if PreuMin:
        minPriceRestriction = ONTO['RestriccioPreu' + str(mss_cnt)]
        g.add((minPriceRestriction, RDF.type, ONTO.RestriccioPreu))
        g.add((minPriceRestriction, ONTO.PreuMin, Literal(PreuMin)))
        g.add((action, ONTO.Restriccions, URIRef(minPriceRestriction)))

    if PreuMax:
        maxPriceRestriction = ONTO['RestriccioPreu' + str(mss_cnt)]
        g.add((maxPriceRestriction, RDF.type, ONTO.RestriccioPreu))
        g.add((maxPriceRestriction, ONTO.PreuMax, Literal(PreuMax)))
        g.add((action, ONTO.Restriccions, URIRef(maxPriceRestriction)))

    if Marca:
        brandRestriction = ONTO['RestriccioMarca' + str(mss_cnt)]
        g.add((brandRestriction, RDF.type, ONTO.RestriccioMarca))
        g.add((brandRestriction, ONTO.Marca, Literal(Marca)))
        g.add((action, ONTO.Restriccions, URIRef(brandRestriction)))

    if Valoracio:
        ratingRestriction = ONTO['RestriccioValoracio' + str(mss_cnt)]
        g.add((ratingRestriction, RDF.type, ONTO.RestriccioValoracio))
        g.add((ratingRestriction, ONTO.Valoracio, Literal(Valoracio)))
        g.add((action, ONTO.Restriccions, URIRef(ratingRestriction)))

    if Categoria:
        categoryRestriction = ONTO['RestriccioCategoria' + str(mss_cnt)]
        g.add((categoryRestriction, RDF.type, ONTO.RestriccioCategoria))
        g.add((categoryRestriction, ONTO.Categoria, Literal(Categoria)))
        g.add((action, ONTO.Restriccions, URIRef(categoryRestriction)))

    print(f'Buscando productos con las siguientes restricciones: {Nom}, {PreuMin}, {PreuMax}, {Marca}, {Valoracio}, {Categoria}')
    msg = build_message(g, ACL.request, AgentAssistent.uri, ServeiBuscador.uri, action, mss_cnt)
    print(f'Mensaje construido: {msg}')
    mss_cnt += 1

    try:
        print(f'Enviando mensaje a ServeiBuscador: {msg}')
        gproducts = send_message(msg, ServeiBuscador.address)
        print(f'Respuesta recibida: {gproducts}')
        products_list = []
        subjects_position = {}
        pos = 0
        for s, p, o in gproducts:
            if s not in subjects_position:
                subjects_position[s] = pos
                pos += 1
                products_list.append({})
            if s in subjects_position:
                product = products_list[subjects_position[s]]
                if p == RDF.type:
                    product['Producte'] = s
                if p == ONTO.ID:
                    product['ID'] = o
                if p == ONTO.Nom:
                    product['Nom'] = o
                if p == ONTO.Marca:
                    product['Marca'] = o
                if p == ONTO.Preu:
                    product['Preu'] = o
                if p == ONTO.Pes:
                    product["Pes"] = o
                if p == ONTO.Valoracio:
                    product["Valoracio"] = o
                if p == ONTO.Categoria:
                    product["Categoria"] = o
        logger.info(f'Productos recibidos: {products_list}')
        return products_list
    except Exception as e:
        logger.error(f"Error en la comunicación con el servicio de búsqueda: {e}")
        return []


@app.route("/historial_comandes", methods=['GET'])
def historial_comandes():
    global DNIusuari
    comandas = consultar_comandas(DNIusuari)
    print(comandas)
    return render_template('historial_comandes.html', comandas=comandas)

@app.route("/comanda/<comanda_id>", methods=['GET'])
def ver_comanda(comanda_id):
    page = request.args.get('page', 1, type=int)
    products_per_page = 10
    comanda = consultar_productes_comanda(comanda_id, page, products_per_page)
    total_pages = (comanda['TotalProducts'] // products_per_page) + 1

    return render_template('ver_comanda.html', comanda=comanda, page=page, total_pages=total_pages)


def consultar_comandas(dni):
    endpoint_url = "http://localhost:3030/ONTO/query"
    client_uri = f"http://www.semanticweb.org/nilde/ontologies/2024/4/{dni}"

    sparql_query_comandas = f"""
    PREFIX rdf: <http://www.w3.org/1999/02/22-rdf-syntax-ns#>
    PREFIX ont: <http://www.semanticweb.org/nilde/ontologies/2024/4/>

    SELECT ?comanda ?ciutat ?prioritat ?creditCard ?preu_total
    WHERE {{
        ?comanda rdf:type ont:Comanda .
        ?comanda ont:Ciutat ?ciutat .
        ?comanda ont:Client ?client .
        ?comanda ont:PreuTotal ?preu_total .
        ?comanda ont:Prioritat ?prioritat .
        ?comanda ont:TargetaCredit ?creditCard .
        VALUES ?client {{ <{client_uri}> }}
    }}
    ORDER BY ?comanda
    """

    sparql = SPARQLWrapper(endpoint_url)
    sparql.setQuery(sparql_query_comandas)
    sparql.setReturnFormat(JSON)
    results_comandas = sparql.query().convert()

    comandas = []
    for result in results_comandas["results"]["bindings"]:
        comanda = {
            "ID": result["comanda"]["value"].split("/")[-1],
            "Ciutat": result["ciutat"]["value"],
            "Prioritat": result["prioritat"]["value"],
            "TargetaCredit": result["creditCard"]["value"],
            "PreuTotal": result["preu_total"]["value"]
        }
        comandas.append(comanda)

    return comandas


def consultar_productes_comanda(comanda_id, page, products_per_page):
    endpoint_url = "http://localhost:3030/ONTO/query"
    comanda_uri = f"http://www.semanticweb.org/nilde/ontologies/2024/4/{comanda_id}"

    sparql_query_productes = f"""
    PREFIX rdf: <http://www.w3.org/1999/02/22-rdf-syntax-ns#>
    PREFIX ont: <http://www.semanticweb.org/nilde/ontologies/2024/4/>

    SELECT ?producte_comanda ?nom ?preu ?data ?pagado ?enviat ?transportista
    WHERE {{
        <{comanda_uri}> ont:ProductesComanda ?producte_comanda .
        ?producte_comanda rdf:type ont:ProducteComanda .
        ?producte_comanda ont:Nom ?nom .
        ?producte_comanda ont:Preu ?preu .
        ?producte_comanda ont:Data ?data .
        ?producte_comanda ont:Pagat ?pagado .
        ?producte_comanda ont:Enviat ?enviat .
        ?producte_comanda ont:TransportistaProducte ?transportista .
    }}
    ORDER BY ?producte_comanda
    """

    sparql = SPARQLWrapper(endpoint_url)
    sparql.setQuery(sparql_query_productes)
    sparql.setReturnFormat(JSON)
    results_productes = sparql.query().convert()

    products = []
    for result in results_productes["results"]["bindings"]:
        producte = {
            "Nom": result["nom"]["value"],
            "Preu": result["preu"]["value"],
            "Data": result["data"]["value"][:10],
            "Pagado": result["pagado"]["value"],
            "Enviado": result["enviat"]["value"],
            "Transportista": result["transportista"]["value"]
        }
        print (producte)
        products.append(producte)

    # Implementar paginación
    total_products = len(products)
    start = (page - 1) * products_per_page
    end = start + products_per_page
    paginated_products = products[start:end]

    comanda = {
        "ID": comanda_id,
        "Productes": paginated_products,
        "TotalProducts": total_products
    }

    return comanda

def agentbehavior1(queue):
    """
    Un comportamiento del agente

    :return:
    """
    pass


if __name__ == '__main__':
    """
    # Ponemos en marcha los behaviors
    ab1 = Process(target=agentbehavior1, args=(cola1,))
    ab1.start()
    compra =False
    # Ponemos en marcha el servidor
    app.run(host=hostname, port=port)

    # Esperamos a que acaben los behaviors
    ab1.join()

    print('The End')
    """
    app.run(host=hostname, port=port)
