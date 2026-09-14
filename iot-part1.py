#ideia do meu projeto eh fazer um quarto inteligente, onde eu possa liga e deligar o meu ar, abrir e fechar as minhas janelas e usando um dector de som para ver se temos alg presente no quarto

import network
import time
import json
from machine import Pin, PWM
from umqtt.simple import MQTTClient

#CONFIGURACOES DO WI-FI E MQTT
SSID = "quarto_camila" #nome da minha rede de wife
SENHA = "camila123" #senha da rede 
BROKER = "broker.hivemq.com"
ID_ESP32 = "camila_quarto_01"

# Topicos MQTT
TOPICO_RELE = b"fei/camila_quarto_01/rele"
TOPICO_JANELA = b"fei/camila_quarto_01/janela"
TOPICO_ESP32 = b"fei/camila_quarto_01/esp32"

TOPICO_DHT22 = b"fei/camila_quarto_01/dht22"
TOPICO_SOM = b"fei/camila_quarto_01/som"
TOPICO_STATUS = b"fei/camila_quarto_01/status"

# 2. CONFIGURACAO DOS COMPONENTES

# Rele do ar-condicionado
rele = Pin(26, Pin.OUT)

# Servomotor da janela
servo = PWM(Pin(25), freq=50)

# Sensor de som
sensor_som = Pin(33, Pin.IN)

# DHT22
from dht import DHT22
sensor_dht = DHT22(Pin(32))

# Estados dos atuadores
ar_ligado = False
janela_aberta = False

# Intervalo de envio dos sensores
intervalo = 3

# Tempo do ultimo envio
ultimo_envio = time.ticks_ms()

# 3. FUNCAO PARA CONECTAR AO WI-FI

def conectar_wifi(ssid, senha):

    wlan = network.WLAN(network.STA_IF)
    wlan.active(True)

    if not wlan.isconnected():

        print("Conectando ao Wi-Fi...")
        wlan.connect(ssid, senha)
        tentativas = 0
        while not wlan.isconnected() and tentativas < 20:

            time.sleep(0.5)
            tentativas += 1

    if wlan.isconnected():
        print("Wi-Fi conectado!")
        print("Endereco IP:", wlan.ifconfig()[0])
    else:
        print("Falha ao conectar ao Wi-Fi")
    return wlan

# 4. FUNCAO PARA CONECTAR AO MQTT

def conectar_mqtt():

    cliente = MQTTClient(ID_ESP32, BROKER)
    cliente.set_callback(callback_mensagem)
    cliente.connect()
    # Assina os topicos de comando
    cliente.subscribe(TOPICO_RELE)
    cliente.subscribe(TOPICO_JANELA)
    cliente.subscribe(TOPICO_ESP32)
    print("Conectado ao broker MQTT!")
    return cliente

# 5. FUNCAO PARA CONTROLAR O RELE (meu ar)

def controlar_rele(comando):
    global ar_ligado
    if comando == b"LIGAR":
        rele.value(1)
        ar_ligado = True
        print("Ar-condicionado ligado")
    elif comando == b"DESLIGAR":
        rele.value(0)
        ar_ligado = False
        print("Ar-condicionado desligado")

# 6. FUNCAO PARA CONTROLAR O SERVO (minha janela)

def controlar_janela(comando):
    global janela_aberta
    if comando == b"ABRIR":
        servo.duty_u16(4915)
        janela_aberta = True
        print("Janela aberta")
    elif comando == b"FECHAR":
        servo.duty_u16(1638)
        janela_aberta = False
        print("Janela fechada")

# 7. FUNCAO DE CALLBACK DO MQTT

def callback_mensagem(topico, mensagem):

    global intervalo

    print("Topico recebido:", topico)
    print("Mensagem recebida:", mensagem)

    if topico == TOPICO_RELE:

        controlar_rele(mensagem)

    elif topico == TOPICO_JANELA:

        controlar_janela(mensagem)

    elif topico == TOPICO_ESP32:

        if mensagem == b"ATIVAR":

            intervalo = 3
            print("Envio dos sensores ativado")

        elif mensagem == b"DESATIVAR":

            intervalo = 0
            print("Envio dos sensores desativado")

        elif mensagem.startswith(b"ATUALIZAR:"):

            try:

                novo_intervalo = int(mensagem.split(b":")[1])

                if 2 <= novo_intervalo <= 10:

                    intervalo = novo_intervalo

                    print("Novo intervalo:", intervalo)

                else:

                    print("Intervalo deve ser entre 2 e 10 segundos")

            except:

                print("Formato invalido")


# =====================================================
# 8. FUNCAO PARA ENVIAR DADOS DOS SENSORES
# =====================================================

def publicar_sensores():

    # Leitura do DHT22
    sensor_dht.measure()

    temperatura = sensor_dht.temperature()
    umidade = sensor_dht.humidity()

    # Leitura do sensor de som
    som_detectado = sensor_som.value()

    # Envia temperatura e umidade
    dados_dht = {
        "temperatura": temperatura,
        "umidade": umidade
    }

    client.publish(
        TOPICO_DHT22,
        json.dumps(dados_dht)
    )

    # Envia dados do sensor de som
    dados_som = {
        "som": som_detectado
    }

    client.publish(
        TOPICO_SOM,
        json.dumps(dados_som)
    )

    # Envia o estado do ar e da janela
    dados_status = {
        "ar": "LIGADO" if ar_ligado else "DESLIGADO",
        "janela": "ABERTA" if janela_aberta else "FECHADA"
    }

    client.publish(
        TOPICO_STATUS,
        json.dumps(dados_status)
    )

    print("Sensores publicados:", dados_dht)
    print("Som:", som_detectado)
    print("Status:", dados_status)


# =====================================================
# 9. PROGRAMA PRINCIPAL
# =====================================================

wlan = conectar_wifi(SSID, SENHA)

if wlan.isconnected():

    client = conectar_mqtt()

    print("Quarto inteligente iniciado!")

    while True:

        try:

            # Verifica se chegaram comandos MQTT
            client.check_msg()

            # Envia os sensores no intervalo definido
            if intervalo > 0:

                agora = time.ticks_ms()

                if time.ticks_diff(agora, ultimo_envio) >= intervalo * 1000:

                    publicar_sensores()

                    ultimo_envio = agora

            time.sleep(0.1)

        except Exception as erro:

            print("Erro:", erro)

            time.sleep(3)

else:

    print("Nao foi possivel iniciar o projeto.")