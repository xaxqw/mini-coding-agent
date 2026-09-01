"""阶段二全链路自动化测试：验证审批 + ask_user + 工具调用。
用法：python test_flow.py
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


def stream_events(session_id, on_event, max_seconds=10):
    """读取 SSE 直到 done；SSE 连接保持打开是预期行为，超时即结束读取。
    注意：必须 readline() 逐行读——read(n) 会等满 n 字节，而 SSE 单行远小于 n。"""
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
            pass  # 连接保持打开：无新事件即超时，视为读取结束


def run_case(name, message, responder=None):
    """responder(ev) -> dict|None，返回 resolve payload"""
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

    stream_events(sid, on_event)
    return events


# ---------- 用例 1：写文件 ----------
def case_write_file():
    evs = run_case("写文件", "帮我创建一个 Python 脚本")
    ok = any(e["event"] == "tool_result" and "已写入" in e["data"]["output"] for e in evs)
    results.append(("创建脚本 → write_file", ok))


# ---------- 用例 2：危险命令审批 ----------
def case_approval():
    def resp(ev):
        if ev["event"] == "approval_request":
            print(f"  [审批] 收到危险命令: {ev['data']['command']} → 批准")
            return {"pid": ev["data"]["pid"], "approved": True}
        return None
    evs = run_case("审批", "测试审批", resp)
    ok = any(e["event"] == "tool_result" and e["data"]["status"] == "approved" for e in evs)
    results.append(("危险命令 → 审批通过并执行", ok))


# ---------- 用例 3：ask_user ----------
def case_ask_user():
    def resp(ev):
        if ev["event"] == "ask_request":
            print(f"  [ask_user] 收到提问: {ev['data']['question']} → 回答'输出到文件'")
            return {"pid": ev["data"]["pid"], "answer": "输出到文件"}
        return None
    evs = run_case("ask_user", "问我一个问题", resp)
    ok = any(e["event"] == "tool_result" and e["data"]["name"] == "ask_user"
             and "输出到文件" in e["data"]["output"] for e in evs)
    results.append(("ask_user → 提问并恢复 loop", ok))


# ---------- 用例 4：并行工具调用（mock 用"总结"触发 list_dir+read_file 并行） ----------
def case_parallel():
    evs = run_case("并行", "总结工作区")
    calls = [e for e in evs if e["event"] == "tool_call"]
    ok = len(calls) >= 2
    results.append((f"工具并行调用（mock 同时发 {len(calls)} 个工具）", ok))


if __name__ == "__main__":
    case_write_file()
    case_approval()
    case_ask_user()
    case_parallel()
    print("\n========== 测试结果 ==========")
    all_ok = True
    for name, ok in results:
        print(f"{'✅' if ok else '❌'} {name}")
        all_ok = all_ok and ok
    sys.exit(0 if all_ok else 1)
