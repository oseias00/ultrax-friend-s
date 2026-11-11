import json, os, queue, random, re, socket, sys, threading, time
import urllib.error, urllib.parse, urllib.request, webbrowser
import tkinter as tk
from tkinter import ttk, messagebox, font as tkfont

VARAS = {
    "Vara de bambu": 10, "Vara de madeira reforçada": 9, "Vara de fibra de vidro": 8,
    "Vara de aço": 7, "Vara de carbono": 6, "Vara encantada": 5,
    "Vara abissal": 4, "Vara lendária": 3, "Vara njord": 2,
}
ARQ = os.path.join(os.environ.get("APPDATA") or os.path.expanduser("~/.config"),
                   "FishersFriend", "config.json")

# ---------- Palavras-chave (ajuste aqui se o bot mudar o texto) ----------
MSG_PESCAR, MSG_EMBARCAR, MSG_ENTRAR, MSG_ACEITAR = "$pescar", "$embarcar", "$entrar", "$aceitar"
PALAVRAS_FROTA = ["lançou a frota", "digite $embarcar"]
PALAVRAS_ZARPOU, PALAVRAS_RESETADO = ["zarpou"], ["resetado"]
PALAVRAS_TURBO, PALAVRAS_TURBO_FIM = ["maré turbo"], ["acabou"]
PALAVRAS_VENDA, PALAVRAS_VENDA_FIM = ["venda turbinada pelos"], ["acabou", "terminou", "encerrou"]
PALAVRAS_MOCHILA = ["mochila", "cheia"]
PALAVRAS_TORNEIO = ["torneio"]
PALAVRAS_TORNEIO_FIM = ["acabou", "terminou", "encerrou", "venceu", "vencedor", "ganhou", "campeão", "resultado"]
DURACAO_TURBO, FATOR_TURBO = 600, 0.5
PALAVRAS_EXPEDICAO_FIM = []   # opcional: palavras da msg que encerra a expedição (precisa te citar)
CD = {"frota": 120, "reset": 15, "turbo": 60, "venda": 120, "mochila": 60,
      "torneio": 120, "aceite": 30, "duelo": 15}

# ---------- Login oficial da Twitch ----------
# Cole aqui o Client ID do seu app (dev.twitch.tv/console, tipo de cliente: Public)
CLIENT_ID = "ou5q0j7cdwzzrxdp4kp6ze63fq1il7"
ESCOPOS = "chat:read chat:edit"
URL_DEVICE = "https://id.twitch.tv/oauth2/device"
URL_TOKEN = "https://id.twitch.tv/oauth2/token"
URL_VALIDATE = "https://id.twitch.tv/oauth2/validate"
URL_REVOKE = "https://id.twitch.tv/oauth2/revoke"

# ---------- Configuração ----------
CFG = {
    "nick": "", "access_token": "", "refresh_token": "", "canal": "", "bot": "twishgamebot",
    "vara": "Vara abissal", "personalizado": False, "segundos": 240, "intervalo": 240,
    "debug": True,
    # valores fixos, só no código:
    "msg_vender": "$vender todos", "exp_seg": 1800,
    "eventos_reset": "sorte rara pelos, rede coletiva pelos, garrafa ao mar, concurso menor peixe, "
                     "peso pesado pelos, xp em dobro, cardume passageiro",
}
FUNCOES = {   # chave: (texto na interface, ligado por padrão)
    "pescar": ("Pescar automático", True),
    "frota": ("Embarcar em frotas", True),
    "venda": ("Venda turbinada", True),
    "mochila": ("Mochila cheia", True),
    "torneio": ("Entrar em torneios", True),
    "duelo": ("Aceitar duelos", True),
}
# "reset" e "turbo" não são mais opções: ficam sempre ativos.
# Estão em FIXAS só para ignorar valores antigos que ainda existam no config.json salvo.
FIXAS = {"msg_vender", "eventos_reset", "exp_seg", "exp_min", "token", "lembrar_token", "intervalo",
         "reset", "turbo"}
for k, (_, on) in FUNCOES.items():
    CFG[k] = on

def salvar_cfg():
    try:
        os.makedirs(os.path.dirname(ARQ), exist_ok=True)
        with open(ARQ, "w", encoding="utf-8") as f:
            json.dump({k: v for k, v in CFG.items() if k not in FIXAS}, f, ensure_ascii=False, indent=2)
    except OSError:
        pass

def carregar_cfg():
    try:
        with open(ARQ, encoding="utf-8") as f:
            CFG.update({k: v for k, v in json.load(f).items() if k not in FIXAS})
    except (OSError, ValueError):
        pass

# ---------- Rede / autenticação ----------
def http(metodo, url, dados=None, headers=None):
    """Devolve (status, json). Status 0 = sem conexão."""
    corpo = urllib.parse.urlencode(dados).encode() if dados else None
    req = urllib.request.Request(url, data=corpo, method=metodo, headers=headers or {})
    if corpo:
        req.add_header("Content-Type", "application/x-www-form-urlencoded")
    try:
        with urllib.request.urlopen(req, timeout=15) as r:
            return r.status, json.loads(r.read().decode() or "{}")
    except urllib.error.HTTPError as e:
        try: return e.code, json.loads(e.read().decode())
        except Exception: return e.code, {}
    except Exception:
        return 0, {}

def _guardar_tokens(j):
    CFG["access_token"] = j.get("access_token", "")
    CFG["refresh_token"] = j.get("refresh_token", CFG["refresh_token"])
    salvar_cfg()

def garantir_token():
    """True = token válido; False = precisa logar de novo; None = sem conexão no momento."""
    tok = CFG.get("access_token", "")
    if tok:
        st, j = http("GET", URL_VALIDATE, headers={"Authorization": f"OAuth {tok}"})
        if st == 200 and "chat:edit" in j.get("scopes", []):
            CFG["nick"] = j.get("login", CFG["nick"]); return True
        if st == 0 or st >= 500: return None
    rt = CFG.get("refresh_token", "")
    if rt:
        st, j = http("POST", URL_TOKEN, dados={"client_id": CLIENT_ID,
                     "grant_type": "refresh_token", "refresh_token": rt})
        if st == 200 and j.get("access_token"):
            _guardar_tokens(j); return garantir_token()
        if st == 0 or st >= 500: return None
    CFG["access_token"] = CFG["refresh_token"] = ""
    salvar_cfg()
    return False

class LoginThread(threading.Thread):
    """Login por código de dispositivo: a pessoa só autoriza no navegador."""
    def __init__(self, q):
        super().__init__(daemon=True)
        self.q, self.cancelar = q, threading.Event()

    def run(self):
        st, j = http("POST", URL_DEVICE, dados={"client_id": CLIENT_ID, "scopes": ESCOPOS})
        if st != 200 or "device_code" not in j:
            self.q.put(("login_erro", f"Não foi possível iniciar o login (erro {st}).\n"
                        "Confira o CLIENT_ID e se o app está como tipo Public.")); return
        self.q.put(("login_codigo", j["user_code"], j["verification_uri"]))
        fim = time.time() + j.get("expires_in", 1800)
        intervalo = j.get("interval", 5)
        while time.time() < fim and not self.cancelar.wait(intervalo):
            st, t = http("POST", URL_TOKEN, dados={
                "client_id": CLIENT_ID, "scopes": ESCOPOS, "device_code": j["device_code"],
                "grant_type": "urn:ietf:params:oauth:grant-type:device_code"})
            if st == 200 and t.get("access_token"):
                _guardar_tokens(t)
                if garantir_token():
                    self.q.put(("login_ok", CFG["nick"])); return
                self.q.put(("login_erro", "A Twitch não liberou as permissões de chat.")); return
            msg = str(t.get("message", "")).lower()
            if "pending" in msg: continue
            if "slow" in msg: intervalo += 5; continue
            self.q.put(("login_erro", f"Login não concluído: {t.get('message', st)}")); return
        if not self.cancelar.is_set():
            self.q.put(("login_erro", "O tempo para autorizar acabou. Tente de novo."))

# ---------- Detectores ----------
def menciona_voce(t):
    return re.search(rf"(?<![a-z0-9_]){re.escape(CFG['nick'].lower())}(?![a-z0-9_])", t) is not None

def do_bot(autor):
    return (not CFG["bot"].strip()) or autor == CFG["bot"].strip().lower()

def tudo(t, ps): return all(p in t for p in ps)
def algum(t, ps): return any(p in t for p in ps)

def eh_zarpou_voce(a, x):
    t = x.lower()
    return do_bot(a) and algum(t, PALAVRAS_ZARPOU) and menciona_voce(t)

def eh_fim_expedicao(a, x):
    t = x.lower()
    return bool(PALAVRAS_EXPEDICAO_FIM) and do_bot(a) and algum(t, PALAVRAS_EXPEDICAO_FIM) and menciona_voce(t)

def eh_frota(a, x): return do_bot(a) and tudo(x.lower(), PALAVRAS_FROTA)

def eh_reset(a, x):
    if not do_bot(a): return False
    t = x.lower()
    if algum(t, PALAVRAS_ZARPOU): return menciona_voce(t)
    if algum(t, PALAVRAS_RESETADO): return True
    if "evento especial" in t and "acabou" not in t:
        eventos = [e.strip().lower() for e in CFG["eventos_reset"].split(",") if e.strip()]
        return algum(t, eventos)
    return False

def eh_turbo(a, x):
    t = x.lower()
    return do_bot(a) and tudo(t, PALAVRAS_TURBO) and not algum(t, PALAVRAS_TURBO_FIM)

def eh_fim_turbo(a, x):
    t = x.lower()
    return do_bot(a) and tudo(t, PALAVRAS_TURBO) and algum(t, PALAVRAS_TURBO_FIM)

def eh_venda(a, x):
    t = x.lower()
    return do_bot(a) and tudo(t, PALAVRAS_VENDA) and not algum(t, PALAVRAS_VENDA_FIM)

def eh_mochila(a, x):
    t = x.lower()
    return do_bot(a) and tudo(t, PALAVRAS_MOCHILA) and menciona_voce(t)

def eh_torneio(a, x):
    t = x.lower()
    return (a == CFG["bot"].strip().lower() and tudo(t, PALAVRAS_TORNEIO)
            and not algum(t, PALAVRAS_TORNEIO_FIM))

def eh_desafio(a, x):
    t = x.lower()
    if not do_bot(a) or "desafiou" not in t or "$aceitar" not in t: return False
    return menciona_voce(t.split("desafiou", 1)[1].split("duelo", 1)[0])

def eh_duelo_ok(a, x):
    t = x.lower()
    return do_bot(a) and "duelo entre" in t and "confirmado" in t and menciona_voce(t)

def intervalo_atual(fim_turbo):
    base = CFG["intervalo"] * (FATOR_TURBO if time.time() < fim_turbo else 1)
    return base + random.randint(5, 30)

def parse_privmsg(linha):
    if " PRIVMSG " not in linha: return None, None
    try:
        return (linha.split("!", 1)[0].lstrip(":").lower(),
                linha.split(" PRIVMSG ", 1)[1].split(" :", 1)[1])
    except IndexError:
        return None, None

# ---------- Lógica ----------
def novo_estado():
    e = {k: 0 for k in CD}
    e.update(proximo_pescar=time.time() + 5, fim_turbo=0, expedicao_ate=0)
    return e

def tratar(est, autor, texto, env, esperar, log):
    if autor == CFG["nick"].lower(): return
    agora = time.time()
    ok = lambda k: agora - est[k] >= CD[k]
    def agendar(): est["proximo_pescar"] = time.time() + intervalo_atual(est["fim_turbo"])
    def d(a, b): esperar(random.uniform(a, b))

    # Diagnóstico: zarpou que não te cita
    if do_bot(autor) and algum(texto.lower(), PALAVRAS_ZARPOU) and not menciona_voce(texto.lower()):
        log(f"Zarpou ignorado: não achei '{CFG['nick']}' na mensagem.")

    # Expedição: o turbo não vale para quem está nela
    if eh_zarpou_voce(autor, texto):
        est["expedicao_ate"] = agora + CFG["exp_seg"]
        if est["fim_turbo"] > agora: log("Expedição iniciada: maré turbo anulada.")
        est["fim_turbo"] = 0
    elif eh_fim_expedicao(autor, texto):
        est["expedicao_ate"] = 0
        log("Expedição encerrada.")
    em_expedicao = agora < est["expedicao_ate"]

    if eh_fim_turbo(autor, texto):
        est["fim_turbo"] = 0
    elif CFG["mochila"] and eh_mochila(autor, texto):
        if ok("mochila"):
            log("Mochila cheia! Vendendo e pescando...")
            d(1.5, 4); env(CFG["msg_vender"]); d(2.5, 4); env(MSG_PESCAR)
            est["mochila"] = est["venda"] = time.time(); agendar()
    elif CFG["duelo"] and eh_desafio(autor, texto):
        if ok("aceite"):
            log("Desafio de duelo! Aceitando...")
            d(1, 2.5); env(MSG_ACEITAR); est["aceite"] = time.time()
    elif eh_duelo_ok(autor, texto):   # sempre pesca ao confirmar, aceito manual ou automático
        if ok("duelo"):
            log("Duelo confirmado! Pescando...")
            d(1, 2.5); env(MSG_PESCAR); est["duelo"] = est["reset"] = time.time(); agendar()
    elif CFG["torneio"] and eh_torneio(autor, texto):
        if ok("torneio"):
            log("Torneio aberto! Entrando...")
            d(1.5, 4); env(MSG_ENTRAR); d(2.5, 4); env(MSG_PESCAR)
            est["torneio"] = time.time(); agendar()
    elif CFG["venda"] and eh_venda(autor, texto):
        if ok("venda"):
            log("Venda turbinada! Vendendo tudo...")
            d(1.5, 4); env(CFG["msg_vender"]); est["venda"] = time.time()
    elif eh_turbo(autor, texto):
        if em_expedicao:
            log("Maré turbo ignorada: você está em expedição.")
        elif ok("turbo"):
            log("Maré turbo! Cooldown pela metade por 10 min.")
            est["fim_turbo"] = est["turbo"] = time.time()
            est["fim_turbo"] += DURACAO_TURBO
            d(1.5, 4); env(MSG_PESCAR); est["reset"] = time.time(); agendar()
    elif CFG["frota"] and eh_frota(autor, texto):
        if ok("frota"):
            log("Frota aberta! Embarcando...")
            d(1.5, 4); env(MSG_EMBARCAR); est["frota"] = time.time()
    elif eh_reset(autor, texto):
        if ok("reset"):
            log("Cooldown resetado! Pescando...")
            d(1.5, 4); env(MSG_PESCAR); est["reset"] = time.time(); agendar()
        else:
            log("Reset ignorado: outro $pescar de reset saiu há menos de 15s.")

class Bot(threading.Thread):
    def __init__(self, log):
        super().__init__(daemon=True)
        self.log, self.parar, self.s = log, threading.Event(), None

    def conectar(self):
        s = socket.socket(); s.settimeout(15)
        s.connect(("irc.chat.twitch.tv", 6667))
        s.send(f"PASS oauth:{CFG['access_token']}\r\nNICK {CFG['nick'].lower()}\r\n"
               f"JOIN #{CFG['canal'].lower()}\r\n".encode())
        s.settimeout(1)
        return s

    def env(self, texto):
        self.s.send(f"PRIVMSG #{CFG['canal'].lower()} :{texto}\r\n".encode("utf-8"))
        self.log(f"{time.strftime('%H:%M:%S')} enviado: {texto}")

    def run(self):
        r = garantir_token()
        if r is False:
            self.log("Sessão expirada: entre com a Twitch novamente."); return
        if r is None:
            self.log("Sem conexão com a Twitch. Tente de novo."); return
        est, buf = novo_estado(), b""
        try:
            self.s = self.conectar()
        except OSError as e:
            self.log(f"Falha ao conectar: {e}"); return
        while not self.parar.is_set():
            try:
                try:
                    dados = self.s.recv(4096)
                    if not dados: raise ConnectionError("fechada")
                    buf += dados
                except socket.timeout:
                    pass
                while b"\r\n" in buf and not self.parar.is_set():
                    bruta, buf = buf.split(b"\r\n", 1)
                    linha = bruta.decode("utf-8", errors="replace")
                    if linha.startswith("PING"):
                        self.s.send(b"PONG :tmi.twitch.tv\r\n"); continue
                    autor, texto = parse_privmsg(linha)
                    if texto is None:
                        low = linha.lower()
                        if "authentication failed" in low or "login unsuccessful" in low:
                            self.log("Login recusado pelo chat. Saia da conta e entre de novo.")
                            self.parar.set(); break
                        if " 001 " in linha: self.log("Conectado ao chat!")
                        elif "NOTICE" in linha: self.log("TWITCH: " + linha)
                        continue
                    if CFG["debug"]: self.log(f"[chat] {autor}: {texto}")
                    try:
                        tratar(est, autor, texto, self.env, self.parar.wait, self.log)
                    except (ConnectionError, OSError):
                        raise
                    except Exception as e:
                        self.log(f"Falha interna ao tratar a mensagem: {e!r}")
                if CFG["pescar"] and time.time() >= est["proximo_pescar"]:
                    self.env(MSG_PESCAR)
                    est["proximo_pescar"] = time.time() + intervalo_atual(est["fim_turbo"])
            except (ConnectionError, OSError):
                if self.parar.is_set(): break
                self.log("Conexão caiu, reconectando...")
                while not self.parar.wait(10):
                    r = garantir_token()   # renova o token se já passou das ~4h
                    if r is False:
                        self.log("Sessão expirada: entre com a Twitch novamente.")
                        self.parar.set(); break
                    if r is None:
                        self.log("Sem conexão com a Twitch, tentando de novo..."); continue
                    try: self.s = self.conectar(); buf = b""; break
                    except OSError: self.log("Falhou, tentando de novo...")
        try: self.s.close()
        except Exception: pass
        self.log("Desconectado.")


# ---------- Interface ----------
BG, PAINEL, CAMPO, BORDA, LOGBG = "#0f0f12", "#18181c", "#25252b", "#2c2c34", "#0b0b0d"
TXT, SUB, ROXO, ROXO2, CLARO = "#efeff1", "#9a9aa8", "#9146ff", "#772ce8", "#bf94ff"
VERDE, VERMELHO, DESAB = "#3ddc84", "#ff6b6b", "#5d5d68"
FONTE, MONO = "Segoe UI", "Consolas"
LARGURA_LARGA, LARGURA_SUB = 820, 640   # abaixo disso o layout empilha / esconde o subtítulo

ICONE_64 = (
    "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"
    "dtC5ff5/AWaZ1VD6taMzAAAAAElFTkSuQmCC"
)
ICONE_32 = (
    "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"
)

def escolher_fontes(root):
    fam = set(tkfont.families(root))
    f = next((n for n in ("Segoe UI", "Inter", "SF Pro Text", "Helvetica Neue", "Noto Sans", "DejaVu Sans") if n in fam), "TkDefaultFont")
    m = next((n for n in ("Cascadia Mono", "Consolas", "SF Mono", "Menlo", "DejaVu Sans Mono") if n in fam), "TkFixedFont")
    return f, m

class Botao(tk.Canvas):
    """Botão arredondado com hover. Aceita config(text=, state=, estilo=, command=)."""
    ESTILOS = {   # normal, hover, texto
        "primario": (ROXO, ROXO2, "#ffffff"),
        "neutro": ("#2d2d35", "#3a3a45", TXT),
    }

    def __init__(self, pai, texto, comando, estilo="neutro", altura=38, largura=10, fundo=PAINEL, tam=10):
        super().__init__(pai, height=altura, width=largura, bg=fundo, highlightthickness=0, bd=0)
        self.texto, self.comando, self.estilo, self.estado, self.tam = texto, comando, estilo, "normal", tam
        self.passou = self.premido = False
        self.bind("<Configure>", lambda e: self.desenhar())
        self.bind("<Enter>", lambda e: self._hover(True))
        self.bind("<Leave>", lambda e: self._hover(False))
        self.bind("<ButtonPress-1>", self._press)
        self.bind("<ButtonRelease-1>", self._release)
        self._cursor()

    def configure(self, cnf=None, **kw):
        mudou = False
        for chave, attr in (("text", "texto"), ("state", "estado"), ("estilo", "estilo"), ("command", "comando")):
            if chave in kw:
                novo = kw.pop(chave)
                if getattr(self, attr) != novo:
                    setattr(self, attr, novo); mudou = True
        if cnf or kw:
            super().configure(cnf, **kw)
        if mudou:
            self._cursor(); self.desenhar()
    config = configure

    def _cursor(self):
        super().configure(cursor="arrow" if self.estado == "disabled" else "hand2")

    def _hover(self, v):
        self.passou = v; self.desenhar()

    def _press(self, e):
        if self.estado != "disabled":
            self.premido = True; self.desenhar()

    def _release(self, e):
        era, self.premido = self.premido, False
        self.desenhar()
        if era and self.estado != "disabled" and self.comando \
                and 0 <= e.x <= self.winfo_width() and 0 <= e.y <= self.winfo_height():
            self.comando()

    def _rr(self, x1, y1, x2, y2, r, **kw):
        r = max(1, min(r, (y2 - y1) // 2))
        pts = [x1 + r, y1, x1 + r, y1, x2 - r, y1, x2 - r, y1, x2, y1, x2, y1 + r, x2, y1 + r, x2, y2 - r,
               x2, y2 - r, x2, y2, x2 - r, y2, x2 - r, y2, x1 + r, y2, x1 + r, y2, x1, y2, x1, y2 - r,
               x1, y2 - r, x1, y1 + r, x1, y1 + r, x1, y1]
        return self.create_polygon(pts, smooth=True, **kw)

    def desenhar(self):
        self.delete("all")
        w, h = self.winfo_width(), self.winfo_height()
        if w < 4 or h < 4: return
        normal, hover, fg = self.ESTILOS.get(self.estilo, self.ESTILOS["neutro"])
        if self.estado == "disabled": cor, fg = "#202026", DESAB
        elif self.premido or self.passou: cor = hover
        else: cor = normal
        self._rr(1, 1, w - 1, h - 1, 10, fill=cor, outline=cor)
        self.create_text(w // 2, h // 2, text=self.texto, fill=fg, font=(FONTE, self.tam, "bold"))

class Chave(tk.Canvas):
    """Interruptor (liga/desliga) ligado a uma BooleanVar."""
    def __init__(self, pai, var, fundo=PAINEL):
        super().__init__(pai, width=42, height=24, bg=fundo, highlightthickness=0, bd=0, cursor="hand2")
        self.var = var
        var.trace_add("write", lambda *a: self.desenhar())
        self.bind("<Button-1>", lambda e: self.alternar())
        self.desenhar()

    def alternar(self):
        self.var.set(not self.var.get())

    def desenhar(self):
        try:
            self.delete("all")
            on = bool(self.var.get())
            cor = ROXO if on else "#3a3a44"
            self.create_oval(1, 1, 23, 23, fill=cor, outline=cor)
            self.create_oval(19, 1, 41, 23, fill=cor, outline=cor)
            self.create_rectangle(12, 1, 30, 23, fill=cor, outline=cor)
            x = 21 if on else 3
            self.create_oval(x, 3, x + 18, 21, fill="#ffffff", outline="#ffffff")
        except tk.TclError:
            pass

class Rolavel(tk.Frame):
    """Área com rolagem vertical que estica o conteúdo quando a janela é maior que ele."""
    def __init__(self, pai, bg):
        super().__init__(pai, bg=bg)
        self.cv = tk.Canvas(self, bg=bg, highlightthickness=0, bd=0)
        self.sb = ttk.Scrollbar(self, orient="vertical", command=self.cv.yview)
        self.cv.configure(yscrollcommand=self.sb.set)
        self.sb.pack(side="right", fill="y")
        self.cv.pack(side="left", fill="both", expand=True)
        self.inner = tk.Frame(self.cv, bg=bg)
        self.win = self.cv.create_window(0, 0, window=self.inner, anchor="nw")
        self.cv.bind("<Configure>", lambda e: self.ajustar())
        self.inner.bind("<Configure>", lambda e: self.ajustar())
        for ev in ("<MouseWheel>", "<Button-4>", "<Button-5>"):
            self.bind_all(ev, self.rolar, add="+")

    def ajustar(self):
        w, h = self.cv.winfo_width(), self.cv.winfo_height()
        alvo = max(h, self.inner.winfo_reqheight())
        self.cv.itemconfigure(self.win, width=w, height=alvo)
        self.cv.configure(scrollregion=(0, 0, w, alvo))
        if alvo <= h: self.cv.yview_moveto(0)

    def rolar(self, e):
        if isinstance(e.widget, (tk.Text, tk.Listbox)): return
        if self.inner.winfo_reqheight() <= self.cv.winfo_height(): return
        if e.num == 4: n = -1
        elif e.num == 5: n = 1
        else: n = -1 if e.delta > 0 else 1
        self.cv.yview_scroll(n * 2, "units")

class App(tk.Tk):
    def __init__(self):
        global FONTE, MONO
        if sys.platform == "win32":   # faz o ícone próprio aparecer na barra de tarefas
            try:
                import ctypes
                ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("ultrax.fishersfriend")
            except Exception:
                pass
        super().__init__()
        FONTE, MONO = escolher_fontes(self)
        self.title("fisher's friend by ultrax"); self.geometry("1020x720"); self.minsize(360, 480)
        self.q, self.bot, self.v, self.login_t, self.dlg = queue.Queue(), None, {}, None, None
        self.largo, self.sub_vis = True, True
        self.ico64, self.ico32 = tk.PhotoImage(data=ICONE_64), tk.PhotoImage(data=ICONE_32)
        try: self.iconphoto(True, self.ico64)
        except tk.TclError: pass
        carregar_cfg()
        self.estilos(); self.montar(); self.sync()
        self.bind("<Configure>", self.ao_redimensionar)
        self.protocol("WM_DELETE_WINDOW", self.fechar)
        self.after(100, self.drenar)

    # ----- estilos -----
    def estilos(self):
        self.configure(bg=BG)
        st = ttk.Style(self); st.theme_use("clam")
        st.configure(".", background=BG, foreground=TXT, fieldbackground=CAMPO, font=(FONTE, 10),
                     bordercolor=BORDA, troughcolor=BG)
        borda = dict(bordercolor=BORDA, lightcolor=BORDA, darkcolor=BORDA)
        foco = dict(bordercolor=[("focus", ROXO)], lightcolor=[("focus", ROXO)], darkcolor=[("focus", ROXO)])
        st.configure("TEntry", fieldbackground=CAMPO, foreground=TXT, insertcolor=TXT, padding=(8, 6), **borda)
        st.map("TEntry", fieldbackground=[("disabled", PAINEL)], foreground=[("disabled", DESAB)], **foco)
        st.configure("TCombobox", fieldbackground=CAMPO, background=CAMPO, foreground=TXT,
                     arrowcolor=SUB, padding=(8, 6), **borda)
        st.map("TCombobox", fieldbackground=[("readonly", CAMPO), ("disabled", PAINEL)],
               foreground=[("readonly", TXT), ("disabled", DESAB)],
               background=[("active", "#2f2f37"), ("disabled", PAINEL)],
               arrowcolor=[("disabled", DESAB)],
               selectbackground=[("readonly", CAMPO)], selectforeground=[("readonly", TXT)], **foco)
        self.option_add("*TCombobox*Listbox.background", CAMPO)
        self.option_add("*TCombobox*Listbox.foreground", TXT)
        self.option_add("*TCombobox*Listbox.selectBackground", ROXO)
        self.option_add("*TCombobox*Listbox.selectForeground", "#ffffff")
        self.bind_class("TCombobox", "<MouseWheel>", lambda e: None)   # evita trocar a vara rolando a página
        for nome, trilho in (("Vertical.TScrollbar", BG), ("Log.Vertical.TScrollbar", LOGBG)):
            st.configure(nome, background="#34343d", troughcolor=trilho, bordercolor=trilho,
                         lightcolor="#34343d", darkcolor="#34343d", arrowcolor=SUB, relief="flat")
            st.map(nome, background=[("active", "#4a4a55"), ("pressed", "#4a4a55")])
            try:   # barra fina, sem setinhas
                st.layout(nome, [("Vertical.Scrollbar.trough", {"sticky": "ns", "children": [
                    ("Vertical.Scrollbar.thumb", {"expand": "1", "sticky": "nswe"})]})])
            except tk.TclError:
                pass

    def var(self, chave, tipo=tk.StringVar):
        self.v[chave] = tipo(value=CFG[chave])
        self.v[chave].trace_add("write", lambda *a: self.sync())
        return self.v[chave]

    # ----- peças -----
    def card(self, pai, titulo):
        f = tk.Frame(pai, bg=PAINEL, highlightthickness=1, highlightbackground=BORDA, highlightcolor=BORDA)
        f.pack(fill="x", pady=(0, 10))
        tk.Label(f, text=titulo.upper(), bg=PAINEL, fg=SUB, font=(FONTE, 8, "bold")).pack(anchor="w", padx=14, pady=(12, 6))
        c = tk.Frame(f, bg=PAINEL); c.pack(fill="x", padx=14, pady=(0, 14))
        return c

    def linha_chave(self, pai, texto, var, pady=4):
        f = tk.Frame(pai, bg=PAINEL); f.pack(fill="x", pady=pady)
        ch = Chave(f, var); ch.pack(side="right")
        lab = tk.Label(f, text=texto, bg=PAINEL, fg=TXT, font=(FONTE, 10), anchor="w", cursor="hand2")
        lab.pack(side="left", fill="x", expand=True)
        lab.bind("<Button-1>", lambda e: ch.alternar())
        return f

    def montar(self):
        # Cabeçalho
        topo = tk.Frame(self, bg=PAINEL); topo.pack(fill="x")
        tk.Label(topo, image=self.ico32, bg=PAINEL).pack(side="left", padx=(14, 10), pady=10)
        tit = tk.Frame(topo, bg=PAINEL); tit.pack(side="left")
        tk.Label(tit, text="fisher's friend", bg=PAINEL, fg=TXT, font=(FONTE, 14, "bold")).pack(anchor="w")
        self.lbl_sub = tk.Label(tit, text="o seu amigo auxiliar de pesca  ·  by ultrax", bg=PAINEL, fg=SUB,
                                font=(FONTE, 9))
        self.lbl_sub.pack(anchor="w")
        pill = tk.Frame(topo, bg=CAMPO); pill.pack(side="right", padx=14)
        self.dot = tk.Label(pill, text="●", bg=CAMPO, fg=SUB, font=(FONTE, 10)); self.dot.pack(side="left", padx=(10, 4), pady=5)
        self.status = tk.Label(pill, text="Desconectado", bg=CAMPO, fg=TXT, font=(FONTE, 9, "bold"))
        self.status.pack(side="left", padx=(0, 12))
        tk.Frame(self, bg=ROXO, height=2).pack(fill="x")

        # Corpo rolável (duas colunas em janela larga, empilhado em janela pequena)
        self.rol = Rolavel(self, BG); self.rol.pack(fill="both", expand=True)
        self.corpo = self.rol.inner
        self.esq, self.dir = tk.Frame(self.corpo, bg=BG), tk.Frame(self.corpo, bg=BG)
        esq, dir_ = self.esq, self.dir

        # Conta
        c = self.card(esq, "Conta da Twitch")
        self.lbl_conta = tk.Label(c, text="", bg=PAINEL, fg=SUB, font=(FONTE, 10), anchor="w", justify="left")
        self.lbl_conta.pack(fill="x")
        self.btn_conta = Botao(c, "Entrar com a Twitch", self.conta_click, "primario")
        self.btn_conta.pack(fill="x", pady=(10, 0))

        # Canal
        c = self.card(esq, "Canal")
        self.campos = []
        for i, (rot, ch) in enumerate((("Canal", "canal"), ("Bot do canal", "bot"))):
            tk.Label(c, text=rot, bg=PAINEL, fg=SUB, font=(FONTE, 9), anchor="w").pack(fill="x", pady=(0 if i == 0 else 8, 3))
            e = ttk.Entry(c, textvariable=self.var(ch)); e.pack(fill="x")
            self.campos.append(e)

        # Vara
        c = self.card(esq, "Vara")
        self.cb = ttk.Combobox(c, textvariable=self.var("vara"), values=list(VARAS), state="readonly")
        self.cb.pack(fill="x")
        self.linha_chave(c, "Tempo personalizado", self.var("personalizado", tk.BooleanVar), pady=(10, 4))
        g = tk.Frame(c, bg=PAINEL); g.pack(fill="x")
        self.ent_seg = ttk.Entry(g, textvariable=self.var("segundos"), width=8, justify="center")
        self.ent_seg.pack(side="right")
        tk.Label(g, text="Segundos", bg=PAINEL, fg=SUB, font=(FONTE, 9)).pack(side="left")
        self.lbl_cd = tk.Label(c, text="", bg=PAINEL, fg=SUB, font=(FONTE, 9), anchor="w", justify="left")
        self.lbl_cd.pack(fill="x", pady=(10, 0))

        # Funções
        c = self.card(esq, "Funções")
        for k, (txt, _) in FUNCOES.items():
            self.linha_chave(c, txt, self.var(k, tk.BooleanVar))
        tk.Label(c, text="Maré turbo e reset de cooldown ficam sempre ativos.", bg=PAINEL, fg=SUB,
                 font=(FONTE, 8), anchor="w", justify="left").pack(fill="x", pady=(8, 0))

        # Botões
        b = tk.Frame(esq, bg=BG); b.pack(fill="x"); b.columnconfigure((0, 1), weight=1, uniform="b")
        self.btn_con = Botao(b, "▶  Conectar", self.conectar, "primario", fundo=BG)
        self.btn_con.grid(row=0, column=0, sticky="ew", padx=(0, 5))
        self.btn_des = Botao(b, "■  Desconectar", self.desconectar, "neutro", fundo=BG)
        self.btn_des.grid(row=0, column=1, sticky="ew", padx=(5, 0))
        self.btn_des.config(state="disabled")

        # Log
        top = tk.Frame(dir_, bg=BG); top.pack(fill="x", pady=(0, 8))
        tk.Label(top, text="Atividade", bg=BG, fg=TXT, font=(FONTE, 12, "bold")).pack(side="left")
        Botao(top, "Limpar", self.limpar_log, "neutro", altura=28, largura=64, fundo=BG, tam=9).pack(side="right")
        sw = tk.Frame(top, bg=BG); sw.pack(side="right", padx=(0, 12))
        tk.Label(sw, text="Mostrar chat", bg=BG, fg=SUB, font=(FONTE, 9)).pack(side="left", padx=(0, 8))
        Chave(sw, self.var("debug", tk.BooleanVar), fundo=BG).pack(side="left")
        caixa = tk.Frame(dir_, bg=LOGBG, highlightthickness=1, highlightbackground=BORDA, highlightcolor=BORDA)
        caixa.pack(fill="both", expand=True)
        self.log_w = tk.Text(caixa, bg=LOGBG, fg=TXT, relief="flat", wrap="word", font=(MONO, 10), height=14,
                             padx=12, pady=10, insertbackground=TXT, highlightthickness=0, borderwidth=0)
        sb = ttk.Scrollbar(caixa, style="Log.Vertical.TScrollbar", command=self.log_w.yview)
        self.log_w.config(yscrollcommand=sb.set)
        sb.pack(side="right", fill="y"); self.log_w.pack(fill="both", expand=True)
        for tag, cor in (("env", VERDE), ("chat", "#7a7a85"), ("erro", VERMELHO), ("info", CLARO)):
            self.log_w.tag_config(tag, foreground=cor)

        self.arranjar()

    # ----- responsividade -----
    def arranjar(self):
        c = self.corpo
        for w in (self.esq, self.dir): w.grid_forget()
        for i in range(2):
            c.columnconfigure(i, weight=0, minsize=0); c.rowconfigure(i, weight=0, minsize=0)
        if self.largo:   # lado a lado
            c.columnconfigure(0, weight=0, minsize=340); c.columnconfigure(1, weight=1); c.rowconfigure(0, weight=1)
            self.esq.grid(row=0, column=0, sticky="nsew", padx=(14, 7), pady=14)
            self.dir.grid(row=0, column=1, sticky="nsew", padx=(7, 14), pady=14)
        else:            # empilhado (janela pequena)
            c.columnconfigure(0, weight=1); c.rowconfigure(1, weight=1)
            self.esq.grid(row=0, column=0, sticky="nsew", padx=14, pady=(14, 7))
            self.dir.grid(row=1, column=0, sticky="nsew", padx=14, pady=(7, 14))
        self.rol.ajustar()

    def ao_redimensionar(self, e):
        if e.widget is not self: return
        largo = e.width >= LARGURA_LARGA
        if largo != self.largo:
            self.largo = largo; self.arranjar()
        sub = e.width >= LARGURA_SUB
        if sub != self.sub_vis:
            self.sub_vis = sub
            if sub: self.lbl_sub.pack(anchor="w")
            else: self.lbl_sub.pack_forget()

    def sync(self):
        for k, var in self.v.items():
            try: CFG[k] = var.get()
            except tk.TclError: pass
        try: seg = int(str(CFG["segundos"]).strip())
        except ValueError: seg = 0
        CFG["intervalo"] = seg if (CFG["personalizado"] and seg > 0) else VARAS.get(CFG["vara"], 4) * 60
        if hasattr(self, "lbl_cd"):
            m, s = divmod(CFG["intervalo"], 60)
            self.lbl_cd.config(text=f"Cooldown usado: {m}m{s:02d}s  ·  turbo: metade")
            pers = bool(CFG["personalizado"])
            self.cb.config(state="disabled" if pers else "readonly")
            self.ent_seg.config(state="normal" if pers else "disabled")

    # ----- log -----
    def logar(self, msg): self.q.put(msg)

    def limpar_log(self): self.log_w.delete("1.0", "end")

    def escrever(self, msg):
        low = msg.lower()
        tag = ("env" if "enviado:" in msg else "chat" if msg.startswith("[chat]") else
               "erro" if any(p in low for p in ("recusado", "falha", "falhou", "caiu", "expirada", "sem conexão"))
               else "info")
        if not re.match(r"\d\d:\d\d:\d\d", msg):
            msg = f"{time.strftime('%H:%M:%S')}  {msg}"
        self.log_w.insert("end", msg + "\n", tag); self.log_w.see("end")
        if int(self.log_w.index("end-1c").split(".")[0]) > 1500: self.log_w.delete("1.0", "300.0")

    # ----- conta -----
    def logado(self): return bool(CFG["refresh_token"] or CFG["access_token"])

    def conta_click(self):
        if self.logado():
            if not messagebox.askyesno("Sair da conta", "Sair da conta da Twitch neste computador?"): return
            tok = CFG["access_token"]
            if tok and CLIENT_ID and not CLIENT_ID.startswith("COLE"):
                threading.Thread(target=http, args=("POST", URL_REVOKE),
                                 kwargs={"dados": {"client_id": CLIENT_ID, "token": tok}}, daemon=True).start()
            CFG["access_token"] = CFG["refresh_token"] = CFG["nick"] = ""; salvar_cfg()
            self.logar("Você saiu da conta.")
        else:
            if not CLIENT_ID or CLIENT_ID.startswith("COLE"):
                messagebox.showinfo("Falta configurar", "O CLIENT_ID do app ainda não foi colocado no código.\n"
                                    "Veja o passo a passo no README e cole o Client ID no topo do arquivo."); return
            self.login_t = LoginThread(self.q); self.login_t.start()

    def dialogo_login(self, codigo, url):
        webbrowser.open(url)
        d = self.dlg = tk.Toplevel(self); d.title("Entrar com a Twitch"); d.configure(bg=PAINEL)
        d.resizable(False, False); d.transient(self)
        try: d.iconphoto(False, self.ico64)
        except tk.TclError: pass
        tk.Frame(d, bg=ROXO, height=3).pack(fill="x")
        corpo = tk.Frame(d, bg=PAINEL); corpo.pack(padx=28, pady=22)
        tk.Label(corpo, text="Autorize no navegador", bg=PAINEL, fg=TXT, font=(FONTE, 14, "bold")).pack()
        tk.Label(corpo, text="Abrimos a página da Twitch. Entre na sua conta e clique em Ativar.\n"
                             "Se ela pedir um código, digite este:", bg=PAINEL, fg=SUB, font=(FONTE, 10),
                 justify="center", wraplength=340).pack(pady=(6, 0))
        caixa = tk.Frame(corpo, bg=CAMPO, highlightthickness=1, highlightbackground=BORDA); caixa.pack(pady=14)
        tk.Label(caixa, text=codigo, bg=CAMPO, fg=CLARO, font=(MONO, 26, "bold"), padx=24, pady=8).pack()
        tk.Label(corpo, text="Aguardando autorização...", bg=PAINEL, fg=SUB, font=(FONTE, 9)).pack()
        b = tk.Frame(corpo, bg=PAINEL); b.pack(fill="x", pady=(16, 0)); b.columnconfigure((0, 1), weight=1, uniform="d")
        bc = Botao(b, "Copiar código", None, "neutro")
        bc.comando = lambda: self.copiar(codigo, bc)
        bc.grid(row=0, column=0, sticky="ew", padx=(0, 4))
        Botao(b, "Abrir navegador", lambda: webbrowser.open(url), "primario").grid(row=0, column=1, sticky="ew", padx=(4, 0))
        Botao(b, "Cancelar", self.cancelar_login, "neutro").grid(row=1, column=0, columnspan=2, sticky="ew", pady=(8, 0))
        d.protocol("WM_DELETE_WINDOW", self.cancelar_login)
        d.update_idletasks()   # centraliza sobre a janela principal
        x = self.winfo_rootx() + (self.winfo_width() - d.winfo_reqwidth()) // 2
        y = self.winfo_rooty() + (self.winfo_height() - d.winfo_reqheight()) // 3
        d.geometry(f"+{max(x, 0)}+{max(y, 0)}")

    def copiar(self, texto, botao):
        self.clipboard_clear(); self.clipboard_append(texto)
        def volta():
            try: botao.config(text="Copiar código")
            except tk.TclError: pass
        botao.config(text="Copiado ✔"); self.after(1500, volta)

    def fechar_dialogo(self):
        if self.dlg:
            try: self.dlg.destroy()
            except Exception: pass
            self.dlg = None

    def cancelar_login(self):
        if self.login_t: self.login_t.cancelar.set()
        self.fechar_dialogo()

    def evento(self, e):
        if e[0] == "login_codigo": self.dialogo_login(e[1], e[2])
        elif e[0] == "login_ok":
            self.fechar_dialogo(); self.logar(f"Login feito como {e[1]}!")
        elif e[0] == "login_erro":
            self.fechar_dialogo(); messagebox.showerror("Login", e[1])

    # ----- bot -----
    def drenar(self):
        try:
            while True:
                m = self.q.get_nowait()
                self.evento(m) if isinstance(m, tuple) else self.escrever(m)
        except queue.Empty:
            pass
        vivo = self.bot is not None and self.bot.is_alive()
        if self.bot and not vivo: self.bot = None
        logado = self.logado()
        if logado: self.lbl_conta.config(text=f"✔  Logado como {CFG['nick'] or '...'}", fg=VERDE)
        else: self.lbl_conta.config(text="Você ainda não entrou na Twitch.", fg=SUB)
        self.btn_conta.config(text="Sair da conta" if logado else "Entrar com a Twitch",
                              estilo="neutro" if logado else "primario",
                              state="disabled" if vivo else "normal")
        self.btn_con.config(state="disabled" if (vivo or not logado) else "normal")
        self.btn_des.config(state="normal" if vivo else "disabled")
        for e in self.campos: e.config(state="disabled" if vivo else "normal")
        self.dot.config(fg=VERDE if vivo else SUB)
        self.status.config(text="Conectado" if vivo else "Desconectado")
        self.after(150, self.drenar)

    def conectar(self):
        self.sync()
        CFG["canal"] = CFG["canal"].strip().lstrip("@#")
        if not CFG["canal"]:
            messagebox.showwarning("Falta o canal", "Digite o nome do canal onde quer pescar."); return
        salvar_cfg()
        self.escrever("Conectando...")
        self.bot = Bot(self.logar); self.bot.start()

    def desconectar(self):
        if self.bot: self.bot.parar.set()

    def fechar(self):
        self.sync(); salvar_cfg(); self.desconectar(); self.cancelar_login(); self.destroy()

if __name__ == "__main__":
    App().mainloop()
