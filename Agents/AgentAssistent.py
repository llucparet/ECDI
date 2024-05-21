# -*- coding: utf-8 -*-
"""
Agente Asistente para el sistema ECSDI.
Utiliza Flask para la interacción web y RDFlib para la manipulación de grafos RDF.
"""

from multiprocessing import Process, Queue
import socket
import flask
from flask import Flask, request, render_template, redirect, url_for
from rdflib import Namespace, Graph, RDF, Literal, URIRef
from Utils.ACLMessages import build_message, get_message_properties
from Utils.FlaskServer import shutdown_server
from Utils.Agent import Agent
from Utils.templates import *
from Utils.OntoNamespaces import ONTO
from Utils.ACL import ACL
from Utils.Logger import config_logger

__author__ = 'Adria'

from Utils.ACLMessages import send_message

# Configuración de logging
logger = config_logger(level=1)

# Configuración del agente
hostname = socket.gethostname()
port = 9011

# Namespaces para RDF
agn = Namespace("http://www.agentes.org#")

# Instancia del Flask app
app = Flask(__name__, template_folder='../Utils/templates')

# Agentes del sistema
AgentAssistent = Agent('AgentAssistent', agn.AgentAssistent, f'http://{hostname}:{port}/comm', f'http://{hostname}:{port}/Stop')
ServeiBuscador = Agent('ServeiBuscador', agn.ServeiBuscador, f'http://{hostname}:9010/comm', f'http://{hostname}:9010/Stop')
#ServeiComandes = Agent('ServeiComandes', agn.ServeiComandes, f'http://{hostname}:9012/comm', f'http://{hostname}:9012/Stop')
#ServeiClients = Agent('ServeiClients', agn.ServeiClients, f'http://{hostname}:9013/comm', f'http://{hostname}:9013/Stop')
#ServeiRetornador = Agent('ServeiRetornador', agn.ServeiRetornador, f'http://{hostname}:9014/comm', f'http://{hostname}:9014/Stop')

cola1 = Queue()

# Variables globales
mss_cnt = 0
productos_recomendados = []
products_list = []
nombreusuario = ""
completo = False
info_bill = {}


@app.route("/", methods=['GET', 'POST'])
def initialize():
    global nombreusuario, productos_recomendados, products_list, completo, info_bill
    if request.method == 'GET':
        if nombreusuario:
            if not productos_recomendados:
                return render_template('home.html', products=None, usuario=nombreusuario, recomendacion=False)
            else:
                return render_template('home.html', products=productos_recomendados, usuario=nombreusuario, recomendacion=True)
        else:
            return render_template('usuari.html')
    elif request.method == 'POST':
        if 'submit' in request.form and request.form['submit'] == 'registro_usuario':
            nombreusuario = request.form['name']
            return render_template('home.html', products=None, usuario=nombreusuario)
        elif 'submit' in request.form and request.form['submit'] == 'search_products':
            return flask.redirect("http://%s:%d/search_products" % (hostname, port))


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
            bill = realizar_compra(products_to_buy, city, priority, creditCard)
            completo = True  # Indica que la compra se ha completado
            return render_template('novaComanda.html', products=None, bill=bill, intento=False, completo=completo)
        elif request.form['submit'] == "Volver a buscar":
            return redirect(url_for('search_products'))


def realizar_compra(products_to_buy, city, priority, creditCard):
    # Simulación de procesamiento de compra
    factura = {
        "ciudad": city,
        "prioridad": priority,
        "tarjeta_credito": creditCard,
        "productos_comprados": [{k: p[k] for k in ['name', 'brand', 'price']} for p in products_to_buy],
        "total": sum(p['price'] for p in products_to_buy)  # Suma total de los precios
    }
    return factura


@app.route("/search_products", methods=['GET', 'POST'])
def search_products():
    global nombreusuario
    if request.method == 'GET':
        return render_template('busquedaProductes.html', products=None, usuario=nombreusuario, busquedafallida=False,errorvaloracio=False)
    else:
        if request.form['submit'] == 'Buscar':
            global products_list
            Nom = request.form['Nom']
            PreuMin = request.form['PreuMin']
            PreuMax = request.form['PreuMax']
            Marca = request.form['Marca']
            Valoracio = request.form['Valoracio']
            products_list = buscar_productos(Nom, PreuMin, PreuMax, Marca, Valoracio)
            if len(products_list) == 0:
                return render_template('busquedaProductes.html', products=None, usuario=nombreusuario, busquedafallida=True,errorvaloracio=False)
            elif Valoracio != "":
                if str(Valoracio) < str(0) or str(Valoracio) > str(5):
                    return render_template('busquedaProductes.html', products=None, usuario=nombreusuario, busquedafallida=False, errorvaloracio=True)
                else:
                    return flask.redirect("http://%s:%d/hacer_pedido" % (hostname, port))
            else:
                return flask.redirect("http://%s:%d/hacer_pedido" % (hostname, port))


def buscar_productos(Nom = None, PreuMin = 0.0, PreuMax = 10000.0, Marca = None, Valoracio=0.0):
    global mss_cnt, products_list
    g = Graph()

    action = FONTO['BuscarProductes' + str(mss_cnt)]
    g.add((action, RDF.type, ONTO.BuscarProductes))

    if Nom:
        nameRestriction = FONTO['RestriccioNom' + str(mss_cnt)]
        g.add((nameRestriction, RDF.type, ONTO.RestriccioNom))
        g.add((nameRestriction, ONTO.Nombre, Literal(Nom)))
        g.add((action, ONTO.Restriccions, URIRef(nameRestriction)))

    if PreuMin:
        minPriceRestriction = FONTO['RestriccioPreu' + str(mss_cnt)]
        g.add((minPriceRestriction, RDF.type, ONTO.RestriccioPreu))
        g.add((minPriceRestriction, ONTO.PrecioMinimo, Literal(PreuMin)))
        g.add((action, ONTO.Restriccions, URIRef(minPriceRestriction)))

    if PreuMax:
        maxPriceRestriction = FONTO['RestriccioPreu' + str(mss_cnt)]
        g.add((maxPriceRestriction, RDF.type, ONTO.RestriccioPreu))
        g.add((maxPriceRestriction, ONTO.PrecioMaximo, Literal(PreuMax)))
        g.add((action, ONTO.Restriccions, URIRef(maxPriceRestriction)))
    if Marca:
        brandRestriction = FONTO['RestriccioMarca' + str(mss_cnt)]
        g.add((brandRestriction, RDF.type, ONTO.RestriccioMarca))
        g.add((brandRestriction, ONTO.Marca, Literal(Marca)))
        g.add((action, ONTO.Restriccions, URIRef(brandRestriction)))
    if Valoracio:
        RatingRestriction = FONTO['RestriccioValoracio' + str(mss_cnt)]
        g.add((RatingRestriction, RDF.type, ONTO.RestriccioValoracio))
        g.add((RatingRestriction, ONTO.Valoracio, Literal(Valoracio)))
        g.add((action, ONTO.Restriccions, URIRef(RatingRestriction)))

    msg = build_message(g, ACL.request, AgentAssistent.uri, ServeiBuscador.uri, action, mss_cnt)
    mss_cnt += 1
    try:
        gproducts = send_message(msg, ServeiBuscador.address)
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
        return products_list
    except Exception as e:
        print("Error en la comunicación con el servicio de búsqueda: ", e)
        return []


def agentbehavior1(queue):
    """
    Un comportamiento del agente

    :return:
    """
    pass


if __name__ == '__main__':
    # Ponemos en marcha los behaviors
    ab1 = Process(target=agentbehavior1, args=(cola1,))
    ab1.start()
    compra =False
    # Ponemos en marcha el servidor
    app.run(host=hostname, port=port)

    # Esperamos a que acaben los behaviors
    ab1.join()

    ('The End')
