import os
import socket
import time
import random
import re

TOKEN = "oauth:seu_token"
NICK = "seu_nick"
CANAL = "nick_do_streamer"

# --- Pescar automático ---
MSG_PESCAR = "$pescar"
INTERVALO = 10 * 24

# --- Detector de frota ---
MSG_EMBARCAR = "$embarcar"
BOT_NOME = "twishgamebot"
PALAVRAS_FROTA = ["lançou a frota", "digite $embarcar"]
COOLDOWN_FROTA = 120
DEBUG = True

# --- Reset de cooldown ---
PALAVRAS_ZARPOU = ["zarpou"]     # exige menção ao seu nick
PALAVRAS_RESETADO = ["resetado"] # exige menção ao seu nick
EVENTOS_RESET = ["sorte rara pelos", "rede coletiva pelos", "garrafa ao mar", "concurso do menor peixe pelos", "peso pesado pelos", "xp em dobro", "🐠 cardume passageiro! um"]               # eventos globais, anunciados pelo nome (sem menção)
COOLDOWN_RESET = 15                       # segundos mínimos entre dois resets (evita spam)
EXIGIR_MENCAO = True

# --- Maré turbo ---
PALAVRAS_TURBO = ["maré turbo"]     # todas precisam aparecer na mensagem
PALAVRAS_TURBO_FIM = ["acabou"]  # ignora avisos de fim
DURACAO_TURBO = 10 * 60             # duração da janela turbo (segundos)
FATOR_TURBO = 0.5                   # 0.5 = cooldown pela metade
COOLDOWN_TURBO = 60                 # mínimo entre dois anúncios de turbo
TURBO_EXIGE_MENCAO = False          # True se o anúncio te marcar quando for pra você

# --- Venda turbinada ---
MSG_VENDER = "$vender todos"
PALAVRAS_VENDA = ["venda turbinada pelos"]               # todas precisam aparecer
PALAVRAS_VENDA_FIM = ["acabou", "terminou", "encerrou"]  # ignora avisos de fim
COOLDOWN_VENDA = 120                                     # mínimo entre dois envios (segundos)
VENDA_EXIGE_MENCAO = False                               # True se o anúncio te marcar

# --- Mochila cheia ---
PALAVRAS_MOCHILA = ["mochila", "cheia"]   # todas precisam aparecer
MOCHILA_EXIGE_MENCAO = True               # o aviso é pessoal, então só reage se te marcar
COOLDOWN_MOCHILA = 60                     # evita loop se a venda falhar

# --- Torneio ---
MSG_ENTRAR = "$entrar"
PALAVRAS_TORNEIO = ["torneio"]            # todas precisam aparecer
PALAVRAS_TORNEIO_FIM = ["acabou", "terminou", "encerrou", "venceu", "vencedor"]
AUTORES_TORNEIO = {BOT_NOME, CANAL.lower()}   # quem pode abrir: o bot e/ou o streamer
COOLDOWN_TORNEIO = 120

# --- Duelo ---
MSG_ACEITAR = "$aceitar"
COOLDOWN_ACEITE = 30      # mínimo entre dois aceites (segundos)
COOLDOWN_DUELO = 15       # mínimo entre dois $pescar de duelo

def conectar():
    s = socket.socket()
    s.connect(("irc.chat.twitch.tv", 6667))
    s.send(f"PASS {TOKEN}\r\n".encode())
    s.send(f"NICK {NICK}\r\n".encode())
    s.send(f"JOIN #{CANAL}\r\n".encode())
    s.settimeout(1)
    return s

def enviar(s, texto):
    s.send(f"PRIVMSG #{CANAL} :{texto}\r\n".encode())
    print(time.strftime("%H:%M:%S"), "enviado:", texto)

def parse_privmsg(linha):
    # formato: :usuario!usuario@usuario.tmi.twitch.tv PRIVMSG #canal :mensagem
    if " PRIVMSG " not in linha:
        return None, None
    try:
        autor = linha.split("!", 1)[0].lstrip(":").lower()
        texto = linha.split(" PRIVMSG ", 1)[1].split(" :", 1)[1]
        return autor, texto
    except IndexError:
        return None, None

def menciona_voce(t):
    # palavra inteira, para não casar com "ultraxfps2", por exemplo
    padrao = rf"(?<![a-z0-9_]){re.escape(NICK.lower())}(?![a-z0-9_])"
    return re.search(padrao, t) is not None

def eh_frota(autor, texto):
    if BOT_NOME and autor != BOT_NOME:
        return False
    t = texto.lower()
    return all(p.lower() in t for p in PALAVRAS_FROTA)

def eh_reset(autor, texto):
    if BOT_NOME and autor != BOT_NOME:
        return False
    t = texto.lower()

    # 1) Frota zarpou: SÓ se te marcar
    if any(p in t for p in PALAVRAS_ZARPOU):
        return menciona_voce(t)

    # 2) "resetado": dispara sem precisar de menção
    if any(p in t for p in PALAVRAS_RESETADO):
        return True

    # 3) Evento global anunciado pelo nome
    if "evento especial" in t and "acabou" not in t:
        return any(e.lower() in t for e in EVENTOS_RESET)

    return False

def eh_turbo(autor, texto):
    if BOT_NOME and autor != BOT_NOME:
        return False
    t = texto.lower()
    if not all(p in t for p in PALAVRAS_TURBO):
        return False
    if any(p in t for p in PALAVRAS_TURBO_FIM):
        return False
    if TURBO_EXIGE_MENCAO and NICK.lower() not in t:
        return False
    return True

def intervalo_atual(fim_turbo):
    base = INTERVALO
    if time.time() < fim_turbo:
        base = INTERVALO * FATOR_TURBO
    return base + random.randint(5, 30)

def eh_venda(autor, texto):
    if BOT_NOME and autor != BOT_NOME:
        return False
    t = texto.lower()
    if not all(p in t for p in PALAVRAS_VENDA):
        return False
    if any(p in t for p in PALAVRAS_VENDA_FIM):
        return False
    if VENDA_EXIGE_MENCAO and NICK.lower() not in t:
        return False
    return True

def eh_mochila_cheia(autor, texto):
    if BOT_NOME and autor != BOT_NOME:
        return False
    t = texto.lower()
    if not all(p in t for p in PALAVRAS_MOCHILA):
        return False
    if MOCHILA_EXIGE_MENCAO and not menciona_voce(t):
        return False
    return True

def eh_torneio(autor, texto):
    if autor not in AUTORES_TORNEIO:
        return False
    t = texto.lower()
    if not all(p in t for p in PALAVRAS_TORNEIO):
        return False
    if any(p in t for p in PALAVRAS_TORNEIO_FIM):
        return False
    return True

def eh_desafio(autor, texto):
    # "@fulano desafiou @voce pra um duelo! ... $aceitar"
    if BOT_NOME and autor != BOT_NOME:
        return False
    t = texto.lower()
    if "desafiou" not in t or "$aceitar" not in t:
        return False
    # só olha o que vem DEPOIS de "desafiou" e antes de "duelo":
    # se você for o desafiante, o seu nick fica antes e não conta
    alvo = t.split("desafiou", 1)[1].split("duelo", 1)[0]
    return menciona_voce(alvo)

def eh_duelo_confirmado(autor, texto):
    if BOT_NOME and autor != BOT_NOME:
        return False
    t = texto.lower()
    return "duelo entre" in t and "confirmado" in t and menciona_voce(t)

def main():
    s = conectar()
    buffer = ""
    proximo_pescar = time.time() + 5
    ultimo_embarque = 0
    ultimo_reset = 0
    ultimo_turbo = 0
    ultima_venda = 0
    ultima_mochila = 0
    ultimo_torneio = 0
    fim_turbo = 0
    ultimo_aceite = 0
    ultimo_duelo = 0

    while True:
        try:
            try:
                dados = s.recv(4096)
                if not dados:
                    raise ConnectionError("conexão fechada")
                buffer += dados.decode(errors="ignore")
            except socket.timeout:
                pass

            while "\r\n" in buffer:
                linha, buffer = buffer.split("\r\n", 1)
                if not linha:
                    continue

                if linha.startswith("PING"):
                    s.send("PONG :tmi.twitch.tv\r\n".encode())
                    continue

                autor, texto = parse_privmsg(linha)
                if texto is None:
                    print("TWITCH:", linha)
                    continue

                if DEBUG:
                    print(f"[chat] {autor}: {texto}")

                if autor == NICK.lower():
                    continue

                # Mochila cheia -> vender tudo e pescar de novo
                if eh_mochila_cheia(autor, texto):
                    if time.time() - ultima_mochila >= COOLDOWN_MOCHILA:
                        print("Mochila cheia! Vendendo e pescando...")
                        time.sleep(random.uniform(1.5, 4))
                        enviar(s, MSG_VENDER)
                        time.sleep(random.uniform(2.5, 4))
                        enviar(s, MSG_PESCAR)
                        ultima_mochila = time.time()
                        ultima_venda = time.time()
                        proximo_pescar = time.time() + intervalo_atual(fim_turbo)

                # Fui desafiado -> aceitar
                elif eh_desafio(autor, texto):
                    if time.time() - ultimo_aceite >= COOLDOWN_ACEITE:
                        print("Desafio de duelo recebido! Aceitando...")
                        time.sleep(random.uniform(1.0, 2.5))
                        enviar(s, MSG_ACEITAR)
                        ultimo_aceite = time.time()

                # Duelo confirmado -> pescar na hora
                elif eh_duelo_confirmado(autor, texto):
                    if time.time() - ultimo_duelo >= COOLDOWN_DUELO:
                        print("Duelo confirmado! Pescando...")
                        time.sleep(random.uniform(1.0, 2.5))
                        enviar(s, MSG_PESCAR)
                        ultimo_duelo = time.time()
                        ultimo_reset = time.time()
                        proximo_pescar = time.time() + intervalo_atual(fim_turbo)

                # Torneio aberto -> entrar e pescar
                elif eh_torneio(autor, texto):
                    if time.time() - ultimo_torneio >= COOLDOWN_TORNEIO:
                        print("Torneio aberto! Entrando...")
                        time.sleep(random.uniform(1.5, 4))
                        enviar(s, MSG_ENTRAR)
                        time.sleep(random.uniform(2.5, 4))
                        enviar(s, MSG_PESCAR)
                        ultimo_torneio = time.time()
                        proximo_pescar = time.time() + intervalo_atual(fim_turbo)

                # Venda turbinada -> vender tudo
                elif eh_venda(autor, texto):
                    if time.time() - ultima_venda >= COOLDOWN_VENDA:
                        print("Venda turbinada! Vendendo tudo...")
                        time.sleep(random.uniform(1.5, 4))
                        enviar(s, MSG_VENDER)
                        ultima_venda = time.time()

                # Maré turbo -> pesca na hora + cooldown reduzido
                elif eh_turbo(autor, texto):
                    if time.time() - ultimo_turbo >= COOLDOWN_TURBO:
                        print("Maré turbo! Cooldown pela metade por 10 min.")
                        fim_turbo = time.time() + DURACAO_TURBO
                        ultimo_turbo = time.time()
                        time.sleep(random.uniform(1.5, 4))
                        enviar(s, MSG_PESCAR)
                        ultimo_reset = time.time()
                        proximo_pescar = time.time() + intervalo_atual(fim_turbo)

                # Frota aberta -> embarcar
                elif eh_frota(autor, texto):
                    if time.time() - ultimo_embarque >= COOLDOWN_FROTA:
                        time.sleep(random.uniform(1.5, 4))
                        enviar(s, MSG_EMBARCAR)
                        ultimo_embarque = time.time()

                # Cooldown resetado -> pescar na hora
                elif eh_reset(autor, texto):
                    if time.time() - ultimo_reset >= COOLDOWN_RESET:
                        print("Cooldown resetado, pescando...")
                        time.sleep(random.uniform(1.5, 4))
                        enviar(s, MSG_PESCAR)
                        ultimo_reset = time.time()
                        proximo_pescar = time.time() + intervalo_atual(fim_turbo)

            if time.time() >= proximo_pescar:
                enviar(s, MSG_PESCAR)
                proximo_pescar = time.time() + intervalo_atual(fim_turbo)

        except (ConnectionError, OSError):
            print("Conexão caiu, reconectando...")
            while True:
                time.sleep(10)
                try:
                    s = conectar()
                    buffer = ""
                    break
                except OSError:
                    print("Falhou, tentando de novo...")

main()