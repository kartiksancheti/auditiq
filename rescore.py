import os, json, sys
from pathlib import Path
from groq import Groq
from dotenv import load_dotenv

load_dotenv()
sys.path.insert(0, '/home/audit/call-auditor')
from auditor import BURGER_SINGH_CRITERIA, score_call_checklist, generate_report_checklist

reports_dir = Path("/home/audit/call-auditor/reports")

for rf in reports_dir.glob("*.checklist.json"):
    try:
        with open(rf) as f:
            old = json.load(f)
        transcript = old.get("full_transcript", "")
        if not transcript:
            print(f"No transcript in {rf.name}, skipping")
            continue
        print(f"Re-scoring: {rf.name}")
        td = {
            "transcript": transcript,
            "agent_talk_ratio": old.get("call_metadata", {}).get("agent_talk_ratio", 50),
            "customer_talk_ratio": old.get("call_metadata", {}).get("customer_talk_ratio", 50),
            "total_duration": old.get("call_metadata", {}).get("duration_seconds", 0),
            "utterance_count": old.get("call_metadata", {}).get("total_turns", 0),
        }
        scores = score_call_checklist(td, BURGER_SINGH_CRITERIA)
        report = generate_report_checklist(old.get("file", rf.name), td, scores, BURGER_SINGH_CRITERIA)
        report["audited_at"] = old.get("audited_at")
        report["audit_id"] = old.get("audit_id")
        with open(rf, "w") as f:
            json.dump(report, f, indent=2, ensure_ascii=False)
        print(f"Done: {report['score_display']}")
    except Exception as e:
        print(f"Error {rf.name}: {e}")

print("\nAll done!")
