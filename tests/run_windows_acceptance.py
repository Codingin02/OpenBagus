"""Exercise the installed console application through its real stdin/stdout."""

import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import queue
import socket
import subprocess
import threading
import time
from urllib.parse import urlsplit
from urllib.request import urlopen


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--exe", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--cwd", type=Path, default=Path(os.environ.get("ProgramFiles", "C:/Program Files")))
    parser.add_argument("--offline", action="store_true")
    args = parser.parse_args()
    executable = args.exe.resolve()
    env = dict(os.environ)
    for key in ("PYTHONPATH", "PYTHONHOME", "VIRTUAL_ENV"):
        env.pop(key, None)
    env["PYTHONUTF8"] = "1"
    profile = args.output.resolve().parent / "test-profile"
    profile.mkdir(parents=True, exist_ok=True)
    env["OPENBAGUS_DATA_ROOT"] = str(Path(env["LOCALAPPDATA"]) / "OpenBagus/data")
    env["LOCALAPPDATA"] = str(profile)
    if args.offline:
        env.update(HTTP_PROXY="http://127.0.0.1:9", HTTPS_PROXY="http://127.0.0.1:9", NO_PROXY="127.0.0.1,localhost")
    def read_output(process, output_queue):
        while True:
            char = process.stdout.read(1)
            if not char:
                output_queue.put(None)
                return
            output_queue.put(char)
    def launch():
        process = subprocess.Popen([str(executable)], cwd=str(args.cwd.resolve()), env=env,
                                   stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                   text=True, encoding="utf-8", errors="replace", bufsize=1)
        output_queue = queue.Queue()
        threading.Thread(target=read_output, args=(process, output_queue), daemon=True).start()
        return process, output_queue

    process, output_queue = launch()

    def receive(timeout=150):
        deadline = time.monotonic() + timeout
        text = ""
        while time.monotonic() < deadline:
            try:
                char = output_queue.get(timeout=0.2)
            except queue.Empty:
                continue
            if char is None:
                raise RuntimeError(f"Application exited ({process.poll()}): {text[-4000:]}")
            text += char
            if text.endswith("openbagus > "):
                return text
        raise TimeoutError(text[-4000:])

    def send(text):
        process.stdin.write(text + "\n")
        process.stdin.flush()
        return receive()

    def status():
        output = send("/status")
        start = output.find("{")
        return json.JSONDecoder().raw_decode(output[start:])[0]

    matrix = [{"test_id": f"{group}{i:02}", "status": "NOT_TESTED", "input": None,
               "expected": "See required acceptance gate", "output": None,
               "runtime_state": None, "model": None, "seconds": None,
               "real_microphone": False, "real_speaker": False,
               "real_model": False, "real_data_tools": False}
              for group, count in (("A",10),("B",10),("C",12),("D",12),("E",10),("F",10))
              for i in range(1, count+1)]
    scenarios = []
    provider_hosts = []
    model_residency = []

    def capture_residency(state):
        with urlopen(state["model"]["base_url"] + "/api/ps", timeout=3) as response:
            model_residency.append(json.load(response))
    def record(ids, input_text, expected, output, state, seconds, passed, tools=False):
        for test_id in ids:
            row = next(item for item in matrix if item["test_id"] == test_id)
            row.update(input=input_text, expected=expected, output=output, runtime_state=state,
                       model=state.get("model"), seconds=seconds,
                       status="PASS_INSTALLED_APP" if passed else "FAIL",
                       real_model=True, real_data_tools=tools)
        scenarios.append({"gates": ids, "input": input_text, "output": output, "state": state,
                          "seconds": seconds, "status": "PASS_INSTALLED_APP" if passed else "FAIL"})

    def check(ids, query, expected, assertion, tools=False):
        started = time.monotonic()
        output = send(query)
        state = status()
        provider_hosts.append(state["model"]["base_url"])
        capture_residency(state)
        passed = bool(assertion(output, state))
        elapsed = round(time.monotonic()-started, 3)
        record(ids, query, expected, output, state, elapsed, passed, tools)
        print(f"{','.join(ids)} {'PASS' if passed else 'FAIL'} {elapsed}s", flush=True)
        return state

    try:
        startup = receive()
        print(startup, flush=True)
        report = json.loads((profile / "OpenBagus/logs/startup.json").read_text(encoding="utf-8"))
        state = status()
        record(["F01", "F02", "F05"], str(executable), "Frozen application with external canonical models, independent of cwd and developer venv",
               startup, state, report["load_probe_seconds"], report["frozen"] and Path(report["models"]) == Path("E:/Projects/OpenBagus/models"))
        if args.offline:
            check(["F04"], "Jelaskan arti kata ramah dalam satu kalimat.", "Local inference works with external HTTP blocked",
                  lambda o,s: bool(o.strip()) and s["provider"].startswith("OLLAMA") and "DEGRADED_READY" in startup)
            check(["C10"], "Berapa harga ETHUSDT?", "Unavailable external crypto providers remain unavailable; no equity substitution or fabricated price",
                  lambda o,s: any(t["name"] == "get_market_price" and t.get("data", {}).get("status") == "DATA_GAP"
                                  and t["data"].get("price") is None and t["data"].get("currency") == "USDT"
                                  for t in s["last_turn"]["tool_calls"]) and "UNAVAILABLE" in o, True)
        else:
            send("/harness on")
            check(["B01","B02"], "Halo", "Natural greeting, no slash prefix", lambda o,s: "Halo" in o)
            check(["B03"], "Aku mau tahu apa yang bisa kamu lakukan?", "Ordinary words do not become TAHU or HALO",
                  lambda o,s: s["context"]["active_ticker"] not in ("TAHU","HALO") and "Pindah fokus" not in o)
            check(["B10"], "Aku ingin ngobrol tentang cara menikmati akhir pekan tanpa membahas uang. Beri satu ide sederhana.", "General conversation does not redirect to finance",
                  lambda o,s: not any(w in o.lower() for w in ("analisis saham", "emiten idx", "pbv", "trading")))
            ratu = check(["C01","C05","C06","C07"], "Analisis saham RATU timeframe D1.", "RATU D1 and real evidence calls, timestamps, not live",
                  lambda o,s: s["context"]["active_ticker"] == "RATU" and s["context"]["time_horizon"] == "D1" and len(s["last_turn"]["tool_calls"]) >= 2 and "diakses UTC" in o and "bukan klaim real-time" in o, True)
            check(["B04"], "Bagaimana laporan keuangannya?", "Follow-up uses RATU",
                  lambda o,s: all(t["arguments"].get("ticker", t["arguments"].get("query")) == "RATU" for t in s["last_turn"]["tool_calls"]), True)
            check(["B05","C02"], "Sekarang ganti ke BBCA.", "Internal state AND tool arguments use BBCA",
                  lambda o,s: s["context"]["active_ticker"] == "BBCA" and all(t["arguments"].get("ticker",t["arguments"].get("query")) == "BBCA" for t in s["last_turn"]["tool_calls"]), True)
            bbca = check(["C08"], "Berapa PBV dan ROE-nya?", "BBCA data only; missing PBV stays missing",
                  lambda o,s: s["context"]["active_ticker"] == "BBCA" and all(t["arguments"].get("ticker",t["arguments"].get("query")) == "BBCA" for t in s["last_turn"]["tool_calls"]) and "DATA_GAP" in o, True)
            ratio_rows = [t["data"] for t in bbca["last_turn"]["tool_calls"] if t["name"] == "calculate_financial_ratios"]
            ratio_ok = bool(ratio_rows) and all(d.get("total_equity") and d.get("net_income") is not None
                           and d.get("roe_pct") == round(d["net_income"] / d["total_equity"] * 100, 2) for d in ratio_rows)
            record(["C12"], "Actual BBCA ratio output", "ROE equals net_income / total_equity * 100 for the reported period",
                   ratio_rows, bbca, 0, ratio_ok, True)
            currency_rows = [t["data"] for s in (ratu, bbca) for t in s["last_turn"]["tool_calls"]
                             if t["name"] == "calculate_financial_ratios" and t.get("data")]
            record(["C11"], "Actual RATU and BBCA ratio output", "RATU USD and BBCA million_IDR remain explicitly labeled",
                   currency_rows, bbca, 0, bool(currency_rows) and all(d.get("currency") and d.get("unit") for d in currency_rows), True)
            check(["B06"], "Bandingkan dengan RATU yang tadi.", "Separate tool arguments and results for RATU and BBCA",
                  lambda o,s: {t["arguments"].get("ticker",t["arguments"].get("query")) for t in s["last_turn"]["tool_calls"]} == {"RATU","BBCA"}, True)
            check(["C09"], "Ada katalis terbaru untuk RATU?", "Actual local event tool; no claim that empty local records prove no exchange announcements",
                  lambda o,s: any(t["name"] == "get_recent_company_events" for t in s["last_turn"]["tool_calls"])
                  and ("bukan bukti" in o.lower() or any(t.get("data", {}).get("items") for t in s["last_turn"]["tool_calls"])), True)
            check(["B07","C03"], "Bukan RATU, maksudku TLKM.", "Correction resolves TLKM and updates state", lambda o,s: s["context"]["active_ticker"] == "TLKM", True)
            check([], "Analisis saham HGII.", "Smaller issuer remains correctly identified", lambda o,s: s["context"]["active_ticker"] == "HGII", True)
            check(["C04"], "Berapa harga BTCUSDT?", "Crypto identity and actual market tool; failures remain explicit",
                  lambda o,s: s["context"]["active_ticker"] == "BTC" and any(t["name"] == "get_market_price" for t in s["last_turn"]["tool_calls"]), True)
            check(["B09"], "Bagusmax pindah ke kanan", "No claim of a companion action that did not execute",
                  lambda o,s: "tidak ada jendela" in o.lower() and not s["last_turn"]["tool_calls"])
            check(["E04"], "Aku mau belajar bahasa Inggris.", "English Tutor namespace activates", lambda o,s: s["context"]["context_namespace"] == "ENGLISH_TUTOR")
            check(["E01","E05"], "Yesterday I go to school.", "FAST responds and corrects go to went", lambda o,s: "went" in o.lower() and "Koreksi" in o)
            send("/mode deep")
            deep_state = check(["E02","E03","E06","E07","E09"], "Explain why went is correct here, with one more past-tense example.", "Substantive DEEP tutor response, correct model and retained context",
                  lambda o,s: s["context"]["context_namespace"] == "ENGLISH_TUTOR" and s["provider"] == "OLLAMA_DEEP" and s["model"]["model_name"] == "qwen3.5:4b" and "tidak menghasilkan" not in o and "Inferensi tutor gagal" not in o and any(w in o.lower() for w in ("past", "went", "yesterday")))
            capture_residency(deep_state)
            check(["E08"], "Sekarang kembali ke analisis RATU.", "Return to financial research with RATU", lambda o,s: s["context"]["context_namespace"] == "FINANCIAL_RESEARCH" and s["context"]["active_ticker"] == "RATU", True)
            send("/mode fast")
        process.stdin.write("/exit\n")
        process.stdin.flush()
        process.stdin.close()
        process.wait(timeout=40)
        tail = ""
        while True:
            try:
                char = output_queue.get(timeout=1)
            except queue.Empty:
                break
            if char is None:
                break
            tail += char
        if not args.offline:
            process, output_queue = launch()
            restarted = receive()
            restored = status()
            provider_hosts.append(restored["model"]["base_url"])
            capture_residency(restored)
            resident_names = {m["name"] for snapshot in model_residency for m in snapshot.get("models", [])}
            record(["E10"], "FAST -> DEEP -> FAST restart", "Both real local models complete inference with at most one model resident; bounded smoke, not a stress or peak-VRAM benchmark",
                   model_residency, restored, None,
                   {"qwen3.5:2b-q4_K_M", "qwen3.5:4b"} <= resident_names
                   and all(len(snapshot.get("models", [])) == 1 for snapshot in model_residency)
                   and all(s["status"] == "PASS_INSTALLED_APP" for s in scenarios if "E01" in s["gates"] or "E02" in s["gates"]))
            record(["B08"], "Restart installed executable with opted-in isolated test profile",
                   "Restore the desktop RATU D1 financial context, not an unrelated ticker or tutor namespace",
                   restarted, restored, None,
                   restored["context"]["active_ticker"] == "RATU"
                   and restored["context"]["context_namespace"] == "FINANCIAL_RESEARCH"
                   and restored["context"]["time_horizon"] == "D1")
            send("/voice off")
            process.stdin.write("/exit\n")
            process.stdin.flush()
            process.stdin.close()
            process.wait(timeout=40)
        released = []
        provider_hosts = list(dict.fromkeys(provider_hosts))
        for host in provider_hosts:
            address = urlsplit(host)
            try:
                with socket.create_connection((address.hostname, address.port), timeout=0.5):
                    released.append(False)
            except OSError:
                released.append(True)
        record(["F06"], "/exit", "Application exits with code 0 and all owned provider ports close",
               {"exit_code": process.returncode, "hosts": provider_hosts, "ports_closed": released},
               state, None, process.returncode == 0 and all(released))
        result = {"generated_at_utc": datetime.now(timezone.utc).isoformat(), "executable": str(executable),
                  "working_directory": str(args.cwd.resolve()),
                  "model_residency": model_residency,
                  "exe_sha256": hashlib.file_digest(executable.open("rb"), "sha256").hexdigest(),
                  "startup": startup, "scenarios": scenarios, "matrix": matrix,
                  "exit_code": process.returncode, "shutdown_output": tail,
                  "offline_proxy_test": args.offline}
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(result, indent=2, ensure_ascii=False), encoding="utf-8")
        print(f"Saved {args.output}; failures: {sum(s['status']=='FAIL' for s in scenarios)}", flush=True)
        return int(process.returncode != 0 or any(s["status"] == "FAIL" for s in scenarios))
    except Exception as error:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps({"executable": str(executable), "matrix": matrix, "scenarios": scenarios,
                                          "error": str(error), "status": "FAIL"}, indent=2, ensure_ascii=False), encoding="utf-8")
        raise
    finally:
        if process.poll() is None:
            process.stdin.close()
            try:
                process.wait(timeout=15)
            except subprocess.TimeoutExpired:
                process.terminate()
                process.wait(timeout=10)


if __name__ == "__main__":
    raise SystemExit(main())
