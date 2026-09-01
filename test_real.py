"""真实模型（apilio 网关 + gpt-5.2-codex）全链路验证。
用法：python test_real.py
区别于 test_flow.py：prompt 面向真实 LLM 设计，检查「流程走通」而非 Mock 关键字。
"""
import json
import sys
import urllib.request

BASE = "http://127.0.0.1:8000"
results = []


def post(path, body):
    req = urllib.request.Request(
        BASE + path,
        data=json.dumps(body).encode(),
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.loads(r.read().decode())


def stream_events(session_id, on_event, max_seconds=90):
    """读取 SSE 直到 done；超时视为结束（连接保持打开是预期）。"""
    url = f"{BASE}/api/events?session_id={session_id}"
    got_done = False
    with urllib.request.urlopen(url, timeout=max_seconds) as r:
        try:
            while not got_done:
                line = r.readline().decode("utf-8", "replace")
                if not line:
                    break
                if line.startswith("data: "):
                    ev = json.loads(line[6:])
                    on_event(ev)
                    if ev["event"] == "done":
                        got_done = True
        except TimeoutError:
            pass


def run_case(name, message, responder=None, max_seconds=90):
    sid = post("/api/chat", {"message": message})["session_id"]
    events = []
    handled = set()

    def on_event(ev):
        events.append(ev)
        if responder:
            payload = responder(ev)
            if payload and payload.get("pid") not in handled:
                handled.add(payload["pid"])
                payload["session_id"] = sid
                post("/api/resolve", payload)

    print(f"  [会话 {sid[:8]}] {message[:40]}...")
    stream_events(sid, on_event, max_seconds)
    return events


def summarize(evs):
    """打印事件流的关键节点。"""
    for e in evs:
        tag = e["event"]
        d = e["data"]
        if tag == "status":
            print(f"    [状态] {d.get('state')}")
        elif tag == "tool_call":
            print(f"    [工具] {d['name']}({json.dumps(d.get('args', {}), ensure_ascii=False)[:80]})")
        elif tag == "tool_result":
            out = str(d.get("output", ""))[:100].replace("\n", " ")
            print(f"    [结果] {d.get('name')} -> {out}")
        elif tag == "approval_request":
            print(f"    [审批] 危险命令: {d.get('command')}")
        elif tag == "ask_request":
            print(f"    [提问] {d.get('question')}")
        elif tag == "error":
            print(f"    [错误] {d.get('message')}")


# ---------- 用例 1：写文件 ----------
def case_write_file():
    evs = run_case("写文件", "请帮我创建一个 Python 脚本 sum1to100.py，计算 1 到 100 的和并打印，写到工作区目录。")
    summarize(evs)
    wrote = any(e["event"] == "tool_result" and e["data"]["name"] == "write_file" and e["data"]["status"] == "ok" for e in evs)
    results.append(("真实模型 → write_file 写文件", wrote))


# ---------- 用例 2：危险命令审批 ----------
def case_approval():
    def resp(ev):
        if ev["event"] == "approval_request":
            print(f"  [审批响应] 批准: {ev['data']['command'][:60]}")
            return {"pid": ev["data"]["pid"], "approved": True}
        return None
    evs = run_case("危险审批", "用 run_command 工具执行命令：rm -rf /tmp/mini_agent_demo。如果工具请求确认，请批准。", resp)
    summarize(evs)
    got = any(e["event"] == "approval_request" for e in evs)
    resumed = any(e["event"] == "status" and e["data"]["state"] == "running" for e in evs[1:]) or \
              any(e["event"] == "tool_result" and e["data"]["status"] == "approved" for e in evs)
    results.append(("真实模型 → 危险命令触发审批并恢复", got and resumed))


# ---------- 用例 3：ask_user ----------
def case_ask_user():
    def resp(ev):
        if ev["event"] == "ask_request":
            print(f"  [提问响应] 回答: 我喜欢吃苹果")
            return {"pid": ev["data"]["pid"], "answer": "我喜欢吃苹果"}
        return None
    evs = run_case("ask_user", "先用 ask_user 工具问我一个关于水果喜好的问题，然后根据我的回答创建一个描述该喜好的 markdown 文件。", resp)
    summarize(evs)
    asked = any(e["event"] == "ask_request" for e in evs)
    answered = any(e["event"] == "tool_result" and e["data"]["name"] == "ask_user"
                   and "我喜欢吃苹果" in str(e["data"]["output"]) for e in evs)
    results.append(("真实模型 → ask_user 提问→回答→继续", asked and answered))


# ---------- 用例 4：并行工具调用 ----------
def case_parallel():
    evs = run_case("并行工具", "请先用 list_dir 列出工作区所有文件，然后用 read_file 读取工作区里每个 .py 和 .md 文件的内容，最后告诉我你看到了什么。可以并行执行工具。", max_seconds=120)
    summarize(evs)
    calls = [e for e in evs if e["event"] == "tool_call"]
    results.append((f"真实模型 → 工具调用 {len(calls)} 次（≥2 视为有并行能力）", len(calls) >= 2))


if __name__ == "__main__":
    print("========== 真实模型全链路验证（gpt-5.2-codex @ apilio）==========\n")
    case_write_file()
    print()
    case_approval()
    print()
    case_ask_user()
    print()
    case_parallel()
    print("\n========== 测试结果 ==========")
    all_ok = True
    for name, ok in results:
        print(f"{'✅' if ok else '❌'} {name}")
        all_ok = all_ok and ok
    sys.exit(0 if all_ok else 1)
