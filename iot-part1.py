# Um "quarto inteligente" controlado a distancia pelo celular via MQTT:
# - Sensor de som     -> detecta se tem alguem no ambiente (presenca)
#- Receptor IR       -> le o controle remoto para ajustar a temperatura
                           #desejada (botao pra cima aumenta, pra baixo
                           #diminui)
#- Rele              -> liga/desliga o ar-condicionado, só por comando MQTT
#  - Servomotor        -> abre/fecha a janela, só por comando MQTT

#som- vazio/presnte
#janela- aberta/fechada
#ar-ligado e deligado

# BIBLIOTECAS
import time    # tempo sem travar o programa (ticks_ms, ticks_us)
import array                      
import network   # controla o Wi-Fi da ESP32
from machine import Pin, PWM  # Pin = pino digital | PWM = sinal para o servo
from umqtt.simple import MQTTClient# biblioteca que conversa com MQTT
#-------------------------------
# CONFIGURACAO DO MMQT (Info necessaria p/ a comunicaçao)
#-------------------------------
SSID = "quarto_camila123"      # nome da rede Wi-Fi que a ESP32 vai usar
SENHA = "camila123"            # senha dessa rede
BROKER = "broker.hivemq.com"   # servidor MQTT publico e gratuito
PORTA = 1883                   # porta padrao do MQTT sem criptografia
MEU_ID = "uniccasilava" # seu identificador unico no broker
BASE = "/" + MEU_ID  # ex: "/uniccasilava"
#BROKER- INTERMEDIARIO DAS MENSSAGENS (recebe e destribui as mensagens)


# cada linha abaixo e so BASE + o nome da "grandeza" (o que aquele topico representa)
#----------------------
#CANAIS DE COMUNICAÇAO
#---------------------
#CDM-COMANDOS
#SATUS-INFO DO ESTADO (EX:ON-OFF)

TOPICO_PRESENCA = BASE + "/presenca" # sensor de som publica aqui
TOPICO_TEMP_ALVO = BASE + "/temperatura_alvo" # receptor IR publica aqui

TOPICO_AC_STATUS = BASE + "/ar_condicionado" # ainformar o estado do ar.(ON-OFF)
TOPICO_AC_CMD = BASE + "/ar_condicionado_cmd" #mandar comandos para o ar-condicionado.

TOPICO_JANELA_STATUS = BASE + "/janela"  #ABRETA-FECHADA
TOPICO_JANELA_CMD = BASE + "/janela_cmd" 
TOPICO_ESP32 = BASE + "/esp32" # comandos gerais da placa

_TOPICO_AC_CMD_B = TOPICO_AC_CMD.encode()
_TOPICO_JANELA_CMD_B = TOPICO_JANELA_CMD.encode()
_TOPICO_ESP32_B = TOPICO_ESP32.encode()

INTERVALO = 3000        # de quanto em quanto tempo (em ms) a ESP32 publica as inf dos sensores: 3000 ms = 3 s
JANELA_PRESENCA = 8000  # depois que o sensor detecta som, o sistema considera que existe presença durante uma janela de 8 s

#--------------------------------------------------
# RELE - AR CONDICIONADO
#---------------------------------------------------
rele = Pin(26, Pin.OUT)  # LIGA MODULO RALE
ATIVO_EM_NIVEL_BAIXO = True #Esse módulo de relé é acionado quando recebe nível baixo.   

servo = PWM(Pin(25), freq=50)         #SERVO-  GPIO 25 gerando PWM a 50 Hz (padrao de servo)
PULSO_MIN = 0.5                       # largura de pulso (ms) que corresponde a   0 graus
PULSO_MAX = 2.5                       # largura de pulso (ms) que corresponde a 180 graus

ac_ligado = False       # guarda se o ar-condicionado esta ligado agora
janela_aberta = False   # guarda se a janela esta aberta agora
#--------------
#FUNCAO DO AR
#--------------
def ac_ligar():
    global ac_ligado                                  
    rele.value(0 if ATIVO_EM_NIVEL_BAIXO else 1)   # manda o nivel que liga o rele
    ac_ligado = True  # atualiza o estado guardado
def ac_desligar():
    global ac_ligado
    rele.value(1 if ATIVO_EM_NIVEL_BAIXO else 0)        # manda o nivel contrario
    ac_ligado = False
    
#----------------   
#SERVO-JANELA
#----------------
#Esta contec na GPIO26, recebe um sinal PWM de:50hz
    
def servo_angulo(graus): #funcao p/ receber um angulo
    graus = max(0, min(180, graus)) #impede que o ângulo seja menor que 0 ou maior que 180.
    largura = PULSO_MIN + (graus / 180) * (PULSO_MAX - PULSO_MIN) #transforma o ângulo em uma largura de pulso
    servo.duty_u16(int(largura / 20 * 65535))
    #Essa função recebe o ângulo desejado e converte esse valor para o sinal PWM que o servo entende

def janela_abrir():
    global janela_aberta
    servo_angulo(90)          # gira o servo pra posicao de "aberta"-90graus
    janela_aberta = True

def janela_fechar():
    global janela_aberta
    servo_angulo(0)           # gira o servo pra posicao de "fechada"-0 graus
    janela_aberta = False
    
#sistema comece em um estado conhecido- 
ac_desligar() #ar deligado
janela_fechar() #janela fechada


#----------------------------------------------------
# SENSOR DE SOM
#--------------------------------------------------
#GPIO 33 está configurado como entrada.
som = Pin(33, Pin.IN)   #SOM                              
_ultimo_som = time.ticks_ms() - JANELA_PRESENCA - 1000 #detecta o som e salva na variavel
def _som_callback(pin):
    global _ultimo_som
    _ultimo_som = time.ticks_ms()    # so guarda "agora foi a ultima vez que ouvi som"
som.irq(trigger=Pin.IRQ_RISING, handler=_som_callback)
#quando acontece a mudanca de 0 - 1 ela chama automaticamente som_callback


#--------------------------
# RECPTOR INFRAVERMELHO
#--------------------------
IR_PINO = 34  #está no GPIO 34
_IR_MAX_BITS = 32 #montar um código de 32 bits.             
_ir_buffer = array.array("i", [0] * _IR_MAX_BITS)  # espaco JA reservado na memoria
_ir_indice = 0            # em que posicao do buffer estou escrevendo agora
_ir_marca = time.ticks_us()  # instante (em microssegundos) da ultima borda vista
_ir_pronto = False        # fica True quando um codigo completo (32 bits) chegou

DEBUG_IR = True   
IR_LIMIAR_US = 1500   # acima disso (microssegundos) e bit 1, abaixo e bit 0

IR_CODIGO_MAIS = 0    # botao que vai AUMENTAR a temperatura desejada
IR_CODIGO_MENOS = 0   # botao que vai DIMINUIR a temperatura desejada

def _ir_callback(pin):
    # roda a cada borda de DESCIDA no pino do receptor IR
    global _ir_indice, _ir_marca, _ir_pronto
    agora = time.ticks_us()                       # tempo atual, em microssegundos
    intervalo = time.ticks_diff(agora, _ir_marca)  # quanto tempo desde a ultima borda
    _ir_marca = agora                              # guarda pra proxima chamada

    if intervalo > 10000:
        _ir_indice = 0
        _ir_pronto = False
        return

    if _ir_indice < _IR_MAX_BITS:
        _ir_buffer[_ir_indice] = intervalo   # guarda esse intervalo no buffer
        _ir_indice += 1                      # avanca pra proxima posicao
        if _ir_indice == _IR_MAX_BITS:
            _ir_pronto = True                # buffer completo -> pode decodificar

ir = Pin(IR_PINO, Pin.IN)                                  # GPIO 34 como entrada
ir.irq(trigger=Pin.IRQ_FALLING, handler=_ir_callback)      # dispara em toda borda de descida

def ir_decodificar(): #pega os sinais que foram armazenados no buffer e transforma em um número.
    
#Essa função pega os sinais recebidos pelo sensor infravermelho
#e transforma os intervalos de tempo em um código que o programa consegue comparar.
    """Le o que esta no buffer e transforma em um numero inteiro unico.
    So chame isso quando _ir_pronto for True."""
    global _ir_indice, _ir_pronto
    codigo = 0
    for i in range(_IR_MAX_BITS):
        bit = 1 if _ir_buffer[i] > IR_LIMIAR_US else 0   # decide se e bit 0 ou 1
        codigo = (codigo << 1) | bit                     # empilha o bit no numero final

    _ir_pronto = False   #Esta esperando o proximo
    _ir_indice = 0
    return codigo
#------------------
#TEMPERATURA INCIAL
temperatura_alvo = 24   # valor inicial da temperatura desejada 24 graus
#-----------------

#-------------------------------------------
# WI-FI -ESP32 precisa entrar na internet/rede.
#-------------------------------------------
wlan = network.WLAN(network.STA_IF)   # configurada para funciona (conectar a um roteador.)
wlan.active(True)                     # liga o Wi-Fi

if not wlan.isconnected():
    wlan.connect(SSID, SENHA)    # tenta conectar com meus dados (´Login´ e senha)
    inicio = time.ticks_ms()
    while not wlan.isconnected(): #continua tentando conectar 
        if time.ticks_diff(time.ticks_ms(), inicio) > 15000: #verifica se já passaram 15 segundos.
            # passou de 15 segundos tentando e nao conectou -> programa gera erro
            raise RuntimeError("Wi-Fi nao conectou")
        time.sleep(0.5)   
print("Wi-Fi ok. IP:", wlan.ifconfig()[0])   # mostra o IP que a ESP32 recebeu


#CORACAO DA RECPCAO DOS COMANDOS MQTT
# CALLBACK MQTT -- o que fazer quando chega uma mensagem
ativo = True   # se False, a placa para de PUBLICAR (mas continua escutando comandos)
def ao_receber(topico, mensagem):
    # essa funcao e chamada AUTOMATICAMENTE pela biblioteca MQTT sempre que
    # chega uma mensagem em qualquer topico que a placa assinou.
    global ativo, INTERVALO
    print("Recebido:", topico, mensagem)   # so pra acompanhar no Shell
    if topico == _TOPICO_AC_CMD_B:
        
        # mensagem chegou no topico de COMANDO DO AR
        if mensagem == b"Ligar":
            ac_ligar()
        elif mensagem == b"Desligar":
            ac_desligar()
        else:
            print("Comando de ar-condicionado desconhecido, ignorado.")

    elif topico == _TOPICO_JANELA_CMD_B:
        # mensagem chegou no topico de COMANDO DA JANELA
        if mensagem == b"Abrir":
            janela_abrir()
        elif mensagem == b"Fechar":
            janela_fechar()
        else:
            print("Comando de janela desconhecido, ignorado.")

    elif topico == _TOPICO_ESP32_B:
        # mensagem chegou no topico de COMANDOS GERAIS DA ESP32
        if mensagem == b"Ativar":
            ativo = True
        elif mensagem == b"Desativar":
            ativo = False
        elif mensagem.startswith(b"Atualizar:"):
            # espera algo como b"Atualizar:5" 
            try:
                # "Atualizar:" tem 10 letras -> mensagem[10:] pega so o que vem depois
                segundos = int(mensagem[10:].decode())   # pega o 5-traforme em 5s- dps em 5milessegundos
                segundos = max(2, min(10, segundos))     
                INTERVALO = segundos * 1000              # limita o intervalo entre 2 e 10
                print("Intervalo atualizado para", segundos, "s")
            except ValueError:
                # chegou algo que nao e um numero valido -- ignora sem quebrar o programa
                print("Valor de Atualizar invalido, ignorado.")
        else:
            print("Comando de ESP32 desconhecido, ignorado.")

    else:
        print("Topico desconhecido, ignorado.")
#-----------------
#CONEXAO AO BROKER
#-----------------
client = MQTTClient(MEU_ID, BROKER, port=PORTA)   # cria o cliente MQTT
client.set_callback(ao_receber)                   # 1)Quando chegar uma mensagem, quem vai cuidar dela é a função ao_receber
client.connect()                                  # 2) conecta no broker
client.subscribe(TOPICO_AC_CMD)                   # 3)faz a ESP32 assinar os tópicos.
client.subscribe(TOPICO_JANELA_CMD)              
client.subscribe(TOPICO_ESP32)                  
# a ORDEM importa: registrar o callback ANTES de assinar. Se assinar antes,
# a mensagem chega mas nada acontece (bug silencioso).

print("Conectado ao broker", BROKER)
print("Escutando comandos em:")
print(" ", TOPICO_AC_CMD)
print(" ", TOPICO_JANELA_CMD)
print(" ", TOPICO_ESP32)

#----------------------
# LOOP PRINCIPAL
#----------------------
ultimo_envio = time.ticks_ms()   # guarda quando foi a ultima publicacao
try:
    while True:
        client.check_msg()   # verifica mensagem 
        if _ir_pronto:
            codigo = ir_decodificar()
            if DEBUG_IR:
                print("Codigo IR recebido:", hex(codigo))   # pra descobrir os codigos
            if IR_CODIGO_MAIS and codigo == IR_CODIGO_MAIS:
                temperatura_alvo = min(30, temperatura_alvo + 1)   # nunca passa de 30 AR COND
                print("Temperatura alvo:", temperatura_alvo)
            elif IR_CODIGO_MENOS and codigo == IR_CODIGO_MENOS:
                temperatura_alvo = max(16, temperatura_alvo - 1)   # nunca abaixo de 16 AR COND
                print("Temperatura alvo:", temperatura_alvo)

        agora = time.ticks_ms()
        if ativo and time.ticks_diff(agora, ultimo_envio) >= INTERVALO:
            ultimo_envio = agora   # reinicia a contagem a partir de agora

            # True se ouviu som ha menos de JANELA_PRESENCA ms
            presente = time.ticks_diff(agora, _ultimo_som) < JANELA_PRESENCA

            client.publish(TOPICO_PRESENCA, "Presente" if presente else "Vazio")
            client.publish(TOPICO_TEMP_ALVO, str(temperatura_alvo))   # numero -> texto
            client.publish(TOPICO_AC_STATUS, "Ligado" if ac_ligado else "Desligado")
            client.publish(TOPICO_JANELA_STATUS, "Aberta" if janela_aberta else "Fechada")

            print("Publicado -- presenca:", presente,
                  "| temp alvo:", temperatura_alvo,
                  "| ac:", ac_ligado,
                  "| janela:", janela_aberta)
finally:
    # roda sempre que o programa para (erro ou Ctrl+C), garantindo que a
    # conexao com o broker fecha direito
    client.disconnect()
    print("Desconectado do broker.")
