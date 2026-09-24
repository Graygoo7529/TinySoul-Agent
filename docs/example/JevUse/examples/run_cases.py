"""Run small Jev application cases against the official API."""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

from jev_client import call_jev, load_dotenv


def payload_for(case: str) -> dict:
    model = os.environ.get("TYPESAFE_MODEL", "jev-latest")
    if case == "support":
        return {
            "model": model,
            "state": {"message": "我被重复扣款了，请尽快退款。", "order_id": "A-104"},
            "questions": {
                "refund_requested": {"type": "noul", "instructions": "用户是否明确要求退款？"},
                "department": {
                    "type": "choice",
                    "instructions": "这条请求应该交给哪个团队？",
                    "criteria": {
                        "billing": "支付、账单、重复扣款或退款",
                        "technical": "产品故障、接口或集成问题",
                        "other": "以上类别都不适用",
                    },
                },
                "urgency": {
                    "type": "score",
                    "instructions": "这条请求有多紧急？",
                    "criteria": ["可排队处理", "本周处理", "今天处理", "关键服务已中断"],
                },
            },
        }
    if case == "kg":
        return {
            "model": model,
            "state": {
                "candidate_triple": {"head": "TypeSafe AI", "relation": "发布", "tail": "Jev"},
                "evidence": "TypeSafe AI announced Jev as its first System One model.",
                "source_date": "2026-09-15",
            },
            "questions": {
                "accept_edge": {"type": "noul", "instructions": "证据是否明确支持该候选关系？"},
                "decision": {
                    "type": "choice",
                    "instructions": "该候选边应如何处理？",
                    "criteria": {"accept": "直接写入", "review": "证据不足，人工复核", "reject": "证据不支持"},
                },
                "evidence_strength": {
                    "type": "score",
                    "instructions": "证据对该关系的支持程度如何？",
                    "criteria": ["弱", "中", "强"],
                },
            },
        }
    if case == "session":
        return {
            "model": model,
            "state": {
                "summary": "用户要求修改生产环境的支付配置。",
                "recent_tool_result": "配置文件已找到，但尚未写入。",
                "proposed_action": "调用写文件工具并重启支付服务",
                "policy": "生产环境写操作必须人工确认。",
            },
            "questions": {
                "needs_confirmation": {"type": "noul", "instructions": "该动作是否需要人工确认？"},
                "action_class": {
                    "type": "choice",
                    "instructions": "当前动作属于哪一类？",
                    "criteria": {
                        "observe": "只读观察或查询",
                        "reversible": "可回滚的低风险修改",
                        "irreversible": "生产写入、删除或不可逆动作",
                    },
                },
                "context_sufficiency": {
                    "type": "score",
                    "instructions": "当前上下文对安全执行的支持程度如何？",
                    "criteria": ["不足", "部分足够", "足够"],
                },
            },
        }
    raise ValueError(f"unknown case: {case}")


def main() -> int:
    load_dotenv()
    parser = argparse.ArgumentParser()
    parser.add_argument("--case", choices=("support", "kg", "session"), required=True)
    parser.add_argument("--save", action="store_true")
    args = parser.parse_args()
    payload = payload_for(args.case)
    started = time.perf_counter()
    response = call_jev(payload)
    elapsed_ms = round((time.perf_counter() - started) * 1000, 1)
    print(json.dumps({"case": args.case, "elapsed_ms": elapsed_ms, "response": response}, ensure_ascii=False, indent=2))
    if args.save:
        output_dir = Path(__file__).resolve().parents[1] / "results"
        output_dir.mkdir(exist_ok=True)
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        path = output_dir / f"{stamp}_{args.case}.json"
        path.write_text(json.dumps({"payload": payload, "response": response, "elapsed_ms": elapsed_ms}, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"saved: {path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
