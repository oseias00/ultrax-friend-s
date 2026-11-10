import json, os, queue, random, re, socket, sys, threading, time
import urllib.error, urllib.parse, urllib.request, webbrowser
import tkinter as tk
from tkinter import ttk, messagebox

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
    "eventos_reset": "sorte rara pelos, rede coletiva pelos, garrafa ao mar, concurso do menor peixe, "
                     "peso pesado pelos, xp em dobro, cardume passageiro",
}
FUNCOES = {   # chave: (texto na interface, ligado por padrão)
    "pescar": ("Pescar automático", True),
    "frota": ("Embarcar em frotas", True),
    "reset": ("Pescar quando o cooldown resetar", True),
    "turbo": ("Maré turbo", True),
    "venda": ("Venda turbinada", True),
    "mochila": ("Mochila cheia", True),
    "torneio": ("Entrar em torneios", True),
    "duelo": ("Aceitar duelos", True),
}
FIXAS = {"msg_vender", "eventos_reset", "exp_seg", "exp_min", "token", "lembrar_token", "intervalo"}
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
        elif CFG["turbo"] and ok("turbo"):
            log("Maré turbo! Cooldown pela metade por 10 min.")
            est["fim_turbo"] = est["turbo"] = time.time()
            est["fim_turbo"] += DURACAO_TURBO
            d(1.5, 4); env(MSG_PESCAR); est["reset"] = time.time(); agendar()
    elif CFG["frota"] and eh_frota(autor, texto):
        if ok("frota"):
            log("Frota aberta! Embarcando...")
            d(1.5, 4); env(MSG_EMBARCAR); est["frota"] = time.time()
    elif CFG["reset"] and eh_reset(autor, texto):
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
BG, PAINEL, CAMPO = "#18181b", "#1f1f23", "#2a2a2e"
TXT, SUB, ROXO, ROXO2, CLARO = "#efeff1", "#adadb8", "#9146ff", "#772ce8", "#bf94ff"
FONTE = "Segoe UI"

class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("fisher's friend by ultrax"); self.geometry("1020x740"); self.minsize(940, 700)
        self.q, self.bot, self.v, self.login_t, self.dlg = queue.Queue(), None, {}, None, None
        carregar_cfg()
        self.estilos(); self.montar(); self.sync()
        self.protocol("WM_DELETE_WINDOW", self.fechar)
        self.after(100, self.drenar)

    def estilos(self):
        self.configure(bg=BG)
        st = ttk.Style(self); st.theme_use("clam")
        st.configure(".", background=BG, foreground=TXT, fieldbackground=CAMPO, font=(FONTE, 10),
                     bordercolor="#3a3a3d", lightcolor=CAMPO, darkcolor=CAMPO, troughcolor=BG)
        st.configure("Card.TFrame", background=PAINEL)
        st.configure("Card.TLabel", background=PAINEL, foreground=TXT)
        st.configure("Sub.TLabel", background=PAINEL, foreground=SUB, font=(FONTE, 9))
        st.configure("Titulo.TLabel", background=PAINEL, foreground=CLARO, font=(FONTE, 11, "bold"))
        st.configure("TEntry", fieldbackground=CAMPO, foreground=TXT, insertcolor=TXT, padding=5)
        st.configure("TCombobox", fieldbackground=CAMPO, background="#3a3a3d", foreground=TXT,
                     arrowcolor=TXT, padding=4)
        st.map("TCombobox", fieldbackground=[("readonly", CAMPO), ("disabled", PAINEL)],
               foreground=[("readonly", TXT), ("disabled", SUB)])
        self.option_add("*TCombobox*Listbox.background", CAMPO)
        self.option_add("*TCombobox*Listbox.foreground", TXT)
        self.option_add("*TCombobox*Listbox.selectBackground", ROXO)
        st.configure("TButton", background="#3a3a3d", foreground=TXT, borderwidth=0, padding=(12, 8))
        st.map("TButton", background=[("active", "#4a4a4d"), ("disabled", "#2a2a2e")],
               foreground=[("disabled", "#6a6a6e")])
        st.configure("Accent.TButton", background=ROXO, foreground="white", font=(FONTE, 10, "bold"))
        st.map("Accent.TButton", background=[("active", ROXO2), ("disabled", "#3a3a3d")],
               foreground=[("disabled", "#6a6a6e")])
        st.configure("Card.TCheckbutton", background=PAINEL, foreground=TXT, padding=3)
        st.map("Card.TCheckbutton", background=[("active", PAINEL)],
               indicatorcolor=[("selected", ROXO), ("!selected", CAMPO)])

    def var(self, chave, tipo=tk.StringVar):
        self.v[chave] = tipo(value=CFG[chave])
        self.v[chave].trace_add("write", lambda *a: self.sync())
        return self.v[chave]

    def card(self, pai, titulo):
        f = ttk.Frame(pai, style="Card.TFrame", padding=12); f.pack(fill="x", pady=(0, 10))
        ttk.Label(f, text=titulo, style="Titulo.TLabel").pack(anchor="w", pady=(0, 6))
        c = ttk.Frame(f, style="Card.TFrame"); c.pack(fill="x")
        return c

    def montar(self):
        topo = tk.Frame(self, bg=ROXO); topo.pack(fill="x")
        tk.Label(topo, text="🎣 fisher's friend - o seu amigo auxiliar de pesca!", bg=ROXO, fg="white",
                 font=(FONTE, 15, "bold"), padx=16, pady=10).pack(side="left")
        self.status = tk.Label(topo, text="● Desconectado", bg=ROXO, fg="white",
                               font=(FONTE, 10, "bold"), padx=16)
        self.status.pack(side="right")
        corpo = ttk.Frame(self, padding=12); corpo.pack(fill="both", expand=True)
        esq = ttk.Frame(corpo); esq.pack(side="left", fill="y")
        dir_ = ttk.Frame(corpo); dir_.pack(side="left", fill="both", expand=True, padx=(12, 0))

        # Conta
        c = self.card(esq, "Conta da Twitch")
        self.lbl_conta = ttk.Label(c, text="", style="Card.TLabel"); self.lbl_conta.pack(anchor="w")
        self.btn_conta = ttk.Button(c, text="Entrar com a Twitch", style="Accent.TButton",
                                    command=self.conta_click)
        self.btn_conta.pack(fill="x", pady=(8, 0))

        # Canal
        c = self.card(esq, "Canal")
        g = ttk.Frame(c, style="Card.TFrame"); g.pack(fill="x"); g.columnconfigure(1, weight=1)
        self.campos = []
        for i, (rot, ch) in enumerate([("Canal", "canal"), ("Bot do canal", "bot")]):
            ttk.Label(g, text=rot, style="Card.TLabel").grid(row=i, column=0, sticky="w", pady=3, padx=(0, 10))
            e = ttk.Entry(g, textvariable=self.var(ch), width=24); e.grid(row=i, column=1, sticky="ew", pady=3)
            self.campos.append(e)

        # Vara
        c = self.card(esq, "Vara")
        self.cb = ttk.Combobox(c, textvariable=self.var("vara"), values=list(VARAS), state="readonly")
        self.cb.pack(fill="x")
        g = ttk.Frame(c, style="Card.TFrame"); g.pack(fill="x", pady=(6, 0))
        ttk.Checkbutton(g, text="Personalizado (seg):", style="Card.TCheckbutton",
                        variable=self.var("personalizado", tk.BooleanVar)).pack(side="left")
        ttk.Entry(g, textvariable=self.var("segundos"), width=6).pack(side="left", padx=6)
        self.lbl_cd = ttk.Label(c, text="", style="Sub.TLabel"); self.lbl_cd.pack(anchor="w", pady=(6, 0))

        # Funções
        c = self.card(esq, "Funções")
        for k, (txt, _) in FUNCOES.items():
            ttk.Checkbutton(c, text=txt, style="Card.TCheckbutton",
                            variable=self.var(k, tk.BooleanVar)).pack(anchor="w")

        # Botões
        b = ttk.Frame(esq); b.pack(fill="x", pady=(2, 0)); b.columnconfigure((0, 1), weight=1)
        self.btn_con = ttk.Button(b, text="▶  Conectar", style="Accent.TButton", command=self.conectar)
        self.btn_con.grid(row=0, column=0, sticky="ew", padx=(0, 4))
        self.btn_des = ttk.Button(b, text="■  Desconectar", command=self.desconectar, state="disabled")
        self.btn_des.grid(row=0, column=1, sticky="ew", padx=(4, 0))

        # Log
        top = ttk.Frame(dir_); top.pack(fill="x", pady=(0, 6))
        ttk.Label(top, text="Atividade", font=(FONTE, 12, "bold")).pack(side="left")
        ttk.Button(top, text="Limpar", command=lambda: self.log_w.delete("1.0", "end")).pack(side="right")
        ttk.Checkbutton(top, text="Mostrar chat", variable=self.var("debug", tk.BooleanVar)).pack(side="right", padx=10)
        caixa = tk.Frame(dir_, bg="#0e0e10"); caixa.pack(fill="both", expand=True)
        self.log_w = tk.Text(caixa, bg="#0e0e10", fg=TXT, relief="flat", wrap="word", font=("Consolas", 10),
                             padx=10, pady=8, insertbackground=TXT, highlightthickness=0)
        sb = ttk.Scrollbar(caixa, command=self.log_w.yview); self.log_w.config(yscrollcommand=sb.set)
        sb.pack(side="right", fill="y"); self.log_w.pack(fill="both", expand=True)
        for tag, cor in (("env", "#3ddc84"), ("chat", "#7a7a85"), ("erro", "#ff6b6b"), ("info", CLARO)):
            self.log_w.tag_config(tag, foreground=cor)

    def sync(self):
        for k, var in self.v.items():
            try: CFG[k] = var.get()
            except tk.TclError: pass
        try: seg = int(str(CFG["segundos"]).strip())
        except ValueError: seg = 0
        CFG["intervalo"] = seg if (CFG["personalizado"] and seg > 0) else VARAS.get(CFG["vara"], 4) * 60
        if hasattr(self, "lbl_cd"):
            m, s = divmod(CFG["intervalo"], 60)
            self.lbl_cd.config(text=f"Cooldown usado: {m}m{s:02d}s (turbo: metade)")
            self.cb.config(state="disabled" if CFG["personalizado"] else "readonly")

    # ----- log -----
    def logar(self, msg): self.q.put(msg)

    def escrever(self, msg):
        low = msg.lower()
        tag = ("env" if "enviado:" in msg else "chat" if msg.startswith("[chat]") else
               "erro" if any(p in low for p in ("recusado", "falha", "falhou", "caiu", "expirada", "sem conexão"))
               else "info")
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
                                    "Veja o passo a passo e cole o Client ID no topo do arquivo."); return
            self.login_t = LoginThread(self.q); self.login_t.start()

    def dialogo_login(self, codigo, url):
        webbrowser.open(url)
        d = self.dlg = tk.Toplevel(self); d.title("Entrar com a Twitch"); d.configure(bg=PAINEL)
        d.geometry("440x300"); d.resizable(False, False); d.transient(self)
        tk.Label(d, text="Autorize no navegador", bg=PAINEL, fg=TXT, font=(FONTE, 14, "bold")).pack(pady=(20, 4))
        tk.Label(d, text="Abrimos a página da Twitch. Entre na sua conta e clique em Ativar.\n"
                         "Se ela pedir um código, digite este:", bg=PAINEL, fg=SUB, font=(FONTE, 10)).pack()
        tk.Label(d, text=codigo, bg=PAINEL, fg=CLARO, font=("Consolas", 28, "bold")).pack(pady=12)
        tk.Label(d, text="Aguardando autorização...", bg=PAINEL, fg=SUB).pack()
        b = tk.Frame(d, bg=PAINEL); b.pack(pady=14)
        ttk.Button(b, text="Abrir navegador", command=lambda: webbrowser.open(url)).pack(side="left", padx=4)
        ttk.Button(b, text="Cancelar", command=self.cancelar_login).pack(side="left", padx=4)
        d.protocol("WM_DELETE_WINDOW", self.cancelar_login)

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
        self.lbl_conta.config(text=f"✔ Conectado como {CFG['nick'] or '...'}" if logado
                              else "Você ainda não entrou na Twitch.")
        self.btn_conta.config(text="Sair da conta" if logado else "Entrar com a Twitch",
                              style="TButton" if logado else "Accent.TButton",
                              state="disabled" if vivo else "normal")
        self.btn_con.config(state="disabled" if (vivo or not logado) else "normal")
        self.btn_des.config(state="normal" if vivo else "disabled")
        for e in self.campos: e.config(state="disabled" if vivo else "normal")
        self.status.config(text="● Conectado" if vivo else "● Desconectado")
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
