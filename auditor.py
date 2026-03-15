import os, json, httpx, asyncio
from pathlib import Path
from datetime import datetime
from groq import Groq
from dotenv import load_dotenv

load_dotenv()

DEEPGRAM_API_KEY = os.getenv("DEEPGRAM_API_KEY")
GROQ_API_KEY = os.getenv("GROQ_API_KEY")
groq_client = Groq(api_key=GROQ_API_KEY)

DEFAULT_CRITERIA = """
1. Greeting: Did the agent greet properly and introduce themselves?
2. Empathy: Did the agent show understanding toward customer's issue?
3. Resolution: Was the customer's issue resolved?
4. Communication: Was the agent clear, polite, and professional?
5. Compliance: Did agent avoid making unauthorized promises or commitments?
6. Closing: Did agent confirm resolution and close the call properly?
"""

async def transcribe_audio(file_path):
    print(f"[1/3] Transcribing: {file_path}")
    import asyncio
    from sarvamai import SarvamAI

    sarvam_key = os.getenv("SARVAM_API_KEY")
    client = SarvamAI(api_subscription_key=sarvam_key)

    # Run blocking SDK calls in thread pool
    def run_transcription():
        import time
        # Step 1: Create job
        job = client.speech_to_text_job.create_job(
            model="saaras:v3",
            mode="transcribe",
            language_code="unknown",
            with_diarization=True,
            num_speakers=2,
        )
        job_id = job.job_id
        print(f"Sarvam job created: {job_id}")

        # Step 2: Get upload links and upload
        upload_links = client.speech_to_text_job.get_upload_links(
            job_id=job_id, files=[os.path.basename(file_path)]
        )
        import requests
        filename = os.path.basename(file_path)
        print(f"Upload URLs keys: {list(upload_links.upload_urls.keys())}")
        # Try first available key if filename doesn't match
        key = filename if filename in upload_links.upload_urls else list(upload_links.upload_urls.keys())[0]
        upload_url = upload_links.upload_urls[key].file_url
        print(f"Uploading to: {upload_url[:80]}...")
        with open(file_path, "rb") as audio_f:
            resp = requests.put(upload_url, data=audio_f, headers={"x-ms-blob-type": "BlockBlob", "Content-Type": "audio/mpeg"})
            print(f"Upload response: {resp.status_code}")
            resp.raise_for_status()
        print(f"File uploaded successfully")

        # Step 3: Start job
        client.speech_to_text_job.start(job_id=job_id)
        print(f"Job started, polling...")

        # Step 4: Poll for completion
        for attempt in range(60):
            time.sleep(5)
            status = client.speech_to_text_job.get_status(job_id=job_id)
            s = str(status.job_state).lower()
            print(f"Status: {s} (attempt {attempt+1})")
            if "complete" in s or "success" in s or "done" in s:
                # Step 5: Get output filenames from job details
                output_files = []
                if status.job_details:
                    for task in status.job_details:
                        for out in task.outputs:
                            output_files.append(out.file_name)
                print(f"Output files: {output_files}")
                
                # Step 6: Get download links
                links = client.speech_to_text_job.get_download_links(job_id=job_id, files=output_files)
                
                # Step 7: Fetch the result JSON
                import requests as req
                dl_urls = links.download_urls if hasattr(links, "download_urls") else links.download_links
                first_key = list(dl_urls.keys())[0] if isinstance(dl_urls, dict) else 0
                result_url = dl_urls[first_key].file_url if isinstance(dl_urls, dict) else dl_urls[0].file_url
                res = req.get(result_url)
                print(f"Result fetched, status: {res.status_code}")
                return res.json()
            elif "fail" in s or "error" in s:
                raise Exception(f"Sarvam job failed: {status}")
        
        raise Exception("Sarvam transcription timed out")

    loop = asyncio.get_event_loop()
    result = await loop.run_in_executor(None, run_transcription)
    return result

def parse_transcript(dg):
    # Handle Sarvam diarized response
    diarized = dg.get("diarized_transcript") or dg.get("transcript", {})
    
    # Handle Sarvam's diarized_transcript format with entries
    utterances = []
    if isinstance(diarized, dict):
        utterances = (diarized.get("entries") or 
                     diarized.get("utterances") or 
                     diarized.get("segments") or [])
    elif isinstance(diarized, list):
        utterances = diarized
    
    # Fallback: try plain transcript
    if not utterances:
        plain = dg.get("transcript") or dg.get("text", "")
        if plain and isinstance(plain, str):
            return {
                "transcript": plain,
                "agent_text": plain,
                "customer_text": "",
                "agent_talk_ratio": 50.0,
                "customer_talk_ratio": 50.0,
                "total_duration": 0,
                "utterance_count": 1,
            }
        return {"error": "No transcript found in Sarvam response"}
    
    lines, agent_text, customer_text = [], [], []
    speakers = {}
    last_end = 0
    for utt in utterances:
        # Sarvam uses speaker_id field
        sid = (utt.get("speaker_id") or utt.get("speaker") or 
               utt.get("spk_id") or "0")
        if sid not in speakers:
            label = f"SPEAKER_{chr(65 + len(speakers))}"
            speakers[sid] = label
        label = speakers[sid]
        text = (utt.get("transcript") or utt.get("text") or "").strip()
        start = round(float(utt.get("start_time_seconds") or utt.get("start", 0)), 1)
        last_end = float(utt.get("end_time_seconds") or utt.get("end", start))
        if text:
            lines.append(f"[{start}s] {label}: {text}")
            agent_text.append(text) if label == "SPEAKER_A" else customer_text.append(text)
    
    aw = sum(len(t.split()) for t in agent_text)
    cw = sum(len(t.split()) for t in customer_text)
    total = aw + cw or 1
    return {
        "transcript": "\n".join(lines),
        "agent_text": " ".join(agent_text),
        "customer_text": " ".join(customer_text),
        "agent_talk_ratio": round(aw / total * 100, 1),
        "customer_talk_ratio": round(cw / total * 100, 1),
        "total_duration": round(last_end, 1),
        "utterance_count": len(utterances),
    }

def score_call(td, criteria=DEFAULT_CRITERIA, client_context=""):
    print("[2/3] Scoring call with AI...")
    prompt = f"""You are an expert Call Center QA Analyst. Analyze this call transcript and provide a detailed quality assessment.

NOTE: Speakers are labeled SPEAKER_A and SPEAKER_B. Determine which one is the company agent (representative/recruiter/support staff) and which one is the customer/candidate based on the context of the conversation. The agent is typically the one who initiated the call or is representing a company/service.

TRANSCRIPT:
{td.get("transcript")}

AGENT TALK RATIO (SPEAKER_A): {td.get("agent_talk_ratio")}%
CUSTOMER TALK RATIO (SPEAKER_B): {td.get("customer_talk_ratio")}%
(Ideal agent talk ratio is 40-60%)

QA CRITERIA:
{criteria}

{f"CLIENT CONTEXT: {client_context}" if client_context else ""}

Respond ONLY with valid JSON in this exact format:
{{
  "agent_speaker": "<SPEAKER_A or SPEAKER_B — whichever is the agent>",
  "overall_score": <1-10>,
  "scores": {{
    "greeting": <1-10>,
    "empathy": <1-10>,
    "resolution": <1-10>,
    "communication": <1-10>,
    "compliance": <1-10>,
    "closing": <1-10>
  }},
  "customer_sentiment": {{
    "start": "<angry|frustrated|neutral|satisfied|happy>",
    "end": "<angry|frustrated|neutral|satisfied|happy>",
    "trend": "<improved|worsened|stable>"
  }},
  "flags": ["<specific issue found, with timestamp if possible>"],
  "strengths": ["<what agent did well>"],
  "improvement_areas": ["<specific coaching suggestion>"],
  "call_summary": "<2-3 sentence summary of the call>",
  "resolution_status": "<resolved|unresolved|escalated|follow_up_needed>",
  "recommendation": "<excellent|good|coaching_needed|critical_review>",
  "compliance_passed": <true|false>
}}"""
    response = groq_client.chat.completions.create(
        model="llama-3.3-70b-versatile",
        messages=[{"role": "user", "content": prompt}],
        temperature=0.1,
        max_tokens=1000,
    )
    raw = response.choices[0].message.content.strip()
    if raw.startswith("```"):
        raw = raw.split("```")[1]
        if raw.startswith("json"):
            raw = raw[4:]
    return json.loads(raw)

def generate_report(file_path, td, scores):
    print("[3/3] Generating report...")
    # Relabel transcript with correct Agent/Customer labels
    agent_spk = scores.get("agent_speaker", "SPEAKER_A")
    fixed_lines = []
    for line in td.get("transcript", "").split("\n"):
        for spk in ["SPEAKER_A", "SPEAKER_B"]:
            label = "Agent" if spk == agent_spk else "Customer"
            line = line.replace(spk, label)
        fixed_lines.append(line)
    td["transcript"] = "\n".join(fixed_lines)
    return {
        "audit_id": f"AUDIT_{datetime.now().strftime('%Y%m%d_%H%M%S')}",
        "file": Path(file_path).name,
        "audited_at": datetime.now().isoformat(),
        "agent_speaker": scores.get("agent_speaker", "SPEAKER_A"),
        "call_metadata": {
            "duration_seconds": td.get("total_duration"),
            "agent_talk_ratio": td.get("agent_talk_ratio"),
            "customer_talk_ratio": td.get("customer_talk_ratio"),
            "total_turns": td.get("utterance_count"),
        },
        "scores": scores.get("scores", {}),
        "overall_score": scores.get("overall_score"),
        "customer_sentiment": scores.get("customer_sentiment"),
        "resolution_status": scores.get("resolution_status"),
        "compliance_passed": scores.get("compliance_passed"),
        "recommendation": scores.get("recommendation"),
        "flags": scores.get("flags", []),
        "strengths": scores.get("strengths", []),
        "improvement_areas": scores.get("improvement_areas", []),
        "call_summary": scores.get("call_summary"),
        "full_transcript": td.get("transcript"),
    }

async def audit_call(file_path, criteria=DEFAULT_CRITERIA, client_context="", save_report=True):
    print(f"\n{'='*50}\nAuditing: {file_path}\n{'='*50}")
    dg = await transcribe_audio(file_path)
    td = parse_transcript(dg)
    if "error" in td:
        return {"error": td["error"], "file": file_path}
    scores = score_call(td, criteria, client_context)
    report = generate_report(file_path, td, scores)
    if save_report:
        rp = Path(file_path).with_suffix(".audit.json")
        with open(rp, "w", encoding="utf-8") as f:
            json.dump(report, f, indent=2, ensure_ascii=False)
        print(f"✅ Report saved: {rp}")
    return report

async def audit_batch(folder_path, criteria=DEFAULT_CRITERIA):
    folder = Path(folder_path)
    audio_files = list(folder.glob("*.mp3")) + list(folder.glob("*.wav"))
    if not audio_files:
        print("No audio files found")
        return []
    results = []
    for i, file in enumerate(audio_files, 1):
        print(f"\nProcessing {i}/{len(audio_files)}: {file.name}")
        try:
            report = await audit_call(str(file), criteria)
            results.append(report)
        except Exception as e:
            results.append({"error": str(e), "file": file.name})
    with open(folder / "batch_summary.json", "w", encoding="utf-8") as f:
        json.dump(results, f, indent=2, ensure_ascii=False)
    print(f"\n✅ {len(results)} calls audited.")
    return results

if __name__ == "__main__":
    import sys
    if len(sys.argv) < 2:
        print("Usage: python auditor.py call.mp3")
        sys.exit(1)
    path = sys.argv[1]
    if Path(path).is_dir():
        asyncio.run(audit_batch(path))
    else:
        report = asyncio.run(audit_call(path))
        print(f"\nAgent Speaker:  {report.get('agent_speaker')}")
        print(f"Score:          {report.get('overall_score')}/10")
        print(f"Recommendation: {report.get('recommendation')}")
        print(f"Resolution:     {report.get('resolution_status')}")
        print(f"Compliance:     {'✅ Passed' if report.get('compliance_passed') else '❌ Failed'}")
        print(f"Summary:        {report.get('call_summary')}")
        if report.get("flags"):
            print(f"\n⚠️  Flags:")
            for flag in report["flags"]:
                print(f"   - {flag}")
