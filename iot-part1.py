
# ============================================================
# ESP32 - SISTEMA DE AUTOMACAO RESIDENCIAL
# INTEGRACAO FIWARE - IoT AGENT JSON - MQTT
# ============================================================

import time
import network
import json
import array

from machine import Pin, PWM
from umqtt.simple import MQTTClient

# ============================================================
# 1. CONFIGURACOES
# ============================================================

WIFI_SSID = "CCM130"
WIFI_PASSWORD = "FEI@2026"

# Informacoes do ambiente FIWARE
MQTT_BROKER = "broker.hivemq.com"
MQTT_PORT = 1883

DEVICE_ID = "esp32_sala001"
API_KEY = "uniccasilva"

# Identificacao logica
ENTITY_ID = "urn:ngsi-ld:SmartRoom:001"

# Topicos IoT Agent JSON
TOPICO_TELEMETRIA = (
    "/json/" + API_KEY + "/" + DEVICE_ID + "/attrs"
)

TOPICO_COMANDOS = (
    "/" + API_KEY + "/" + DEVICE_ID + "/cmd"
)

TOPICO_RESULTADO = (
    "/json/" + API_KEY + "/" + DEVICE_ID + "/cmdexe"
)

# Temporizacao
INTERVALO_PUBLICACAO = 3000
JANELA_PRESENCA = 8000

# ============================================================
# 2. HARDWARE
# ============================================================

RELE_PIN = 26
SOM_PIN = 34
IR_PIN = 35
SERVO_PIN = 25

ATIVO_EM_NIVEL_BAIXO = True

rele = Pin(RELE_PIN, Pin.OUT)

# Inicializacao segura do rele
rele.value(1 if ATIVO_EM_NIVEL_BAIXO else 0)

servo = PWM(Pin(SERVO_PIN), freq=50)

# Posicoes do servo
PULSO_MIN = 0.5
PULSO_MAX = 2.5

som = Pin(SOM_PIN, Pin.IN)
ir = Pin(IR_PIN, Pin.IN)

# ============================================================
# 3. VARIAVEIS DE ESTADO
# ============================================================

ac_ligado = False
janela_aberta = False

temperatura_alvo = 24

sistema_ativo = True

som_detectado = False
ultimo_som = time.ticks_ms() - JANELA_PRESENCA - 1000

ultimo_ir = 0
ultimo_codigo_ir = 0

# ============================================================
# 4. CONTROLE DOS ATUADORES
# ============================================================

def controlar_ar(ligar):

    global ac_ligado

    rele.value(
        0 if ligar == ATIVO_EM_NIVEL_BAIXO
        else 1
    )

    ac_ligado = bool(ligar)

    print("Ar condicionado:", ac_ligado)


def mover_servo(graus):

    graus = max(0, min(180, int(graus)))

    largura = (
        PULSO_MIN +
        (graus / 180) * (PULSO_MAX - PULSO_MIN)
    )

    servo.duty_u16(
        int((largura / 20) * 65535)
    )


def controlar_janela(abrir):

    global janela_aberta

    mover_servo(90 if abrir else 0)

    janela_aberta = bool(abrir)

    print("Janela aberta:", janela_aberta)


# Estado inicial
controlar_ar(False)
controlar_janela(False)

# ============================================================
# 5. SENSOR DE SOM - DETECCAO DE PRESENCA
# ============================================================

def callback_som(pin):

    global ultimo_som
    global som_detectado

    agora = time.ticks_ms()

    # Evita interferencia do controle IR
    if time.ticks_diff(agora, ultimo_ir) < 500:
        return

    ultimo_som = agora
    som_detectado = True


som.irq(
    trigger=Pin.IRQ_RISING,
    handler=callback_som
)


def verificar_presenca():

    return (
        time.ticks_diff(
            time.ticks_ms(),
            ultimo_som
        ) < JANELA_PRESENCA
    )


# ============================================================
# 6. CONTROLE INFRAVERMELHO - NEC
# ============================================================

IR_MAX_BITS = 32
IR_LIMIAR_US = 1600

ir_buffer = array.array("i", [0] * IR_MAX_BITS)

ir_indice = 0
ir_marca = time.ticks_us()
ir_pronto = False

# Codigos NEC - substituir pelos codigos reais
IR_CODIGO_AUMENTAR = 0xf7a857
IR_CODIGO_DIMINUIR = 0xf74ab5

def callback_ir(pin):

    global ir_indice
    global ir_marca
    global ir_pronto
    global ultimo_ir

    agora = time.ticks_us()

    intervalo = time.ticks_diff(
        agora,
        ir_marca
    )

    ir_marca = agora

    ultimo_ir = time.ticks_ms()

    # Inicio de um novo quadro NEC
    if intervalo > 10000:

        ir_indice = 0
        ir_pronto = False

        return

    # Ignora pulsos curtos e quadros ja completos
    if intervalo < 700 or ir_pronto:
        return

    if ir_indice < IR_MAX_BITS:

        ir_buffer[ir_indice] = intervalo
        ir_indice += 1

        if ir_indice == IR_MAX_BITS:
            ir_pronto = True


ir.irq(
    trigger=Pin.IRQ_FALLING,
    handler=callback_ir
)


def decodificar_ir():

    global ir_indice
    global ir_pronto

    codigo = 0

    if not ir_pronto:
        return None

    for i in range(IR_MAX_BITS):

        codigo = (codigo << 1)

        if ir_buffer[i] > IR_LIMIAR_US:
            codigo |= 1

    ir_indice = 0
    ir_pronto = False

    return codigo


def processar_ir():

    global temperatura_alvo
    global ultimo_codigo_ir

    codigo = decodificar_ir()

    if codigo is None:
        return

    ultimo_codigo_ir = codigo

    print("IR recebido:", hex(codigo))

    if codigo == IR_CODIGO_AUMENTAR:

        temperatura_alvo = min(
            30,
            temperatura_alvo + 1
        )

    elif codigo == IR_CODIGO_DIMINUIR:

        temperatura_alvo = max(
            16,
            temperatura_alvo - 1
        )


# ============================================================
# 7. CONEXAO WIFI
# ============================================================

wlan = network.WLAN(network.STA_IF)


def conectar_wifi():

    wlan.active(True)

    if wlan.isconnected():
        return

    print("Conectando ao Wi-Fi...")

    wlan.connect(
        WIFI_SSID,
        WIFI_PASSWORD
    )

    inicio = time.ticks_ms()

    while not wlan.isconnected():

        if time.ticks_diff(
            time.ticks_ms(),
            inicio
        ) > 15000:

            raise RuntimeError("Falha no Wi-Fi")

        time.sleep(0.5)

    print("Wi-Fi conectado:", wlan.ifconfig()[0])


# ============================================================
# 8. COMANDOS RECEBIDOS DO FIWARE
# ============================================================

def ao_receber_mensagem(topico, mensagem):

    global sistema_ativo
    global temperatura_alvo
    global INTERVALO_PUBLICACAO

    print("Comando FIWARE:", mensagem)

    try:

        dados = json.loads(mensagem.decode())

        # Ar condicionado
        if "setAirConditioner" in dados:

            valor = dados["setAirConditioner"]

            if isinstance(valor, dict):
                valor = valor.get("value")

            controlar_ar(
                str(valor).lower() in ("ligar", "on", "true", "1")
            )

        # Janela
        if "setWindow" in dados:

            valor = dados["setWindow"]

            if isinstance(valor, dict):
                valor = valor.get("value")

            controlar_janela(
                str(valor).lower() in ("abrir", "open", "true", "1")
            )

        # Temperatura
        if "setTargetTemperature" in dados:

            valor = dados["setTargetTemperature"]

            if isinstance(valor, dict):
                valor = valor.get("value")

            temperatura_alvo = max(
                16,
                min(30, int(valor))
            )

        # Sistema
        if "setSystemStatus" in dados:

            valor = dados["setSystemStatus"]

            if isinstance(valor, dict):
                valor = valor.get("value")

            sistema_ativo = (
                str(valor).lower() in ("ativo", "on", "true", "1")
            )

    except Exception as erro:

        print("Erro no comando:", erro)


# ============================================================
# 9. CONEXAO MQTT FIWARE
# ============================================================

client = None


def conectar_mqtt():

    global client

    client = MQTTClient(
        client_id=DEVICE_ID,
        server=MQTT_BROKER,
        port=MQTT_PORT,
        keepalive=60
    )

    client.set_callback(ao_receber_mensagem)

    client.connect()

    client.subscribe(TOPICO_COMANDOS)

    print("MQTT conectado ao FIWARE")

    print("Topico de telemetria:", TOPICO_TELEMETRIA)

    print("Topico de comandos:", TOPICO_COMANDOS)


# ============================================================
# 10. PUBLICACAO DE TELEMETRIA
# ============================================================

def publicar_telemetria():

    if not sistema_ativo:
        return

    dados = {

        "presence": (
            "Presente"
            if verificar_presenca()
            else "Vazio"
        ),

        "targetTemperature": temperatura_alvo,

        "airConditioner": (
            "Ligado"
            if ac_ligado
            else "Desligado"
        ),

        "window": (
            "Aberta"
            if janela_aberta
            else "Fechada"
        ),

        "systemStatus": "Ativo",

        "soundDetected": bool(som_detectado),

        "lastIRCommand": hex(ultimo_codigo_ir)
    }

    mensagem = json.dumps(dados)

    client.publish(
        TOPICO_TELEMETRIA,
        mensagem.encode()
    )

    print("Telemetria enviada:", mensagem)


# ============================================================
# 11. LOOP PRINCIPAL
# ============================================================

def iniciar_sistema():

    global som_detectado

    conectar_wifi()
    conectar_mqtt()

    print("Sistema ESP32 + FIWARE iniciado")

    ultimo_envio = time.ticks_ms()

    while True:

        try:

            # Verifica conectividade
            if not wlan.isconnected():

                print("Wi-Fi desconectado")

                conectar_wifi()

            # Recebe comandos do FIWARE
            try:

                client.check_msg()

            except OSError:

                print("Reconectando MQTT...")

                conectar_mqtt()

            # Processa controle infravermelho
            processar_ir()

            # Processa eventos do som
            if som_detectado:

                som_detectado = False

                print("Som detectado")

            agora = time.ticks_ms()

            # Publicacao periodica
            if time.ticks_diff(
                agora,
                ultimo_envio
            ) >= INTERVALO_PUBLICACAO:

                ultimo_envio = agora

                publicar_telemetria()

            time.sleep_ms(20)

        except OSError as erro:

            print("Erro de comunicacao:", erro)

            time.sleep(2)


# ============================================================
# 12. EXECUCAO
# ============================================================

try:

    iniciar_sistema()

except KeyboardInterrupt:

    print("Sistema encerrado")

finally:

    controlar_ar(False)
    controlar_janela(False)

    if client:

        try:
            client.disconnect()

        except:
            pass

