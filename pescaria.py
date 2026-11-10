import os
import socket
import time
import random

TOKEN = "seu_token"
NICK = "seu_nick"
CANAL = "nick_da_live"

# --- Pescar automático ---
MSG_PESCAR = "$pescar"
INTERVALO = 10 * 18

# --- Detector de frota ---
MSG_EMBARCAR = "$embarcar"
BOT_NOME = "twishgamebot"
PALAVRAS_FROTA = ["lançou a frota", "digite $embarcar"]
COOLDOWN_FROTA = 120
DEBUG = True

# --- Reset de cooldown do pescar ---
PALAVRAS_RESET = ["zarpou", "resetado"]   
COOLDOWN_RESET = 15                       

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

def eh_frota(autor, texto):
    if BOT_NOME and autor != BOT_NOME:
        return False
    t = texto.lower()
    return all(p.lower() in t for p in PALAVRAS_FROTA)

def eh_reset(autor, texto):
    if BOT_NOME and autor != BOT_NOME:
        return False
    t = texto.lower()
    return any(p in t for p in PALAVRAS_RESET)

def main():
    s = conectar()
    buffer = ""
    proximo_pescar = time.time() + 5
    ultimo_embarque = 0
    ultimo_reset = 0

    while True:
        try:
            try:
                buffer += s.recv(4096).decode(errors="ignore")
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

                # Frota aberta -> embarcar
                if eh_frota(autor, texto):
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
                        proximo_pescar = time.time() + INTERVALO + random.randint(5, 30)

            if time.time() >= proximo_pescar:
                enviar(s, MSG_PESCAR)
                proximo_pescar = time.time() + INTERVALO + random.randint(5, 30)

        except (ConnectionError, OSError):
            print("Conexão caiu, reconectando...")
            time.sleep(5)
            s = conectar()
            buffer = ""

main()