import csv
import os
import re
import time
import logging
from datetime import datetime
from dotenv import dotenv_values
import pexpect

# ── Configuração ──────────────────────────────────────────────────────────────
BASE_DIR      = os.path.dirname(os.path.abspath(__file__))
OLT_DIR       = os.path.join(BASE_DIR, "olt")
CSV_IN        = os.path.join(OLT_DIR, "base.csv")
CSV_OUT       = os.path.join(OLT_DIR, "dados_atualizados.csv")
CSV_FALHAS    = os.path.join(OLT_DIR, "falhas_manuais.csv")
LOG_FILE      = os.path.join(OLT_DIR, f"acs_{datetime.now().strftime('%Y%m%d_%H%M%S')}.log")

PROMPT        = r"#"
CMD_DELAY     = 3
TIMEOUT       = 7

logging.basicConfig(
    filename=LOG_FILE,
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)

# ── Helpers ───────────────────────────────────────────────────────────────────

def load_env():
    cfg = dotenv_values(os.path.join(BASE_DIR, ".env"))
    return (
        cfg.get("ip"),
        cfg.get("login"),
        cfg.get("senha"),
        cfg.get("url"),
        cfg.get("username_acs"),
        cfg.get("passwd_acs"),
        cfg.get("inform"),
        cfg.get("port"),
        cfg.get("username_conn"),
        cfg.get("passwd_conn"),
    )


SERIAL_PATTERN = re.compile(r'^FHTT[0-9a-fA-F]+$')

def load_serials():
    rows = []
    with open(CSV_IN, newline="", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            parts = line.split(",", 1)
            if len(parts) == 2:
                serial = parts[1].strip()
                if SERIAL_PATTERN.match(serial):
                    rows.append((parts[0].strip(), serial))
    return rows


def progress_bar(current, total, start_time, width=40):
    pct     = current / total
    filled  = int(width * pct)
    bar     = "█" * filled + "░" * (width - filled)
    elapsed = time.time() - start_time
    eta     = (elapsed / current * (total - current)) if current else 0
    print(f"\r[{bar}] {current}/{total}  ETA: {int(eta)}s  ", end="", flush=True)


def ssh_connect(ip, login, senha):
    child = pexpect.spawn(
        f"ssh -o StrictHostKeyChecking=no -o ConnectTimeout=15 {login}@{ip}",
        encoding="utf-8",
        timeout=20,
    )
    child.expect(r"[Pp]assword")
    child.sendline(senha)
    child.expect(PROMPT, timeout=20)
    return child


def send_cmd(child, cmd, timeout=TIMEOUT):
    child.sendline(cmd)
    child.expect(PROMPT, timeout=timeout)
    return child.before


def close_session(child):
    try:
        child.sendline("cd .")
        child.expect(PROMPT, timeout=5)
        time.sleep(CMD_DELAY)
        child.sendline("exit")
        child.expect(pexpect.EOF, timeout=10)
    except Exception:
        pass
    finally:
        child.close()


def resync_prompt(child):
    child.sendline("")
    try:
        child.expect(PROMPT, timeout=5)
    except Exception:
        pass


# ── Etapa 1 – Consulta de seriais ─────────────────────────────────────────────
# Retorna:
#   ok       → lista de (nome, serial, slot, pon, onu)  com dados completos
#   sem_dados→ lista de (nome, serial) que retornaram mas sem match
#   timeouts → lista de (nome, serial) que deram timeout

def query_serials(child, rows):
    ok        = []
    sem_dados = []
    timeouts  = []

    send_cmd(child, "cd onu", timeout=10)
    time.sleep(CMD_DELAY)

    total      = len(rows)
    start_time = time.time()

    for idx, (nome, serial) in enumerate(rows, 1):
        progress_bar(idx, total, start_time)
        try:
            child.sendline(f"show onu-info by {serial}")
            child.expect(PROMPT, timeout=TIMEOUT)
            output = child.before

            match = re.search(r"-+\s+(\d+)\s+(\d+)\s+(\d+)\s+\w+\s+-+", output)
            if match:
                slot, pon, onu = match.group(1), match.group(2), match.group(3)
                ok.append((nome, serial, slot, pon, onu))
                logging.info(f"OK | {serial} | SLOT={slot} PON={pon} ONU={onu}")
            else:
                sem_dados.append((nome, serial))
                logging.warning(f"SEM_DADOS | {serial} | output: {output.strip()}")

        except pexpect.TIMEOUT:
            timeouts.append((nome, serial))
            logging.error(f"TIMEOUT | {serial}")
            print(f"\n  [!] Timeout: {serial}")
            resync_prompt(child)

        time.sleep(CMD_DELAY)

    print()
    return ok, sem_dados, timeouts


def rotate_file(path):
    """Se o arquivo existir, renomeia para _old1, _old2, etc. antes de sobrescrever."""
    if not os.path.exists(path):
        return
    base, ext = os.path.splitext(path)
    n = 1
    while os.path.exists(f"{base}_old{n}{ext}"):
        n += 1
    os.rename(path, f"{base}_old{n}{ext}")


def save_csv(results):
    rotate_file(CSV_OUT)
    with open(CSV_OUT, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["NOME", "SERIAL", "SLOT", "PON", "ONU"])
        writer.writerows(results)


def save_falhas_csv(falhas):
    rotate_file(CSV_FALHAS)
    with open(CSV_FALHAS, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["NOME", "SERIAL", "MOTIVO"])
        writer.writerows(falhas)


# ── Etapa 2 – Configuração de ACS ─────────────────────────────────────────────

def apply_acs(child, results, acs_url, username_acs, passwd_acs, inform, port, username_conn, passwd_conn):
    success      = 0
    acs_failures = []  # (nome, serial) que falharam no envio do ACS

    send_cmd(child, "cd onu", timeout=10)
    time.sleep(CMD_DELAY)

    total      = len(results)
    start_time = time.time()

    for idx, (nome, serial, slot, pon, onu) in enumerate(results, 1):
        progress_bar(idx, total, start_time)

        cmd = (
            f"set remote_manage_cfg slot {slot} pon {pon} onu {onu} "
            f"tr069 enable acs_url {acs_url} "
            f"acl_user {username_acs} acl_pswd {passwd_acs} "
            f"inform enable interval {inform} "
            f"port {port} user {username_conn} pswd {passwd_conn}"
        )
        try:
            child.sendline(cmd)
            child.expect(PROMPT, timeout=TIMEOUT)
            logging.info(f"ACS_OK | {serial} | SLOT={slot} PON={pon} ONU={onu}")
            success += 1
        except pexpect.TIMEOUT:
            logging.error(f"ACS_TIMEOUT | {serial}")
            acs_failures.append((nome, serial))
            resync_prompt(child)

        time.sleep(CMD_DELAY)

    print()
    return success, acs_failures


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    ip, login, senha, acs_url, username_acs, passwd_acs, inform, port, username_conn, passwd_conn = load_env()
    if not all([ip, login, senha, acs_url, username_acs, passwd_acs, inform, port, username_conn, passwd_conn]):
        print("[ERRO] Verifique todas as variáveis no .env")
        return

    rows = load_serials()
    if not rows:
        print("[ERRO] Nenhum registro encontrado em base.csv")
        return

    print(f"\n{'='*55}")
    print(f"  OLT: {ip}  |  Registros: {len(rows)}  |  ACS: {acs_url}")
    print(f"{'='*55}\n")

    print("Conectando via SSH...")
    try:
        child = ssh_connect(ip, login, senha)
    except Exception as e:
        print(f"[ERRO] Falha na conexão SSH: {e}")
        return
    print("Conectado.\n")

    # ── Etapa 1: primeira coleta ──
    print("Etapa 1/2 – Consultando seriais na OLT...\n")
    ok, sem_dados, timeouts = query_serials(child, rows)

    pendentes = sem_dados + timeouts  # (nome, serial) sem dados

    # ── Retentativa única se houver pendentes ──
    segunda_tentativa = False
    if pendentes:
        total_pend = len(pendentes)
        motivos = (
            [f"sem retorno: {s}" for _, s in sem_dados] +
            [f"timeout: {s}"     for _, s in timeouts]
        )
        print(f"\n  {total_pend} ONU(s) sem dados coletados:")
        for m in motivos:
            print(f"    • {m}")

        save_csv(ok + [(n, s, "", "", "") for n, s in pendentes])
        print(f"\nArquivo salvo em: {CSV_OUT}")

        while True:
            resp = input(
                "\nOs dados foram capturados corretamente? "
                "[Y] Continuar  [X] Fechar  [R] Tentar nova coleta: "
            ).strip().upper()
            if resp == "X":
                close_session(child)
                print("Sessão encerrada.")
                return
            if resp in ("Y", "R"):
                break

        if resp == "R":
            segunda_tentativa = True
            print(f"\nRetentando coleta para {total_pend} ONU(s)...\n")
            ok2, sem_dados2, timeouts2 = query_serials(child, pendentes)
            ok = ok + ok2
            pendentes = sem_dados2 + timeouts2

            if pendentes:
                print(f"\n  {len(pendentes)} ONU(s) ainda sem dados após segunda tentativa:")
                for _, s in pendentes:
                    print(f"    • {s}")
                logging.warning(f"SEGUNDA_TENTATIVA_FALHA | {[s for _, s in pendentes]}")

    else:
        save_csv(ok)
        print(f"\nArquivo salvo em: {CSV_OUT}")

    # ── Confirmação final (sem opção R) ──
    if segunda_tentativa or not pendentes:
        # se veio de segunda tentativa, já informou as falhas acima; pede confirmação simples
        while True:
            resp = input(
                "\nOs dados foram capturados corretamente? [Y] Continuar  [X] Fechar: "
            ).strip().upper()
            if resp == "X":
                close_session(child)
                print("Sessão encerrada.")
                return
            if resp == "Y":
                break

    # ── Salva CSV final com todos (ok com dados, pendentes sem dados) ──
    falhas_coleta = [(n, s, "sem dados após coleta") for n, s in pendentes]
    save_csv(ok + [(n, s, "", "", "") for n, s in pendentes])

    # ── Etapa 2: aplicar ACS apenas nas que têm dados ──
    print("\nEtapa 2/2 – Aplicando configuração de ACS...\n")
    success, acs_failures = apply_acs(child, ok, acs_url, username_acs, passwd_acs, inform, port, username_conn, passwd_conn)

    # ── Encerra sessão ──
    close_session(child)

    # ── Gera CSV de falhas manuais ──
    todas_falhas = falhas_coleta + [(n, s, "falha no envio ACS") for n, s in acs_failures]
    if todas_falhas:
        save_falhas_csv(todas_falhas)

    # ── Resumo final ──
    total_falhas = len(todas_falhas)
    print(f"\n{'='*55}")
    print(f"  Concluído!")
    print(f"  Sucesso  : {success}")
    print(f"  Falhas   : {total_falhas}")
    if todas_falhas:
        print(f"\n  ONU(s) com falha:")
        for nome, serial, motivo in todas_falhas:
            print(f"    • {serial} ({nome}) → {motivo}")
        print(f"\n  CSV de falhas : {CSV_FALHAS}")
    print(f"  Log           : {LOG_FILE}")
    print(f"{'='*55}\n")
    logging.info(f"RESUMO | sucesso={success} falhas={total_falhas}")


if __name__ == "__main__":
    main()
